"""sec 子命令：SEC EDGAR 美股数据（免费官方源，无需 key）。

用法:
    invest-cli sec <ticker> [--forms 10-K,10-Q,8-K] [--filings 5] [--years 5] [--quarterly] [--json]
        # 快照：最新年报指标 + 近 N 年序列 + 最近申报
    invest-cli sec <ticker> --search "关键词" [--forms 10-K] [--from 2025-01] [--to 2025-12] [--limit 10]
        # 全文检索：在**该公司申报正文**里找原文段落（EDGAR 全文索引 2001 年起）
    invest-cli sec <ticker> --insiders [--days 180] [--limit 20]
        # 内部人交易：Form 4 逐笔（谁、什么代码、多少股、什么价、交易后持股）
    invest-cli sec <ticker> --events [--days 365] [--limit 20]
        # 事件：8-K 逐事项（业绩/高管变动/协议/减值…）+ 13D/13G 权益变动
    invest-cli sec <投资人> --holdings [--limit 40]
        # 13F 机构持仓：机构名/CIK/上市代码 → 最新一期持仓（按发行人聚合）

数据 = SEC 官方原文口径；与 Wind / yfinance 的结构化数字交叉验证时以本命令为准。
一次只做一件事：--holdings/--insiders/--events/--search 互斥（同时给会报错）。
"""
from __future__ import annotations

import json
import sys
import unicodedata



