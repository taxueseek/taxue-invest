"""FMP 数据源适配器测试（全部离线：HTTP 出口 _get_json 整体替换 / opener 打桩）。

免费档边界（2026-09-30 实测，防止将来误判）：三表 annual 通、quarterly 402；
ratios-ttm 的 ROE/ROA=null（免费档不给）；estimates 仅 annual（quarterly 402）；
etf-holdings 明确付费墙。**坏标的与付费墙同码 402**，必须按文案分流——
这是本文件固定的关键行为契约。
"""
from __future__ import annotations

import io
import urllib.error
from typing import Any, Optional

import pytest

import sources._http as _shared_http
import sources.fmp as fmp


# ---------- 假 HTTP 出口 ----------

def _fake_get_json(routes: dict[str, Any]):
    def fake(url: str, timeout: int = 15) -> tuple[Optional[Any], Optional[str]]:
        for frag, payload in routes.items():
            if frag in url:
                if isinstance(payload, str) and payload.startswith("ERR:"):
                    return None, payload[4:]
                return payload, None
        return None, f"fake_get_json 未覆盖该 URL: {url[:80]}"
    return fake


QUOTE = {"symbol": "AAPL", "name": "Apple Inc.", "price": 329.4, "changePercentage": -2.65957,
         "change": -9, "volume": 37773928, "dayLow": 328.815, "dayHigh": 337.06,
         "yearHigh": 345.34, "yearLow": 243.42, "marketCap": 4838015066400,
         "priceAvg50": 321.98, "priceAvg200": 288.33, "exchange": "NASDAQ",
         "open": 337.06, "previousClose": 338.4}

PROFILE = {"symbol": "AAPL", "companyName": "Apple Inc.", "currency": "USD",
           "sector": "Technology", "industry": "Consumer Electronics", "ceo": "John Ternus",
           "fullTimeEmployees": "166000", "ipoDate": "1980-12-12", "exchange": "NASDAQ",
           "exchangeFullName": "NASDAQ Global Select", "cik": "0000320193",
           "isin": "US0378331005", "website": "https://www.apple.com"}

RATIOS = {"symbol": "AAPL", "grossProfitMarginTTM": 0.465, "operatingProfitMarginTTM": 0.317,
          "netProfitMarginTTM": 0.263, "ebitdaMarginTTM": 0.34,
          "currentRatioTTM": 1.0033, "debtToAssetsRatioTTM": 0.32, "debtToEquityRatioTTM": 1.47,
          "dividendYieldTTM": 0.00321797, "dividendPayoutRatioTTM": 0.155,
          "dividendPerShareTTM": 1.06, "priceToFreeCashFlowRatioTTM": 35.7,
          "returnOnEquityTTM": None, "returnOnAssetsTTM": None,  # 免费档=null，不透传
          "someUnknownFieldTTM": 1.23}  # 白名单外字段必须被滤掉

METRICS = {"symbol": "AAPL", "enterpriseValueTTM": 4882778066400, "evToSalesTTM": 10.46,
           "evToFreeCashFlowTTM": 35.72, "evToEBITDATTM": 28.98, "netDebtToEBITDATTM": 1.0}

RATING = {"symbol": "AAPL", "rating": "B", "overallScore": 3, "discountedCashFlowScore": 3,
          "returnOnEquityScore": 5, "returnOnAssetsScore": 5, "debtToEquityScore": 1,
          "priceToEarningsScore": 2, "priceToBookScore": 1}

ESTIMATES = [{"symbol": "AAPL", "date": "2026-09-30T00:00:00.000Z", "revenueLow": 3.9e11,
              "revenueAvg": 4.1e11, "revenueHigh": 4.3e11, "epsLow": 7.0, "epsAvg": 7.4,
              "epsHigh": 7.8, "numAnalysts": 41}]

INCOME = [{"date": "2025-09-27", "symbol": "AAPL", "fiscalYear": "2025", "period": "FY",
           "revenue": 416161000000, "netIncome": 112010000000, "epsDiluted": 7.46}]
