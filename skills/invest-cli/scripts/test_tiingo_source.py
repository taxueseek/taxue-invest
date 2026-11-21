"""Tiingo 数据源适配器测试（全部离线：HTTP 出口 _get_json 整体替换）。

实测边界（2026-09-29，真实 key）：EOD 日线/元数据/估值序列/IEX 收盘价免费；
新闻与三表在付费墙内——涉及这些边界的行为契约都固定在这里，防止将来
有人把「付费墙内」误当成「适配器坏了」去修。
"""
from __future__ import annotations

from typing import Any, Optional

import pytest

import sources._http as _shared_http
import sources.tiingo as tiingo


# ---------- 假 HTTP 出口：按 URL 片段分发，覆盖所有取数通道 ----------

def _bar(date: str, close: float, *, high: float | None = None, low: float | None = None,
         div: float = 0.0, split: float = 1.0) -> dict[str, Any]:
    return {"date": f"{date}T00:00:00.000Z", "open": close, "high": high or close,
            "low": low or close, "close": close, "adjClose": close,
            "volume": 1_000_000, "divCash": div, "splitFactor": split}


def _fake_get_json(routes: dict[str, Any]):
    """routes: url 片段 → payload 或 异常消息字符串（以 'ERR:' 开头表示失败）。"""
    def fake(url: str, timeout: int = 15) -> tuple[Optional[Any], Optional[str]]:
        for frag, payload in routes.items():
            if frag in url:
                if isinstance(payload, str) and payload.startswith("ERR:"):
                    return None, payload[4:]
                return payload, None
        return None, f"fake_get_json 未覆盖该 URL: {url[:80]}"
    return fake


AAPL_ROUTES = {
    "/iex/": [{"ticker": "AAPL", "tngoLast": 329.4, "prevClose": 338.4,
               "open": 336.965, "high": 337.085, "low": 328.7, "volume": 38478037,
               "timestamp": "2026-09-29T20:00:00+00:00"}],
    "/tiingo/daily/AAPL?": {"ticker": "AAPL", "name": "Apple Inc", "priceCurrency": "USD"},
    "/fundamentals/AAPL/daily": [
        {"date": "2026-09-27T00:00:00.000Z", "marketCap": None, "peRatio": None, "pbRatio": None},
        {"date": "2026-09-29T00:00:00.000Z", "marketCap": 4.838e12, "peRatio": 37.52,
         "pbRatio": 44.99, "trailingPEG1Y": 2.1},
    ],
    "/daily/AAPL/prices": [
        _bar("2026-09-26", 341.07, high=341.67, low=334.53),
        _bar("2026-09-28", 338.4, high=342.988, low=338.04, div=0.26),
        _bar("2026-09-29", 329.4, high=337.085, low=328.7, div=0.26),
    ],
}


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "test-key-not-real")


# ---------- 代码规范化与守卫 ----------

def test_normalize_ticker_accepts_and_cleans():
    assert tiingo.normalize_ticker("aapl") == "AAPL"
    assert tiingo.normalize_ticker("A A P L") == "AAPL"  # 实测 agent 会传分写形式
    assert tiingo.normalize_ticker("BRK.B") == "BRK.B"


def test_normalize_ticker_rejects_path_injection():
    # 字符白名单是 SSRF 闸的第一层：路径注入、query 注入在这里就进不了 URL
    for bad in ("", "AAPL/prices", "AAPL?x=1", "a b; rm", "../etc", "A" * 13):
        assert tiingo.normalize_ticker(bad) == "", bad