def _disp_width(s: str) -> int:
    """终端显示宽度（CJK 双宽），用于对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _disp_width(s))


def _fmt_value(row: dict) -> str:
    value = row.get("value")
    unit = row.get("unit")
    if value is None:
        return "-"
    if unit == "USD/shares":
        return f"{float(value):,.2f} 美元/股"
    if unit == "USD":
        return f"{float(value) / 1e8:,.2f} 亿美元"
    if unit == "shares":
        return f"{float(value) / 1e8:,.2f} 亿股"
    return f"{value} {unit}"


def _fmt_usd(value) -> str:
    """美元金额 → 亿/万亿的可读形式（13F 与交易金额共用）。"""
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(v) >= 1e12:
        return f"{v / 1e12:,.2f} 万亿美元"
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.2f} 亿美元"
    return f"{v:,.0f} 美元"


def format_terminal(data: dict) -> str:
    from sources import sec_edgar

    lines: list[str] = []
    ticker = data.get("ticker") or ""
    name = data.get("name") or ticker
    lines.append("=" * 64)
    lines.append(f"  SEC EDGAR · {name}（{ticker}，CIK {data.get('cik')}）")
    lines.append("=" * 64)
    fy = data.get("fiscal_year")
    if fy:
        lines.append(f"  最新年报：FY{fy}（10-K，XBRL 原文口径）")
    lines.append("")
    lines.append(f"  {_pad('指标', 14)}{_pad('数值', 22)}us-gaap 标签")
    lines.append("  " + "-" * 60)
    metrics = data.get("metrics") or {}
    for key, label in sec_edgar.METRIC_LABELS.items():
        row = metrics.get(key)
        if not row:
            continue
        tag = row.get("tag") or ""
        lines.append(f"  {_pad(label, 14)}{_pad(_fmt_value(row), 22)}{tag}")
    series = data.get("series") or {}
    trend_keys = ["revenue", "gross_profit", "operating_income", "net_income",
                  "operating_cash_flow", "free_cash_flow", "assets", "equity", "eps_diluted"]
    trend = [(k, series.get(k)) for k in trend_keys if series.get(k)]
    if trend:
        years = sorted({str(r.get("fy")) for _, rows in trend for r in rows})
        lines.append("")
        lines.append(f"  近 {len(years)} 年趋势（亿美元；EPS 为美元/股）")
        lines.append("  " + _pad("指标", 14) + "".join(_pad(f"FY{y}", 12) for y in years))
        for key, rows in trend:
            by_fy = {str(r.get("fy")): r.get("value") for r in rows}
            cells = ""
            for y in years:
                v = by_fy.get(y)
                if v is None:
                    cells += _pad("-", 12)
                elif key == "eps_diluted":
                    cells += _pad(f"{float(v):,.2f}", 12)
                else:
                    cells += _pad(f"{float(v) / 1e8:,.0f}", 12)
            lines.append("  " + _pad(sec_edgar.METRIC_LABELS.get(key, key), 14) + cells)
    if data.get("quarterly"):
        lines.append("")
        lines.append("  季度序列已包含在 --json 输出（Q4 为推导值，标 derived）")
    filings = data.get("filings") or []
    if filings:
        lines.append("")
        lines.append("  最近申报：")
        for f in filings:
            lines.append(f"    {str(f.get('form', '')):<6} {f.get('filing_date', '')}  {f.get('url', '')}")
    if data.get("filings_error"):
        lines.append(f"  （申报清单获取失败：{data['filings_error']}）")
    lines.append("")
    lines.append(f"  来源：{data.get('source_url', '')}")
    return "\n".join(lines)


def format_search(data: dict) -> str:
    lines = [
        "=" * 64,
        f"  SEC 全文检索 · {data.get('name')}（{data.get('ticker')}）",
        f"  检索词：{data.get('query')}   命中 {data.get('total_hits')} 条，返回 {data.get('returned')} 条",
        "=" * 64,
    ]
    for r in data.get("results") or []:
        lines.append(f"\n  [{r.get('form')}] {r.get('filing_date')}  期至 {r.get('period_ending')}")
        lines.append(f"  {r.get('url')}")
        if r.get("snippet"):
            lines.append(f"    …{r['snippet']}")
    if not (data.get("results") or []):
        lines.append("\n  （无命中：换个词，或去掉 --forms/日期限制）")
    return "\n".join(lines)


def format_insiders(data: dict) -> str:
    lines = [
        "=" * 64,
        f"  内部人交易 · {data.get('name')}（{data.get('ticker')}）",
        f"  近 {data.get('days')} 天，扫描 {data.get('filings_scanned')} 份 Form 4",
        "=" * 64,
    ]
    rows = data.get("transactions") or []
    if not rows:
        lines.append("  （区间内没有 Form 4 申报）")
    for t in rows:
        amount = _fmt_usd(t.get("value")) if t.get("value") is not None else "-"
        price = f"@{t['price']:,.2f}" if t.get("price") is not None else ""
        shares = f"{float(t.get('shares') or 0):,.0f} 股"
        after = t.get("shares_after")
        after_txt = f"{float(after):,.0f}" if isinstance(after, (int, float)) else "-"
        lines.append(
            f"  {t.get('date')}  {_pad(str(t.get('owner') or ''), 20)}"
            f"{_pad(str(t.get('owner_role') or ''), 12)}"
            f"{_pad(str(t.get('code') or ''), 3)}{_pad(str(t.get('code_label') or ''), 18)}"
            f"{_pad(shares, 14)}{_pad(price, 12)}{_pad(amount, 16)}→ 持股 {after_txt}"
        )
    for err in data.get("errors") or []:
        lines.append(f"  （{err}）")
    return "\n".join(lines)


def format_events(data: dict) -> str:
    lines = [
        "=" * 64,
        f"  公司事件 · {data.get('name')}（{data.get('ticker')}）",
        "=" * 64,
    ]
    rows = data.get("events") or []
    if not rows:
        lines.append("  （区间内没有 8-K / 13D / 13G 申报）")
    for e in rows:
        labels = "、".join(i.get("label", "") for i in (e.get("items") or []))
        kind = "权益变动" if e.get("kind") == "ownership" else (labels or "8-K")
        lines.append(f"  {e.get('date')}  {_pad(str(e.get('form')), 10)}{kind}")
        lines.append(f"              {e.get('url')}")
    return "\n".join(lines)


def format_holdings(data: dict) -> str:
    unit = "美元" if data.get("value_unit") == "USD" else "千美元"
    lines = [
        "=" * 64,
        f"  13F 机构持仓 · {data.get('filer')}（CIK {data.get('filer_cik')}）",
        f"  报告期 {data.get('period')}，申报 {data.get('filed')}，"
        f"共 {data.get('holdings_count')} 个持仓，合计 {_fmt_usd(data.get('total_value'))}"
        + ("" if unit == "美元" else f"（{unit}口径）"),
        "=" * 64,
    ]
    lines.append(f"  {_pad('发行人', 34)}{_pad('CUSIP', 12)}{_pad('市值', 18)}{_pad('占比', 8)}股数")
    for h in data.get("holdings") or []:
        issuer = f"{h.get('issuer', '')} {h.get('class', '')}".strip()[:32]
        shares = f"{float(h.get('shares') or 0):,.0f}"
        pct = f"{h.get('pct')}%" if h.get("pct") is not None else "-"
        lines.append(
            f"  {_pad(issuer, 34)}{_pad(str(h.get('cusip') or ''), 12)}"
            f"{_pad(_fmt_usd(h.get('value')), 18)}{_pad(pct, 8)}{shares}"
        )
    lines.append("")
    lines.append(f"  说明：{data.get('note', '')}")
    return "\n".join(lines)


ACTIONS = ("holdings", "insiders", "events", "search")


def _brief_snapshot(res: dict) -> dict:
    """快照的 `--brief`：砍掉 5 年年度序列（体积主体），保留最新指标与申报清单。

    为什么单独给 sec：companyfacts 的 series 是 22 个指标 × 多年的矩阵，默认
    快照 28.5KB，经 agent 工具（24k 字符上限）会被截成坏 JSON。题面只问
    「营收/净利多少」时，series 是纯陪跑。
    """
    data = dict(res.get("data") or {})
    series = data.pop("series", None)
    quarterly = data.pop("quarterly", None)
    if series is not None:
        data["series_omitted"] = len(series or {})
    if quarterly is not None:
        data["quarterly_omitted"] = True
    data["brief"] = True
    return {**res, "data": data}


def run(ticker: str, forms: str = "", limit: int = 5, as_json: bool = False,
        years: int = 5, quarterly: bool = False, search: str = "",
        from_ym: str = "", to_ym: str = "", insiders: bool = False,
        events_flag: bool = False, holdings: bool = False, days: int = -1,
        rows_limit: int = 0, brief: bool = False) -> int:
    from sources import sec_edgar

    # `sec_edgar.filings` 内部用 `max(1, limit)` 兜底，所以 `--filings 0` 会
    # 静默返回 1 条、`--filings -3` 同样返回 1 条——参数被无声吞掉。
    # 「最近 0 条申报」本身没有意义，属于调用方写错，边界上直接报错比给一条
    # 意外数据更好（agent 拿到 1 条会以为参数生效了）。
    if limit < 1:
        print(f"错误: --filings 必须是 ≥1 的整数（收到 {limit}）", file=sys.stderr)
        return 1
    if days < -1 or years < 0 or rows_limit < 0:
        print("错误: --days（-1=按动作默认）不能小于 -1，--years/--limit 不能为负", file=sys.stderr)
        return 1
    chosen = [name for name, on in (
        ("--holdings", holdings), ("--insiders", insiders),
        ("--events", events_flag), ("--search", bool(search)),
    ) if on]
    if len(chosen) > 1:
        print(f"错误: 一次只做一件事（同时给了 {' 和 '.join(chosen)}）；"
              f"分多次调用，或去掉多余的旗标", file=sys.stderr)
        return 1
    form_list = [f.strip() for f in (forms or "").split(",") if f.strip()]
    # 快照的申报清单默认收窄到三类定期/临时报告（不然清单里全是 Form 4/SD 噪音）；
    # 全文检索**不**套这个默认——搜「供应承诺」可能命中 20-F/S-1，多一层隐式过滤
    # 会让人以为「没写」，其实是没搜。
    snapshot_forms = form_list or ["10-K", "10-Q", "8-K"]
    # days=-1 表示「按动作取默认」：内部人 180 天，事件不限（事件稀疏，
    # 半年窗口经常只剩两三条，看不出节奏）。
    ins_days = 180 if days < 0 else days
    ev_days = 0 if days < 0 else days

    if holdings:
        res = sec_edgar.institutional_holdings(ticker, limit=rows_limit or 40)
    elif insiders:
        res = sec_edgar.insider_trades(ticker, days=ins_days, limit=rows_limit or 20)
    elif events_flag:
        res = sec_edgar.events(ticker, limit=rows_limit or 20, days=ev_days)
    elif search:
        res = sec_edgar.filing_search(ticker, search, forms=form_list or None,
                                      from_ym=from_ym, to_ym=to_ym,
                                      limit=rows_limit or 10)
    else:
        res = sec_edgar.snapshot(ticker, forms=snapshot_forms, limit=limit,
                                 years=years, quarterly=quarterly)

    if as_json:
        # brief 只作用于「快照」这一个动作；检索/内部人/事件/13F 没有 series，
        # 加了 brief 也不该改变它们的形状。
        if brief and not any((search, insiders, events_flag, holdings)):
            res = _brief_snapshot(res)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if not res.get("ok"):
        print(f"SEC 取数失败: {res.get('error')}", file=sys.stderr)
        return 1
    data = res["data"]
    kind = res.get("kind")
    if kind == "filing_search":
        print(format_search(data))
    elif kind == "insider_trades":
        print(format_insiders(data))
    elif kind == "events":
        print(format_events(data))
    elif kind == "institutional_holdings":
        print(format_holdings(data))
    else:
        print(format_terminal(data))
    return 0
