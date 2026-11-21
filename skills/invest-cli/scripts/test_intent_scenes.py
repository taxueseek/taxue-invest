#!/usr/bin/env python3
"""intent 场景路由契约 — 不打外部网络。

覆盖 2026-08-30 review 修复的回归点：
1. portfolio/plan/present 的 ROUTES 必须是可调用 lambda（曾是裸 tuple → TypeError）
2. deep bond 路由到 wind bond_data 且保留标的代码
3. present 路由到本地 cmd_present（不再引用不存在的 Wind RenderHtmlToPdf）
4. classify 英文类型词精确匹配（bond/gold/commodity 不误判美股）
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cmd_intent import (  # noqa: E402
    ROUTES,
    _dispatch,
    classify,
)


def test_scene_routes_are_callable() -> None:
    """present/portfolio/plan 的 default 必须是 lambda，不能是裸 tuple。"""
    for scene in ("portfolio", "plan", "present"):
        r = ROUTES[scene]["default"]
        assert callable(r), f"{scene} default 不可调用: {r!r}"


def test_dispatch_scene_shapes() -> None:
    for scene, kind in (
        ("portfolio", "portfolio_check"),
        ("plan", "yingmi"),
        ("present", "present_html"),
    ):
        d = _dispatch(scene, "示例输入")
        assert d["route"][0] == kind, f"{scene} 应路由到 {kind}，实际 {d}"
    # JSON 输入交给 _portfolio_with_fallback 层解析
    d = _dispatch("portfolio", '{"totalAssets": 1000000}')
    assert d["route"][0] == "portfolio_check"
    assert d["route"][1] == '{"totalAssets": 1000000}'


def test_portfolio_natural_language_becomes_fund_list() -> None:
    """SKILL 承诺「持仓 json 或自然语言」；旧实现把整串当 input 发出去，服务端必回 400。"""
    from cmd_intent import _portfolio_params

    assert _portfolio_params("110011:50,005827:50") == {"fundList": [
        {"fundCode": "110011", "amount": 50.0},
        {"fundCode": "005827", "amount": 50.0},
    ]}
    # 不写金额时给等权默认，至少能诊断出持仓结构
    p2 = _portfolio_params("110011 005827")
    assert [i["fundCode"] for i in p2["fundList"]] == ["110011", "005827"]
    assert all(i["amount"] > 0 for i in p2["fundList"])


def test_plan_natural_language_becomes_three_params() -> None:
    """「能承受 20% 回撤 / 5 年 / 年化 8%」要换算成三个查询参数（百分比→小数）。"""
    d = _dispatch("plan", "能承受20%回撤 5年 预期年化8%")
    params = d["route"][2]
    assert params["expectedDrawdown"] == 0.2
    assert params["expectedAnnualizedReturnRate"] == 0.08
    assert params["expectedInvestTime"] == "5y"


def test_present_no_ghost_wind_tool() -> None:
    """不得再引用 wind-mcp-skill 中不存在的 RenderHtmlToPdf。"""
    assert "RenderHtmlToPdf" not in str(ROUTES)


def test_deep_bond_keeps_target() -> None:
    """deep bond 必须把标的代码带进路由（wind → mxds 降级链）。"""
    d = _dispatch("deep", "bond 019547.SH")
    assert d["route"][0] == "bond_deep"
    assert "019547.SH" in str(d["route"][1])
    assert d["type"] == "bond"


def test_deep_commodity_routes_ttskill_gold() -> None:
    # ttfund 已退役：黄金深取改走官方 TTFUND_GOLD_INFO
    d = _dispatch("deep", "commodity AU9999")
    assert d["route"][0] == "ttskill_scene"
    assert d["route"][1] == "TTFUND_GOLD_INFO"
    assert d["route"][2] == {"query_scope": "gold"}


def test_classify_english_type_words() -> None:
    assert classify("bond") == "bond"
    assert classify("BOND") == "bond"
    assert classify("gold") == "commodity"
    assert classify("commodity") == "commodity"
    assert classify("AAPL") == "us"  # 真美股代码不受影响


def test_screen_fund_search_carries_pagination_and_keyword() -> None:
    """SearchFunds 两个静默空结果来源（2026-10-11 实测回归点）必须都兜住。

    v3.8 起基金筛选主路升级为 sfg（fund_screen），盈米 SearchFunds 为兜底，
    仍必须保留分页与关键词提炼防线。
    """
    from cmd_intent import _fund_search_keyword

    d = _dispatch("screen", "红利主题基金")
    assert d["route"][0] == "fund_screen", f"基金语义应路由 fund_screen: {d}"
    assert d["route"][1] == "红利主题基金"
    # 短语要提炼成名字关键词：剥通用修饰词，不做语义猜测
    assert _fund_search_keyword("红利主题基金") == "红利"
    assert _fund_search_keyword("医药基金") == "医药"
    assert _fund_search_keyword("基金") == "基金"
    # 「混合/优选/精选」是真名用词，不在剥离词表里
    assert _fund_search_keyword("华商红利优选混合") == "华商红利优选混合"


def test_screen_fund_sfg_gets_conditions_not_query(monkeypatch) -> None:
    """sfg_screen_funds 的 props 没有 query——必须传 conditions（旧写法恒回
    「请传 conditions」，2026-11-21 实测）。"""
    import cmd_intent
    from sources import sfg as sfg_src

    seen: dict = {}

    def fake_call(tool, params=None, **kw):
        seen.update({"tool": tool, "params": params})
        return {"ok": True, "data": {"items": []}}

    monkeypatch.setattr(cmd_intent, "_parse_conditions", lambda t, y: [{"year": 2026, "yieldMin": 0.2}])
    monkeypatch.setattr(sfg_src, "load_token", lambda: "x")
    monkeypatch.setattr(sfg_src, "detect", lambda: (True, "已配置"))
    monkeypatch.setattr(sfg_src, "call", fake_call)
    monkeypatch.setattr(cmd_intent, "load_registry", lambda: {"sfg": {"priority": 64}},
                        raising=False)

    cmd_intent._fund_screen_with_fallback("近3年收益大于20%的基金")

    assert seen["tool"] == "sfg_screen_funds", seen
    assert "query" not in seen["params"], f"上游没有 query 参数：{seen['params']}"
    assert seen["params"]["conditions"] == [{"year": 2026, "yieldMin": 0.2}]


def test_deep_fund_falls_back_to_miaoxiang_not_sfg(monkeypatch) -> None:
    """v3.8.2：deep fund 顺序为 盈米 → route 结构化快照 → 妙想兜底，sfg 不进通用链。"""
    import cmd_intent
    import sources
    import sources.registry as reg
    import sources.route as route_mod

    order: list[str] = []

    monkeypatch.setattr(sources, "load_registry", lambda: {
        "yingmi": {"priority": 70}, "mxds": {"priority": 55}, "sfg": {"priority": 64},
    })
    monkeypatch.setattr(reg, "detect", lambda conf: (True, "ok"))

    class _Ym:
        @staticmethod
        def call(tool, params=None):
            order.append("yingmi")
            return {"ok": False, "error": "no"}

    class _Mx:
        @staticmethod
        def auto(q):
            order.append("mxds")
            return {"ok": True, "data": {"q": q}}

    monkeypatch.setattr(sources, "yingmi", _Ym, raising=False)
    monkeypatch.setattr(sources, "mxds", _Mx, raising=False)
    monkeypatch.setattr(cmd_intent, "_resolve_fund_code", lambda t: t)
    monkeypatch.setattr(
        route_mod,
        "fetch",
        lambda kind, target: (order.append("route"), {"ok": False, "error": "down"})[1],
    )

    res = cmd_intent._fund_with_fallback("005827")

    assert res.get("ok") is True
    assert order == ["yingmi", "route", "mxds"], f"结构化快照应优先于妙想且不含 sfg：{order}"


def test_plain_keyword_fund_screen_skips_sfg_to_save_credits(monkeypatch) -> None:
    """v3.8.2：纯关键词搜基金不触发积分制 sfg，直接走盈米 SearchFunds。"""
    import cmd_intent
    from sources import sfg as sfg_src, yingmi as ym_src

    called: list[str] = []
    monkeypatch.setattr(sfg_src, "call", lambda *a, **k: (called.append("sfg"), {"ok": True})[1])
    monkeypatch.setattr(ym_src, "call", lambda tool, params=None: (called.append(f"yingmi:{tool}"), {"ok": True, "data": []})[1])

    res = cmd_intent._fund_screen_with_fallback("红利主题基金")
    assert res.get("ok") is True
    assert called == ["yingmi:SearchFunds"], f"纯关键词不应消耗 sfg 积分：{called}"


if __name__ == "__main__":
    test_scene_routes_are_callable()
    test_dispatch_scene_shapes()
    test_present_no_ghost_wind_tool()
    test_deep_bond_keeps_target()
    test_deep_commodity_routes_ttskill_gold()
    test_classify_english_type_words()
    test_screen_fund_search_carries_pagination_and_keyword()
    print("test_intent_scenes: OK")
