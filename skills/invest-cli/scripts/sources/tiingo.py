"""Tiingo 美股 EOD 数据源适配器（invest-cli 数据源）。

定位：官方交易所口径的美股收盘数据——EOD 日线（含复权价/分红/拆股因子）、
日频估值序列（市值/PE/PB/PEG）、IEX 桥收盘报价。

免费档实测边界（2026-09-29，用真实 key 逐端点验证）：
  - /tiingo/daily/{t}/prices        通：全量 OHLCV + adjClose + divCash + splitFactor
  - /tiingo/daily/{t}               通：名称/描述/交易所元数据
  - /tiingo/fundamentals/{t}/daily  通：市值/enterpriseVal/PE/PB/PEG 日频序列（约 3 年）
  - /iex/?tickers=                  通：tngoLast 为收盘口径（非实时盘口，bid/ask 全空）
  - /tiingo/news/                   付费墙：{"detail": "no permission"}
  - 三表报表端点                    付费墙（免费档不可用，美股财报走 sec_edgar）

链上位次（priority 36，卡在腾讯 37 与 bitget 35 之间，是刻意的）：
  us 链 → [yfinance(40), tencent(37), tiingo(36), bitget(35)]
  · 不上 37 之上：免费档无三表无 ROE，且 tngoLast 是收盘口径——盘中查快照时
    腾讯的实时价更新；收市后两者同价。提到腾讯之上就是用旧价换位数，属能力降级。
  · 压过 bitget：官方交易所收盘价 vs 「代币价/USDT/非交易所官方价」，严格更优。
    bitget 因此实际只剩「Tiingo 也挂了」这一种触发场景。

单位纪律（与 yfinance/tencent 快照载荷对齐，否则渲染器会算错一个数量级）：
  market_cap 绝对值；change_pct 百分数（2.35 = +2.35%）；dividend_yield 小数
  （0.0044 = 0.44%，用 1 年 divCash 合计 ÷ 现价重算，与 cmd_us.normalize_
  dividend_yield 的「重算优先」同一口径）；max_drawdown_1y 负小数。

安全约束（SSRF 闸）：_get_json 是唯一 HTTP 出口，四层闸（仅 https / host 白名单
/ 请求前 DNS 逐 IP 公网校验 / 禁重定向）全部收口在 sources/_http.guarded_open——
本模块与 fmp.py 曾各持一份内联实现、与 _http 三处并行，闸的任何一层演进都要同步
三处，漏一处就是真实缺口（第九轮 2026-11-08 并口）。本模块只保留信封语义与
HTTPError 文案分流。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ._http import guarded_open

SOURCE_LABEL = "Tiingo 美股 EOD"
API_HOST = "api.tiingo.com"
API_BASE = f"https://{API_HOST}"
ENV_KEY = "TIINGO_API_KEY"
DEFAULT_TIMEOUT = 15
PROBE_USER_AGENT = "invest-cli/1.0 (tiingo source)"

# ticker 字符白名单：字母数字 + 点（类别股 BRK.B）+ 连字符。进 URL 前必须过。
_TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,11}$")
# fundamentals/daily 每行只取这些键（整条序列约 3 年日频，全量拉回按尾行取值）
_FUND_KEYS = ("marketCap", "peRatio", "pbRatio", "trailingPEG1Y", "date")


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "tiingo.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "tiingo.env",
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
        return True, f"{ENV_KEY} 已配置（EOD 日线/估值序列/IEX 收盘价）"
    return False, f"缺少 {ENV_KEY} 且无凭据文件（~/.config/invest-cli/tiingo.env）"


def normalize_ticker(symbol: str) -> str:
    """大写 + 去内部空格；不合法即空串（调用方按无法解析处理）。"""
    t = re.sub(r"\s+", "", str(symbol or "").strip().upper())
    return t if _TICKER_RE.match(t) else ""


def _get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[Optional[Any], Optional[str]]:
    """唯一 HTTP 出口：闸（https/白名单/逐 IP 公网校验/禁重定向）走共享 guarded_open。

    本函数只保留信封语义：(payload, err) 元组与 HTTPError 的文案分流。
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
        detail = ""
        try:
            detail = (json.loads(e.read().decode("utf-8", errors="replace")) or {}).get("detail", "")
        except Exception:
            pass
        if e.code in (401, 403):
            return None, f"鉴权失败 HTTP {e.code}：{detail or 'key 无效或该端点在付费墙内'}"
        return None, f"Tiingo HTTP {e.code}: {detail or e.reason}"
    except (urllib.error.URLError, OSError) as e:
        return None, f"Tiingo 请求失败: {e}"
    try:
        return json.loads(body), None
    except json.JSONDecodeError:
        return None, "Tiingo 返回非 JSON"


def _url(path: str, **params: Any) -> str:
    key = load_api_key()
    qs = urllib.parse.urlencode({"token": key, **{k: v for k, v in params.items() if v is not None}})
    return f"{API_BASE}{path}?{qs}"


