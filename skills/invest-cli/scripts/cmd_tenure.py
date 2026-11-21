#!/usr/bin/env python3
"""invest-cli tenure —— 基金经理任职期复盘（分年度业绩/回撤 + 任职以来逐日收益 vs 业绩基准指数）。

为什么需要这条命令（第一性原理）：一次「某经理任职以来表现怎么样」的调研，人工要串
「在管清单 → 逐只档案/任职日/基准 → 分段取净值 → 取基准指数 → 分年度统计 → 复利累乘
→ Excel」七八步，且每步都踩同一个坑（Wind 净值单次只回 100 行 → 6 只基金 53 次调用、
人工编排 ≈14 分钟，实测 2026-09-23）。这些步骤**没有一步需要人的判断**，全是确定性取数与
算术；把它们固化成命令，调研就从「手工作业」变成「一次调用」。

用法:
    invest-cli tenure <基金代码|名称> [--manager 姓名] [--since YYYY-MM-DD]
                      [--benchmark auto|指数代码] [--source auto|wind|ttskill]
                      [--years 5] [--excel 路径.xlsx] [--json]
    invest-cli tenure --manager 姓名 [--company 公司] [--excel 路径.xlsx] [--json]

产物三层：
  1. 终端：档案 + 分年度业绩/回撤 + 任职以来（基金 vs 基准）+ 校验行；
  2. --json：结构化信封 {source, kind, ok, data, error}，供 agent 消费；
  3. --excel：工作簿（概览 / 每只基金明细 / 数据来源），供人复核与留档。

口径（与 Wind 官方字段对齐，改这里必须同步 scripts/test_tenure.py）：
  - 任职以来基期 = 任职日前一交易日复权净值（任职日即成立日时取成立日），
    与 Wind「区间收益率（复权单位净值增长率）」一致：任职当日收益计入；
  - 分年度收益率/最大回撤优先取 Wind 官方字段，本地复算只做交叉校验与补位；
  - 基准指数 = 基金代码 + BI.WI（万得编制的基金业绩比较基准指数），
    港股假期无行情，当日点位沿用前值。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from tenure_calc import (
    TOLERANCE_PP,
    annual_table,
    build_daily,
    default_years,
)

KIND = "tenure"
SHARE_CLASS_RE = re.compile(r"^(?P<stem>.+?)(?P<cls>[A-Z])$")
# 历任基金经理字段形如「周海栋(20210119-20250312)\r\n余懿(20250312至今)」
# 两种写法并存：区间 "周海栋(20210119-20250312)" 与在任 "余懿(20250312至今)"（后者没有连字符）
MGR_RE = re.compile(r"(?P<name>[^()\s]+)\((?P<start>\d{8})(?:-(?P<end>\d{8})|(?P<open>至今))\)")


# ═══ 解析层（纯函数，可单测） ═══

def parse_manager_history(history: str) -> list[dict[str, str]]:
    """Wind「历任基金经理姓名和任职时间」→ [{name, start, end}]（日期转 ISO）。"""
    out = []
    for m in MGR_RE.finditer(history or ""):
        out.append({
            "name": m.group("name").strip(),
            "start": _iso8(m.group("start")),
            "end": "" if m.group("open") else _iso8(m.group("end")),
        })
    return out


def _iso8(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s


def appointment_of(history: str, manager: str) -> str | None:
    """该经理在本基金的任职起始日；不在历任记录里返回 None（调用方按 --since/成立日兜底）。"""
    for rec in parse_manager_history(history):
        if rec["name"] == (manager or "").strip():
            return rec["start"]
    return None


def initial_share_only(funds: list[dict]) -> tuple[list[dict], list[dict]]:
    """按份额类别分组，每组只留初始份额（A 类或无类别后缀者）。

    为什么用命名规则而不是逐只查档案：份额类别**只体现在名称后缀**（A/C/E/I…），
    Wind 的在管清单一次就带回来；为每只基金再查一次档案去判类别，等于把 1 次调用
    变成 N 次，而收益为零。分组键是「去掉尾部单个大写字母后的名称」，
    同键内优先取 A 类，其次取无后缀者；单只独立成组，不受影响。
    """
    groups: dict[str, list[dict]] = {}
    for f in funds:
        m = SHARE_CLASS_RE.match(f["name"])
        stem = m.group("stem") if m else f["name"]
        groups.setdefault(stem, []).append(f)
    keep, dropped = [], []
    for stem, members in groups.items():
        if len(members) == 1:
            keep.append(members[0])
            continue
        picked = next((x for x in members if SHARE_CLASS_RE.match(x["name"]) and SHARE_CLASS_RE.match(x["name"]).group("cls") == "A"),
                      next((x for x in members if not SHARE_CLASS_RE.match(x["name"])), members[0]))
        keep.append(picked)
        dropped.extend(x for x in members if x is not picked)
    order = {f["code"]: i for i, f in enumerate(funds)}
    keep.sort(key=lambda x: order.get(x["code"], 99))
    dropped.sort(key=lambda x: order.get(x["code"], 99))
    return keep, dropped


def _short_err(err: Any, limit: int = 48) -> str:
    """把上游错误压成一行：Wind 的积分不足错误自带充值链接，原样进提示会淹掉正文。"""
    text = str(err or "").replace("\n", " ")
    if "积分" in text:
        return "Wind 积分余额不足"
    m = re.search(r"'text': '([^']+)'", text)
    if m:
        text = m.group(1)
    return text[:limit]


def _fcode(code: str) -> str:
    return code.split(".")[0]


# ═══ 取数层（源适配器 + 降级链） ═══

def fetch_nav(code: str, name: str, begin: str, end: str, prefer: str = "auto") -> dict:
    """任职区间复权净值序列：Wind 分段精确取数（默认）→ ttskill 快路径（降级）。

    为什么默认不是更快的 ttskill：它的日增长率只有 2 位小数、且成立后前 6 周是周频，
    实测任职以来累计会偏 0.20pct（001959）、单年偏 3.4pct；而本命令的产物要能对着
    Wind 终端逐位复核，精度优先。快路径留给「Wind 不可用」或用户显式 `--source ttskill`。
    """
    from sources import wind as wind_src

    warnings: list[str] = []
    if prefer in ("auto", "wind"):
        res = wind_src.fund_nav_series(code, name, begin, end)
        if res.get("ok"):
            return {"ok": True, "series": res["series"], "source": "wind",
                    "calls": res.get("calls"), "warnings": warnings, "error": None}
        if prefer == "wind":
            return {"ok": False, "series": [], "source": "wind", "warnings": warnings,
                    "error": f"Wind 取数失败：{res.get('error')}"}
        warnings.append(f"Wind 净值取数失败（{res.get('error')}），已回退 ttskill 快路径")
    from sources import ttskill as ttskill_src

    res = ttskill_src.nav_series(_fcode(code), begin)
    if not res.get("ok"):
        return {"ok": False, "series": [], "source": "ttskill", "warnings": warnings,
                "error": f"ttskill 取数失败：{res.get('error')}"}
    cov = res.get("coverage") or {}
    if cov.get("weekly_head"):
        warnings.append(f"ttskill 快路径：成立后前 6 周上游只给周频（{cov.get('head_rows_6w')} 行），"
                        "该段无逐日收益，累计口径已按累计净值差分补齐")
    if cov.get("recovered_growth_days"):
        warnings.append(f"ttskill 快路径：{cov.get('recovered_growth_days')} 个交易日无官方日增长率，"
                        "已用累计净值差分复原")
    warnings.append("ttskill 快路径的日增长率仅 2 位小数，长区间累计收益与 Wind 官方值可能存在 ≤0.3pct 偏差")
    return {"ok": True, "series": res["series"], "source": "ttskill",
            "calls": 1, "warnings": warnings, "error": None}


def fetch_index(idxcode: str, begin: str, end: str) -> dict:
    """业绩基准指数点位序列（唯一源：Wind —— BI.WI 是万得编制指数）。"""
    from sources import wind as wind_src

    res = wind_src.index_series(idxcode, begin, end)
    return {"ok": bool(res.get("ok")), "series": res.get("series") or [],
            "source": "wind", "error": res.get("error")}


# P3 超集预取的进程内交接区：manager 模式 run() 预取后写入，build_fund() 消费
# 后 pop。单只模式不经过这里，原 fetch_index 路径不变。
_INDEX_SUPERSET: dict = {}


def fetch_profile(code: str, name: str, prefer: str = "auto") -> dict:
    """基金档案：Wind（含历任任职时间，精确口径）→ ttskill（无任职记录，降级）。

    prefer="ttskill" 时**完全不碰 Wind**：Wind 每次调用都计费，快路径的语义就是零 Wind 依赖。
    """
    from sources import wind as wind_src

    if prefer == "ttskill":
        from sources import ttskill as ttskill_src

        alt = ttskill_src.base_profile(_fcode(code))
        if alt.get("ok"):
            return {"ok": True, "data": alt["data"], "source": "ttskill", "warnings": []}
        return {"ok": False, "data": None, "source": None, "error": f"ttskill 档案取数失败：{alt.get('error')}"}

    res = wind_src.fund_profile(code, name)
    if res.get("ok"):
        return {"ok": True, "data": res["data"], "source": "wind", "warnings": []}
    warnings = [f"Wind 档案取数失败（{_short_err(res.get('error'))}），已回退 ttskill"]
    from sources import ttskill as ttskill_src

    alt = ttskill_src.base_profile(_fcode(code))
    if not alt.get("ok"):
        return {"ok": False, "data": None, "source": None,
                "error": f"档案取数失败：Wind（{res.get('error')}）；ttskill（{alt.get('error')}）"}
    return {"ok": True, "data": alt["data"], "source": "ttskill", "warnings": warnings}


def build_fund(
    code: str,
    name: str,
    manager: str = "",
    since: str = "",
    benchmark: str = "auto",
    prefer: str = "auto",
    years: list[int] | None = None,
    as_of: str = "",
) -> dict:
    """单只基金的完整复盘结果（取数 + 计算 + 校验），失败时 ok=False 且带原因。"""
    from datetime import timedelta

    from sources import wind as wind_src

    warnings: list[str] = []
    # 代码归一：ttskill 在管清单给裸 6 位（001959），Wind 给 001959.OF；
    # 产物里必须只有一种写法，否则同一个基金在概览/明细/JSON 里长得像两只。
    code = code if code.endswith(".OF") else f"{_fcode(code)}.OF"
    prof = fetch_profile(code, name, prefer)
    if not prof.get("ok"):
        return {"ok": False, "code": code, "name": name, "error": prof.get("error")}
    profile = prof["data"] or {}
    warnings.extend(prof.get("warnings") or [])
    if name in (code, _fcode(code)) and profile.get("short_name"):
        name = profile["short_name"]  # 只给了代码时用档案简称回填，产物里不该出现裸代码当名称

    inception = profile.get("inception") or ""
    history = profile.get("manager_history") or ""
    resolved = resolve_appointment(code, manager, history, since)
    warnings.extend(resolved["warnings"])
    if not since:
        since = resolved["appointment"] or inception
    if not since:
        return {"ok": False, "code": code, "name": name,
                "error": "无法确定任职日：档案未返回成立日/任职记录，请用 --since 指定"}

    years = years or default_years(as_of or date.today().isoformat())
    # 取数下界 = 年度表要的最早基期（首年上年末）与任职期基期取更早者，但**不早于成立日**：
    #   · 早于成立日的分段必然返回空行，既烧 Wind 积分（按次计费）又会被判成取数失败；
    #   · 老基金（如 001959 成立于 2015）从成立日抓同样浪费 —— 年度表用不到的早年不必取。
    annual_begin = f"{years[0] - 1}-12-31"
    since_begin = (date.fromisoformat(since) - timedelta(days=7)).isoformat()
    begin = min(annual_begin, since_begin)
    if inception:
        begin = max(begin, inception)

    end = as_of or date.today().isoformat()
    nav = fetch_nav(code, name, begin, end, prefer)
    if not nav.get("ok"):
        return {"ok": False, "code": code, "name": name, "error": nav.get("error")}
    warnings.extend(nav.get("warnings") or [])
    series = nav["series"]
    last = series[-1][0]

    idxcode = benchmark if benchmark not in ("auto", "") else f"{_fcode(code)}BI.WI"
    # P3 超集预取的消费端：若调用方（manager 模式）已按同 idxcode 预取超集区间，
    # _INDEX_SUPERSET 命中则直接切片，省一次上游调用；未命中走原 fetch_index。
    idx = _INDEX_SUPERSET.pop(idxcode, None)
    if idx is None:
        idx = fetch_index(idxcode, begin, last)
    else:
        _s = idx.get("series") or []
        idx = {"ok": True, "series": [r for r in _s if begin <= str(r[0])[:10] <= last],
               "source": idx.get("source", "wind-superset"), "error": None}
    if not idx.get("ok"):
        warnings.append(f"基准指数 {idxcode} 取数失败（{_short_err(idx.get('error'))}），本次仅输出基金口径")

    official = {}
    if prefer == "ttskill":
        warnings.append("--source ttskill：本次不调用 Wind（年度字段由本地复算，累计值未经官方校验）")
    else:
        stats_res = wind_src.fund_annual_stats(code, name, years)
        if stats_res.get("ok"):
            official = stats_res["data"]
        else:
            warnings.append(f"Wind 官方年度字段未取到（{_short_err(stats_res.get('error'))}），年度表由本地复算填充")

    daily = build_daily(series, idx.get("series") or [], since)
    stats = daily["stats"]
    if idx.get("series"):
        stats["index_code"] = idxcode

    annual = annual_table(series, inception or since, since, years, official)

    # 校验：本地复算累计 vs Wind 区间收益率（同一口径，偏差 >0.05pct 必须暴露）
    checks = []
    off = ({"ok": False, "value": None, "error": "fast path"}
           if prefer == "ttskill" else wind_src.range_return(code, name, since, last))
    if off.get("ok") and off.get("value") is not None:
        diff = (stats["total"] - off["value"]) * 100.0
        checks.append({"name": "任职以来累计收益率", "local": stats["total"], "official": off["value"],
                       "diff_pp": diff, "ok": abs(diff) <= TOLERANCE_PP})
    elif prefer != "ttskill":
        warnings.append(f"Wind 区间收益率未取到（{_short_err(off.get('error'))}），累计值未经官方校验")
    worst = max((abs(a["diff_pp"]) for a in annual if a["diff_pp"] is not None), default=None)
    if worst is not None and worst > TOLERANCE_PP:
        warnings.append(f"年度收益率本地复算与官方字段最大偏差 {worst:.2f}pct，已以官方值为准")

    return {
        "ok": True,
        "code": code, "name": name, "full_name": profile.get("full_name") or name,
        "inception": inception, "managers": profile.get("managers") or manager,
        "manager": manager, "appointment": since,
        "benchmark": profile.get("benchmark") or "",
        "benchmark_index": idxcode if idx.get("series") else "",
        "fund_type": profile.get("fund_type") or "", "aum": profile.get("aum"),
        "as_of": last, "annual": annual, "tenure": stats,
        "daily": daily["rows"], "validations": checks,
        "sources": {"profile": prof.get("source"), "nav": nav.get("source"),
                    "nav_calls": nav.get("calls"),
                    "index": idx.get("source") if idx.get("series") else None,
                    "annual": "wind" if official else "local"},
        "warnings": warnings,
    }


def resolve_manager_funds(manager: str, company: str = "") -> dict:
    """经理 → 在管产品清单：Wind search_funds（含份额类别与公司）→ ttskill MANAGER_INFO。"""
    from sources import wind as wind_src

    res = wind_src.manager_funds(manager, company)
    if res.get("ok"):
        return {"ok": True, "funds": res["rows"], "source": "wind", "warnings": []}
    from sources import ttskill as ttskill_src

    alt = ttskill_src.manager_funds(manager)
    if not alt.get("ok"):
        return {"ok": False, "funds": None, "source": None,
                "error": f"在管清单取数失败：Wind（{_short_err(res.get('error'))}）；"
                         f"ttskill（{alt.get('error')}）"}
    rows = alt["rows"]
    if company:
        rows = [r for r in rows if company in (r.get("company") or "")] or rows
    return {"ok": True, "funds": rows, "source": "ttskill",
            "warnings": [f"Wind 在管清单取数失败（{_short_err(res.get('error'))}），已回退 ttskill"]}


def resolve_appointment(code: str, manager: str, history: str = "", since: str = "") -> dict:
    """任职日解析：--since > 档案历任任职时间 > 经理在管清单的任职日 > 空（调用方退回成立日）。"""
    if since:
        return {"appointment": since, "source": "arg", "warnings": []}
    if manager:
        hit = appointment_of(history, manager)
        if hit:
            return {"appointment": hit, "source": "profile", "warnings": []}
        from sources import ttskill as ttskill_src

        alt = ttskill_src.manager_funds(manager)
        if alt.get("ok"):
            for row in alt["rows"]:
                if _fcode(row.get("code") or "") == _fcode(code) and row.get("appt"):
                    return {"appointment": row["appt"], "source": "ttskill_manager",
                            "warnings": [f"任职日取自 ttskill 经理在管清单（{row['appt']}）"]}
        return {"appointment": "", "source": None,
                "warnings": [f"未在档案/在管清单中找到 {manager} 的任职记录，改用基金成立日"]}
    return {"appointment": "", "source": None, "warnings": []}


# ═══ 渲染层 ═══

def _pct(x: float | None, digits: int = 2) -> str:
    return "-" if x is None else f"{x * 100:+.{digits}f}%"


MODE_LABEL = {
    "full": "完整年度", "since_incep": "成立日至年末", "未成立": "未成立", "未任职": "未任职",
}


def render_fund(r: dict) -> str:
    lines: list[str] = []
    if not r.get("ok"):
        return f"  {r.get('code', '')} {r.get('name', '')} — 失败：{r.get('error')}"

    who = r.get("manager") or r.get("managers") or ""
    lines.append(f"\n{'=' * 68}")
    lines.append(f"  {r['name']}（{r['code']}）— {who} 任职期复盘")
    lines.append(f"{'=' * 68}")
    t = r["tenure"]
    lines.append(f"  数据截至 {r['as_of']} · 任职日 {r['appointment']}（基期 {t['base_date']} · "
                 f"复权净值 {t['base_nav']:.4f}）· {t['n']} 个交易日")
    if r.get("benchmark"):
        lines.append(f"  业绩比较基准  {r['benchmark']}")
    if r.get("benchmark_index"):
        lines.append(f"  基准指数      {r['benchmark_index']}")

    lines.append(f"\n  {'分年度业绩（收益率 / 最大回撤）':<28}")
    lines.append(f"  {'-' * 60}")
    as_of_year = int((r.get("as_of") or "")[:4] or 0)
    for a in r["annual"]:
        ylabel = f"{a['year']}YTD" if a["year"] == as_of_year else f"{a['year']}"
        mode = MODE_LABEL.get(a["mode"], a["mode"])
        if a["year"] == as_of_year and a["mode"] == "full":
            mode = "年内至今"
        lines.append(f"    {ylabel:<8} {_pct(a['ret']):>10} / {_pct(a['mdd']):>10}   {mode}")

    lines.append(f"\n  {'任职以来 vs 基准':<28}")
    lines.append(f"  {'-' * 60}")
    lines.append(f"    基金累计   {_pct(t['total']):>10}   年化 {_pct(t['annualized'])}")
    if t.get("index_total") is not None:
        lines.append(f"    基准累计   {_pct(t['index_total']):>10}   年化 {_pct(t['index_annualized'])}")
        lines.append(f"    累计超额   {_pct(t['excess']):>10}")
        if t.get("filled_days"):
            lines.append(f"    注：基准指数 {t['filled_days']} 个交易日无行情（港股假期），点位沿用前值")

    for c in r.get("validations") or []:
        mark = "✓" if c["ok"] else "✗ 超差"
        lines.append(f"  校验  {c['name']} 本地 {_pct(c['local'])} vs Wind 官方 {_pct(c['official'])}"
                     f"（偏差 {c['diff_pp']:+.2f}pct）{mark}")
    for w in r.get("warnings") or []:
        lines.append(f"  提示  {w}")
    return "\n".join(lines)


def render_terminal(payload: dict) -> str:
    d = payload["data"]
    lines = []
    if d.get("mode") == "manager":
        lines.append(f"\n{'=' * 68}")
        lines.append(f"  {d['manager']} 在管基金任职期复盘（初始份额 {len(d['funds'])} 只）")
        lines.append(f"{'=' * 68}")
        if d.get("dropped"):
            lines.append("  已按初始份额口径剔除：" +
                         "、".join(f"{x['code']} {x['name']}" for x in d["dropped"]))
    for r in d["funds"]:
        lines.append(render_fund(r))
    ok = [r for r in d["funds"] if r.get("ok")]
    if len(d["funds"]) > 1:
        lines.append(f"\n{'=' * 68}")
        lines.append("  汇总（任职以来累计 / 基准 / 超额）")
        lines.append(f"  {'-' * 60}")
        for r in ok:
            t = r["tenure"]
            lines.append(f"    {r['code']} {r['name']:<14} {_pct(t['total']):>10} / "
                         f"{_pct(t.get('index_total')):>10} / {_pct(t.get('excess')):>10}")
    return "\n".join(lines)


# ═══ 产物层：表格单一真源 + 两个写出器（xlsx / csv） ═══
#
# 为什么先建表再写盘：Excel 与 CSV 是同一份数据的两种容器，若各自定义列，
# 加一列就得改两处、漏一处就静默丢字段。表格在这里只定义一次，写出器只负责格式。

KIND_DATE, KIND_TEXT, KIND_NUM4, KIND_PCT2, KIND_PCT4 = "date", "text", "num4", "pct2", "pct4"


def build_tables(payload: dict) -> list[dict]:
    """产物表格：[{name, header, rows, kinds}]。CSV 与 Excel 共用，保证两容器字段一致。"""
    d = payload["data"]
    funds = [r for r in d["funds"] if r.get("ok")]
    years = [a["year"] for a in funds[0]["annual"]] if funds else []
    as_of = funds[0]["as_of"] if funds else "-"

    header = ["基金代码", "基金名称", "基金成立日", "基金经理", "任职日"]
    kinds = [KIND_TEXT, KIND_TEXT, KIND_DATE, KIND_TEXT, KIND_DATE]
    as_of_year = int(as_of[:4]) if as_of[:4].isdigit() else 0
    for y in years:
        tag = f"{y}YTD" if y == as_of_year else f"{y}"
        header += [f"{tag}收益率", f"{tag}最大回撤"]
        kinds += [KIND_PCT2, KIND_PCT2]
    header += ["业绩比较基准", "业绩基准指数代码", "任职以来累计收益率", "任职以来年化收益率", "备注"]
    kinds += [KIND_TEXT, KIND_TEXT, KIND_PCT2, KIND_PCT2, KIND_TEXT]
    rows = []
    for r in funds:
        t = r["tenure"]
        row = [r["code"], r["name"], r.get("inception") or "",
               r.get("managers") or r.get("manager") or "", r["appointment"]]
        for a in r["annual"]:
            for k in ("ret", "mdd"):
                v = a[k]
                row.append(v if v is not None else MODE_LABEL.get(a["mode"], a["mode"]))
        notes = []
        for a in r["annual"]:
            if a["mode"] == "since_incep":
                notes.append(f"{a['year']} 年为成立日至年末口径")
            elif a["mode"] == "未任职":
                notes.append(f"{a['year']} 年未任职（业绩未列示）")
        if (r.get("sources") or {}).get("nav") != "wind":
            notes.append(f"净值源：{r.get('sources', {}).get('nav')} 快路径（精度与口径见「数据来源」表）")
        if not r.get("benchmark_index"):
            notes.append("业绩基准指数缺失（Wind 不可用），本次仅基金口径")
        row += [r.get("benchmark") or "", r.get("benchmark_index") or "",
                t["total"], t["annualized"], "；".join(notes)]
        rows.append(row)
    tables = [{"name": "概览", "header": header, "rows": rows, "kinds": kinds}]

    for r in funds:
        rows = []
        for x in r["daily"]:
            rows.append([x["date"], x["nav"], x["ret"], x["cum"],
                         r.get("benchmark_index") or "", x["index"], x["index_ret"],
                         x["index_cum"], x["excess"], x["note"]])
        tables.append({
            "name": f"{_fcode(r['code'])}{r['name']}"[:31],
            "header": ["日期", "基金复权单位净值", "基金日收益率", "基金累计收益率", "基准指数代码",
                       "基准指数收盘点位", "基准指数日收益率", "基准指数累计收益率",
                       "累计超额收益率(基金-基准)", "备注"],
            "rows": rows,
            "kinds": [KIND_DATE, KIND_NUM4, KIND_PCT4, KIND_PCT2, KIND_TEXT, KIND_NUM4,
                      KIND_PCT4, KIND_PCT2, KIND_PCT2, KIND_TEXT],
        })

    src_rows = [
        ["数据源", _source_note(funds)],
        ["基金范围", "初始份额（A 类或无类别后缀的份额），不含 C 类等后续份额。"],
        ["基准指数", "基金代码 + BI.WI（万得编制的基金业绩比较基准指数，基点 1000）。"],
        ["任职以来口径", "基期 = 任职日前一交易日复权净值（任职日即成立日时取成立日）；日收益率 = 复权净值日环比；"
                    "累计收益率 = 期末/基期 - 1；年化按 365 自然日。"],
        ["年度口径", "收益率与最大回撤取 Wind 官方字段（年度最大回撤为年内峰值→谷值口径，不跨年回溯）；"
                  "基金年内成立或经理年内任职的年度，取成立日/任职日起的可获得区间并标注。"],
        ["港股假期", "含港股仓位的基准指数在港股假期无行情，当日点位沿用前值（日收益记 0）。"],
        ["校验", "任职以来累计收益率与 Wind 区间收益率逐只比对；分年度收益率与官方字段比对，"
               "偏差超过 0.05pct 在「备注」列提示。"],
        ["数据截至", as_of],
        ["免责声明", "本表基于公开数据整理，仅供研究参考，不构成投资建议。"],
    ]
    tables.append({"name": "数据来源", "header": ["项目", "说明"], "rows": src_rows,
                   "kinds": [KIND_TEXT, KIND_TEXT]})
    return tables


def _source_note(funds: list[dict]) -> str:
    """按实际用到的源生成说明（降级时不能还写「数据来自 Wind」）。"""
    used = {r.get("sources", {}).get("nav") for r in funds} | {r.get("sources", {}).get("index") for r in funds}
    used.discard(None)
    parts = []
    if "wind" in used:
        parts.append("万得 Wind（复权净值 get_fund_performance 分段并行取数，单次硬顶 100 行；"
                     "基准指数 get_index_kline；档案 get_fund_info；年度字段为官方字段）")
    if "ttskill" in used:
        parts.append("天天基金官方 gateway（成立来净值序列 TTFUND_NAV_INFO；档案 TTFUND_BASE_INFOS；"
                     "经理在管清单 TTFUND_MANAGER_INFO）")
    return "；".join(parts) + "。降级路径的日增长率为 2 位小数，长区间累计与 Wind 官方值可能有 ≤0.3pct 偏差。"


def write_excel(tables: list[dict], path: Path, title: str, subtitle: str) -> None:
    """概览 / 每只基金明细 / 数据来源 → xlsx。openpyxl 懒加载（只服务本产物）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    fmt = {KIND_PCT2: "0.00%;[Red]-0.00%", KIND_PCT4: "0.0000%;[Red]-0.0000%",
           KIND_NUM4: "0.0000", KIND_DATE: "yyyy-mm-dd"}
    hdr_fill = PatternFill("solid", fgColor="1F4E79")
    hdr_font = Font(color="FFFFFF", bold=True, size=10)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    wb = Workbook()
    wb.remove(wb.active)
    for tb in tables:
        ws = wb.create_sheet(tb["name"])
        ws.append(tb["header"])
        for c in ws[1]:
            c.fill, c.font = hdr_fill, hdr_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        ws.row_dimensions[1].height = 30
        for row in tb["rows"]:
            ws.append(row)
        for i, kind in enumerate(tb["kinds"], start=1):
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                c = row[0]
                c.border = border
                if kind in fmt:
                    c.number_format = fmt[kind]
                    if kind == KIND_DATE and isinstance(c.value, str):
                        c.value = date.fromisoformat(c.value)
                elif isinstance(c.value, str):
                    c.alignment = Alignment(vertical="top", wrap_text=len(c.value) > 30)
        widths = []
        for i, h in enumerate(tb["header"], start=1):
            vals = [len(str(r[i - 1])) for r in tb["rows"][:200] if r[i - 1] is not None] or [0]
            widths.append(max(10, min(46, max([len(h) * 2 + 2] + vals))))
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        if len(tb["header"]) > 2:
            ws.freeze_panes = "B2"
    ws = wb["数据来源"]
    ws.insert_rows(1, 2)
    ws.cell(1, 1, title).font = Font(bold=True, size=13)
    ws.cell(2, 1, subtitle).font = Font(size=9, color="808080")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_csv(tables: list[dict], out_dir: Path) -> list[Path]:
    """无 openpyxl 时的等价产物：每张表一个 UTF-8-BOM CSV（Excel 双击即正常显示中文）。"""
    import csv

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for tb in tables:
        path = out_dir / f"{tb['name']}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(tb["header"])
            for row in tb["rows"]:
                out = []
                for v, kind in zip(row, tb["kinds"]):
                    if v is None:
                        out.append("")
                    elif kind == KIND_PCT2 and isinstance(v, (int, float)):
                        out.append(f"{v * 100:.2f}%")
                    elif kind == KIND_PCT4 and isinstance(v, (int, float)):
                        out.append(f"{v * 100:.4f}%")
                    elif kind == KIND_NUM4 and isinstance(v, (int, float)):
                        out.append(f"{v:.4f}")
                    else:
                        out.append(v)
                w.writerow(out)
        written.append(path)
    return written


