"""妙想(MX) MCP 数据源适配器测试（全部离线：_call_tool/_mcp_call 整体替换）。

线上行为契约（2026-10-11 实测，真实 key）：
- 服务端 NLU 不认裸 ticker："AAPL" 返回空数组，"AAPL 股价" 正常——us() 对
  ticker 形态输入包装查询模板；
- 单次调用 1.2s+（服务端 NLU 主导，连接复用零收益），auto() 按查询文本缓存
  300s（相邻调用 ≤300s 占 96.7%，第五轮治理报告口径）；
- MCP StreamableHttp 服务端可返回 SSE（spec 2025-06-18），_extract_payload 双支持。
"""
from __future__ import annotations

import pytest

import sources.mxds as mxds


# ---------- 路由（auto） ----------

def _capture_call(monkeypatch):
    calls = []

    def fake(tool, q, **kwargs):
        calls.append((tool, q))
        return {"source": "mxds", "kind": tool, "ok": True,
                "data": {"data": [{"columns": [], "items": []}]}, "error": None}

    monkeypatch.setattr(mxds, "_call_tool", fake)
    return calls


def test_auto_pe_routes_to_screener(monkeypatch):
    """「PE 最低的银行股」曾因 \\b[A-Za-z]{2,5}\\b 误路由到美股工具（选股分支排在其后永远轮不到）。"""
    calls = _capture_call(monkeypatch)
    mxds.auto("PE 最低的银行股")
    assert calls[0][0] == "mx_stocks_screener"


def test_auto_roe_pb_routes_to_screener(monkeypatch):
    calls = _capture_call(monkeypatch)
    mxds.auto("ROE 大于 20 的消费股")
    assert calls[0][0] == "mx_stocks_screener"
    mxds.auto("PB 最小的钢铁股")
    assert calls[-1][0] == "mx_stocks_screener"


def test_auto_hk_0prefix_4digit(monkeypatch):
    """0700 是港股惯写；「3000亿」这类金额表达不得误入港股分支。"""
    calls = _capture_call(monkeypatch)
    mxds.auto("0700 股价")
    assert calls[0][0] == "mx_hk_finance_data"
    mxds.auto("3000亿市值的公司")
    assert calls[-1][0] != "mx_hk_finance_data"


def test_auto_year_not_hk(monkeypatch):
    calls = _capture_call(monkeypatch)
    mxds.auto("贵州茅台2026年目标价")
    assert calls[0][0] == "mx_ashare_finance_data"


def test_auto_ashare_default(monkeypatch):
    calls = _capture_call(monkeypatch)
    mxds.auto("贵州茅台最新价")
    assert calls[0][0] == "mx_ashare_finance_data"


def test_auto_lowercase_english_not_us(monkeypatch):
    """小写英文词不是美股信号（旧判据 [A-Za-z]{2,5} 会命中）。"""
    calls = _capture_call(monkeypatch)
    mxds.auto("茅台的 apple 供应链")
    assert calls[0][0] == "mx_ashare_finance_data"


# ---------- us() ticker 模板包装 ----------

def test_us_bare_ticker_wrapped(monkeypatch):
    """裸 ticker 服务端 NLU 不识别（实测 "AAPL" 返回空数组），必须包装查询模板。"""
    calls = _capture_call(monkeypatch)
    mxds.us("aapl")
    assert calls[0][1] == "AAPL 股价"


def test_us_ticker_with_suffix(monkeypatch):
    calls = _capture_call(monkeypatch)
    mxds.us("BRK.A")
    assert calls[0][1] == "BRK.A 股价"


def test_us_natural_language_untouched(monkeypatch):
    calls = _capture_call(monkeypatch)
    mxds.us("苹果公司最新股价")
    assert calls[0][1] == "苹果公司最新股价"


# ---------- auto() 查询缓存 ----------

def test_auto_cache_hit_skips_second_call(monkeypatch):
    """同查询 300s 内第二次不再打网，命中带 cached=True。"""
    n = {"count": 0}

    def fake(tool, q, **kwargs):
        n["count"] += 1
        return {"source": "mxds", "kind": tool, "ok": True,
                "data": {"data": [{"v": q}]}, "error": None}

    monkeypatch.setattr(mxds, "_call_tool", fake)
    r1 = mxds.auto("贵州茅台最新价")
    assert "cached" not in r1
    r2 = mxds.auto("贵州茅台最新价")
    assert n["count"] == 1
    assert r2["cached"] is True
    assert r2["data"] == r1["data"]


