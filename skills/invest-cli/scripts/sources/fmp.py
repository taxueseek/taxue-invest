"""Financial Modeling Prep（FMP）美股深取适配器（invest-cli 数据源）。

定位：**深取专项源**（sec_edgar 同型，不进快照链）——免费档 250 次/天扛不住
日常兜底消耗，但一次深取能拿到别处没有的加工数据。默认快照链的 us 兜底已由
tiingo 承担，本源与 sec_edgar 分工：
  - sec_edgar：10-K XBRL **原文级**（官方免费，申报清单/Form 4/8-K/13F）
  - fmp：**加工好**的三表 JSON + TTM 比率 + 结构化评级 + 年度分析师预测

免费档实测边界（2026-09-30，用真实 key 逐端点验证，/stable 版）：
  通：quote（含 50/200 日均线）、profile（sector/industry/CEO/员工/CIK/ISIN/上市日）、
      三表 annual（income/balance/cash-flow，fiscalYear/filingDate 齐全）、
      key-metrics-ttm（EV 系）、ratios-ttm（利润率/流动性/杠杆/股息；**ROE/ROA=null**
      ——免费档不给，要从三表自己算）、ratings-snapshot（字母评级+6 维分项分）、
      analyst-estimates（**annual 可用，quarterly 402 付费**）、
      dividends 历史 + dividends-calendar（市场级）、historical-price-eod/full（约 5 年）
  锁：etf-holdings 明确 402 付费墙；peers/press-releases/insider-trading/sec-filings
      在 stable 下 404
错误形态（实测）：缺/坏 key → 401 "Invalid API KEY"；付费端点 → 402 "Restricted
  Endpoint"；**标的不在订阅覆盖 → 也回 402**（"Premium Query Parameter"），与付费墙
  同码，必须按文案分流；超限 → "Too many requests"。

单位纪律（与 cmd_us 渲染器约定对齐）：change_pct 百分数（FMP 原生就是百分数）；
margins/dividend_yield 小数（FMP 原生小数，直传）；market_cap 绝对值。

安全约束（SSRF 闸）：_get_json 是唯一 HTTP 出口，四层闸（仅 https / host 白名单
/ 请求前 DNS 逐 IP 公网校验 / 禁重定向）全部收口在 sources/_http.guarded_open——
tiingo 与本模块曾各持一份内联实现、与 _http 三处并行，闸的任何一层演进都要同步
三处，漏一处就是真实缺口（第九轮 2026-11-08 并口）。本模块只保留信封语义与
402 付费墙 / 覆盖外的文案分流。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ._http import guarded_open

SOURCE_LABEL = "FMP 美股深取"
API_HOST = "financialmodelingprep.com"
API_BASE = f"https://{API_HOST}/stable"
ENV_KEY = "FMP_API_KEY"
DEFAULT_TIMEOUT = 15
PROBE_USER_AGENT = "invest-cli/1.0 (fmp source)"

_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,11}$")


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "fmp.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "fmp.env",
    ]
    return [p for p in cands if p.is_file()]


def load_api_key() -> Optional[str]:
    from .env import read_credential_file, read_env

    val = read_env(ENV_KEY)
    if val:
        return val
    return read_credential_file(ENV_KEY, credential_files()) or None


def detect() -> tuple[bool, str]:
    if load_api_key():
        return True, f"{ENV_KEY} 已配置（三表/TTM 比率/评级/年度预测 深取）"
    return False, f"缺少 {ENV_KEY} 且无凭据文件（~/.config/invest-cli/fmp.env）"


def normalize_ticker(symbol: str) -> str:
    t = re.sub(r"\s+", "", str(symbol or "").strip().upper())
    return t if _TICKER_RE.match(t) else ""


def _get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[Optional[Any], Optional[str]]:
    """唯一 HTTP 出口：闸（https/白名单/逐 IP 公网校验/禁重定向）走共享 guarded_open。

    本函数只保留信封语义：(payload, err) 元组与错误文案分流。
    402 的两种文案必须分流（实测同码不同义）：
      - "Restricted Endpoint" → 该**端点**在付费墙内
      - "Premium Query Parameter"/"Special Endpoint" → 该**标的**不在订阅覆盖
        （免费档查无此票也走这条），按「未找到」处理
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None, "URL 非法"
    if parts.scheme != "https" or parts.hostname != API_HOST:
        return None, f"拒绝非 {API_HOST} 的 https 请求"
    req = urllib.request.Request(url, headers={"User-Agent": PROBE_USER_AGENT})
    try:
        with guarded_open(req, timeout=timeout, allowed_host=API_HOST) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except ValueError as e:
        return None, f"host 校验拒绝: {e}"
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        detail = raw[:200]
        try:
            detail = str(json.loads(raw).get("Error Message") or raw)[:200]
        except Exception:
            pass
        if e.code == 401:
            return None, f"鉴权失败 HTTP 401：key 无效或缺失（{detail}）"
        if e.code == 402:
            if "Restricted Endpoint" in raw:
                return None, f"该端点在 FMP 付费墙内（当前订阅不含）：{detail}"
            return None, f"未找到标的或不在订阅覆盖内（FMP HTTP 402）：{detail}"
        if e.code == 429:
            return None, f"FMP 超出限额（免费档 250 次/天）：{detail or 'Too many requests'}"
        return None, f"FMP HTTP {e.code}: {detail or e.reason}"
    except (urllib.error.URLError, OSError) as e:
        return None, f"FMP 请求失败: {e}"
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, "FMP 返回非 JSON"


