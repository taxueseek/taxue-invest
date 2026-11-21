#!/usr/bin/env python3
"""research etf-rank 契约 — 用 2026-11-08 的真实回包形状，不打外部网络。

钉住四件事：
1. 指数代码走 index_codes、名称走 keyword，top_n 是成分股条数；
2. 真实回包的 selection_result 直挂 data，同时兼容文档写的 raw_result.body；
3. 结构缺失、fund_items 为空、上游失败都必须 rc=1，不许返回空表；
4. 排序、规模<2亿汇总、risk_note 原样透出，--out 落盘可复核。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cmd_research as R  # noqa: E402


def _fund(code: str, name: str, score=None, scale=10.0, risk=None) -> dict:
    return {
        "fund_code": code, "fund_name": name, "fund_company": "某基金",
        "type_name": None, "establish_date": "2013-03-06",
        "index_code": "000300", "index_name": "沪深300",
        "fund_size_yi": scale, "management_fee": 0.15, "custodian_fee": 0.05,
        "sales_service_fee": None, "total_fee": 0.2, "period_code": "03",
        "metric_date": "2026-11-06", "excess_return": 1.2,
        "tracking_error": 0.35, "information_ratio": 5.0, "correlation": 99.5,
        "score": score, "risk_note": risk,
    }


def _selection(funds, score_note="未含实时成交额") -> dict:
    return {"code": "0000", "message": "success", "data": {
        "index_candidates": [{"index_code": "000300", "index_name": "沪深300",
                              "fund_count": len(funds)}],
        "fund_items": funds,
        "component_items": [{"index_code": "000300", "index_name": "沪深300指数",
                             "component_trade_date": "2026-11-06", "component_count": 300,
                             "top10_weight_pct": 22.43, "rank_no": 1,
                             "stock_code": "600519", "stock_name": "贵州茅台",
                             "weight_pct": 3.88}],
        "valuation_items": [{"trade_date": "2026-11-06", "pe_ttm": 13.5, "pb": 1.23,
                             "pe_percentile_5y": 74.83, "pb_percentile_5y": 37.38,
                             "valuation_level": "偏高", "quadrant": "黄金象限"}],
        "score_note": score_note,
    }}


def _payload(funds=None, score_note="未含实时成交额") -> dict:
    return {"source": "ttskill", "kind": "TTFUND_INDEX_FUND_SELECTION", "ok": True,
            "data": {"success": True, "action": "query",
                     "selection_result": _selection(funds or [], score_note)},
            "error": None}


def test_request_uses_code_or_keyword() -> None:
    assert R._etf_request("000300", "03", 10) == {
        "period_codes": ["03"], "top_n": 10, "index_codes": ["000300"]}
    assert R._etf_request("沪深300", "03", 99) == {
        "period_codes": ["03"], "top_n": 50, "keyword": "沪深300"}


def test_selection_of_accepts_documented_nested_shape() -> None:
    sr = _selection([_fund("510310", "沪深300ETF易方达", 100)])
    assert R._selection_of({"selection_result": sr}) is sr
    assert R._selection_of({"raw_result": {"body": {"selection_result": sr}}}) is sr


def test_parse_sorts_and_flags_missing_and_small() -> None:
    parsed = R._parse_etf(_selection([
        _fund("000001", "小规模基金", 90, scale=1.5, risk="规模低于2亿"),
        _fund("510310", "沪深300ETF易方达", 100, scale=517.9),
        _fund("999999", "无评分基金", None, scale=10),
    ]))
    assert [f["code"] for f in parsed["funds"]] == ["510310", "000001", "999999"]
    assert parsed["funds"][1]["risk_note"] == "规模低于2亿"
    assert parsed["score_note"] == "未含实时成交额"
    assert parsed["component_meta"]["count"] == 300
    assert parsed["valuation"]["pe_ttm"] == 13.5


def test_run_json_end_to_end(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sources.ttskill.invoke_scene", lambda sid, body: _payload([
        _fund("510310", "沪深300ETF易方达", 100, scale=517.9),
        _fund("510300", "沪深300ETF华泰柏瑞", 99.6, scale=1000),
    ]))
    assert R.run("etf-rank", "000300", top=2, as_json=True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["index_name"] == "沪深300"
    assert out["funds"][0]["rank"] == 1
    assert out["funds"][0]["code"] == "510310"
    assert out["valuation"]["valuation_level"] == "偏高"
    assert out["small_scale"] == []
    assert out["provenance"]["score_note"] == "未含实时成交额"


def test_run_text_and_out(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr("sources.ttskill.invoke_scene", lambda sid, body: _payload([
        _fund("510310", "沪深300ETF易方达", 100, scale=517.9),
        _fund("000001", "小规模基金", 50, scale=1.2, risk="规模低于2亿"),
    ]))
    assert R.run("etf-rank", "沪深300", top=2, out=str(tmp_path), as_json=False) == 0
    text = capsys.readouterr().out
    assert "指数基金横评" in text
    assert "510310" in text
    assert "规模<2亿" in text
    assert "贵州茅台" in text
    assert (tmp_path / "result.json").is_file()
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| 1 | 510310 |" in report
    assert "规模低于2亿" in report


def test_empty_fund_items_is_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sources.ttskill.invoke_scene", lambda sid, body: _payload([]))
    assert R.run("etf-rank", "000300") == 1
    assert "fund_items 为空" in capsys.readouterr().err


def test_missing_selection_result_is_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sources.ttskill.invoke_scene",
                        lambda sid, body: {"ok": True, "data": {"success": True}})
    assert R.run("etf-rank", "000300") == 1
    assert "selection_result" in capsys.readouterr().err


def test_upstream_failure_is_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sources.ttskill.invoke_scene", lambda sid, body: {
        "ok": False, "error": "登录已过期"})
    assert R.run("etf-rank", "000300") == 1
    assert "登录已过期" in capsys.readouterr().err


def test_bad_period_rejected_before_call(monkeypatch, capsys) -> None:
    called = []
    monkeypatch.setattr("sources.ttskill.invoke_scene",
                        lambda sid, body: called.append(1) or _payload([]))
    assert R.run("etf-rank", "000300", period="2y") == 1
    assert called == []
    assert "--period" in capsys.readouterr().err


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
