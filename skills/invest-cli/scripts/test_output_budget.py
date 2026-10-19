#!/usr/bin/env python3
"""输出体积预算：screen --limit / sec --brief / us --history --brief（全部离线）。

为什么单独一组：这三个命令的默认载荷会撞上 agent 工具的 24k 字符上限
（sec 28.5k、us --history 59.9k、东财选股更肥），撞上就是**断裂 JSON**。
裁剪必须带 total/returned/truncated 或 omitted 计数，不能静默丢数据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _mxds_payload(n: int) -> dict:
    return {
        "source": "mxds", "kind": "screen", "ok": True,
        "data": {"data": [{
            "columns": ["代码", "名称"],
            "items": [[f"{i:06d}", f"股票{i}"] for i in range(n)],
            "sheetName": "测试",
        }]},
    }


def _eastmoney_payload(n: int) -> dict:
    md = "|代码|名称|\n|---|---|\n" + "\n".join(f"|{i:06d}|股票{i}|" for i in range(n))
    return {
        "source": "eastmoney", "kind": "screen", "ok": True,
        "data": {"success": True, "data": {"requestId": "x",
                                           "data": {"partialResults": md, "securityCount": n}}},
    }


def test_screen_limit_trims_mxds_and_reports_total(monkeypatch, capsys) -> None:
    import cmd_screen
    from sources import route

    monkeypatch.setattr(route, "fetch", lambda kind, arg: _mxds_payload(42))
    assert cmd_screen.run("x", as_json=True, limit=20) == 0
    out = json.loads(capsys.readouterr().out)
    table = out["data"][0]
    assert len(table["items"]) == 20
    assert table["items_total"] == 42 and table["truncated"] is True
    assert out["screen_meta"] == {"total": 42, "returned": 20, "truncated": True, "limit": 20}


def test_screen_limit_trims_eastmoney_markdown(monkeypatch, capsys) -> None:
    import cmd_screen
    from sources import route

    monkeypatch.setattr(route, "fetch", lambda kind, arg: _eastmoney_payload(25))
    assert cmd_screen.run("x", as_json=True, limit=20) == 0
    out = json.loads(capsys.readouterr().out)
    inner = out["data"]["data"]
    assert inner["rows_returned"] == 20
    assert inner["partialResults"].count("\n") == 21  # 表头 + 分隔线 + 20 行
    assert out["screen_meta"]["total"] == 25


def test_screen_limit_zero_keeps_everything(monkeypatch, capsys) -> None:
    import cmd_screen
    from sources import route

    monkeypatch.setattr(route, "fetch", lambda kind, arg: _mxds_payload(42))
    assert cmd_screen.run("x", as_json=True, limit=0) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["data"][0]["items"]) == 42
    assert "screen_meta" not in out


def test_sec_brief_drops_series_but_keeps_metrics(monkeypatch, capsys) -> None:
    import cmd_sec
    from sources import sec_edgar

    payload = {"source": "sec_edgar", "kind": "snapshot", "ok": True, "data": {
        "ticker": "AAPL", "metrics": {"revenue": {"value": 1}},
        "series": {"revenue": [1, 2, 3], "net_income": [1, 2, 3]},
    }}
    monkeypatch.setattr(sec_edgar, "snapshot", lambda *a, **k: payload)
    assert cmd_sec.run("AAPL", as_json=True, brief=True) == 0
    out = json.loads(capsys.readouterr().out)
    assert "series" not in out["data"]
    assert out["data"]["series_omitted"] == 2
    assert out["data"]["metrics"]["revenue"]["value"] == 1


def test_us_history_brief_drops_bars(monkeypatch, capsys) -> None:
    import cmd_us
    from sources import tiingo

    payload = {"ok": True, "data": {
        "symbol": "AAPL", "summary": {"bars": 2}, "bars": [{"date": "2026-01-01"}, {"date": "2026-01-02"}],
    }}
    monkeypatch.setattr(tiingo, "eod_history", lambda *a, **k: payload)
    assert cmd_us.print_eod_history("AAPL", as_json=True, brief=True) == 0
    out = json.loads(capsys.readouterr().out)
    assert "bars" not in out
    assert out["bars_omitted"] == 2 and out["brief"] is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