def _url(path: str, **params: Any) -> str:
    key = load_api_key()
    qs = urllib.parse.urlencode({"apikey": key, **{k: v for k, v in params.items() if v is not None}})
    return f"{API_BASE}{path}?{qs}"


def _first_row(payload: Any, err: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    if err:
        return None, err
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0], None
    return None, None  # 空数组=该票无此数据，不算传输错误


def _fetch_quote(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    payload, err = _get_json(_url("/quote", symbol=ticker))
    return _first_row(payload, err)


def _fetch_profile(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    payload, err = _get_json(_url("/profile", symbol=ticker))
    return _first_row(payload, err)


def _fetch_ratios(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    payload, err = _get_json(_url("/ratios-ttm", symbol=ticker))
    return _first_row(payload, err)


def _fetch_metrics(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    payload, err = _get_json(_url("/key-metrics-ttm", symbol=ticker))
    return _first_row(payload, err)


def _fetch_rating(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    payload, err = _get_json(_url("/ratings-snapshot", symbol=ticker))
    return _first_row(payload, err)


def _envelope(kind: str, ok: bool, data: Any = None, error: str = "") -> dict[str, Any]:
    """本源的出口。构造收口到 sources/envelope（P1，2026-11-09）。"""
    from .envelope import envelope

    return envelope("fmp", kind, ok, data=data, error=error or None)


# TTM 比率透传白名单：免费档有值的部分（ROE/ROA=null 不放进来占位，
# 要 ROE 走三表自己算或在快照链的 yfinance 里拿）
_RATIO_KEYS = {
    # 键 → (快照字段名, 是否小数比率)
    "grossProfitMarginTTM": ("gross_margin", True),
    "operatingProfitMarginTTM": ("operating_margin", True),
    "netProfitMarginTTM": ("net_margin", True),
    "ebitdaMarginTTM": ("ebitda_margin", True),
    "currentRatioTTM": ("current_ratio", False),
    "debtToAssetsRatioTTM": ("debt_to_assets", True),
    "debtToEquityRatioTTM": ("debt_to_equity", True),
    "dividendYieldTTM": ("dividend_yield", True),
    "dividendPayoutRatioTTM": ("payout_ratio", True),
    "dividendPerShareTTM": ("dividend_per_share", False),
    "freeCashFlowPerShareTTM": ("fcf_per_share", False),
    "priceToFreeCashFlowRatioTTM": ("price_to_fcf", False),
}
_METRIC_KEYS = {
    "enterpriseValueTTM": ("enterprise_value", False),
    "evToSalesTTM": ("ev_to_sales", False),
    "evToFreeCashFlowTTM": ("ev_to_fcf", False),
    "evToEBITDATTM": ("ev_to_ebitda", False),
    "netDebtToEBITDATTM": ("net_debt_to_ebitda", False),
}
_RATING_KEYS = {
    "rating": "rating",
    "overallScore": "overall_score",
    "discountedCashFlowScore": "dcf_score",
    "returnOnEquityScore": "roe_score",
    "returnOnAssetsScore": "roa_score",
    "debtToEquityScore": "debt_score",
    "priceToEarningsScore": "pe_score",
    "priceToBookScore": "pb_score",
}


def deep_snapshot(symbol: str) -> dict[str, Any]:
    """FMP 深取快照：quote + profile + ratios-ttm + key-metrics-ttm + 评级。

    四路请求互不依赖，并发收敛到最慢一路；评级缺席不拖垮快照，
    **价格**缺失才算失败（与 tiingo.us 同一条结构自洽纪律）。
    """
    ticker = normalize_ticker(symbol)
    if not ticker:
        return _envelope("fmp_deep", False, error=f"无法解析美股标的：{symbol}")
    if not load_api_key():
        return _envelope("fmp_deep", False, error=f"缺少 {ENV_KEY} 且无凭据文件")

    with ThreadPoolExecutor(max_workers=5) as pool:
        fut_quote = pool.submit(_fetch_quote, ticker)
        fut_prof = pool.submit(_fetch_profile, ticker)
        fut_rat = pool.submit(_fetch_ratios, ticker)
        fut_met = pool.submit(_fetch_metrics, ticker)
        fut_ratg = pool.submit(_fetch_rating, ticker)
        quote_raw, quote_err = fut_quote.result()
        prof, _e = fut_prof.result()
        ratios, _e = fut_rat.result()
        metrics, _e = fut_met.result()
        rating, _e = fut_ratg.result()

    if quote_raw is None:
        detail = str(quote_err or "FMP 无该代码的行情")
        return _envelope("fmp_deep", False, error=detail)

    quote: dict[str, Any] = {
        "price": quote_raw.get("price"),
        "change_pct": quote_raw.get("changePercentage"),  # FMP 原生百分数，与渲染器约定一致
        "previous_close": quote_raw.get("previousClose"),
        "open": quote_raw.get("open"),
        "day_high": quote_raw.get("dayHigh"),
        "day_low": quote_raw.get("dayLow"),
        "year_high": quote_raw.get("yearHigh"),
        "year_low": quote_raw.get("yearLow"),
        "volume": quote_raw.get("volume"),
        "avg_volume": quote_raw.get("avgVolume") or quote_raw.get("averageVolume"),
        "market_cap": quote_raw.get("marketCap"),
        "beta": quote_raw.get("beta"),
        "pe_trailing": quote_raw.get("pe"),
        "pb": quote_raw.get("pb"),
        "price_avg_50": quote_raw.get("priceAvg50"),
        "price_avg_200": quote_raw.get("priceAvg200"),
    }
    quote = {k: v for k, v in quote.items() if v is not None}

    financial: dict[str, Any] = {}
    if isinstance(ratios, dict):
        for src, (dst, _is_ratio) in _RATIO_KEYS.items():
            if ratios.get(src) is not None:
                financial[dst] = ratios[src]
    if isinstance(metrics, dict):
        for src, (dst, _is_ratio) in _METRIC_KEYS.items():
            if metrics.get(src) is not None:
                financial[dst] = metrics[src]

    rating_out: dict[str, Any] = {}
    if isinstance(rating, dict):
        for src, dst in _RATING_KEYS.items():
            if rating.get(src) is not None:
                rating_out[dst] = rating[src]

    data = {
        "source": "fmp",
        "symbol": ticker,
        "name": (prof or {}).get("companyName") or ticker,
        "currency": (prof or {}).get("currency") or "USD",
        "timestamp": datetime.now().isoformat(),
        "quote": quote,
        "financial": financial,
        "rating": rating_out,
        "business": {
            "sector": (prof or {}).get("sector"),
            "industry": (prof or {}).get("industry"),
            "country": (prof or {}).get("country"),
            "ceo": (prof or {}).get("ceo"),
            "employees": (prof or {}).get("fullTimeEmployees"),
            "ipo_date": (prof or {}).get("ipoDate"),
            "exchange": (prof or {}).get("exchangeFullName") or (prof or {}).get("exchange"),
            "cik": (prof or {}).get("cik"),
            "isin": (prof or {}).get("isin"),
            "website": (prof or {}).get("website"),
        },
    }
    data["business"] = {k: v for k, v in data["business"].items() if v is not None}
    return _envelope("fmp_deep", True, data=data)


def us(symbol: str) -> dict[str, Any]:
    """美股快照（快照链末位兜底）：把深取结果收敛成 cmd_us 的统一形状。

    为什么在链尾而不是链首：免费档 250 次/天，且一次快照要 5 个请求；
    放在 bitget 之后意味着只有前面四源全败时才会消耗配额。能力上是全链最全的
    基本面兜底（三表比率 + 评级 + 公司信息），代价是延迟与配额，故只做最后一道。
    """
    deep = deep_snapshot(symbol)
    if not deep.get("ok"):
        return _envelope("us", False, error=str(deep.get("error") or f"FMP 无 {symbol} 的行情"))
    d = deep.get("data") or {}
    q = d.get("quote") or {}
    if q.get("price") is None:
        return _envelope("us", False, error=f"FMP 无 {symbol} 的价格")
    financial = d.get("financial") or {}
    snapshot = {
        "source": "fmp",
        "symbol": d.get("symbol") or normalize_ticker(symbol),
        "name": d.get("name") or normalize_ticker(symbol),
        "currency": d.get("currency") or "USD",
        "timestamp": d.get("timestamp") or datetime.now().isoformat(),
        # FMP 免费档有延迟，且非交易所直连；与 tiingo 的 eod 标记同型，不冒充实时。
        "quote_basis": "delayed",
        "quote": {
            k: q.get(k)
            for k in ("price", "change_pct", "market_cap", "pe_trailing", "pb",
                      "dividend_yield", "beta", "year_high", "year_low")
            if q.get(k) is not None
        },
        "financial": financial,
        "analyst": d.get("rating") or {},
        "risk": {"beta": q.get("beta"), "max_drawdown_1y": None},
        "business": d.get("business") or {},
    }
    if financial.get("dividend_yield") is not None:
        snapshot["quote"].setdefault("dividend_yield", financial["dividend_yield"])
    return _envelope("us", True, data=snapshot)


def analyst_estimates(symbol: str) -> dict[str, Any]:
    """年度分析师预测（EPS/营收 低/均/高，免费档 annual 可用、quarterly 402）。"""
    ticker = normalize_ticker(symbol)
    if not ticker:
        return _envelope("estimates", False, error=f"无法解析美股标的：{symbol}")
    if not load_api_key():
        return _envelope("estimates", False, error=f"缺少 {ENV_KEY}")
    payload, err = _get_json(_url("/analyst-estimates", symbol=ticker, period="annual"))
    if err:
        return _envelope("estimates", False, error=err)
    rows = [r for r in (payload or []) if isinstance(r, dict)]
    if not rows:
        return _envelope("estimates", False, error=f"未找到标的「{symbol}」的分析师预测（可能覆盖不足）")
    rows.sort(key=lambda r: r.get("date") or "")  # API 返回序不稳定，统一按年度升序好读
    data = {
        "symbol": ticker,
        "period": "annual",
        "rows": [
            {
                "date": (r.get("date") or "")[:10],
                "revenue_low": r.get("revenueLow"),
                "revenue_avg": r.get("revenueAvg"),
                "revenue_high": r.get("revenueHigh"),
                "eps_low": r.get("epsLow"),
                "eps_avg": r.get("epsAvg"),
                "eps_high": r.get("epsHigh"),
                "num_analysts": r.get("numAnalysts"),
            }
            for r in rows
        ],
    }
    return _envelope("estimates", True, data=data)


def statements(symbol: str, period: str = "annual", limit: int = 2) -> dict[str, Any]:
    """三表（income/balance/cash-flow）。免费档 annual 实测通；quarterly 未承诺。"""
    ticker = normalize_ticker(symbol)
    if not ticker:
        return _envelope("statements", False, error=f"无法解析美股标的：{symbol}")
    if not load_api_key():
        return _envelope("statements", False, error=f"缺少 {ENV_KEY}")
    out: dict[str, Any] = {"symbol": ticker, "period": period, "statements": {}}
    errors: list[str] = []
    for name, path in (("income", "/income-statement"), ("balance", "/balance-sheet-statement"),
                       ("cash_flow", "/cash-flow-statement")):
        payload, err = _get_json(_url(path, symbol=ticker, period=period, limit=max(1, limit)))
        if err:
            errors.append(f"{name}: {err}")
            continue
        rows = [r for r in (payload or []) if isinstance(r, dict)]
        if rows:
            out["statements"][name] = rows
    if not out["statements"]:
        return _envelope("statements", False, error="; ".join(errors) or "FMP 无三表数据")
    out["statement_errors"] = errors
    return _envelope("statements", True, data=out)


def dividends(symbol: str) -> dict[str, Any]:
    """分红历史（记录日/除权日/支付日/金额）。"""
    ticker = normalize_ticker(symbol)
    if not ticker:
        return _envelope("dividends", False, error=f"无法解析美股标的：{symbol}")
    if not load_api_key():
        return _envelope("dividends", False, error=f"缺少 {ENV_KEY}")
    payload, err = _get_json(_url("/dividends", symbol=ticker))
    if err:
        return _envelope("dividends", False, error=err)
    rows = [r for r in (payload or []) if isinstance(r, dict)]
    if not rows:
        return _envelope("dividends", False, error=f"未找到标的「{symbol}」的分红记录")
    total = round(sum(float(r.get("dividend") or 0.0) for r in rows), 6)
    data = {
        "symbol": ticker,
        "count": len(rows),
        "total": total,
        "rows": [
            {
                "date": (r.get("date") or "")[:10],
                "record_date": (r.get("recordDate") or "")[:10],
                "payment_date": (r.get("paymentDate") or "")[:10],
                "declaration_date": (r.get("declarationDate") or "")[:10],
                "dividend": r.get("dividend"),
                "yield": r.get("yield"),
            }
            for r in rows
        ],
    }
    return _envelope("dividends", True, data=data)


if __name__ == "__main__":  # 快速自检：在 scripts/ 目录下 python3 -m sources.fmp
    import sys

    print(json.dumps(deep_snapshot(sys.argv[1] if len(sys.argv) > 1 else "AAPL"),
                     ensure_ascii=False, indent=2, default=str)[:2000])
