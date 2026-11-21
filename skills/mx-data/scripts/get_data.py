#!/usr/bin/env python3
"""Unified data access — in-process wrapper around invest-cli route layer.

Does NOT call APIs directly. Does NOT manage auth.
Calls route.fetch / cmd_* helpers in-process: no subprocess spawn.

解释器升级自愈：invest-cli 自带 venv 存在且当前解释器不是它时，本脚本会
exec 进 venv 再跑（只此一次，MX_DATA_NO_REEXEC=1 可关闭）。2026-10-25 起
不再限美股场景——系统 3.9 已 EOL（2025-10 停安全维护）且其 LibreSSL 会打
NotOpenSSLWarning 假故障，本机运行时统一走 skill 自带 venv（版本随本机
Python 升级而变，不写死；基础解释器失效由 runtime_guard 当天自检报出）。
venv 不存在时保持现状（系统解释器 + subprocess 兜底）；公开仓承诺的
Python 3.9+ 兼容下限不变——这是本机运行时选择，不是代码门槛。

Fallback: subprocess to `invest-cli` binary if in-process import fails.
"""
import argparse
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

# 底线防线：系统 3.9（LibreSSL）下 urllib3 在导入期报 NotOpenSSLWarning，对把
# stdout/stderr 合并解析的调用方是假故障源。venv 化后主路径（OpenSSL）
# 不会再发此告警，但 venv 缺失时的兜底路径仍可能是任意系统解释器——过滤器
# 跟着入口走（写法与 invest_cli.py 同一条，见其注释：category 必须 Warning）。
warnings.filterwarnings("ignore", category=Warning, module=r"urllib3.*")

sys.path.insert(0, str(Path(__file__).parent))
from query_router import detect_scenario, get_route, scenario_argv, scenario_route_kind


def _resolve_invest_cli_scripts() -> Path:
    """invest-cli 的 scripts 目录：env → 同根兄弟 → 常见安装根。

    旧实现写死 `Path.home()/".agents"/"skills"/...`，换安装根（.claude、
    INVEST_CLI_ROOT）就整条 in-process 路径失效，只剩 subprocess 兜底。
    """
    env = os.environ.get("INVEST_CLI_ROOT", "").strip()
    cands: list[Path] = []
    if env:
        cands.append(Path(env).expanduser() / "scripts")
    cands += [
        Path(__file__).resolve().parents[2] / "invest-cli" / "scripts",  # 同根兄弟
        Path.home() / ".agents" / "skills" / "invest-cli" / "scripts",
        Path.home() / ".claude" / "skills" / "invest-cli" / "scripts",
    ]
    for cand in cands:
        if (cand / "sources" / "route.py").is_file():
            return cand
    return cands[0]


INVEST_CLI_SCRIPTS = _resolve_invest_cli_scripts()


def _ensure_scripts_on_path() -> bool:
    p = str(INVEST_CLI_SCRIPTS)
    if INVEST_CLI_SCRIPTS.is_dir():
        if p not in sys.path:
            sys.path.insert(0, p)
        return True
    return False


def _fetch_in_process(scenario: str, code: str) -> dict:
    """Call invest-cli fetch helpers without spawning a process."""
    from sources.route import fetch, unwrap_snapshot

    kind, market = scenario_route_kind(scenario)
    if kind == "stock":
        from cmd_stock import _looks_like_hk

        market = "hk" if _looks_like_hk(code) else "a"
    res = fetch(kind, code, market=market)
    return {"status": "ok" if res.get("ok") else "error",
            "snapshot": unwrap_snapshot(res) if res.get("ok") else None,
            "message": None if res.get("ok") else res.get("error"),
            "source": res.get("source"), "cached": bool(res.get("cached"))}