BALANCE = [{"date": "2025-09-27", "totalAssets": 364980000000, "totalLiabilities": 308030000000,
            "totalStockholdersEquity": 56950000000}]
CASHFLOW = [{"date": "2025-09-27", "operatingCashFlow": 120800000000,
             "freeCashFlow": 108800000000}]

DEEP_ROUTES = {
    # FMP 单票端点返回「列表包一行」，夹具保持同形
    "/quote?": [QUOTE],
    "/profile?": [PROFILE],
    "/ratios-ttm": [RATIOS],
    "/key-metrics-ttm": [METRICS],
    "/ratings-snapshot": [RATING],
}


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key-not-real")


def _raise_http_error(code: int, body: str):
    class _BoomOpener:
        def open(self, *a, **k):
            raise urllib.error.HTTPError(
                f"https://{fmp.API_HOST}/stable/quote", code, "error", {},
                io.BytesIO(body.encode()))

    return _BoomOpener()


# ---------- 注册表：深取专项 + us 链末位兜底 ----------

def test_registry_declaration():
    from sources import load_registry

    conf = load_registry().get("fmp")
    assert conf, "data-sources.yaml 缺 fmp 声明"
    assert conf["priority"] == 38
    for tag in ("us", "us_fundamentals", "us_estimates", "us_rating", "dividends"):
        assert tag in conf["coverage"]
    assert conf["route_kinds"] == ["us"], "fmp 参与美股快照链"
    assert conf["env_var"] == "FMP_API_KEY"


def test_fmp_is_us_chain_last_resort():
    from sources.route import candidates

    chain = candidates("us")
    assert "fmp" in chain
    assert chain.index("fmp") < chain.index("tencent") < chain.index("tiingo"), (
        f"v3.8 起 fmp 基本面源应排在行情/EOD 兜底源之前（当前 {chain}）"
    )
    assert "bitget" not in chain, chain


def test_detect_reflects_key_presence(monkeypatch):
    monkeypatch.setattr(fmp, "load_api_key", lambda: "k")
    ok, detail = fmp.detect()
    assert ok and "已配置" in detail
    monkeypatch.setattr(fmp, "load_api_key", lambda: None)
    ok, detail = fmp.detect()
    assert not ok and "fmp.env" in detail


def test_normalize_ticker():
    assert fmp.normalize_ticker("aapl") == "AAPL"
    assert fmp.normalize_ticker("AAPL/prices") == ""


# ---------- 深取快照：形态、白名单、单位 ----------

def test_deep_snapshot_shape_and_units(monkeypatch, with_key):
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json(DEEP_ROUTES))
    res = fmp.deep_snapshot("aapl")
    assert res["ok"] is True and res["source"] == "fmp"
    d = res["data"]
    q = d["quote"]
    assert q["price"] == 329.4
    assert q["change_pct"] == -2.65957           # FMP 原生百分数，直传不换算
    assert q["market_cap"] == 4838015066400      # 绝对值
    f = d["financial"]
    assert f["gross_margin"] == pytest.approx(0.465)     # 小数比率直传
    assert f["dividend_yield"] == pytest.approx(0.00321797, abs=1e-6)
    assert f["ev_to_sales"] == pytest.approx(10.46)
    # 免费档 ROE/ROA=null 不透传；白名单外字段滤掉
    assert "roe" not in f and "roa" not in f
    assert all(v is not None for v in f.values())
    assert d["rating"]["rating"] == "B" and d["rating"]["overall_score"] == 3
    assert d["rating"]["roe_score"] == 5
    b = d["business"]
    assert b["sector"] == "Technology" and b["ceo"] == "John Ternus"
    assert d["name"] == "Apple Inc." and d["currency"] == "USD"


