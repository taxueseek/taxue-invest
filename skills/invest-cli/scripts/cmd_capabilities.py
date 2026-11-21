"""capabilities 子命令：数据源能力发现层。

为什么需要（2026-09-03 教训）：invest-cli 曾因"不知道外部源有什么"而重复低效——
盈米 69 工具只收敛 5 个、ttskill 37 包只封装 4 个，其余靠记忆必然遗忘，
Agent 遇到未封装场景只能现场翻官方包学调用（低效且易错）。
本命令让三件事一处可见：外部源有什么、invest-cli 收敛到哪、怎么调。

用法:
    invest-cli capabilities              数据源总览 + 高层入口速查
    invest-cli capabilities yingmi       盈米 69 工具清单（动态）+ 收敛标注
    invest-cli capabilities ttskill      天天基金 37 包清单（动态）+ 收敛标注
    invest-cli capabilities westock      westock 已收敛子命令 → cn 高层入口
    invest-cli capabilities <source> --json    JSON 输出（给 skill 层做路由决策）

注意：本命令只列清单与标注，不取业务数据。取数仍走 fund/stock/intent 高层入口
或 yingmi/ttskill/wind 透传。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# —— 已收敛到 invest-cli 高层入口的外部工具（改 cmd_intent/适配器时同步维护） ——
YINGMI_CONVERGED: dict[str, str] = {
    "GuessFundCode": "自动分类/名称→代码（intent classify）",
    "SearchFunds": "intent screen fund（关键词搜基金）",
    "GetFundDiagnosis": "intent deep fund（先诊断，快照链回退）",
    "DiagnoseFundPortfolio": "intent portfolio（持仓组合诊断）",
    "GetAssetAllocationPlan": "intent plan（资产配置方案）",
}
TTSKILL_CONVERGED: dict[str, str] = {
    "TTFUND_SEARCH": "fund 快照链内嵌（名称→代码）",
    "TTFUND_BASE_INFOS": "fund 快照链内嵌（详情+业绩+风险族）",
    "TTFUND_HOLDING_INFO": "fund 快照链内嵌（重仓+行业+资产配置）",
    "TTFUND_GOLD_INFO": "intent deep commodity（黄金）",
    "TTFUND_INDEX_FUND_SELECTION": "research etf-rank（同指数基金横评 + 成分/估值）",
}
# westock（腾讯微证券）高频子命令 → cn 高层入口（2026-09-24 收敛）。
# 只登记已收敛的：长尾 40+ 子命令仍走 `invest-cli westock <子命令>` 透传，
# 清单以 `westock --help` 为准（不在此维护第二份，避免随版本漂移）。
WESTOCK_CONVERGED: dict[str, str] = {
    "notice": "cn notice（公告列表；--search 走巨潮 cninfo 检索）",
    "consensus": "cn consensus（一致预期：目标价 + 年度预测）",
    "shareholder": "cn holders（股东研究：十大股东 + 变动）",
    "disclosure": "cn disclosure（财报披露日历）",
    "report": "cn report（研报列表，可翻页）",
}
# 账户/交易域：invest-cli 定位只读数据分析，不为这些建高层入口（透传不新增权限，
# 但分析链路不消费持仓/下单类数据）。列在此处仅为清单标注。
_TTSKILL_BOUNDARY = {
    "ACCOUNT_HOLDING", "ACCOUNT_PROFIT", "TRADE_QUERY", "CONDITION_ORDER",
    "SIM_TRADE", "SUBACCOUNT", "RATION_PLAN",
}


def converge_status(source: str, tool_id: str) -> str:
    """外部工具 → invest-cli 收敛状态：✅ 已收敛 / 🔒 边界外 / ⬜ 透传可用。"""
    table = YINGMI_CONVERGED if source == "yingmi" else TTSKILL_CONVERGED
    if tool_id in table:
        return f"✅ {table[tool_id]}"
    if source == "ttskill" and tool_id in _TTSKILL_BOUNDARY:
        return "🔒 账户/交易域（不建高层入口，数据链路不消费）"
    if source == "yingmi":
        return "⬜ 透传: invest-cli yingmi <tool>"
    return "⬜ 透传: invest-cli ttskill <skill_id>"


# —— 动态清单获取（官方接口/本机索引为准，不手写第二份数据） ——
def _yingmi_tools() -> list[dict]:
    """盈米 OpenAPI 操作清单（直连 docs.json，不跑 yingmi-skill-cli）。"""
    try:
        from sources import yingmi as yingmi_src

        return yingmi_src.list_tools()
    except Exception:
        return []


def _ttskill_skills() -> list[dict]:
    """已装业务包清单：读本机 skills/index.json + 各包 SKILL.md 描述。

    旧实现跑 `ttskill skill list --json` 子进程；这里直接读官方落盘的索引，
    零子进程，且不把业务包本体搬进本仓。
    """
    from sources import ttskill as tts_src

    try:
        raw = json.loads(tts_src.SKILLS_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("skills") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for s in items:
        if not isinstance(s, dict) or not s.get("skill_id"):
            continue
        desc = ""
        install_path = str(s.get("install_path") or "")
        if install_path:
            md = Path(install_path) / "SKILL.md"
            try:
                if md.is_file():
                    text = md.read_text(encoding="utf-8", errors="ignore")[:600]
                    m = re.search(r"(?ms)^description:\s*[>|-]?\s*\n?(.*?)\n---", text)
                    if m:
                        desc = m.group(1).strip().splitlines()[0][:150]
            except OSError:
                pass
        out.append({
            "skill_id": str(s["skill_id"]),
            "status": str(s.get("status", "")),
            "description": desc,
        })
    return out


def _fmt_row(cells: list[str], widths: list[int]) -> str:
    return "  " + "  ".join(f"{c[:w]:<{w}}" for c, w in zip(cells, widths))


def run(source: str, as_json: bool = False) -> int:
    if source in ("", "sources", "all"):
        from sources import registry

        states = registry.detect_all()
        rows = [
            ["源", "优先级", "覆盖", "可用", "说明"],
            ["---", "---", "---", "---", "---"],
        ]
        for sid in sorted(states, key=lambda k: -states[k].get("priority", 0)):
            st = states[sid]
            avail = "✅" if st.get("available") else "❌"
            rows.append([st.get("name", sid), str(st.get("priority", "")),
                         ",".join(st.get("coverage", [])), avail, str(st.get("detail", ""))[:60]])
        if as_json:
            print(json.dumps({k: {"available": v["available"], "detail": v["detail"]}
                              for k, v in states.items()}, ensure_ascii=False, indent=2))
            return 0
        print("\n  数据源总览（invest-cli datasources 同源）\n")
        for row in rows:
            print(_fmt_row(row, [26, 6, 24, 4, 62]))
        print("\n  高层入口速查：")
        print("    fund <代码> / stock <代码> / us <代码> / screen <条件>")
        print("    quote <代码[,代码...]>                             免鉴权批量实时行情（跨市场，最省时）")
        print("    intent deep <fund|stock|bond|commodity> <标的>   意图深取")
        print("    intent screen/portfolio/plan/macro                意图筛选/组合/方案/宏观")
        print("    info <词> / watchlist                             资讯(argo)/自选")
        print("    cn <子命令> <代码>                                 A股/港股市场结构：notice 公告（--search 巨潮检索）")
        print("                                                      / consensus 一致预期 / holders 股东 / disclosure 披露日历 / report 研报")
        print("    sec <代码> [--search 词|--insiders|--events|--holdings]  SEC EDGAR：全文检索/内部人/事件/13F")
        print("    tenure <基金> [--manager 姓名] [--excel out.xlsx]  任职期复盘（分年度业绩/回撤 + 任职以来 vs 基准）")
        print("    westock <子命令>                                   腾讯微证券长尾能力（筹码/龙虎榜/资金流/")
        print("                                                      ESG/评级/产业链/板块估值）；高频五个已收敛到 cn；")
        print("                                                      `westock --help` 看 40+ 子命令")
        print("    透传（高级/补漏）：wind / yingmi / ttskill / htbr / sfg — 清单见下方子命令")
        print("    capabilities yingmi | ttskill | westock | sfg | htbr  官方能力清单+收敛标注")
        return 0

    if source == "yingmi":
        tools = _yingmi_tools()
        if not tools:
            print("盈米不可用（缺 apiKey）", file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps([{"name": t["name"], "status": converge_status("yingmi", t["name"]),
                               "description": t["description"]} for t in tools],
                             ensure_ascii=False, indent=2))
            return 0
        print(f"\n  盈米且慢工具清单（直连 OpenAPI 动态，共 {len(tools)} 个）\n")
        for t in sorted(tools, key=lambda x: (converge_status("yingmi", x["name"]).startswith("⬜"), x["name"])):
            line = f"  {t['name']:<38} {converge_status('yingmi', t['name'])}"
            print(line)
            desc = (t["description"] or "").replace("\n", " ")[:150]
            if desc:
                print(f"      {desc}")
        print("\n  参数以官方 schema 为准；拿不准先取官方工具描述，或搜 examples。")
        return 0

    if source == "ttskill":
        skills = _ttskill_skills()
        if not skills:
            print("ttskill 不可用或未安装（先 ttskill login --env prod）", file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps([{"skill_id": s["skill_id"], "status": converge_status("ttskill", s["skill_id"]),
                               "description": s["description"]} for s in skills],
                             ensure_ascii=False, indent=2))
            return 0
        print(f"\n  天天基金官方业务包（本机已装包索引，共 {len(skills)} 个）\n")
        for s in sorted(skills, key=lambda x: (converge_status("ttskill", x["skill_id"]).startswith("⬜"), x["skill_id"])):
            st = converge_status("ttskill", s["skill_id"])
            line = f"  {s['skill_id']:<34} {st}"
            print(line)
            if s["description"]:
                print(f"      {s['description'][:140]}")
        print("\n  透传调用示例：invest-cli ttskill MANAGER_INFO --input '{\"manager_name\":\"谢治宇\"}'")
        print("  参数以官方包 examples/*.example.json 为准。")
        return 0

    if source == "westock":
        if as_json:
            print(json.dumps([{"command": k, "status": v} for k, v in WESTOCK_CONVERGED.items()],
                             ensure_ascii=False, indent=2))
            return 0
        print("\n  westock 已收敛到 cn 高层入口（2026-09-24）\n")
        for cmd, status in WESTOCK_CONVERGED.items():
            print(f"  westock {cmd:<14} ✅ {status}")
        print("\n  其余 40+ 子命令仍走透传：invest-cli westock <子命令> [参数]")
        print("  完整命令树：invest-cli westock --help")
        return 0

    if source == "sfg":
        from sources import sfg as sfg_src

        items = [{"alias": k, "tool": v} for k, v in sfg_src.ALIASES.items()]
        # 别名表外的上游工具也要可见，否则「上游有、invest-cli 没登记」的能力
        # 在发现层是隐形的（agent 只会用 capabilities 里的东西）。分两类：
        # 可用（可直接 invest-cli sfg <工具名>）与边界外（投顾账户/报告存档域）。
        mapped = set(sfg_src.ALIASES.values())
        extra = [
            {"tool": t, "note": note}
            for t, note in sfg_src.TOOLS_UNMAPPED.items() if t not in mapped
        ]
        if as_json:
            print(json.dumps({"aliases": items, "other_tools": extra}, ensure_ascii=False, indent=2))
            return 0
        print(f"\n  见基行事(seefundgo) 公募基金 MCP 语义别名（共 {len(items)} 项）\n")
        for it in items:
            print(f"  sfg {it['alias']:<22} → {it['tool']}")
        if extra:
            print(f"\n  未建别名但可直传的工具（{len(extra)} 项；用完整 sfg_* 名调用）\n")
            for it in extra:
                mark = "🔒" if "边界外" in it["note"] else "⬜"
                print(f"  {mark} {it['tool']:<34} {it['note']}")
        print("\n  高层入口：intent deep fund / intent screen fund / intent portfolio / intent sfg")
        print("  组合体检走异步：portfolio-submit 拿 job_id，再 --poll <job_id>")
        print("  注意：本源为积分制，余额不足时所有工具被拒（通用取数请走妙想）")
        print(f"  出处标注：{sfg_src.ATTRIBUTION_LINE}")
        return 0

    if source == "htbr":
        from sources import htbr as htbr_src

        items = [{"alias": k, "api_id": v} for k, v in htbr_src.ALIASES.items()]
        if as_json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        print(f"\n  华泰柏瑞ETF 事实查询语义别名（共 {len(items)} 项，需内网/VPN）\n")
        for it in items:
            print(f"  htbr {it['alias']:<22} → {it['api_id']}")
        return 0

    print(f"未知 source: {source}（可选: yingmi / ttskill / westock / sfg / htbr / 空=总览）", file=sys.stderr)
    return 1
