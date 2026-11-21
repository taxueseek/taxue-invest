"""invest-recap-card 离线单元测试。"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_market  # noqa: E402
import render_card  # noqa: E402
import run  # noqa: E402


def test_fetch_market_returns_error_without_fake_numbers(monkeypatch):
    monkeypatch.setattr(fetch_market, "_cli_prefix", lambda: None)
    data = fetch_market.fetch_market_data(datetime.date(2026, 11, 13))

    assert data["sh_index"]["close"] is None
    assert data["turnover_total"] is None
    assert "未安装" in data.get("fetch_error", "")


def test_fetch_market_parses_historical_kline_envelope(monkeypatch):
    monkeypatch.setattr(fetch_market, "_cli_prefix", lambda: ["fake-invest-cli"])

    def fake_run(cmd, **_kwargs):
        sym = cmd[2]
        rows_by_sym = {
            "sh000001": [
                {"date": "2026-11-11", "close": 3400.0},
                {"date": "2026-11-12", "close": 3434.0, "high": 3450.5, "low": 3395.0, "amount": 6.5e11},
            ],
            "sz399001": [
                {"date": "2026-11-11", "close": 11000.0},
                {"date": "2026-11-12", "close": 11110.0, "amount": 9.8e11},
            ],
            "sz399006": [
                {"date": "2026-11-11", "close": 2300.0},
                {"date": "2026-11-12", "close": 2346.0},
            ],
        }
        payload = {"ok": True, "data": {"symbol": sym, "rows": rows_by_sym[sym]}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(fetch_market.subprocess, "run", fake_run)
    data = fetch_market.fetch_market_data(datetime.date(2026, 11, 12))

    assert data["sh_index"]["close"] == 3434.0
    assert data["sh_index"]["change"] == 34.0
    assert data["sh_index"]["change_pct"] == "+1.00%"
    assert data["sh_index"]["high"] == 3450.5
    assert data["sh_index"]["low"] == 3395.0
    assert data["sz_index"]["change_pct"] == "+1.00%"
    assert data["cy_index"]["close"] == 2346.0
    assert data["cy_index"]["change_pct"] == "+2.00%"
    assert "fetch_error" not in data


def test_fetch_market_parses_today_quote_envelope(monkeypatch):
    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    monkeypatch.setattr(fetch_market, "_cli_prefix", lambda: ["fake-invest-cli"])

    def fake_run(cmd, **_kwargs):
        subcmd = cmd[1]
        if subcmd == "kline":
            payload = {
                "ok": True,
                "data": {"rows": [{"date": today_str, "close": 3480.0, "high": 3495.0, "low": 3460.0}]},
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        if subcmd == "quote":
            payload = {
                "ok": True,
                "data": {
                    "quotes": [
                        {"symbol": "sh000001", "price": 3488.25, "change": 18.5, "change_pct": 0.53, "high": 3496.0, "low": 3462.0, "amount": 7.2e11},
                        {"symbol": "sz399001", "price": 11220.10, "change_pct": 1.12, "amount": 9.3e11},
                        {"symbol": "sz399006", "price": 2380.40, "change_pct": 1.65},
                    ]
                },
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="westock unavailable")

    monkeypatch.setattr(fetch_market.subprocess, "run", fake_run)
    data = fetch_market.fetch_market_data(today)

    assert data["sh_index"]["close"] == 3488.25
    assert data["sh_index"]["change_pct"] == "+0.53%"
    assert data["sz_index"]["change_pct"] == "+1.12%"
    assert data["cy_index"]["close"] == 2380.40
    assert data["turnover_total"] == "1.65 万亿"


def test_build_card_html_is_dynamic_and_escapes_html():
    market = {
        "date": "2026-11-12",
        "weekday": "周四",
        "is_today": False,
        "sh_index": {"close": 3488.25, "change": 28.1, "change_pct": "+0.81%", "high": 3492.0, "low": 3455.0},
        "sz_index": {"close": 11220.1, "change_pct": "+1.12%"},
        "cy_index": {"close": 2380.4, "change_pct": "+1.45%"},
        "turnover_total": "1.65万亿",
    }
    html = run.build_card_html(
        market,
        title="周四观察：<script>alert(1)</script>",
        content_overrides={
            "subtitle": '测试副标题 "引号" & <tag>',
            "col1_items": [{"label": "热点<x>", "text": "算力 & 存储"}],
        },
    )

    assert "3488.25" in html
    assert "+0.81%" in html
    assert "1.65万亿" in html
    assert "3700 点" not in html
    assert "1.5 万亿" not in html
    assert "双双翻绿" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "测试副标题 &quot;引号&quot; &amp; &lt;tag&gt;" in html
    assert "<strong>热点&lt;x&gt;：</strong>算力 &amp; 存储" in html


def test_run_main_refuses_render_on_empty_market(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "get_target_date", lambda _spec: datetime.date(2026, 11, 13))
    monkeypatch.setattr(
        run,
        "fetch_market_data",
        lambda _dt: {
            "date": "2026-11-13",
            "weekday": "周五",
            "is_today": False,
            "sh_index": {"close": None, "change": None, "change_pct": None, "high": None, "low": None},
            "sz_index": {"close": None, "change_pct": None},
            "cy_index": {"close": None, "change_pct": None},
            "turnover_total": None,
            "fetch_error": "mock failure",
        },
    )
    called = []
    monkeypatch.setattr(run, "render_html_to_artifacts", lambda *a, **kw: called.append((a, kw)) or True)
    monkeypatch.setattr(sys, "argv", ["run.py", "--date", "2026-11-13", "--out-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc:
        run.main()

    assert exc.value.code == 1
    assert called == []


def test_render_card_passes_paths_via_argv(monkeypatch, tmp_path):
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

    monkeypatch.setattr(render_card.subprocess, "run", fake_run)
    monkeypatch.setattr(render_card, "_resolve_render_python", lambda: "/usr/bin/python3")

    html_f = tmp_path / "a'b \"c\".html"
    pdf_f = tmp_path / "out.pdf"
    png_f = tmp_path / "out.png"
    html_f.write_text("<html></html>", encoding="utf-8")

    ok = render_card.render_html_to_artifacts(html_f, pdf_f, png_f, dpi=180)
    assert ok is True
    assert recorded["cmd"][0] == "/usr/bin/python3"
    assert recorded["cmd"][1] == "-c"
    assert str(html_f.resolve()) not in recorded["cmd"][2]
    assert recorded["cmd"][3:] == [str(html_f.resolve()), str(pdf_f.resolve()), str(png_f.resolve()), "180"]
