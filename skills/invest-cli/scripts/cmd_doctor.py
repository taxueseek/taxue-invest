#!/usr/bin/env python3
"""doctor 子命令：一条命令自检 invest-cli 的运行面健康。

为什么存在：排查「数据源挂没挂 / 缓存多大 / 解释器缺不缺件 / 注册软链断没断 /
DSH 插件副本漂没漂 / 过去 24h 取数是不是在连续失败」此前要跑五个入口翻多处
文档（2026-10-25 体检把核查手册收敛为一个命令，2026-11 补运行时账本一面）。检查项全部**只读**，不修复任何东西；退出码：任一 FAIL → 1，
全 PASS/WARN/SKIP → 0。

用法:
    invest-cli doctor            # 文本报告
    invest-cli doctor --json     # 结构化 {ok, checks: {名称: {status, detail}}}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from sources import registry
from sources.envelope import (
    HEALTH_FAIL,
    HEALTH_PASS,
    HEALTH_SKIP,
    HEALTH_WARN,
    is_blocking,
)

_HERE = Path(__file__).resolve().parent
_PLUGIN_SRC = _HERE.parent / "packages" / "dsh-plugin"

# 缓存健康阈值：_common 的 CACHE_MAX_AGE 是 7 天（读时惰性清理），doctor 只报
# 告不清理；最老文件超过 14 天说明有一段时间没被任何读路径触碰过。
_CACHE_STALE_WARN = 14 * 24 * 3600.0

# mx-data 兜底路径（系统解释器 in-process import route 层）的硬前提。
# 2026-10-23 Python 环境清理后系统 3.9 一度缺 yaml，mx-data 快路径静默退化成
# subprocess 慢路（351ms 级）且无人报警——这条检查就是那次的防线。
_SYSTEM_RUNTIMES = ("yaml",)


def check_sources() -> tuple[str, str]:
    states = registry.detect_all()
    if not states:
        return HEALTH_FAIL, "未加载到任何数据源配置（缺 data-sources.yaml）"
    avail = registry.available_ids(states)
    if not avail:
        return HEALTH_FAIL, f"0/{len(states)} 可用——凭据与网络全断，取数只剩本地缓存"
    from sources.route import chains

    empty = [k for k, v in chains().items() if not v]
    detail = f"{len(avail)}/{len(states)} 可用：{', '.join(avail[:10])}"
    if len(avail) < 10 and len(avail) < len(states) // 2:
        return HEALTH_WARN, detail + "——过半源不可用，快照链变窄"
    if empty:
        return HEALTH_WARN, detail + f"；空链：{', '.join(empty)}"
    return HEALTH_PASS, detail


def check_cache(cache_root: Optional[Path] = None) -> tuple[str, str]:
    from _common import cache_root as _root

    root = cache_root or _root()
    if not root.is_dir():
        return HEALTH_PASS, f"{root} 不存在（尚未产生缓存）"
    files = [p for p in root.rglob("*") if p.is_file()]
    if not files:
        return HEALTH_PASS, f"{root} 为空"
    total = sum(p.stat().st_size for p in files)
    oldest = min(time.time() - p.stat().st_mtime for p in files)
    mb = total / 1e6
    detail = (f"{len(files)} 文件 / {mb:.1f}MB / 最老 {oldest / 86400:.1f} 天前"
              f"（{root}）")
    if oldest > _CACHE_STALE_WARN:
        return HEALTH_WARN, detail + "——超过 14 天没被读路径触碰，可手动清（删了会自动重建）"
    return HEALTH_PASS, detail


def check_interpreters(system_py: Optional[str] = None,
                       skill_root: Optional[Path] = None) -> tuple[str, str]:
    """运行时健康：venv 判据与 wrapper / mx-data 共用 runtime_guard 单一真源。

    旧版用 `venv_py.is_file()` 只看「路径看起来在」，断链时当前解释器明明已
    回退系统 python3（detail 里写着「非 venv」）却仍判 pass——能力降级无人报。
    broken / incomplete 是**能力故障**，判 fail；公开仓无 venv 是支持形态，
    兜底解释器的检查逻辑保持不变。
    """
    from runtime_guard import health

    root = Path(skill_root) if skill_root is not None else _HERE.parent
    state, why = health(root)
    cur = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    in_venv = Path(sys.prefix).resolve() == (root / ".venv").resolve()
    head = f"当前解释器 {cur}（{'venv' if in_venv else '非 venv'}）"
    if state == "broken":
        return HEALTH_FAIL, head + f"；{why}——按 requirements.txt 重建 venv"
    if state == "incomplete":
        return HEALTH_FAIL, head + f"；{why}——补齐 requirements.txt 里的关键依赖"
    if state == "ok":
        head += "；venv 关键依赖齐备"
    # 兜底候选两条：PATH python3（agent 裸调用的默认）+ /usr/bin/python3
    # （macOS 常驻系统解释器，mx-data 的历史运行时）。PATH 上常见 homebrew
    # 的某个 Python 版本——PEP 668 拦装包所以缺 yaml/requests 属常态，只要 /usr/bin 侧
    # 齐备就有兜底，不误报。显式传 system_py 时只测它（供单测）。
    cands: list[str] = []
    py = system_py or shutil.which("python3")
    if py:
        cands.append(py)
    if system_py is None and Path("/usr/bin/python3").is_file():
        cands.append("/usr/bin/python3")
    if not cands:
        return HEALTH_PASS, head + "；无系统 python3（跳过兜底解释器检查）"
    code = ("import importlib.util as u;"
            "print(','.join(m + '=' + str(u.find_spec(m) is not None)"
            f" for m in {list(_SYSTEM_RUNTIMES)!r}))")
    probe_ok, probe_detail = [], []
    for cand in cands:
        try:
            out = subprocess.run([cand, "-c", code], capture_output=True,
                                 text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            probe_detail.append(f"{cand} 探测失败({type(e).__name__})")
            continue
        missing = [p.split("=")[0] for p in out.stdout.strip().split(",")
                   if p.endswith("=False")]
        if out.returncode == 0 and not missing:
            probe_ok.append(cand)
        else:
            probe_detail.append(f"{cand} 缺 {'、'.join(missing) or '探测异常'}")
    if probe_ok:
        return HEALTH_PASS, head + f"；兜底齐备：{', '.join(probe_ok)}"
    return (HEALTH_WARN, head + "；" + "；".join(probe_detail)
            + "——mx-data 兜底路径会退化 subprocess（功能在、变慢）")


def check_symlinks(skill_root: Optional[Path] = None,
                   registry_root: Optional[Path] = None) -> tuple[str, str]:
    """注册根（~/.agents/skills/）的 invest 家族软链必须 resolve 回真源。

    真源与注册根从本文件位置推导，不硬编码个人路径；公开仓用户没有这层
    软链（真源即安装处）时自动跳过。
    """
    sroot = skill_root or _HERE.parents[1]
    rroot = registry_root or (_HERE.parents[3] / "skills")
    if rroot == sroot:
        return HEALTH_PASS, "真源即安装处（无软链层，公开仓形态）"
    members = sorted(p.name for p in sroot.iterdir() if p.is_dir()
                     and not p.name.startswith((".", "_")))
    if not members:
        return HEALTH_SKIP, f"真源 {sroot} 下无成员"
    broken, missing = [], []
    for name in members:
        link = rroot / name
        if not link.exists():
            missing.append(name)
        elif link.resolve() != (sroot / name).resolve():
            broken.append(name)
    if broken or missing:
        return (HEALTH_FAIL, f"注册根 {rroot}：断链 {broken or '无'}、缺失 {missing or '无'}"
                "——宿主会读不到这些技能")
    return HEALTH_PASS, f"{len(members)} 个家族成员软链完好（{rroot}）"


def _plugin_payload_files(src: Path) -> list[str]:
    """插件 package.json `files` 声明的装机面，展开为相对路径清单。

    不另维护 KEYS 名单：doctor 与 sync-local.sh 曾各写一份（3 件 vs 5 件），
    漏掉 50KB 的 dsh/client.js 时两边都无感。装机面本来就是 package.json
    的 `files` 字段说了算，它是唯一真源。
    """
    import json

    manifest = json.loads((src / "package.json").read_text(encoding="utf-8"))
    out: list[str] = ["package.json"]
    for entry in manifest.get("files", []):
        p = src / entry
        if p.is_file():
            out.append(entry)
        elif p.is_dir():
            out += [str(f.relative_to(src)) for f in sorted(p.rglob("*")) if f.is_file()]
    return out


def check_dsh(profiles_root: Optional[Path] = None,
              plugin_src: Optional[Path] = None) -> tuple[str, str]:
    """DSH 装机副本必须与源一致：file: 依赖是复制副本，只改源不同步=装机读旧包
    （argo 同款教训）。比对 package.json `files` 声明的全部装机文件，
    漂移只 WARN——功能性漂移另算。"""
    proot = profiles_root or (Path.home() / ".dsh" / "profiles")
    src = plugin_src or _PLUGIN_SRC
    if not proot.is_dir():
        return HEALTH_SKIP, f"{proot} 不存在（非 DSH 环境）"
    keys = _plugin_payload_files(src)
    drifted, installed = [], []
    for prof in sorted(proot.iterdir()):
        copy = prof / "node_modules" / "@taxueseek" / "invest-cli-dsh"
        if not copy.is_dir():
            continue
        installed.append(prof.name)
        for rel in keys:
            a, b = src / rel, copy / rel
            if not b.is_file() or a.read_text(encoding="utf-8",
                                              errors="replace") != b.read_text(encoding="utf-8", errors="replace"):
                drifted.append(f"{prof.name}/{rel}")
    if not installed:
        return HEALTH_SKIP, f"{proot} 下无 invest-cli-dsh 装机副本"
    if drifted:
        return (HEALTH_WARN, f"装机副本漂移：{', '.join(drifted)}"
                "——跑 packages/dsh-plugin/scripts/sync-local.sh 同步")
    return HEALTH_PASS, f"{len(installed)} 个 profile 副本与源一致（{', '.join(installed)}）"


# 运行时账本（usage_log）的判据。比「当下探测」多一层：doctor 一直只能看见
# 「此刻这个源可不可用」，看不见「过去 24h 它是不是在连续失败、降级链被触发了
# 多少次」。次数阈值取小值，因为 CLI 是低频命令，24h 内 3 次连续失败已足够异常。
# 命令级只 WARN 不 FAIL：命令失败常是参数错误或上游临时抖动，不足以判定环境坏掉。
_USAGE_WINDOW_HOURS = 24.0
_USAGE_MIN_SAMPLES = 5
_USAGE_FAIL_RATE_WARN = 0.5
_USAGE_CONSEC_WARN = 3
_USAGE_CONSEC_FAIL = 5
_USAGE_CMD_CONSEC_WARN = 5


def check_usage() -> tuple[str, str]:
    """最近 24h 的真实取数成败：源级与命令级分开报。

    聚合逻辑下沉到 `_common.usage_stats`，datasources 读同一份，避免两处各写
    一遍时间窗与连续失败判据。
    """
    from _common import usage_log_dir, usage_stats

    stats = usage_stats(_USAGE_WINDOW_HOURS)
    src, direct, cmd = stats["source"], stats["direct"], stats["cmd"]
    if stats["records"] == 0:
        return HEALTH_PASS, f"尚无运行记录（{usage_log_dir()}）"
    if not src["total"] and not direct["total"] and not cmd["total"]:
        stats_7d = usage_stats(168.0)
        s7, d7, c7 = stats_7d["source"], stats_7d["direct"], stats_7d["cmd"]
        if s7["total"] or d7["total"] or c7["total"]:
            return HEALTH_PASS, (
                f"最近 24h 无取数/命令（账本历史 {stats['records']} 条；"
                f"近 7d：源级 {s7['total']} / 降级 {s7['fallback']}，"
                f"直取 {d7['total']}，命令 {c7['total']}）"
            )
        return HEALTH_PASS, f"最近 24h 无取数/命令（账本历史 {stats['records']} 条）"

    parts: list[str] = []
    if src["total"]:
        ok_rate = src["ok"] / src["total"] * 100
        parts.append(f"源级 {src['total']} 次，成功 {src['ok']}（{ok_rate:.0f}%），"
                     f"降级 {src['fallback']} 次")
        top = sorted(src["by_source"].items(), key=lambda kv: kv[1], reverse=True)[:3]
        if top:
            parts.append("失败归因：" + "、".join(f"{sid}×{n}" for sid, n in top))
        fb_failed = src.get("fallback_failed") or {}
        if fb_failed:
            top_fb = sorted(fb_failed.items(), key=lambda kv: kv[1], reverse=True)[:3]
            parts.append("降级前失败：" + "、".join(f"{sid}×{n}" for sid, n in top_fb))
        # 交付条数（P2）：谁出货、谁空转，与耗时配对才能判断「慢源拖尾」
        # 还是「唯一出货」。argo engine_results 同构。
        delivered = src.get("delivered") or {}
        if delivered:
            top_delivered = sorted(delivered.items(), key=lambda kv: kv[1], reverse=True)[:3]
            parts.append("交付：" + "、".join(f"{sid} {n} 条" for sid, n in top_delivered))
        empty = src.get("empty") or {}
        if empty:
            parts.append("空结果：" + "、".join(f"{sid}×{n}" for sid, n in empty.items()))
        if src["consecutive"]:
            parts.append("源链尾部连续失败："
                         + "、".join(f"{k}×{n}" for k, n in src["consecutive"].items()))
    else:
        parts.append("源级无取数")
    if direct["total"]:
        parts.append(f"直取级 {direct['total']} 次，失败 {direct['failed']}")
        if direct["consecutive"]:
            parts.append("直取尾部连续失败："
                         + "、".join(f"{k}×{n}" for k, n in direct["consecutive"].items()))
    if cmd["total"]:
        parts.append(f"命令级 {cmd['total']} 次，失败 {cmd['failed']}")
        if cmd["consecutive"]:
            parts.append("命令尾部连续失败："
                         + "、".join(f"{k}×{n}" for k, n in cmd["consecutive"].items()))

    # 空结果基线破位（P3）：健康源突然一直空，比「失败」更隐蔽——它 ok=True。
    stale = stats.get("suspected_stale") or {}
    if stale:
        parts.append("疑似失效（空结果基线破位）：" + "、".join(
            f"{sid}（连续 {v['consecutive_empty']} 次空，跨 {v['distinct_queries']} 查询）"
            for sid, v in stale.items()))
    head = "；".join(parts)

    worst_src = max(src["consecutive"].values(), default=0)
    worst_direct = max(direct["consecutive"].values(), default=0)
    worst_cmd = max(cmd["consecutive"].values(), default=0)
    if worst_src >= _USAGE_CONSEC_FAIL:
        return HEALTH_FAIL, head + "——同一条链连续失败，先跑 `invest-cli datasources` 看原因"
    # suspected_stale 只 WARN：空结果可能是上游口径变化，不足以判定环境坏掉，
    # 但它比「无记录」更需要人看一眼（ok=True 的失效最隐蔽）。
    if stale:
        return HEALTH_WARN, head + "——该源 ok=True 但持续空结果，检查上游口径或凭据"
    if worst_src >= _USAGE_CONSEC_WARN:
        return HEALTH_WARN, head
    if src["total"] >= _USAGE_MIN_SAMPLES and src["failed"] / src["total"] >= _USAGE_FAIL_RATE_WARN:
        return HEALTH_WARN, head + "——失败率过半，检查凭据或上游配额"
    if worst_direct >= _USAGE_CMD_CONSEC_WARN:
        return HEALTH_WARN, head + "——同一数据源直取连续失败；先查凭据与上游配额"
    if worst_cmd >= _USAGE_CMD_CONSEC_WARN:
        return HEALTH_WARN, head + "——同一命令连续失败；直取命令先查凭据与上游配额"
    return HEALTH_PASS, head


CHECKS: list[tuple[str, Callable[..., tuple[str, str]]]] = [
    ("sources", check_sources),
    ("usage", check_usage),
    ("cache", check_cache),
    ("interpreters", check_interpreters),
    ("symlinks", check_symlinks),
    ("dsh", check_dsh),
]

_BADGE = {HEALTH_PASS: "[PASS]", HEALTH_WARN: "[WARN]", HEALTH_FAIL: "[FAIL]", HEALTH_SKIP: "[SKIP]"}


def run(as_json: bool = False) -> int:
    results: dict[str, dict[str, Any]] = {}
    for name, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as e:  # 检查项自身崩溃不算医生死掉
            status, detail = HEALTH_WARN, f"检查异常：{type(e).__name__}: {e}"
        results[name] = {"status": status, "detail": detail}
    ok = all(not is_blocking(v["status"]) for v in results.values())
    if as_json:
        print(json.dumps({"ok": ok, "checks": results}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    print("\n  invest-cli doctor")
    print("  " + "-" * 62)
    for name, res in results.items():
        print(f"  {_BADGE[res['status']]} {name:<14}{res['detail']}")
    print("  " + "-" * 62)
    print(f"  结论：{'健康' if ok else '存在 FAIL 项'}（PASS/WARN 不阻塞，FAIL 须处理）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run("--json" in sys.argv))
