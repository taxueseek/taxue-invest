#!/usr/bin/env python3
"""见基行事(seefundgo) MCP 数据源适配器测试（全部离线：HTTP 与上游被替换）。

守护的是本源的三个实测坑：
1. **会话式协议**：initialize 拿 mcp-session-id 后必须回带，否则 -32600；
2. **代码口径**：上游要标准码（005827.OF），裸 6 位码 404；同一代码可能场内外
   并存，**不猜后缀**，先搜索解析（猜错即答错标的）；
3. **组合诊断异步**：同步接口有 30s 服务端硬顶，必须走 submit + 轮询；
4. **轮询上限要覆盖真实耗时**：实测 succeeded 298-340s，上限低于此值等于白提交；
5. **积分制**：余额 0 时全工具被拒，本源只能做垂直深取、不能当通用主渠道。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest  # noqa: E402

import sources.sfg as sfg  # noqa: E402


def _sse(payload: dict, sid: str = "sess-1") -> tuple[int, bytes, dict]:
    """构造一条 SSE 响应（本源服务端实际形态）。"""
    body = ("event: message\n\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
    return 200, body, {"Content-Type": "text/event-stream", "mcp-session-id": sid}


def _install_fake_http(monkeypatch, calls: list[dict], responses: list[tuple[int, bytes, dict]]):
    """替换 guarded_request，按序返回响应并记录调用参数。"""
    seq = iter(responses)

    def _fake(url, **kw):
        calls.append({"url": url, "headers": kw.get("headers"), "data": kw.get("data")})
        return next(seq)

    monkeypatch.setattr("sources._http.guarded_request", _fake)


@pytest.fixture(autouse=True)
def _fresh_session():
    """每个用例从空会话开始：否则前一条用例的 session id 会让后续断言失真。"""
    sfg._SESSION._sid = ""
    yield
    sfg._SESSION._sid = ""


# ── 1. 凭据与探测 ────────────────────────────────────────

def test_detect_requires_token(monkeypatch):
    monkeypatch.setattr(sfg, "load_token", lambda: "")
    ok, detail = sfg.detect()
    assert ok is False
    assert "SFG_MCP_TOKEN" in detail


def test_detect_ok_with_token(monkeypatch):
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    ok, detail = sfg.detect()
    assert ok is True


# ── 2. 会话协议：initialize 后必须带 mcp-session-id ──────────

def test_call_sends_session_id_and_auth(monkeypatch):
    """首次调用必须 initialize；后续必须带 session id 与 Bearer。"""
    calls: list[dict] = []
    init_ok = (200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
               {"Content-Type": "application/json", "mcp-session-id": "sess-9"})
    call_ok = _sse({"jsonrpc": "2.0", "id": 2, "result": {
        "content": [{"type": "text", "text": json.dumps({"ok": 1}, ensure_ascii=False)}],
        "structuredContent": {"result": {"ok": 1}},
    }}, sid="sess-9")
    _install_fake_http(monkeypatch, calls, [init_ok, call_ok])
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")

    res = sfg.call("sfg_help", {}, question="你好")

    assert res["ok"] is True, res
    assert len(calls) == 2
    # 第一次是 initialize，第二次带 session id + Bearer
    assert json.loads(calls[0]["data"])["method"] == "initialize"
    assert "mcp-session-id" not in (calls[0]["headers"] or {})
    assert calls[1]["headers"].get("mcp-session-id") == "sess-9"
    assert calls[1]["headers"].get("Authorization") == "Bearer sfg_x"


def test_session_expiry_triggers_reinitialize(monkeypatch):
    """400 后必须重新 initialize 再重试（会话过期是常态，不能直接失败）。"""
    calls: list[dict] = []
    init = (200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
            {"Content-Type": "application/json", "mcp-session-id": "sess-new"})
    _install_fake_http(monkeypatch, calls, [
        init,
        (400, b'{"error":"Session not found"}', {}),
        init,
        _sse({"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"result": {"ok": 1}},
        }}),
    ])
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")

    res = sfg.call("sfg_help", {})
    assert res["ok"] is True
    methods = [json.loads(c["data"])["method"] for c in calls]
    assert methods.count("initialize") == 2, "会话过期后未重新 initialize"


# ── 3. HTTP 出口必须过安全闸 ────────────────────────────────

def test_sfg_uses_guarded_request(monkeypatch):
    """本源所有请求必须走 guarded_request（P0 四层闸的端到端锚）。"""
    calls: list[dict] = []
    _install_fake_http(monkeypatch, calls, [
        (200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
         {"Content-Type": "application/json", "mcp-session-id": "s"}),
        _sse({"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"result": {}},
        }}),
    ])
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    sfg.call("sfg_help", {})
    for c in calls:
        assert c["url"].startswith("https://www.fundfof.com/mcp"), c["url"]
    assert sfg.MCP_HOST == "www.fundfof.com"


# ── 4. 代码口径：不猜后缀，先搜后取 ──────────────────────────

def test_normalize_does_not_guess_suffix():
    """裸码不得被猜成某个后缀（猜错即取错标的）。"""
    assert sfg.normalize_fund_code("005827") == "005827"
    assert sfg.normalize_fund_code(" 005827.of ") == "005827.OF"


def test_resolve_strips_result_wrapper(monkeypatch):
    """搜索返回多一层 result 包装，必须剥掉再取 items。"""
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "call", lambda *a, **k: {
        "ok": True,
        "data": {"result": {"items": [
            {"fund_symbol": "005827.OF", "fund_name": "易方达蓝筹精选混合"},
        ]}},
    })
    r = sfg.resolve_fund_code("005827")
    assert r["code"] == "005827.OF"


def test_resolve_bare_code_matches_standard_code(monkeypatch):
    """裸码查询要与标准码的代码段比对，否则单只查询被误判成多候选。"""
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "call", lambda *a, **k: {
        "ok": True,
        "data": {"items": [{"fund_symbol": "161725.SZ", "fund_name": "招商中证白酒指数A"}]},
    })
    r = sfg.resolve_fund_code("161725")
    assert r["code"] == "161725.SZ"
    assert len(r["candidates"]) == 1


def test_fund_refuses_to_pick_among_ambiguous_candidates(monkeypatch):
    """多候选（A/C 份额）不得自动挑第一个——选错即答错标的。"""
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "resolve_fund_code", lambda *a, **k: {
        "code": "161725.SZ", "name": "招商中证白酒指数A",
        "candidates": [
            {"code": "161725.SZ", "name": "招商中证白酒指数A"},
            {"code": "012414.OF", "name": "招商中证白酒指数C"},
        ],
    })
    res = sfg.fund("161725")
    assert res["ok"] is False
    assert "多个匹配" in res["error"]
    assert res["candidates"]


# ── 5. 组合诊断走异步 submit ────────────────────────────────

def test_auto_multi_codes_uses_submit(monkeypatch):
    """多只基金走异步提交（同步接口有 30s 硬顶，实测两只基金即超时）。"""
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "_resolve_code", lambda c: f"{c}.OF")
    seen: dict = {}
    monkeypatch.setattr(sfg, "call", lambda tool, params=None, **k: seen.update(
        {"tool": tool, "params": params}) or {"ok": True, "data": {}})

    sfg.auto("005827 110011")

    assert seen["tool"] == "sfg_portfolio_check_submit", seen
    assert seen["params"]["codes"] == ["005827.OF", "110011.OF"]


def test_auto_single_code_uses_fund(monkeypatch):
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "fund", lambda kw: {"ok": True, "data": {"kw": kw}})
    res = sfg.auto("005827")
    assert res["ok"] is True
    assert res["data"]["kw"] == "005827"


def test_resolve_tool_rejects_unknown_alias():
    """未知别名必须本地抛错，不得透传给上游 MCP。"""
    assert sfg.resolve_tool("profile") == "sfg_fund_profile"
    assert sfg.resolve_tool("sfg_custom_tool") == "sfg_custom_tool"
    with pytest.raises(ValueError, match="未知 sfg 工具或别名"):
        sfg.resolve_tool("not_a_real_alias")


def test_resolve_fund_code_uses_disk_cache(monkeypatch):
    """第二次解析同一代码应命中磁盘缓存，不再重复调 sfg_search_funds。"""
    calls: list[str] = []
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")

    def fake_call(tool, params=None, **kw):
        calls.append(tool)
        return {
            "ok": True,
            "data": {"items": [{"fund_symbol": "005827.OF", "fund_name": "易方达蓝筹精选混合"}]},
        }

    monkeypatch.setattr(sfg, "call", fake_call)
    r1 = sfg.resolve_fund_code("005827")
    r2 = sfg.resolve_fund_code("005827")
    assert r1["code"] == "005827.OF" and r2["code"] == "005827.OF"
    assert len(calls) == 1, f"第二次应命中磁盘缓存，实际调用 {len(calls)} 次"


# ── 6. 别名解析 ──────────────────────────────────────────────

def test_resolve_tool_alias():
    assert sfg.resolve_tool("profile") == "sfg_fund_profile"
    assert sfg.resolve_tool("sfg_fund_profile") == "sfg_fund_profile"
    assert sfg.resolve_tool("portfolio-check") == "sfg_portfolio_check"


def test_attribution_line_is_present():
    """出处标注是本源强制要求，适配器不得丢掉。"""
    assert sfg.ATTRIBUTION_LINE == "数据来源：见基行事MCP（fundfof.com）"


# ── 7. 轮询上限必须覆盖真实耗时 ────────────────────────────────

def test_poll_max_wait_covers_upstream_runtime(monkeypatch):
    """上限低于上游实测耗时（298-340s）会在结果落盘前返回 running = 白提交。"""
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "call", lambda *a, **k: {
        "ok": True, "data": {"result": {"status": "running",
                                         "retry_after_seconds": 5}},
    })
    import inspect

    sig = inspect.signature(sfg.poll_portfolio)
    default_wait = sig.parameters["max_wait"].default
    assert default_wait >= 420, f"默认轮询上限 {default_wait}s 不足以覆盖实测 340s"
    assert sfg.POLL_MAX_WAIT == default_wait


def test_poll_timeout_keeps_job_id_for_retry(monkeypatch):
    """超时必须 ok=False 且带 job_id 与已等待时长，不能沿用 running 态的 ok=True。"""
    monkeypatch.setattr(sfg, "load_token", lambda: "sfg_x")
    monkeypatch.setattr(sfg, "call", lambda *a, **k: {
        "ok": True, "data": {"result": {"status": "running"}},
    })
    res = sfg.poll_portfolio("job-abc", interval=1, max_wait=1)
    assert res.get("ok") is False, "超时不得返回 ok=True 假成功"
    assert res.get("poll_timeout") is True
    assert res.get("job_id") == "job-abc"
    assert "job-abc" in res.get("error", ""), "超时报错要带上 job_id 才能续查"


# ── 8. 条件式筛选的参数构造（intent screen fund）──────────────

def test_parse_conditions_attaches_number_to_metric():
    """数字必须贴着指标词取——「近3年收益大于20%」不是收益 3%，「2024年夏普
    大于1」不是夏普 2024。这是修复后的回归锚（旧写法全文 findall）。"""
    from cmd_intent import _parse_conditions

    assert _parse_conditions("近3年收益大于20%的基金", 2026) == [{"year": 2026, "yieldMin": 0.2}]
    assert _parse_conditions("2024年夏普大于1的基金", 2026) == [{"year": 2024, "sharpeMin": 1.0}]
    assert _parse_conditions("最大回撤小于15%的基金", 2026) == [{"year": 2026, "maxDrawdown": -0.15}]
    # 回撤接口是负数口径
    cond = _parse_conditions("回撤小于两成", 2026)
    assert cond is None or cond[0].get("maxDrawdown", 0) <= 0


def test_parse_conditions_fee_percent():
    """费率是百分数口径，含 0.5% / 1% / 1.5% 均需转为小数。"""
    from cmd_intent import _parse_conditions

    assert _parse_conditions("费率低于0.5%的指数基金", 2026) == [{"year": 2026, "feeMax": 0.005}]
    assert _parse_conditions("管理费率低于1%", 2026) == [{"year": 2026, "feeMax": 0.01}]
    assert _parse_conditions("管理费低于1.5%的主动基金", 2026) == [{"year": 2026, "feeMax": 0.015}]


def test_parse_conditions_multi_factor_and_low_percent():
    """v3.8.2：多因子条件方向不得串台，带 % 的低阈值（3%/5%）不得漏除 100。"""
    from cmd_intent import _parse_conditions

    assert _parse_conditions("年化收益大于15%且回撤低于20%", 2026) == [
        {"year": 2026, "maxDrawdown": -0.2, "yieldMin": 0.15}
    ]
    assert _parse_conditions("收益大于3%且回撤低于5%的固收+基金", 2026) == [
        {"year": 2026, "maxDrawdown": -0.05, "yieldMin": 0.03}
    ]


def test_parse_conditions_ignores_rank_intent():
    """「前十」是排名意图，不是阈值筛选（旧判据含裸「前」会误判）。"""
    from cmd_intent import _parse_conditions, _COND_WORDS

    assert _parse_conditions("白酒基金前十", 2026) is None
    assert _parse_conditions("白酒基金", 2026) is None
    assert "前" not in _COND_WORDS


# ── 9. 未映射工具在发现层可见 ─────────────────────────────────

def test_unmapped_tools_are_declared():
    """上游 45 个工具不得有「隐形」：未建别名的也要登记用途或标边界外。"""
    assert sfg.TOOLS_UNMAPPED, "未映射工具清单为空"
    assert "sfg_index_enhance" in sfg.TOOLS_UNMAPPED
    # 投顾账户域必须显式标边界外，避免被当成可用能力
    advisor = [t for t, note in sfg.TOOLS_UNMAPPED.items() if t.startswith("sfg_client")]
    assert advisor and all("边界外" in sfg.TOOLS_UNMAPPED[t] for t in advisor)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