# ═══ 命令入口 ═══

def run(
    keyword: str = "",
    manager: str = "",
    company: str = "",
    since: str = "",
    benchmark: str = "auto",
    prefer: str = "auto",
    years: int = 5,
    excel: str = "",
    csv_dir: str = "",
    brief: bool = False,
    as_json: bool = False,
) -> int:
    funds: list[dict] = []
    dropped: list[dict] = []
    meta: dict[str, Any] = {"manager": manager, "company": company, "mode": "single"}

    if not keyword and not manager:
        print("tenure 错误: 需要 <基金代码|名称> 或 --manager 姓名", file=sys.stderr)
        return 2

    if manager and not keyword:
        meta["mode"] = "manager"
        res = resolve_manager_funds(manager, company)
        if not res.get("ok"):
            print(f"tenure 错误: {res.get('error')}", file=sys.stderr)
            return 1
        keep, dropped = initial_share_only(res["funds"])
        yl = default_years(date.today().isoformat(), years)
        # P0 多基金并行：build_fund 是纯函数（输入 code/name/manager/benchmark
        # → 输出 dict，无共享状态），ThreadPoolExecutor 安全。Wind 按次计费
        # 不按并发计费；顺序用 map 保持与 keep 一致，产物可比性不变。
        # P3 超集预取：同 benchmark（或同 auto 解析结果）的多只基金，先拉一次
        # [min(基期下界) → max(end)] 超集指数，各 build_fund 内切片复用。
        # 超集键是 idxcode；auto 模式下各基金 BI.WI 不同，不预取（key 必然不一致）。
        from concurrent.futures import ThreadPoolExecutor
        _jobs = [(f["code"], f["name"]) for f in keep]
        if len(_jobs) > 1 and benchmark not in ("auto", ""):
            _begins, _ends = [], []
            for _c, _n in _jobs:
                _prof = fetch_profile(_c if _c.endswith(".OF") else f"{_fcode(_c)}.OF", _n, prefer)
                _pd = _prof.get("data") or {}
                _since = (resolve_appointment(_c, manager, _pd.get("manager_history") or "", "").get("appointment")
                          or _pd.get("inception") or "")
                if _since:
                    from datetime import timedelta as _td
                    _b = min(f"{yl[0] - 1}-12-31",
                             (date.fromisoformat(_since) - _td(days=7)).isoformat())
                    if _pd.get("inception"):
                        _b = max(_b, _pd["inception"])
                    _begins.append(_b)
            _end = date.today().isoformat()
            if _begins:
                _super = fetch_index(benchmark, min(_begins), _end)
                if _super.get("ok") and _super.get("series"):
                    _INDEX_SUPERSET[benchmark] = _super
        if len(_jobs) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(_jobs))) as _pool:
                funds.extend(list(_pool.map(
                    lambda _cn: build_fund(_cn[0], _cn[1], manager=manager, since="",
                                           benchmark=benchmark, prefer=prefer, years=yl),
                    _jobs)))
            _INDEX_SUPERSET.clear()
        else:
            for f in keep:
                funds.append(build_fund(f["code"], f["name"], manager=manager, since="",
                                        benchmark=benchmark, prefer=prefer, years=yl))
    else:
        code = keyword
        name = keyword
        if not (keyword.isdigit() and len(keyword) == 6) and not keyword.endswith(".OF"):
            from sources import ttskill as ttskill_src

            try:
                fcode, fname = ttskill_src.resolve_fcode(keyword)
                code, name = fcode, fname
            except Exception as e:  # noqa: BLE001 —— 名称解析失败时把原因交给用户
                print(f"tenure 错误: 无法解析基金名称「{keyword}」（{e}）", file=sys.stderr)
                return 1
        code = code if code.endswith(".OF") else f"{_fcode(code)}.OF"
        yl = None
        if years:
            yl = default_years(date.today().isoformat(), years)
        funds.append(build_fund(code, name, manager=manager, since=since,
                                benchmark=benchmark, prefer=prefer, years=yl))

    if brief:
        # 逐日序列占 JSON 的 95%（6 只基金 ≈1.1MB），喂给 agent 会直接吃掉上下文窗口；
        # 只要结论时用 --brief，要明细就用 --excel/--csv 落盘。
        for f in funds:
            f.pop("daily", None)
    payload = {
        "source": "wind", "kind": KIND, "ok": any(f.get("ok") for f in funds),
        "data": {"manager": manager, "company": company, "mode": meta["mode"],
                 "dropped": dropped, "funds": funds},
        "error": None if any(f.get("ok") for f in funds) else (funds[0].get("error") if funds else "无数据"),
    }

    tables = build_tables(payload) if (excel or csv_dir) else []
    as_of = next((f["as_of"] for f in funds if f.get("ok")), "-")
    if csv_dir:
        written = write_csv(tables, Path(csv_dir).expanduser())
        print(f"已导出 {len(written)} 个 CSV: {Path(csv_dir).expanduser()}", file=sys.stderr)
    if excel:
        path = Path(excel).expanduser()
        title = (f"{manager} 任职期复盘" if manager else f"{funds[0].get('name', '')} 任职期复盘")
        subtitle = f"生成时间 {date.today().isoformat()} · 数据截至 {as_of} · 由 invest-cli tenure 生成"
        try:
            write_excel(tables, path, title, subtitle)
            print(f"已导出: {path}", file=sys.stderr)
        except ImportError:
            # 拿不到 xlsx 也不该拿不到数据：同表同口径落成 CSV，并给出打开 xlsx 的下一步
            csv_fallback = path.with_suffix("")
            written = write_csv(tables, csv_fallback)
            print(f"未安装 openpyxl，已改为导出 {len(written)} 个 CSV: {csv_fallback}", file=sys.stderr)
            print("需要 xlsx 时执行: uv pip install --python ~/.agents/skills/invest-cli/.venv/bin/python openpyxl",
                  file=sys.stderr)

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_terminal(payload))
    return 0 if payload["ok"] else 1


def main() -> None:  # 便于 `python3 cmd_tenure.py` 直接调试
    import argparse

    p = argparse.ArgumentParser(description="基金经理任职期复盘")
    p.add_argument("keyword", nargs="?", default="")
    p.add_argument("--manager", default="")
    p.add_argument("--company", default="")
    p.add_argument("--since", default="")
    p.add_argument("--benchmark", default="auto")
    p.add_argument("--source", dest="prefer", default="auto")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--excel", default="")
    p.add_argument("--csv", dest="csv_dir", default="")
    p.add_argument("--brief", action="store_true", help="JSON 里不带逐日序列（只要结论时用）")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    sys.exit(run(a.keyword, a.manager, a.company, a.since, a.benchmark, a.prefer,
                 a.years, a.excel, a.csv_dir, a.brief, a.json))


if __name__ == "__main__":
    main()