def test_us_adapter_maps_deep_snapshot_to_cmd_us_shape(monkeypatch, with_key):
    """链尾兜底必须交回 cmd_us 认得的快照形状，而不是 fmp_deep 的深取形状。"""
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json(DEEP_ROUTES))
    res = fmp.us("aapl")
    assert res["ok"] is True and res["kind"] == "us"
    data = res["data"]
    assert data["source"] == "fmp" and data["symbol"] == "AAPL"
    assert data["quote_basis"] == "delayed"
    assert data["quote"]["price"] == 329.4
    assert data["quote"]["market_cap"] == 4838015066400
    assert "gross_margin" in data["financial"]
    assert data["analyst"]["rating"] == "B"
    assert data["business"]["sector"] == "Technology"


def test_deep_snapshot_quote_only_survives(monkeypatch, with_key):
    """profile/比率/评级任一路失败只缺字段；价格在就行。"""
    routes = dict(DEEP_ROUTES)
    for frag in ("/profile?", "/ratios-ttm", "/key-metrics-ttm", "/ratings-snapshot"):
        routes[frag] = "ERR: FMP HTTP 500: oops"
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json(routes))
    res = fmp.deep_snapshot("AAPL")
    assert res["ok"] is True
    d = res["data"]
    assert d["quote"]["price"] == 329.4
    assert d["financial"] == {} and d["rating"] == {}
    assert d["name"] == "AAPL"  # 元数据缺席退 ticker


def test_deep_snapshot_quote_auth_fail(monkeypatch, with_key):
    routes = {frag: "ERR: 鉴权失败 HTTP 401：key 无效" for frag in DEEP_ROUTES}
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json(routes))
    res = fmp.deep_snapshot("AAPL")
    assert res["ok"] is False and "401" in res["error"]


def test_deep_snapshot_no_key(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr(fmp, "load_api_key", lambda: None)
    res = fmp.deep_snapshot("AAPL")
    assert res["ok"] is False and "FMP_API_KEY" in res["error"]


# ---------- 错误形态分流（_get_json 出口层，真实 HTTPError 打桩） ----------

def test_error_mapping_401(monkeypatch):
    monkeypatch.setattr(_shared_http, "_OPENER", _raise_http_error(
        401, '{"Error Message": "Invalid API KEY"}'))
    payload, err = fmp._get_json(f"https://{fmp.API_HOST}/stable/quote?symbol=AAPL&apikey=x")
    assert payload is None and "401" in err and "Invalid API KEY" in err


def test_error_mapping_402_paywall_vs_unknown_ticker(monkeypatch):
    """同码不同义：付费墙 vs 标的不在订阅覆盖，必须分流成不同文案。"""
    monkeypatch.setattr(_shared_http, "_OPENER", _raise_http_error(
        402, "Restricted Endpoint: This endpoint is not available under your current subscription"))
    payload, err = fmp._get_json(f"https://{fmp.API_HOST}/stable/etf/holdings?symbol=SPY&apikey=x")
    assert payload is None and "付费墙" in err

    monkeypatch.setattr(_shared_http, "_OPENER", _raise_http_error(
        402, "Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is not available"))
    payload, err = fmp._get_json(f"https://{fmp.API_HOST}/stable/quote?symbol=NOTREAL&apikey=x")
    assert payload is None and "未找到标的" in err


def test_error_mapping_429(monkeypatch):
    monkeypatch.setattr(_shared_http, "_OPENER", _raise_http_error(429, "Too many requests"))
    payload, err = fmp._get_json(f"https://{fmp.API_HOST}/stable/quote?symbol=AAPL&apikey=x")
    assert payload is None and "250 次/天" in err


# ---------- SSRF 闸（与 tiingo 同一套） ----------

def test_get_json_rejects_non_https_and_foreign_host():
    for url in ("http://financialmodelingprep.com/stable/quote",
                "https://evil.example.com/stable/quote",
                "https://127.0.0.1/stable/quote"):
        payload, err = fmp._get_json(url)
        assert payload is None and "拒绝" in err, url


def test_get_json_allows_fake_ip_rejects_loopback(monkeypatch):
    class _Info:
        def __init__(self, ip):
            self.ip = ip

        def __getitem__(self, i):
            return (self.ip, 443) if i == 4 else None

    class _BoomOpener:
        def open(self, *a, **k):
            raise OSError("连接层测试桩")

    import socket as _socket

    monkeypatch.setattr(_socket, "getaddrinfo", lambda *a, **k: [_Info("2001:2::f0")])
    monkeypatch.setattr(_shared_http, "_OPENER", _BoomOpener())
    _, err = fmp._get_json(f"https://{fmp.API_HOST}/stable/quote?symbol=AAPL")
    assert "host 校验拒绝" not in (err or "")  # fake-ip 放行到连接层

    monkeypatch.setattr(_socket, "getaddrinfo", lambda *a, **k: [_Info("192.168.1.1")])
    _, err = fmp._get_json(f"https://{fmp.API_HOST}/stable/quote?symbol=AAPL")
    assert "非公网地址" in err  # 危险段照拒


# ---------- 三表 / 预测 / 分红 ----------

def test_statements_three_tables(monkeypatch, with_key):
    routes = {"/income-statement": INCOME, "/balance-sheet-statement": BALANCE,
              "/cash-flow-statement": CASHFLOW}
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json(routes))
    res = fmp.statements("AAPL", period="annual", limit=1)
    assert res["ok"] is True
    st = res["data"]["statements"]
    assert set(st) == {"income", "balance", "cash_flow"}
    assert st["income"][0]["revenue"] == 416161000000