def test_auto_failed_call_not_cached(monkeypatch):
    """失败结果不写缓存——偶发服务端波动不该被固化为 5 分钟失败。"""
    n = {"count": 0}

    def fake(tool, q, **kwargs):
        n["count"] += 1
        return {"source": "mxds", "kind": tool, "ok": False,
                "data": None, "error": "HTTP 503: Service Unavailable: up"}

    monkeypatch.setattr(mxds, "_call_tool", fake)
    mxds.auto("贵州茅台最新价")
    mxds.auto("贵州茅台最新价")
    assert n["count"] == 2


# ---------- SSE 兼容（_extract_payload） ----------

def test_extract_payload_json_passthrough():
    body = '{"jsonrpc":"2.0","id":1}'
    assert mxds._extract_payload(body, "application/json") == body


def test_extract_payload_sse_takes_last_data_line():
    body = 'event: message\ndata: {"a":1}\n\ndata: {"b":2}\n'
    assert mxds._extract_payload(body, "text/event-stream") == '{"b":2}'


def test_extract_payload_sse_without_data_is_error():
    with pytest.raises(ValueError):
        mxds._extract_payload("event: ping\n", "text/event-stream")


# ---------- 失败信封 raw 透传 ----------

def test_call_tool_failure_passes_raw(monkeypatch):
    """raw 透传：失败时调用方能看到服务端原始返回，排障不再断链。"""

    def fake_mcp(tool, query, timeout=30):
        return {"ok": False, "error": f"服务端未识别查询或无数据: {query!r}",
                "raw": {"data": []}}

    monkeypatch.setattr(mxds, "_mcp_call", fake_mcp)
    r = mxds._call_tool("mx_us_finance_data", "AAPL")
    assert r["ok"] is False
    assert r["raw"] == {"data": []}


# ---------- _ticker_like ----------

def test_ticker_like():
    assert mxds._ticker_like("AAPL 最新价") is True
    assert mxds._ticker_like("PE 最低的银行股") is False
    assert mxds._ticker_like("苹果公司") is False


# ---------- 快照信封校验（消灭「模糊匹配答错标的」整类） ----------
#
# 背景（2026-10-14 实测）：妙想快照类工具的服务端实现是自然语言检索，对**所有**
# 输入都返回表格信封——真实标的、不存在代码、错别字名称无一例外。route 快照链的
# 「第一个 ok 即停」把检索结果当快照交接，后果两种都坏：
#   ① `stock 999999` → cmd_stock.format_terminal 在 list 上 `.get("昨收")`
#      炸 AttributeError（rc=1 + traceback）；
#   ② `intent deep stock 999999` → rc=0 把「全部A股(板块)」全市场汇总当个股
#      快照静默交付（known-issues 自列的最危险类别）。
# 处置（2026-10-14 晚审查后修订）：_call_tool 的 snapshot 参数把两种契约显式
# 分开——route 链（stock/fund/us）要 dict 快照，intent mxds（auto()）要原样
# 表格。判据是正向契约「快照的 data 必须是 dict」，不是「拒带 columns 的表格」
# （后者漏 list-of-entity-dicts / 顶层数组 / 表格包 dict 三类形态，审查实测
# 均复现原 P0）。

def _search_envelope() -> dict:
    """妙想 NLU 检索信封（实测形状）：表格列表，非单一标的快照。"""
    return {"data": [{"columns": ["全部A股(板块)", "2026-10-14(日)"],
                      "items": [["营业总收入(合计)", "37.78万亿元"]]}]}


def _stub_mcp(monkeypatch, payload):
    monkeypatch.setattr(mxds, "_mcp_call",
                        lambda tool, q, timeout=30: {"ok": True, "data": payload,
                                                     "raw_text": "stub"})


def test_snapshot_tools_reject_search_envelope(monkeypatch):
    """stock/fund/us 拿到表格信封必须按未找到拒绝，而不是放行成快照。"""
    _stub_mcp(monkeypatch, _search_envelope())
    for fn, arg in ((mxds.stock, "999999"), (mxds.fund, "110011"),
                    (mxds.us, "AAPL")):
        res = fn(arg)
        assert res["ok"] is False, f"{fn.__name__}({arg}) 放行了检索信封"
        assert "未找到匹配标的" in res["error"]
        assert res["data"] is None


