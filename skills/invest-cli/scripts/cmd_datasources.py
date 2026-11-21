"""datasources 子命令：列出并探测所有已登记数据源的可用性。

用法:
    invest-cli datasources            # 表格输出
    invest-cli datasources --json     # 诊断：可用性 + 默认快照链；取数不要每次前置
"""
from __future__ import annotations

import json
import sys

from sources import registry


def _fmt_available(v: bool) -> str:
    return "可用" if v else "不可用"


def _usage_line(stats: dict) -> str:
    """把 usage_stats 的源级/直取级/命令级汇总压成一行，供表格尾部与排查时直读。"""
    src, direct, cmd = stats["source"], stats["direct"], stats["cmd"]
    if not src["total"] and not direct["total"] and not cmd["total"]:
        return f"最近 {stats['window_hours']:.0f}h 无记录（账本 {stats['records']} 条）"
    bits = [f"源级 {src['total']} 次，成功 {src['ok']}，降级 {src['fallback']}"]
    if src["consecutive"]:
        bits.append("源链尾部连续失败：" + "、".join(
            f"{k}×{n}" for k, n in src["consecutive"].items()))
    delivered = src.get("delivered") or {}
    if delivered:
        bits.append("交付条数：" + "、".join(
            f"{sid} {n}" for sid, n in sorted(delivered.items(),
                                              key=lambda kv: kv[1], reverse=True)[:5]))
    if direct["total"]:
        bits.append(f"直取级 {direct['total']} 次，失败 {direct['failed']}")
    bits.append(f"命令级 {cmd['total']} 次，失败 {cmd['failed']}")
    return "；".join(bits)


def run(detect_only: bool = False, as_json: bool = False) -> int:
    states = registry.detect_all()
    if not states:
        print("未加载到任何数据源配置（缺 data-sources.yaml）", file=sys.stderr)
        return 1

    from _common import usage_stats

    usage = usage_stats(24.0)
    from sources.route import chains, disabled_sources

    user_disabled = disabled_sources()
    try:
        ch = chains(states=states)
    except TypeError:
        ch = chains()
    if as_json:
        payload = dict(states)
        payload["_chains"] = ch
        payload["_usage"] = usage
        payload["_disabled"] = sorted(user_disabled)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # 可读表格
    print("\n  invest-cli 数据源状态")
    print("  " + "-" * 62)
    print(f"  {'数据源':<12}{'可用':<8}{'优先级':<8}{'覆盖场景'}")
    print("  " + "-" * 62)
    ranked = sorted(states.items(), key=lambda kv: kv[1].get("priority", 0), reverse=True)
    for sid, st in ranked:
        cov = ",".join(st.get("coverage", []))[:20]
        avail_txt = "停用" if sid in user_disabled else _fmt_available(st.get("available", False))
        print(f"  {sid:<12}{avail_txt:<8}{st.get('priority', 0):<8}{cov}")
        print(f"    └ {st.get('detail', '')}")
        # 参与 route.fetch 的 kind 与展示标签分开报：标签大而全，链路只认前者。
        rk = st.get("route_kinds")
        if rk is not None:
            print(f"    └ 路由: {', '.join(rk) if rk else '无（仅透传/直调）'}")
    print("  " + "-" * 62)
    if user_disabled:
        print(f"\n  用户停用（INVEST_CLI_DISABLE_SOURCES，不参与自动路由）: "
              f"{', '.join(sorted(user_disabled))}")
    avail = registry.available_ids()
    print(f"\n  当前可用数据源（按优先级）: {', '.join(avail) if avail else '无'}")
    print("\n  默认快照链（yaml × 真方法 × 可用性 − 用户停用集，整单回退）")
    for name, ids in ch.items():
        print(f"    {name:<10} {' > '.join(ids) if ids else '无'}")
    print("  组合规则: 同一问题不混源；行情/诊断/选股/资讯是不同问题才并行选源。")
    print("\n  运行时账本（只记真实取数与命令成败，命中缓存不记）")
    print(f"    {_usage_line(usage)}")
    return 0
