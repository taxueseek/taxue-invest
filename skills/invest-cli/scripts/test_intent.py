#!/usr/bin/env python3
"""intent 分类与选股路由契约 — 不打盈米/东财网络。"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cmd_intent import (  # noqa: E402
    _dispatch,
    classify,
    kind_from_code,
)


def test_kind_from_code() -> None:
    assert kind_from_code("600519") == "stock"
    assert kind_from_code("000858") is None  # 与基金 00xxxx 重叠
    assert kind_from_code("300750") == "stock"
    assert kind_from_code("688981") == "stock"
    assert kind_from_code("110011") == "fund"
    assert kind_from_code("161725") == "fund"
    assert kind_from_code("510300") == "fund"
    assert kind_from_code("00700") == "stock"
    assert kind_from_code("茅台") is None
    # 可转债确定性段（盈米实测 2026-09-03：113/123/127/128 段查询全部 400 查无基金）
    assert kind_from_code("113050") == "bond"
    assert kind_from_code("113509") == "bond"
    assert kind_from_code("123111") == "bond"
    assert kind_from_code("127030") == "bond"
    assert kind_from_code("128133") == "bond"


def test_classify_does_not_call_yingmi_for_shanghai() -> None:
    import cmd_intent as m

    def boom(_t: str) -> bool:
        raise AssertionError("600519 不得打盈米 GuessFundCode")

    orig = m._is_fund_by_yingmi
    m._is_fund_by_yingmi = boom  # type: ignore[assignment]
    try:
        assert classify("600519") == "stock"
        assert classify("300750") == "stock"
        assert classify("110011") == "fund"
        assert classify("113050") == "bond"  # 转债段不得打盈米
        assert classify("AAPL") == "us"
        assert classify("易方达蓝筹精选混合") == "fund"
    finally:
        m._is_fund_by_yingmi = orig


def test_screen_defaults_to_eastmoney() -> None:
    d = _dispatch("screen", "市盈率低于10的银行股")
    assert d["route"][0] == "eastmoney_screen"
    d2 = _dispatch("screen", "夏普大于1的基金")
    assert d2["route"][0] == "fund_screen"


def test_cjk_name_is_not_a_us_ticker() -> None:
    """汉字也是 isalpha()：中文名不得被判成美股代码。

    旧写法 `t.isalpha() and 1 <= len(t) <= 5` 对「茅台」「腾讯」为真，
    `intent deep 茅台` 于是去 Yahoo 找「茅台」，白付两轮失败网络（实测 3.2s）。
    判据必须是「ASCII 字母」而不是「字母」。
    """
    import cmd_intent as m

    assert "茅台".isalpha()  # 前提：Python 认为汉字是字母，旧判据因此失真
    orig = m._is_fund_by_yingmi
    m._is_fund_by_yingmi = lambda _t: False  # 不打盈米网络，只验分类分支
    try:
        assert classify("茅台") == "stock"
        assert classify("腾讯") == "stock"
        assert classify("苹果") == "stock"
        assert classify("AAPL") == "us"
        assert classify("nvda") == "us"
    finally:
        m._is_fund_by_yingmi = orig


def test_deep_type_word_without_target_is_an_error() -> None:
    """`intent deep stock`（只有类型词没有标的）是缺参数，不是标的 STOCK。

    反向对照：commodity/gold 是固定场景（TTFUND_GOLD_INFO），不需要标的，
    不得被这条守卫误拦——`intent deep commodity` 是 SKILL 文档里的合法用法。
    """
    for word in ("stock", "fund", "us", "bond"):
        d = _dispatch("deep", word)
        assert "error" in d and "缺少标的" in d["error"], (word, d)
    for word in ("commodity", "gold"):
        d = _dispatch("deep", word)
        assert d.get("route", (None,))[0] == "ttskill_scene", (word, d)


def test_short_name_skips_fund_fuzzy_match() -> None:
    """2 字名不做盈米基金模糊匹配：「腾讯」会误中「银河定投宝腾讯济安指数」。"""
    import cmd_intent as m

    called: list[str] = []
    orig = m._is_fund_by_yingmi
    m._is_fund_by_yingmi = lambda t: (called.append(t), True)[1]
    try:
        assert classify("腾讯") == "stock"
        assert called == [], "2 字名不应打盈米做基金模糊匹配"
        assert classify("易方达蓝筹精选") == "fund"
        assert called == ["易方达蓝筹精选"], "长名仍应保留基金兜底"
    finally:
        m._is_fund_by_yingmi = orig


def test_yingmi_fuzzy_match_must_correspond_to_query(monkeypatch) -> None:
    """盈米 GuessFundCode 是子串式模糊匹配，返回了东西 ≠ 查询的是基金。

    实测误配：中国平安 → 华银平安中国主题灵活配置混合；
    招商银行 → 银叶投资-招商银行-宁海工业园1号。
    旧判据只看「有没有 fundName」，于是这两只股票被判成基金。
    """
    import cmd_intent as m
    from sources import yingmi as ym

    matched = {
        "中国平安": "华银平安中国主题灵活配置混合",
        "招商银行": "银叶投资-招商银行-宁海工业园1号",
        "腾讯": "银河定投宝腾讯济安指数",
        "易方达蓝筹精选": "易方达蓝筹精选混合",
        "中欧医疗健康": "中欧医疗健康混合A",
    }

    def fake_call(tool, params=None, params_json=None):
        name = matched.get((params or {}).get("fundNameOrCode"), "")
        return {"source": "yingmi", "ok": bool(name),
                "data": {"fundName": name} if name else None, "error": None}

    monkeypatch.setattr(ym, "call", fake_call)

    for stock_name in ("中国平安", "招商银行", "腾讯"):
        assert m._is_fund_by_yingmi(stock_name) is False, f"{stock_name} 被误判为基金"
    assert m._is_fund_by_yingmi("易方达蓝筹精选") is True
    assert m._is_fund_by_yingmi("中欧医疗健康") is True


def test_classify_supports_class_share_tickers() -> None:
    """BRK.B / BRK-B / BF.B 类美股代码必须判为 us，不能掉进 A/H 股链。"""
    for ticker in ("BRK.B", "BRK-B", "BF.B"):
        assert classify(ticker) == "us", ticker
    assert classify("茅台") == "stock"


def test_macro_region_routing_avoids_us_cn_mismatch(monkeypatch) -> None:
    """v3.8：美国流动性不得兜底到中国统计局，中国宏观不得走美联储 FRED。"""
    import cmd_intent as m
    from sources import argo as argo_src, fred as fred_src, registry as reg_mod

    assert m._is_cn_macro("中国 CPI 社融") is True
    assert m._is_cn_macro("美联储 缩表 SOFR") is False
    assert m._is_cn_macro("") is False

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(reg_mod, "detect", lambda conf: (False, "off"))
    monkeypatch.setattr(fred_src, "liquidity", lambda: {"ok": False, "data": None, "error": "down"})
    monkeypatch.setattr(
        argo_src,
        "search",
        lambda q, engine="": (seen.append((engine, q)), {"ok": True, "source": "argo", "data": []})[1],
    )

    m._macro_pipeline("美联储 流动性")
    m._macro_pipeline("中国 社融 M2")
    assert seen[0][0] == "macro", "美国宏观失败不得兜底到 nbs_stats"
    assert seen[1][0] == "nbs_stats", "中国宏观应走 nbs_stats"


def test_bond_deep_falls_back_to_mxds_when_wind_unavailable(monkeypatch) -> None:
    """v3.8：无 Wind Key 时债券深取应自动降级到 mxds，而非单点硬死。"""
    import cmd_intent as m
    from sources import mxds as mxds_src, registry as reg_mod

    def fake_detect(conf):
        if conf.get("env_var") == "WIND_API_KEY":
            return False, "no wind"
        if conf.get("env_var") == "EM_API_KEY":
            return True, "ok"
        return False, "off"

    monkeypatch.setattr(reg_mod, "detect", fake_detect)
    monkeypatch.setattr(mxds_src, "bond", lambda q: {"ok": True, "source": "mxds", "data": {"q": q}})
    res = m._bond_with_fallback("113050")
    assert res["ok"] is True
    assert res["source"] == "mxds"
    assert res["fallback_from"] == "wind"


def test_fund_screen_prefers_sfg_and_falls_back_to_yingmi(monkeypatch) -> None:
    """v3.8：基金筛选 sfg 主路，sfg 不可用时降级盈米 SearchFunds。"""
    import cmd_intent as m
    from sources import registry as reg_mod, sfg as sfg_src, yingmi as ym_src

    monkeypatch.setattr(reg_mod, "detect", lambda conf: (conf.get("env_var") == "SFG_MCP_TOKEN", ""))
    monkeypatch.setattr(sfg_src, "call", lambda tool, params=None, **k: {"ok": True, "source": "sfg", "kind": tool, "data": []})
    res_sfg = m._fund_screen_with_fallback("夏普大于1的基金")
    assert res_sfg["source"] == "sfg" and res_sfg["kind"] == "sfg_screen_funds"

    monkeypatch.setattr(reg_mod, "detect", lambda conf: (False, "off"))
    monkeypatch.setattr(ym_src, "call", lambda tool, params=None: {"ok": True, "source": "yingmi", "kind": tool, "data": []})
    res_ym = m._fund_screen_with_fallback("红利主题基金")
    assert res_ym["source"] == "yingmi" and res_ym["kind"] == "SearchFunds"


if __name__ == "__main__":
    test_kind_from_code()
    test_classify_does_not_call_yingmi_for_shanghai()
    test_screen_defaults_to_eastmoney()
    test_classify_supports_class_share_tickers()
    print("test_intent: OK")