def test_us_without_key_is_input_error_not_crash(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.setattr(tiingo, "load_api_key", lambda: None)
    res = tiingo.us("AAPL")
    assert res["ok"] is False and "TIINGO_API_KEY" in res["error"]


def test_us_invalid_ticker_never_touches_network(monkeypatch, with_key):
    called = []

    def boom(url, timeout=15):
        called.append(url)
        raise AssertionError("非法 ticker 不应发起任何请求")

    monkeypatch.setattr(tiingo, "_get_json", boom)
    res = tiingo.us("../etc/passwd")
    assert res["ok"] is False and "无法解析" in res["error"] and not called


# ---------- us 快照：形态、单位口径、降级 ----------

def test_us_snapshot_shape_and_units(monkeypatch, with_key):
    monkeypatch.setattr(tiingo, "_get_json", _fake_get_json(AAPL_ROUTES))
    res = tiingo.us("aapl")
    assert res["ok"] is True and res["source"] == "tiingo"
    snap = res["data"]
    # 渲染器硬依赖的两个键（_format_yfinance 直接下标取）
    assert snap["symbol"] == "AAPL" and snap["timestamp"]
    assert snap["name"] == "Apple Inc" and snap["currency"] == "USD"
    q = snap["quote"]
    # 单位纪律（错一个数量级渲染器就跟着错）：
    assert q["price"] == 329.4
    assert q["change_pct"] == pytest.approx(-2.656, abs=0.01)  # 百分数：-2.66 不是 -0.0266
    assert q["market_cap"] == 4.838e12                          # 绝对值，不是「亿」
    assert q["pe_trailing"] == pytest.approx(37.52)
    assert q["pb"] == pytest.approx(44.99)
    assert q["dividend_yield"] == pytest.approx(0.52 / 329.4, abs=1e-4)  # 小数 0.0016
    assert q["high_52w"] == pytest.approx(342.988)
    assert snap["risk"]["max_drawdown_1y"] <= 0
    # 收盘口径的诚实标注 + 与 yfinance 快照同形的分区键
    assert snap["quote_basis"] == "eod" and snap["eod_asof"] == "2026-09-29"
    for section in ("quote", "financial", "analyst", "risk", "business"):
        assert section in snap


def test_us_degrades_gracefully_when_aux_channels_fail(monkeypatch, with_key):
    """估值/元数据/历史任一路失败只缺字段不失败——价格在就行。"""
    routes = dict(AAPL_ROUTES)
    routes["/fundamentals/AAPL/daily"] = "ERR: Tiingo HTTP 404"
    routes["/tiingo/daily/AAPL?"] = "ERR: Tiingo HTTP 500"
    routes["/daily/AAPL/prices"] = "ERR: Tiingo HTTP 500"
    monkeypatch.setattr(tiingo, "_get_json", _fake_get_json(routes))
    res = tiingo.us("AAPL")
    assert res["ok"] is True
    snap = res["data"]
    assert snap["quote"]["price"] == 329.4
    assert "market_cap" not in snap["quote"] and "pe_trailing" not in snap["quote"]
    assert snap["name"] == "AAPL"  # 元数据缺席退 ticker，不冒充
    assert snap["risk"]["max_drawdown_1y"] is None


def test_us_iex_down_falls_back_to_last_bar(monkeypatch, with_key):
    routes = dict(AAPL_ROUTES)
    routes["/iex/"] = "ERR: Tiingo 请求失败: timeout"
    monkeypatch.setattr(tiingo, "_get_json", _fake_get_json(routes))
    res = tiingo.us("AAPL")
    assert res["ok"] is True
    assert res["data"]["quote"]["price"] == 329.4
    assert res["data"]["quote"]["change_pct"] == pytest.approx(
        (329.4 / 338.4 - 1) * 100, abs=0.01)


def test_us_unknown_ticker_reports_not_found(monkeypatch, with_key):
    routes = {
        "/iex/": "ERR: Tiingo HTTP 404: Error: Ticker 'NOTREAL' not found",
        "/daily/NOTREAL/prices": "ERR: Tiingo HTTP 404: Error: Ticker 'NOTREAL' not found",
    }
    monkeypatch.setattr(tiingo, "_get_json", _fake_get_json(routes))
    res = tiingo.us("NOTREAL")
    assert res["ok"] is False and "未找到标的" in res["error"]


def test_us_auth_failure_message_is_actionable(monkeypatch, with_key):
    """鉴权失败必须全链失败并给出可行动的错误：只有 iex 挂不算（其余通道兜底）。"""
    auth_err = "ERR: 鉴权失败 HTTP 401：key 无效"
    routes = {frag: auth_err for frag in ("/iex/", "/tiingo/daily/AAPL?", "/fundamentals/AAPL/daily", "/daily/AAPL/prices")}
    monkeypatch.setattr(tiingo, "_get_json", _fake_get_json(routes))
    res = tiingo.us("AAPL")
    assert res["ok"] is False and "401" in res["error"]


# ---------- eod_history：独有能力 ----------

def test_eod_history_summary_math(monkeypatch, with_key):
    routes = {
        "/daily/NVDA/prices": [
            _bar("2025-10-01", 100.0, div=0.01),
            _bar("2026-03-01", 130.0, div=0.01, split=10.0),  # 拆股事件要被捞出来
            _bar("2026-06-01", 90.0, div=0.01),               # 相对峰值 130 的回撤
            _bar("2026-09-29", 110.0, div=0.01),
        ],
    }
    monkeypatch.setattr(tiingo, "_get_json", _fake_get_json(routes))
    res = tiingo.eod_history("nvda", years=1.0, use_cache=False)
    assert res["ok"] is True
    s = res["data"]["summary"]
    assert s["bars"] == 4 and s["end"] == "2026-09-29"
    assert s["high_window"] == 130.0 and s["low_window"] == 90.0
    assert s["max_drawdown"] == pytest.approx((90 - 130) / 130, abs=1e-4)
    assert s["dividends_ttm"] == pytest.approx(0.04)
    assert s["splits"] == [{"date": "2026-03-01", "split_factor": 10.0}]
    assert len(res["data"]["bars"]) == 4


def test_eod_history_cache_roundtrip(monkeypatch, with_key, tmp_path):
    calls = []

    def counting_fake(url, timeout=15):
        calls.append(url)
        return AAPL_ROUTES["/daily/AAPL/prices"], None

    monkeypatch.setattr(tiingo, "_get_json", counting_fake)
    first = tiingo.eod_history("AAPL", use_cache=True)
    assert first["ok"] is True and not first.get("cached")
    second = tiingo.eod_history("AAPL", use_cache=True)
    assert second.get("cached") is True and len(calls) == 1  # 第二次零网络
    # use_cache=False 是测试逃生舱：不读也不写（fred 的缓存污染教训）
    fresh = tiingo.eod_history("AAPL", use_cache=False)
    assert fresh.get("cached") is None and len(calls) == 2


def test_eod_history_not_found(monkeypatch, with_key):
    monkeypatch.setattr(tiingo, "_get_json",
                        _fake_get_json({"/daily/GHOST/prices": []}))  # 空数组=无历史
    res = tiingo.eod_history("GHOST", use_cache=False)
    assert res["ok"] is False and "未找到标的" in res["error"]


# ---------- SSRF 闸：出口层四道校验 ----------

def test_get_json_rejects_non_https_and_foreign_host():
    for url in ("http://api.tiingo.com/iex/?tickers=AAPL",
                "https://evil.example.com/iex/?tickers=AAPL",
                "https://127.0.0.1/iex/?tickers=AAPL",
                "ftp://api.tiingo.com/x"):
        payload, err = tiingo._get_json(url)
        assert payload is None and "拒绝" in err, url


def test_get_json_rejects_dns_rebinding_to_private_ip(monkeypatch):
    class _FakeInfo:
        def __getitem__(self, i):
            # getaddrinfo 五元组：info[4] 必须直接是 (ip, port)
            return ("127.0.0.1", 443) if i == 4 else None

    import socket as _socket

    monkeypatch.setattr(_socket, "getaddrinfo",
                        lambda *a, **k: [_FakeInfo()])
    payload, err = tiingo._get_json(f"https://{tiingo.API_HOST}/iex/?tickers=AAPL")
    assert payload is None and "非公网地址" in err


def test_get_json_allows_clash_fake_ip_range(monkeypatch):
    """本机 Clash TUN 把所有域名解析到 fake-ip 段（v4 198.18.0.0/15、v6 2001:2::/48，
    均实测出过）——连接由 TUN 按域名转出，守卫若拒它就成了断网器；
    危险段仍拒（对照上一条用例）。"""
    class _BoomOpener:
        def open(self, *a, **k):
            raise OSError("fake-ip 放行后走到连接层（测试桩）")

    import socket as _socket

    for fake_ip in ("198.18.0.241", "2001:2::f0"):
        class _FakeInfo:
            def __getitem__(self, i):
                return (fake_ip, 443) if i == 4 else None

        monkeypatch.setattr(_socket, "getaddrinfo",
                            lambda *a, **k: [_FakeInfo()])
        monkeypatch.setattr(_shared_http, "_OPENER", _BoomOpener())
        payload, err = tiingo._get_json(f"https://{tiingo.API_HOST}/iex/?tickers=AAPL")
        # fake-ip 被放行到连接层：错误是「请求失败」而不是「host 校验拒绝」
        assert "host 校验拒绝" not in (err or ""), fake_ip


def test_no_redirect_handler_rejects_all_redirects():
    """302 的目标不过白名单：跟随即绕闸，处理器必须一律拒绝。

    第九轮并口后 _NoRedirect 的唯一真身在 sources/_http（tiingo/fmp 的内联
    副本已删），行为契约钉在共享出口上。
    """
    handler = _shared_http._NoRedirect()
    assert handler.redirect_request(
        None, None, 302, "Found", {"Location": "http://169.254.169.254/"},
        "http://169.254.169.254/") is None


# ---------- 注册表与路由：链上位次是本源的核心契约 ----------

def test_registry_declaration():
    from sources import load_registry

    conf = load_registry().get("tiingo")
    assert conf, "data-sources.yaml 缺 tiingo 声明"
    assert conf["priority"] == 36
    assert "us" in conf["coverage"] and "eod_history" in conf["coverage"]
    assert conf["env_var"] == "TIINGO_API_KEY"


def test_us_chain_order_yfinance_tencent_tiingo_bitget():
    from sources.route import candidates

    # v3.8（金融口径收口）：us 默认链为 yfinance > fmp > tencent > tiingo；
    # bitget（USDT 代币价）已移出默认股票快照链。
    chain = candidates("us")
    if "yfinance" in chain:
        assert chain[:4] == ["yfinance", "fmp", "tencent", "tiingo"], chain
    else:
        assert chain[:3] == ["fmp", "tencent", "tiingo"], chain
    assert "bitget" not in chain, chain


def test_detect_reflects_key_presence(monkeypatch):
    monkeypatch.setattr(tiingo, "load_api_key", lambda: "k")
    ok, detail = tiingo.detect()
    assert ok and "已配置" in detail
    monkeypatch.setattr(tiingo, "load_api_key", lambda: None)
    ok, detail = tiingo.detect()
    assert not ok and "tiingo.env" in detail


# ---------- 真实通道（默认跳过；INVEST_LIVE=1 时跑） ----------

@pytest.mark.live
def test_live_us_and_history():
    if __import__("os").environ.get("INVEST_LIVE") != "1":
        pytest.skip("INVEST_LIVE!=1")
    res = tiingo.us("AAPL")
    assert res["ok"] is True and res["data"]["quote"]["price"]
    hist = tiingo.eod_history("AAPL", use_cache=False)
    assert hist["ok"] is True and hist["data"]["summary"]["bars"] > 200


if __name__ == "__main__":  # 直跑便利
    raise SystemExit(pytest.main([__file__, "-q"]))
