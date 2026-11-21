"""SEC EDGAR XBRL companyfacts 抽取纯函数集（从 sec_edgar.py 拆出，免受体积红线挤压）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 400
QUARTER_MIN_DAYS = 60
QUARTER_MAX_DAYS = 110

# 指标 → 候选 us-gaap 标签（按优先级回退；标签漂移时取第一个存在的）。
# 2026-09-24 从 9 项扩到 24 项：三关/四维需要的负债、现金、资本开支、回购分红
# 原先只能靠 yfinance/Wind 侧补，原文级口径缺位。空列表 = 派生指标（见 DERIVED_METRICS）。
METRIC_TAGS: dict[str, list[str]] = {
    # 利润表
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "research_and_development": ["ResearchAndDevelopmentExpense"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    # 现金流
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "free_cash_flow": [],  # 派生：经营现金流 − 资本开支（同一期间）
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends_paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "dividends_per_share": [
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ],
    # 资产负债表
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent"],
    # dei 命名空间（不是 us-gaap）：流通股数
    "shares_outstanding": [],
}

# 派生指标：来源是同一期间的两个原始指标，不是 XBRL 标签。
# 只在两个来源指标都存在且期间一致时产出，绝不单边估算。
DERIVED_METRICS: dict[str, tuple[str, str, str]] = {
    # 指标: (被减项, 减项, 标签说明)
    "free_cash_flow": ("operating_cash_flow", "capex", "经营现金流 − 资本开支"),
}

METRIC_LABELS: dict[str, str] = {
    "revenue": "营业收入",
    "gross_profit": "毛利润",
    "operating_income": "营业利润",
    "net_income": "净利润",
    "eps_diluted": "稀释每股收益",
    "eps_basic": "基本每股收益",
    "research_and_development": "研发费用",
    "sga": "销售管理费用",
    "income_tax": "所得税费用",
    "operating_cash_flow": "经营现金流",
    "capex": "资本开支",
    "free_cash_flow": "自由现金流",
    "buybacks": "股票回购",
    "dividends_paid": "现金分红",
    "dividends_per_share": "每股股利",
    "assets": "总资产",
    "liabilities": "总负债",
    "equity": "股东权益",
    "cash": "现金及等价物",
    "long_term_debt": "长期债务",
    "inventory": "存货",
    "receivables": "应收账款",
    "shares_outstanding": "流通股数",
}

# dei 命名空间的事实（companyfacts 的 facts.dei），与 us-gaap 分开维护
DEI_TAGS: dict[str, list[str]] = {
    "shares_outstanding": ["EntityCommonStockSharesOutstanding"],
}


def _annual_rows(unit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤 10-K / FY，时长型事实要求年跨度，按期间升序返回。"""
    out: list[dict[str, Any]] = []
    for r in unit_rows or []:
        if r.get("form") != "10-K" or r.get("fp") != "FY":
            continue
        start, end = r.get("start"), r.get("end")
        if start:
            try:
                days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
            except (TypeError, ValueError):
                continue
            if not (ANNUAL_MIN_DAYS <= days <= ANNUAL_MAX_DAYS):
                continue
        out.append(r)
    out.sort(key=lambda r: (r.get("end", ""), r.get("start", "")))
    return out


def _unit_of(units: dict[str, Any]) -> str:
    for preferred in ("USD", "USD/shares"):
        if preferred in units:
            return preferred
    return next(iter(units), "")