def _fetch_subprocess(argv: list[str]) -> dict:
    """以参数列表起子进程（不含 invest-cli 本身）。

    旧实现收一个字符串再 `cmd.split()`：查询词一含空格就被拆成多个位置
    参数——实测 `--type news --query "茅台 股价"` 生成
    `["invest-cli","info","茅台","股价"]`，而 `info` 只接受一个 `query`，
    argparse 直接 rc=2 把整段 usage 打给用户。含引号、`|`、`$` 时还会被按
    shell 语义误解。改为从构造处就保持参数边界：`_scenario_cmd` 产出 list，
    这里只追加程序名，不再做任何字符串切分。
    """
    try:
        result = subprocess.run(
            ["invest-cli", *argv],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            try:
                return {"status": "ok", "snapshot": json.loads(result.stdout)}
            except json.JSONDecodeError:
                return {"status": "ok", "snapshot": result.stdout}
        return {"status": "error", "message": result.stderr}
    except FileNotFoundError:
        return {"status": "error", "message": "invest-cli not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "invest-cli timeout"}


def _scenario_cmd(scenario: str, code: str, query_str: str) -> list[str]:
    """场景 → invest-cli 的 argv 列表（不含 invest名本身）。

    单一派生点：argv 由 query_router.SCENARIO_COMMANDS 给出（场景状态机真源），
    本函数只做占位符替换。返回 list 而不是字符串：字符串形态必须由调用方再
    切分才能喂给 subprocess，而查询词含空格/引号时一切就错（见
    `_fetch_subprocess` 的历史坑）。
    """
    return scenario_argv(scenario, code, query_str)


def _display_argv(argv: list[str]) -> str:
    """argv → 可复制的展示串。含空格或引号的参数加引号，避免读者以为被切开了。

    只为展示服务，不参与执行（执行走 list 本身）。普通参数保持裸写，与既有
    `command` 字段的历史形状一致（测试按此断言，且该字段有消费方）。

    为什么不用 shlex.quote：它把一切不在 `[a-zA-Z0-9_@%+=:,./-]` 里的字符都
    加引号，中文名因此变成 `'隆基绿能'`，而 `command` 的历史形状是裸写
    `invest-cli stock 隆基绿能 --json`。这里只在「不引号就会被误读」时才引号，
    即参数含空格或引号字符时；Python 的 repr 对 str 会选一个不冲突的引号
    包裹，输出恰好是合法 shell 转义，够用且不破坏形状。
    """
    return " ".join(
        a if (a and not any(c in a for c in " \t\"'")) else repr(a)
        for a in argv
    )


def _ensure_runtime() -> None:
    """解释器升级自愈：venv 存在且当前不在 venv 里时，re-exec 进 venv 一次。

    判据是「当前解释器的 sys.prefix 是否就是 venv」而不是「路径看起来不对」：
    venv/bin/python 常是指向基础解释器的软链，比 sys.executable 会把系统
    python3 误判成「已在 venv」、re-exec 永不发生。MX_DATA_NO_REEXEC=1 供
    测试/排障关闭；exec 前也设上它，万一 venv 里同样缺包，不会形成 exec 环。
    venv 不存在时直接返回：系统解释器（含公开仓用户的任意 3.9+）仍是
    支持形态，import 失败由既有的 subprocess 兜底接管。
    """
    if os.environ.get("MX_DATA_NO_REEXEC") == "1":
        return
    # 判据不在本文件另写一份：与 wrapper / doctor / CLI 入口共用 runtime_guard。
    # 旧版只判 `is_file()`，venv 解释器软链断掉时照样 re-exec 到一个跑不起来的
    # 二进制（或干脆静默不升级）；executable() 与 shell 的 `[ -x ]` 同义。
    scripts = str(INVEST_CLI_SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from runtime_guard import executable, venv_python
    except ImportError:
        return  # 独立分发时没有该模块：维持系统解释器形态，不硬造依赖
    venv_root = INVEST_CLI_SCRIPTS.parent / ".venv"
    venv_py = venv_python(INVEST_CLI_SCRIPTS.parent)
    if not executable(venv_py):
        return
    try:
        if Path(sys.prefix).resolve() == venv_root.resolve():
            return
    except OSError:
        pass
    os.environ["MX_DATA_NO_REEXEC"] = "1"
    os.execv(str(venv_py), [str(venv_py), *sys.argv])


def get_data(code="", metrics=None, scenario="", query_str="", target_type=""):
    """Unified data access via invest-cli (in-process first)."""
    if not scenario:
        # 把 code 一起传下去：`--type stock --code AAPL` 要靠它判定美股。
        scenario = detect_scenario(query_str, target_type or "", code=code)
    route_kind = scenario_route_kind(scenario)
    if not code and query_str and route_kind is not None:
        import re as _re

        m = _re.search(r"[A-Za-z]{1,5}(?:\.[A-Za-z]{1,3})?|\d{5,6}", query_str)
        # ① 英文字母/点号代码，但要求去点后 ≥4 字符（数字段除外）。
        #    1-3 字母段与财务指标词字面完全重叠，而东财/yfinance 会把它们
        #    模糊匹配到真实公司：实测 `stock ROE` → Astoria US Equal Weight
        #    Quality(ROE.O)、`stock PB` → Prosperity Bancshares(PB.N)、
        #    `stock FCF` → 第一联邦金融(FCF.N)，全部 rc=0。于是「茅台 ROE」
        #    被答成一家美国 ETF——静默答错标的比报错更糟。
        #    真实可交易 ticker 以 ≥4 字符为主（AAPL/TSLA/NVDA/BRK.B），
        #    ≤3 字母段一律不当代码；确有 1-3 字符 ticker 时用 `--code` 直给。
        #    这是长度判据，不是名单：不预设哪几个词是指标。
        if m and (m.group(0).isdigit() or len(m.group(0).replace(".", "")) >= 4):
            code = m.group(0)
        else:
            # ② 第一个连续中文段（≥2 字）——「茅台 ROE」→「茅台」，
            #    「隆基绿能 毛利率」→「隆基绿能」。名称消歧归上游：
            #    hithink/东财支持按名称检索，实测「隆基绿能」「中芯国际」
            #    「招商证券」均直接解析出代码，都不在 cmd_stock 那 12 条
            #    硬编码映射里——能力本就在上游，不做本地字典扩展。
            # ③ 无中文段且无合格代码时不留 code：让上层报「空标的」，
            #    而不是把一个 2-3 字母词当成标的去撞上游的模糊匹配。
            cn = _re.search(r"[\u4e00-\u9fff]{2,}", query_str)
            if cn:
                code = cn.group(0).strip()
            elif not m:
                code = query_str.strip()
    _ensure_runtime()
    route = get_route(scenario)
    cmd = _scenario_cmd(scenario, code, query_str)

    result = None
    via = "in-process"
    if route_kind is not None and _ensure_scripts_on_path():
        try:
            result = _fetch_in_process(scenario, code)
        except Exception as e:  # noqa: BLE001 —— 降级不断链
            result = None
            via = f"subprocess (in-process failed: {type(e).__name__})"
    if result is None:
        via = "subprocess" if via == "in-process" else via
        raw = _fetch_subprocess(cmd)
        result = {"status": raw["status"],
                  "snapshot": raw.get("snapshot") or raw.get("data"),
                  "message": raw.get("message")}

    return {"status": result["status"], "scenario": scenario,
            "command": "invest-cli " + _display_argv(cmd), "via": via,
            # 哪个解释器真正执行的：美股自愈 re-exec 是否生效，一眼可查。
            "runtime": sys.executable,
            "route_info": route, "data": result.get("snapshot"),
            "source": result.get("source"), "cached": result.get("cached"),
            "error": result.get("message")}


def main():
    parser = argparse.ArgumentParser(description="Unified data access via invest-cli")
    parser.add_argument("--type", choices=["stock", "us", "fund", "bond", "industry", "enterprise", "news", "macro"], help="Target type（stock + 字母代码会自动识别为美股）")
    parser.add_argument("--code", default="", help="Security/fund/bond code")
    parser.add_argument("--query", default="", help="Natural language query")
    parser.add_argument("--metrics", nargs="*", default=[], help="指标名（仅回传，不做过滤；过滤在分析层）")
    args = parser.parse_args()

    query_str = args.query or args.code
    result = get_data(code=args.code, metrics=args.metrics, query_str=query_str,
                      target_type=args.type or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