def _fetch_iex(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    """IEX 桥报价：免费档 tngoLast 为官方收盘口径（非实时盘口）。"""
    payload, err = _get_json(_url("/iex/", tickers=ticker))
    if err:
        return None, err
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None, "IEX 桥无数据"
    return payload[0], None


def _fetch_meta(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    payload, err = _get_json(_url(f"/tiingo/daily/{ticker}"))
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "元数据返回异常结构"
    return payload, None


def _fetch_fundamentals_tail(ticker: str) -> tuple[Optional[dict], Optional[str]]:
    """日频估值序列的**尾行**（该端点不支持倒序，全量拉回取最后一条有效行）。

    序列里 marketCap 等字段有单日缺口（实测 AAPL 有 marketCap=null 的行），
    从尾部往前找第一条关键字段非空的行；找不到返回 (None, None)——
    估值字段全部缺席不致命，快照照发（price 仍在），不能算错误。
    """
    payload, err = _get_json(_url(f"/tiingo/fundamentals/{ticker}/daily"))
    if err:
        return None, err
    if not isinstance(payload, list):
        return None, "估值序列返回异常结构"
    for row in reversed(payload):
        if isinstance(row, dict) and any(row.get(k) is not None for k in ("marketCap", "peRatio", "pbRatio")):
            return {k: row.get(k) for k in _FUND_KEYS}, None
    return None, None


def _fetch_history(ticker: str, years: float) -> tuple[Optional[list[dict]], Optional[str]]:
    """EOD 日线（含 adjClose/divCash/splitFactor），years 年窗口。

    空列表返回 (None, None)：标的存在但无历史（新股/停牌）不算错误。
    """
    start = (datetime.now(timezone.utc) - timedelta(days=int(365 * years))).strftime("%Y-%m-%d")
    payload, err = _get_json(_url(
        f"/tiingo/daily/{ticker}/prices", startDate=start,
        columns="date,open,high,low,close,adjClose,volume,divCash,splitFactor",
    ))
    if err:
        return None, err
    if not isinstance(payload, list):
        return None, "日线返回异常结构"
    bars = [b for b in payload if isinstance(b, dict) and b.get("close") is not None]
    return (bars, None) if bars else (None, None)


def _max_drawdown(closes: list[float]) -> Optional[float]:
    if not closes:
        return None
    peak = closes[0]
    worst = 0.0
    for c in closes:
        if c > peak:
            peak = c
        elif peak > 0:
            worst = min(worst, (c - peak) / peak)
    return round(worst, 6)


def _history_summary(bars: list[dict], price: Optional[float]) -> dict[str, Any]:
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars if b.get("high") is not None]
    lows = [float(b["low"]) for b in bars if b.get("low") is not None]
    ref = float(price) if price else closes[-1]
    divs = round(sum(float(b.get("divCash") or 0.0) for b in bars), 6)
    return {
        "bars": len(bars),
        "start": (bars[0].get("date") or "")[:10],
        "end": (bars[-1].get("date") or "")[:10],
        "high_window": max(highs) if highs else None,
        "low_window": min(lows) if lows else None,
        "max_drawdown": _max_drawdown(closes),
        "dividends_ttm": divs,
        # 与 cmd_us.normalize_dividend_yield 同一口径：年股息 ÷ 现价，小数
        "dividend_yield": round(divs / ref, 6) if ref else None,
        "splits": [
            {"date": (b.get("date") or "")[:10], "split_factor": b.get("splitFactor")}
            for b in bars if b.get("splitFactor") not in (None, 0.0, 1.0)
        ],
    }


def _envelope(kind: str, ok: bool, data: Any = None, error: str = "") -> dict[str, Any]:
    """本源的出口。构造收口到 sources/envelope（P1，2026-11-09）。"""
    from .envelope import envelope

    return envelope("tiingo", kind, ok, data=data, error=error or None)


def eod_history(symbol: str, years: float = 1.0, use_cache: bool = True) -> dict[str, Any]:
    """EOD 历史专项能力：本源在链上的**独有贡献**（快照链其余源都不给可靠复权历史）。

    use_cache=False 供测试用：不读也不写（fred.liquidity 的教训——只绕过读
    仍写缓存，会把 mock 数据落进生产缓存污染之后的真实查询）。
    """
    ticker = normalize_ticker(symbol)
    if not ticker:
        return _envelope("eod_history", False, error=f"无法解析美股标的：{symbol}")
    cache_key = f"eod|{ticker}|{years}"
    if use_cache:
        try:
            from _common import CACHE_TTL_FUNDAMENTAL, cache_get

            hit = cache_get("eod", cache_key, CACHE_TTL_FUNDAMENTAL)
        except Exception:
            hit = None
        if isinstance(hit, dict) and hit.get("ok"):
            return {**hit, "cached": True}
    bars, err = _fetch_history(ticker, years)
    if err:
        return _envelope("eod_history", False, error=err)
    if not bars:
        return _envelope("eod_history", False, error=f"未找到标的「{symbol}」（Tiingo 无该代码的历史）")
    data = {
        "symbol": ticker,
        "currency": "USD",
        "price_basis": "official_eod",
        "summary": _history_summary(bars, None),
        "bars": [
            {
                "date": (b.get("date") or "")[:10],
                "open": b.get("open"), "high": b.get("high"),
                "low": b.get("low"), "close": b.get("close"),
                "adj_close": b.get("adjClose"), "volume": b.get("volume"),
                "div_cash": b.get("divCash"), "split_factor": b.get("splitFactor"),
            }
            for b in bars
        ],
    }
    res = _envelope("eod_history", True, data=data)
    if use_cache:
        try:
            from _common import cache_set

            cache_set("eod", cache_key, res)
        except Exception:
            pass
    return res


def us(symbol: str) -> dict[str, Any]:
    """美股快照（Tiingo EOD 口径）：IEX 收盘报价 + 估值尾行 + 1 年历史派生。

    四路请求互不依赖，串行等于四段 RTT 相加（fred._collect_series 同型问题）；
    并发后收敛到最慢一路。历史/估值/元数据任一路失败只缺对应派生字段，
    不拖垮快照——只有**价格**缺失才算失败（结构自洽守卫，与 cmd_us.
    _identity_present 同思路：标识字段一个都没有才判「未找到」）。
    """
    ticker = normalize_ticker(symbol)
    if not ticker:
        return _envelope("us", False, error=f"无法解析美股标的：{symbol}")
    if not load_api_key():
        return _envelope("us", False, error=f"缺少 {ENV_KEY} 且无凭据文件")

    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_iex = pool.submit(_fetch_iex, ticker)
        fut_meta = pool.submit(_fetch_meta, ticker)
        fut_fund = pool.submit(_fetch_fundamentals_tail, ticker)
        fut_hist = pool.submit(_fetch_history, ticker, 1.0)
        iex, iex_err = fut_iex.result()
        meta, _meta_err = fut_meta.result()
        fund, _fund_err = fut_fund.result()
        bars, _hist_err = fut_hist.result()

    # 价格身份：IEX tngoLast 优先；IEX 缺席退最后一根日线收盘（prevClose 同理）
    price = iex.get("tngoLast") or iex.get("prevClose") if isinstance(iex, dict) else None
    prev_ref = iex.get("prevClose") if isinstance(iex, dict) else None
    if price is None and bars:
        price = bars[-1]["close"]
        if len(bars) >= 2:
            prev_ref = bars[-2]["close"]
    if price is None:
        detail = str(iex_err or "Tiingo 无该代码的行情")
        if "not found" in detail.lower() or "Ticker" in detail:
            return _envelope("us", False, error=f"未找到标的「{symbol}」（Tiingo 无该代码）")
        return _envelope("us", False, error=detail)

    quote: dict[str, Any] = {"price": price}
    if price and prev_ref:
        quote["change_pct"] = round((float(price) / float(prev_ref) - 1.0) * 100.0, 4)
    if isinstance(iex, dict):
        for k in ("open", "high", "low", "volume"):
            if iex.get(k) is not None:
                quote[k] = iex.get(k)
    if isinstance(fund, dict):
        if fund.get("marketCap") is not None:
            quote["market_cap"] = fund["marketCap"]
        if fund.get("peRatio") is not None:
            quote["pe_trailing"] = fund["peRatio"]
        if fund.get("pbRatio") is not None:
            quote["pb"] = fund["pbRatio"]
        if fund.get("trailingPEG1Y") is not None:
            quote["peg_trailing"] = fund["trailingPEG1Y"]
    if bars:
        summary = _history_summary(bars, price)
        quote["high_52w"] = summary["high_window"]
        quote["low_52w"] = summary["low_window"]
        if summary["dividend_yield"]:
            quote["dividend_yield"] = summary["dividend_yield"]

    snapshot: dict[str, Any] = {
        "source": "tiingo",
        "symbol": ticker,
        "name": (meta or {}).get("name") or ticker,
        "currency": (meta or {}).get("priceCurrency") or "USD",
        "timestamp": datetime.now().isoformat(),
        # 诚实标注：这是收盘口径，不是盘中实时价（与 bitget 的 quote_type 同型语义标记）
        "quote_basis": "eod",
        "eod_asof": (bars[-1].get("date") or "")[:10] if bars else str((iex or {}).get("timestamp") or "")[:10],
        "quote": quote,
        "financial": {},   # 免费档无三表：美股财报走 sec_edgar（yaml 里已注明分工）
        "analyst": {},
        "risk": {
            "max_drawdown_1y": _history_summary(bars, price)["max_drawdown"] if bars else None,
            "dividends_ttm": _history_summary(bars, price)["dividends_ttm"] if bars else None,
        },
        "business": {},
    }
    return _envelope("us", True, data=snapshot)


if __name__ == "__main__":  # 快速自检：在 scripts/ 目录下 python3 -m sources.tiingo
    import sys

    print(json.dumps(us(sys.argv[1] if len(sys.argv) > 1 else "AAPL"),
                     ensure_ascii=False, indent=2, default=str)[:2000])