def extract_annual(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从 companyfacts 抽取年报关键指标（最新一期）。纯函数，供离线测试。"""
    gaap = ((facts.get("facts") or {}).get("us-gaap")) or {}
    out: dict[str, dict[str, Any]] = {}
    for metric, tags in METRIC_TAGS.items():
        if not tags:  # 派生/独立命名空间指标，单独处理
            continue
        for tag in tags:
            node = gaap.get(tag)
            if not isinstance(node, dict):
                continue
            units = node.get("units") or {}
            unit = _unit_of(units)
            rows = _annual_rows(units.get(unit) or [])
            if not rows:
                continue
            last = rows[-1]
            out[metric] = {
                "value": last.get("val"),
                "unit": unit,
                "tag": tag,
                "fy": last.get("fy"),
                "start": last.get("start"),
                "end": last.get("end"),
                "form": last.get("form"),
            }
            break
    out.update(_dei_metrics(facts))
    _apply_derived(out)
    return out


def _dei_metrics(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """dei 命名空间指标（流通股数等）：取最近一个期末值。"""
    dei = ((facts.get("facts") or {}).get("dei")) or {}
    out: dict[str, dict[str, Any]] = {}
    for metric, tags in DEI_TAGS.items():
        for tag in tags:
            node = dei.get(tag)
            if not isinstance(node, dict):
                continue
            units = node.get("units") or {}
            unit = next(iter(units), "")
            rows = [r for r in (units.get(unit) or []) if r.get("val") is not None]
            if not rows:
                continue
            rows.sort(key=lambda r: r.get("end", ""))
            last = rows[-1]
            out[metric] = {
                "value": last.get("val"),
                "unit": unit,
                "tag": f"dei:{tag}",
                "fy": last.get("fy"),
                "start": last.get("start"),
                "end": last.get("end"),
                "form": last.get("form"),
            }
            break
    return out


def _apply_derived(out: dict[str, dict[str, Any]]) -> None:
    """就地计算派生指标：只在两个来源指标存在且期间一致时产出。"""
    for metric, (a, b, _note) in DERIVED_METRICS.items():
        ra, rb = out.get(a), out.get(b)
        if not ra or not rb:
            continue
        va, vb = ra.get("value"), rb.get("value")
        if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
            continue
        # 期间必须一致：不同财年/不同季度的两个数字相减是错的
        if (ra.get("start"), ra.get("end")) != (rb.get("start"), rb.get("end")):
            continue
        out[metric] = {
            "value": va - vb,
            "unit": ra.get("unit"),
            "tag": f"derived:{a}-{b}",
            "fy": ra.get("fy"),
            "start": ra.get("start"),
            "end": ra.get("end"),
            "form": ra.get("form"),
            "derived": True,
        }


def extract_series(facts: dict[str, Any], years: int = 5) -> dict[str, list[dict[str, Any]]]:
    """近 N 年年度序列（每年一行，升序）。纯函数，供离线测试。"""
    gaap = ((facts.get("facts") or {}).get("us-gaap")) or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for metric, tags in METRIC_TAGS.items():
        if not tags:
            continue
        for tag in tags:
            node = gaap.get(tag)
            if not isinstance(node, dict):
                continue
            units = node.get("units") or {}
            unit = _unit_of(units)
            rows = _annual_rows(units.get(unit) or [])
            if not rows:
                continue
            by_fy: dict[Any, dict[str, Any]] = {}
            for r in rows:
                key = r.get("fy") or r.get("end")
                by_fy[key] = r
            series = [
                {"fy": r.get("fy"), "end": r.get("end"), "value": r.get("val"),
                 "form": r.get("form"), "tag": tag, "unit": unit}
                for r in sorted(by_fy.values(), key=lambda x: (x.get("end", ""), x.get("start", "")))
            ]
            out[metric] = series[-max(1, years):]
            break
    _apply_derived_series(out)
    return out


def _apply_derived_series(out: dict[str, list[dict[str, Any]]]) -> None:
    """派生指标的年度序列：按 (start, end) 对齐两个来源序列后逐期相减。"""
    for metric, (a, b, _note) in DERIVED_METRICS.items():
        sa, sb = out.get(a) or [], out.get(b) or []
        if not sa or not sb:
            continue
        idx_b = {(r.get("start"), r.get("end")): r for r in sb}
        series: list[dict[str, Any]] = []
        for ra in sa:
            rb = idx_b.get((ra.get("start"), ra.get("end")))
            if not rb or not isinstance(ra.get("value"), (int, float)) or not isinstance(rb.get("value"), (int, float)):
                continue
            series.append({
                "fy": ra.get("fy"), "end": ra.get("end"),
                "value": ra["value"] - rb["value"],
                "form": ra.get("form"), "tag": f"derived:{a}-{b}",
                "unit": ra.get("unit"), "derived": True,
            })
        if series:
            out[metric] = series


def extract_quarterly(facts: dict[str, Any], quarters: int = 8) -> dict[str, list[dict[str, Any]]]:
    """近 N 个季度序列（升序）。纯函数，供离线测试。"""
    gaap = ((facts.get("facts") or {}).get("us-gaap")) or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for metric, tags in METRIC_TAGS.items():
        if not tags:
            continue
        for tag in tags:
            node = gaap.get(tag)
            if not isinstance(node, dict):
                continue
            units = node.get("units") or {}
            unit = _unit_of(units)
            rows = units.get(unit) or []
            if not rows:
                continue
            flow_rows = [r for r in rows if r.get("start")]
            if flow_rows:
                series = _quarterly_flow(flow_rows)
            else:
                series = _quarterly_instant(rows)
            if not series:
                continue
            out[metric] = series[-max(1, quarters):]
            break
    return out


def _span_days(r: dict[str, Any]) -> Optional[int]:
    start, end = r.get("start"), r.get("end")
    if not start or not end:
        return None
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
    except (TypeError, ValueError):
        return None


def _quarterly_flow(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """流量型季度序列：10-Q 的 Q1-Q3 + 推导 Q4。"""
    q: dict[tuple[Any, str], dict[str, Any]] = {}
    fy_rows: dict[Any, dict[str, Any]] = {}
    for r in rows:
        form = r.get("form")
        fp = r.get("fp")
        days = _span_days(r)
        if form == "10-Q" and fp in ("Q1", "Q2", "Q3") and days is not None \
                and QUARTER_MIN_DAYS <= days <= QUARTER_MAX_DAYS:
            key = (r.get("fy") or r.get("end"), fp)
            q[key] = r
        elif form == "10-K" and fp == "FY" and days is not None \
                and ANNUAL_MIN_DAYS <= days <= ANNUAL_MAX_DAYS:
            fy_rows[r.get("fy") or r.get("end")] = r
    series = [
        {"fy": r.get("fy"), "fp": r.get("fp"), "end": r.get("end"), "value": r.get("val"),
         "form": r.get("form"), "derived": False}
        for (_, fp), r in q.items()
    ]
    for fy, fyr in fy_rows.items():
        parts = [q.get((fy, fp)) for fp in ("Q1", "Q2", "Q3")]
        if any(p is None for p in parts) or fyr.get("val") is None:
            continue
        if any(p.get("val") is None for p in parts):
            continue
        series.append({
            "fy": fy, "fp": "Q4", "end": fyr.get("end"),
            "value": fyr["val"] - sum(p["val"] for p in parts),
            "form": fyr.get("form"), "derived": True,
        })
    series.sort(key=lambda r: (r.get("end") or "", r.get("fp") or ""))
    return series


def _quarterly_instant(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """时点型季度序列：10-Q/10-K 的期末值，按 end 去重（后者覆盖）。"""
    by_end: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("form") not in ("10-Q", "10-K") or r.get("val") is None:
            continue
        end = r.get("end")
        if not end:
            continue
        by_end[end] = r
    return [
        {"fy": r.get("fy"), "fp": r.get("fp"), "end": r.get("end"), "value": r.get("val"),
         "form": r.get("form"), "derived": False}
        for r in sorted(by_end.values(), key=lambda x: x.get("end", ""))
    ]