def test_snapshot_rejects_all_non_dict_shapes(monkeypatch):
    """正向契约：快照的 data 必须是 dict。三类漏网形态同样会让
    format_terminal 崩溃或输出空表（2026-10-14 审查实测复现），必须拒。"""
    shapes = {
        "list_of_entity_dicts": {"data": [{"name": "贵州茅台", "code": "600519"}]},
        "table_wrapped_in_dict": {"data": {"columns": ["贵州茅台"], "items": [["1286.0"]]}},
        "top_level_array": ["贵州茅台", "1286.0"],
    }
    for name, payload in shapes.items():
        _stub_mcp(monkeypatch, payload)
        res = mxds.stock("600519")
        assert res["ok"] is False, f"{name} 漏过了守卫"
        assert "未找到匹配标的" in res["error"], name


def test_snapshot_tools_accept_dict_snapshot(monkeypatch):
    """dict 形状（真实快照）不受影响——守卫只要求 dict，不预判未来形态。"""
    snap = {"data": {"name": "贵州茅台", "code": "600519", "昨收": "1286.0"}}
    _stub_mcp(monkeypatch, snap)
    res = mxds.stock("600519")
    assert res["ok"] is True
    assert res["data"] is snap


def test_search_tools_keep_table_envelope(monkeypatch):
    """screen/news/notice/bond/index/macro/comprehensive 要的就是表格，不拒。"""
    _stub_mcp(monkeypatch, _search_envelope())
    for fn, arg in ((mxds.screen, "市盈率低于10的银行股"), (mxds.news, "茅台"),
                    (mxds.notice, "贵州茅台 年报"), (mxds.bond, "019546"),
                    (mxds.index, "沪深300"), (mxds.macro, "GDP"),
                    (mxds.comprehensive, "宁德时代")):
        assert fn(arg)["ok"] is True, f"{fn.__name__} 误拒了表格"


def test_auto_keeps_tables_for_intent_mxds(monkeypatch):
    """auto() 是 intent mxds 的入口，契约是「表格即答案」——SKILL.md 明文
    推荐 `intent mxds "AAPL 股价"`。2026-10-14 审查实测：把拒绝设为
    _call_tool 的默认行为会误杀这 4 条路由，故 auto() 显式放行。"""
    _stub_mcp(monkeypatch, _search_envelope())
    for q in ("999999", "腾讯 港股", "易方达蓝筹 基金净值", "AAPL 股价"):
        res = mxds.auto(q)
        assert res["ok"] is True, f"auto({q!r}) 误杀了 intent mxds 路由"
        assert res["data"] == _search_envelope()


def test_route_chain_falls_through_mxds_rejection(monkeypatch):
    """route「第一个 ok 即停」：mxds 拒了必须落到下一源，而不是崩或停。"""
    from sources import route

    _stub_mcp(monkeypatch, _search_envelope())

    def fake_invoke(sid, kind, arg):
        if sid == "mxds":
            return mxds.stock(arg)
        return {"source": sid, "kind": kind, "ok": True,
                "data": {"name": "兜底源快照"}}

    res = route.fetch("stock", "999999", order=["mxds", "fake_fallback"],
                      invoke=fake_invoke)
    assert res["ok"] is True
    assert res["source"] == "fake_fallback"
    assert res.get("fallback_from") == "mxds"
    assert "mxds" in res.get("fallback_error", "")


def test_unwrap_snapshot_raises_clean_error_not_attributeerror(monkeypatch):
    """症状回归：修复前表格信封流过 unwrap_snapshot，format_terminal 在 list
    上 .get 炸 AttributeError；现在 unwrap 直接抛带明确文案的 RuntimeError。"""
    from sources.route import unwrap_snapshot

    _stub_mcp(monkeypatch, _search_envelope())
    res = mxds.stock("999999")
    assert res["ok"] is False
    with pytest.raises(RuntimeError, match="未找到匹配标的"):
        unwrap_snapshot(res)


def test_is_search_envelope_branches():
    """形状判据分支：表格列表 / 表格 dict 命中，实体 dict 列表 / 空 / 非 dict 不命中。"""
    assert mxds._is_search_envelope({"data": [{"columns": [], "items": []}]}) is True
    assert mxds._is_search_envelope({"data": {"columns": [], "items": []}}) is True
    assert mxds._is_search_envelope({"data": [{"name": "x"}]}) is False
    assert mxds._is_search_envelope({"data": {}}) is False
    assert mxds._is_search_envelope({"data": []}) is False
    assert mxds._is_search_envelope(["top", "level"]) is False
    assert mxds._is_search_envelope(None) is False