def test_statements_partial_failure_tolerated(monkeypatch, with_key):
    routes = {"/income-statement": INCOME,
              "/balance-sheet-statement": "ERR: FMP HTTP 500",
              "/cash-flow-statement": "ERR: FMP HTTP 500"}
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json(routes))
    res = fmp.statements("AAPL")
    assert res["ok"] is True and set(res["data"]["statements"]) == {"income"}
    assert len(res["data"]["statement_errors"]) == 2


def test_estimates_passes_annual_period(monkeypatch, with_key):
    urls: list[str] = []

    def fake(url, timeout=15):
        urls.append(url)
        return ESTIMATES, None

    monkeypatch.setattr(fmp, "_get_json", fake)
    res = fmp.analyst_estimates("AAPL")
    assert res["ok"] is True
    assert "period=annual" in urls[0], "免费档必须带 annual（quarterly 是 402）"
    row = res["data"]["rows"][0]
    assert row["revenue_avg"] == 4.1e11 and row["eps_avg"] == 7.4 and row["num_analysts"] == 41


def test_dividends_totals_and_rows(monkeypatch, with_key):
    rows = [{"date": "2026-08-10T00:00:00.000Z", "recordDate": "2026-08-11T00:00:00.000Z",
             "paymentDate": "2026-08-14T00:00:00.000Z", "declarationDate": None,
             "dividend": 0.26, "yield": 0.0032},
            {"date": "2026-05-10T00:00:00.000Z", "dividend": 0.25}]
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json({"/dividends?": rows}))
    res = fmp.dividends("AAPL")
    assert res["ok"] is True
    assert res["data"]["count"] == 2 and res["data"]["total"] == pytest.approx(0.51)
    assert res["data"]["rows"][0]["payment_date"] == "2026-08-14"


def test_dividends_empty_is_not_found(monkeypatch, with_key):
    monkeypatch.setattr(fmp, "_get_json", _fake_get_json({"/dividends?": []}))
    res = fmp.dividends("NODIV")
    assert res["ok"] is False and "未找到" in res["error"]


# ---------- 真实通道（默认跳过；INVEST_LIVE=1 时跑，消耗 250 次/天配额） ----------

@pytest.mark.live
def test_live_deep_snapshot():
    if __import__("os").environ.get("INVEST_LIVE") != "1":
        pytest.skip("INVEST_LIVE!=1")
    res = fmp.deep_snapshot("AAPL")
    assert res["ok"] is True and res["data"]["quote"]["price"]
    est = fmp.analyst_estimates("AAPL")
    assert est["ok"] is True and est["data"]["rows"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
