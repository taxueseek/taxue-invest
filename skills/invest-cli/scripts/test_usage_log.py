#!/usr/bin/env python3
"""运行时事实层（usage_log）的行为契约。

这层存在的理由：651 条测试此前全是静态猜（AST/正则/体积/F401），没有任何一条
记录「运行时到底发生了什么」。这里钉住四件事：

1. 写一条、读一条，字段形状稳定；
2. 损坏行（进程被杀留下的半行）不让整本账作废；
3. 开关 INVEST_CLI_USAGE_LOG=0 能彻底关闭（隐私敏感/测试场景）；
4. route.fetch 只在默认路径记账：注入链是造出来的、缓存命中没碰源，都不写。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import _common
from _common import usage_emit, usage_log_dir, usage_tail


def _write(records: list[dict]) -> None:
    d = usage_log_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "calls.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def _ts(minutes_ago: float = 0) -> str:
    return (datetime.now().astimezone() - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds")


def test_emit_and_tail_roundtrip() -> None:
    assert usage_emit({"kind": "stock", "ok": True, "source": "hithink"}) is True
    rows = usage_tail(10)
    assert len(rows) == 1
    assert rows[0]["kind"] == "stock"
    assert rows[0]["source"] == "hithink"
    assert rows[0]["version"] == 1
    assert rows[0]["ts"]


def test_switch_off_disables_both_sides(monkeypatch) -> None:
    monkeypatch.setenv("INVEST_CLI_USAGE_LOG", "0")
    assert usage_emit({"kind": "stock", "ok": True}) is False
    assert usage_tail() == []


def test_corrupt_line_is_skipped_not_fatal(monkeypatch) -> None:
    d = usage_log_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "calls.jsonl").write_text(
        json.dumps({"ts": _ts(), "kind": "stock", "ok": True}) + "\n"
        + '{"ts": "2026-11-08T10:00:00", "kind": "sto\n'  # 半行
        + json.dumps({"ts": _ts(), "kind": "fund", "ok": False}) + "\n",
        encoding="utf-8",
    )
    rows = usage_tail(10)
    assert [r["kind"] for r in rows] == ["stock", "fund"]


def test_oversize_log_is_rolled_down(monkeypatch) -> None:
    monkeypatch.setattr(_common, "USAGE_LOG_MAX_BYTES", 200)
    monkeypatch.setattr(_common, "USAGE_LOG_KEEP_LINES", 2)
    for i in range(6):
        usage_emit({"kind": "stock", "ok": True, "n": i})
    rows = usage_tail(10)
    # 回缩保留最近 N 行后再追加当前这条，稳态是 N+1 行——关键契约是「有界」且
    # 「留下的是最新的」，不是精确等于 N。
    assert len(rows) <= 3
    assert [r["n"] for r in rows] == sorted(r["n"] for r in rows)
    assert rows[-1]["n"] == 5


def test_route_fetch_logs_default_path(monkeypatch) -> None:
    import sources.route as route

    monkeypatch.setattr(route, "_fetch_impl", lambda *a, **kw: {
        "ok": True, "source": "hithink",
        "fallback_from": "eastmoney", "fallback_error": "eastmoney: 超时",
    })
    route.fetch("stock", "600519")
    row = usage_tail(1)[0]
    assert row["kind"] == "stock"
    assert row["ok"] is True
    assert row["source"] == "hithink"
    assert row["fallback_from"] == "eastmoney"
    assert isinstance(row["elapsed_ms"], int)


def test_route_fetch_does_not_log_injected_or_cached(monkeypatch) -> None:
    import sources.route as route

    monkeypatch.setattr(route, "_fetch_impl", lambda *a, **kw: {"ok": True})
    route.fetch("stock", "600519", order=["hithink"])
    monkeypatch.setattr(route, "_fetch_impl", lambda *a, **kw: {
        "ok": True, "source": "hithink", "cached": True})
    route.fetch("stock", "600519")
    assert usage_tail() == []


def test_route_fetch_logs_per_source_errors(monkeypatch) -> None:
    import sources.route as route

    monkeypatch.setattr(route, "_fetch_impl", lambda *a, **kw: {
        "ok": False,
        "error": "hithink: 配额用尽; eastmoney: 超时",
        "tried": ["hithink", "eastmoney"],
    })
    route.fetch("fund", "005827")
    row = usage_tail(1)[0]
    assert row["ok"] is False
    assert row["errors"] == ["hithink: 配额用尽", "eastmoney: 超时"]
    assert row["tried"] == ["hithink", "eastmoney"]


def test_input_rejection_is_not_logged() -> None:
    """空标的在触碰任何源之前就被拒，不该进账本（否则错字会污染连续失败判据）。"""
    from sources.route import fetch

    assert fetch("stock", "")["ok"] is False
    assert usage_tail() == []


def test_doctor_warns_on_consecutive_failures() -> None:
    from cmd_doctor import check_usage

    _write([
        {"ts": _ts(30), "kind": "stock", "ok": True, "source": "hithink"},
        {"ts": _ts(20), "kind": "stock", "ok": False,
         "error": "hithink: 配额用尽", "errors": ["hithink: 配额用尽"]},
        {"ts": _ts(10), "kind": "stock", "ok": False,
         "error": "hithink: 配额用尽", "errors": ["hithink: 配额用尽"]},
        {"ts": _ts(5), "kind": "stock", "ok": False,
         "error": "hithink: 配额用尽", "errors": ["hithink: 配额用尽"]},
    ])
    status, detail = check_usage()
    assert status == "warn", detail
    assert "连续失败" in detail
    assert "hithink×3" in detail


def test_doctor_ignores_records_older_than_window() -> None:
    from cmd_doctor import check_usage

    _write([{"ts": _ts(60 * 48), "kind": "stock", "ok": False, "errors": ["hithink: x"]}])
    status, detail = check_usage()
    assert status == "pass", detail
    assert "最近 24h 无取数" in detail


def test_doctor_passes_on_healthy_recent_calls() -> None:
    from cmd_doctor import check_usage

    _write([{"ts": _ts(i), "kind": "stock", "ok": True, "source": "hithink"}
            for i in range(6)])
    status, detail = check_usage()
    assert status == "pass", detail
    assert "成功 6" in detail


def test_usage_stats_separates_source_and_command() -> None:
    """源级与命令级共用一个文件，但统计必须分开：两者的失败含义不同。"""
    from _common import usage_stats

    _write([
        {"ts": _ts(30), "kind": "stock", "ok": True, "source": "hithink"},
        {"ts": _ts(20), "kind": "fund", "ok": False, "errors": ["eastmoney: 超时"]},
        {"ts": _ts(10), "scope": "cmd", "cmd": "stock", "ok": True, "rc": 0},
        {"ts": _ts(5), "scope": "cmd", "cmd": "report", "ok": False, "rc": 1},
    ])
    stats = usage_stats(24.0)
    assert stats["source"]["total"] == 2
    assert stats["source"]["ok"] == 1
    assert stats["source"]["by_source"] == {"eastmoney": 1}
    assert stats["source"]["consecutive"] == {"fund": 1}
    assert stats["cmd"]["total"] == 2
    assert stats["cmd"]["failed"] == 1
    assert stats["cmd"]["consecutive"] == {"report": 1}
    assert stats["direct"]["total"] == 0


def test_usage_stats_separates_direct_source_calls() -> None:
    """直取命令不进 route，源级统计不能把它们算成快照链的 kind。"""
    from _common import usage_stats

    _write([
        {"ts": _ts(30), "kind": "stock", "ok": True, "source": "hithink"},
        {"ts": _ts(20), "scope": "direct", "src": "htbr", "cmd": "htbr", "ok": True},
        {"ts": _ts(10), "scope": "direct", "src": "htbr", "cmd": "htbr", "ok": False},
        {"ts": _ts(5), "scope": "cmd", "cmd": "htbr", "ok": False, "rc": 1},
    ])
    stats = usage_stats(24.0)
    assert stats["source"]["total"] == 1
    assert stats["direct"]["total"] == 2
    assert stats["direct"]["failed"] == 1
    assert stats["direct"]["consecutive"] == {"htbr": 1}
    assert stats["cmd"]["total"] == 1


def test_direct_command_logs_both_records() -> None:
    import time

    from invest_cli import _log_command_usage

    _log_command_usage("htbr", time.perf_counter(), 1, "配额用尽")
    rows = usage_tail(5)
    scopes = {r.get("scope") for r in rows}
    assert scopes == {"direct", "cmd"}, rows
    direct = next(r for r in rows if r.get("scope") == "direct")
    assert direct["src"] == "htbr" and direct["ok"] is False
    assert "配额用尽" in direct["error"]


def test_doctor_warns_on_repeated_direct_failures() -> None:
    from cmd_doctor import check_usage

    _write([{"ts": _ts(i), "scope": "direct", "src": "htbr", "cmd": "htbr", "ok": False}
            for i in range(5)])
    status, detail = check_usage()
    assert status == "warn", detail
    assert "直取尾部连续失败" in detail
    assert "htbr×5" in detail


def test_doctor_warns_on_repeated_command_failures() -> None:
    from cmd_doctor import check_usage

    _write([{"ts": _ts(i), "scope": "cmd", "cmd": "watchlist", "ok": False, "rc": 1}
            for i in range(5)])
    status, detail = check_usage()
    assert status == "warn", detail
    assert "命令尾部连续失败" in detail
    assert "watchlist×5" in detail


def test_diagnostic_commands_are_not_logged() -> None:
    """doctor/datasources/capabilities 自己读账本，记自己会造成自我干扰。"""
    import time

    from invest_cli import _log_command_usage

    _log_command_usage("doctor", time.perf_counter(), 0)
    _log_command_usage("datasources", time.perf_counter(), 0)
    assert usage_tail() == []

    _log_command_usage("stock", time.perf_counter(), 0)
    row = usage_tail(1)[0]
    assert row["scope"] == "cmd"
    assert row["cmd"] == "stock"
    assert row["ok"] is True


def test_main_writes_command_level_record(tmp_path) -> None:
    """从真实进程入口验证接线：非信封路径也要记账，且退出码不变。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent / "invest_cli.py"
    env = dict(os.environ)
    env.update({
        "INVEST_CLI_STATE_DIR": str(tmp_path / "state"),
        "INVEST_CLI_CACHE_DIR": str(tmp_path / "cache"),
        "INVEST_CLI_USAGE_LOG": "1",
    })
    proc = subprocess.run([sys.executable, str(script), "watchlist", "list"],
                          capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    rows = [r for r in usage_tail(50) if r.get("scope") == "cmd"]
    assert len(rows) == 1, rows
    assert rows[0]["cmd"] == "watchlist"
    assert rows[0]["ok"] is True
    assert rows[0]["rc"] == 0


def test_datasources_surfaces_ledger(monkeypatch, capsys) -> None:
    """datasources 是排查入口：账本要能顺手看到，而不是只埋在一个文件里。"""
    import cmd_datasources
    import sources.registry as registry
    import sources.route as route

    monkeypatch.setattr(registry, "detect_all", lambda: {
        "hithink": {"available": True, "priority": 80, "coverage": ["stock"],
                    "detail": "ok", "route_kinds": ["stock"]},
    })
    monkeypatch.setattr(registry, "available_ids", lambda *a, **k: ["hithink"])
    monkeypatch.setattr(route, "chains", lambda: {"stock": ["hithink"]})
    _write([{"ts": _ts(5), "kind": "stock", "ok": True, "source": "hithink"}])

    assert cmd_datasources.run(as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["_usage"]["source"]["total"] == 1
    assert payload["_usage"]["cmd"]["total"] == 0

    assert cmd_datasources.run() == 0
    text = capsys.readouterr().out
    assert "运行时账本" in text
    assert "源级 1 次" in text


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


# ── P2（2026-11-09）：交付条数与空结果 ────────────────────────────────────

def test_usage_bucket_aggregates_delivered_and_empty() -> None:
    """_usage_bucket 必须按源聚合交付条数与空结果数（P2）。"""
    from _common import _usage_bucket

    rows = [
        {"ok": True, "source": "hithink", "kind": "stock", "count": 1, "elapsed_ms": 100},
        {"ok": True, "source": "tencent", "kind": "stock", "count": 0, "empty": True,
         "elapsed_ms": 50},
        {"ok": True, "source": "hithink", "kind": "fund", "count": 1, "elapsed_ms": 120},
        {"ok": False, "kind": "stock", "errors": ["yfinance: timeout"]},
    ]
    bucket = _usage_bucket(rows, "kind")
    # delivered 按 source 聚合（source 优先于 kind），所以 hithink 两笔相加；
    # 0 条也记（tencent 空转是事实，P3 的 suspected_stale 要靠它区分「从未出货」）
    assert bucket["delivered"] == {"hithink": 2, "tencent": 0}, bucket["delivered"]
    assert bucket["empty"] == {"tencent": 1}, bucket["empty"]
    assert bucket["ok"] == 3 and bucket["failed"] == 1


def test_route_logs_count_for_list_and_dict() -> None:
    """列表 data 记元素数，dict 记 1，空 dict 记 0（P2 粒度口径）。"""
    from sources.route import _result_row_count

    assert _result_row_count({"ok": True, "data": [1, 2, 3]}) == 3
    assert _result_row_count({"ok": True, "data": {"a": 1}}) == 1
    assert _result_row_count({"ok": True, "data": {}}) == 0
    assert _result_row_count({"ok": True, "data": None}) == 0
    assert _result_row_count({"ok": False}) == 0


def test_route_emits_count_in_record(monkeypatch, tmp_path) -> None:
    """成功取数的账本记录必须带 count（P2 接线锚）。"""
    from sources import route

    records = []
    import _common
    monkeypatch.setattr(_common, "usage_emit", lambda rec: records.append(rec))

    route._emit_usage("stock", "600519", None,
                      {"ok": True, "source": "hithink", "data": {"code": "600519"}}, 0.0)
    assert records and records[-1]["count"] == 1, records
    assert "empty" not in records[-1]


# ── P3（2026-11-09）：空结果基线破位 suspected_stale ────────────────────────

def test_suspected_stale_detects_baseline_break() -> None:
    """历史曾非空 + 近期连续空 ≥3 + 跨 ≥2 查询 → suspected_stale（P3）。"""
    from _common import _suspected_stale

    rows = [
        {"ok": True, "source": "htbr", "arg": "A", "count": 5, "ts": "2026-11-08T10:00:00"},
        {"ok": True, "source": "htbr", "arg": "B", "count": 0, "empty": True,
         "ts": "2026-11-09T10:00:00"},
        {"ok": True, "source": "htbr", "arg": "C", "count": 0, "empty": True,
         "ts": "2026-11-09T11:00:00"},
        {"ok": True, "source": "htbr", "arg": "D", "count": 0, "empty": True,
         "ts": "2026-11-09T12:00:00"},
    ]
    stale = _suspected_stale(rows)
    assert "htbr" in stale, stale
    assert stale["htbr"]["consecutive_empty"] == 3
    assert stale["htbr"]["distinct_queries"] == 3


def test_suspected_stale_ignores_never_nonempty_source() -> None:
    """从未交付过非空结果的源不判（无基线可破，可能是新源/新凭据）。"""
    from _common import _suspected_stale

    rows = [
        {"ok": True, "source": "new_src", "arg": "A", "count": 0, "empty": True},
        {"ok": True, "source": "new_src", "arg": "B", "count": 0, "empty": True},
        {"ok": True, "source": "new_src", "arg": "C", "count": 0, "empty": True},
    ]
    assert _suspected_stale(rows) == {}


def test_suspected_stale_requires_distinct_queries() -> None:
    """同一查询反复空不算破位（防单查询抖动误报）。"""
    from _common import _suspected_stale

    rows = [
        {"ok": True, "source": "s", "arg": "X", "count": 1, "ts": "t0"},
        {"ok": True, "source": "s", "arg": "X", "count": 0, "empty": True},
        {"ok": True, "source": "s", "arg": "X", "count": 0, "empty": True},
        {"ok": True, "source": "s", "arg": "X", "count": 0, "empty": True},
    ]
    assert _suspected_stale(rows) == {}


def test_usage_stats_exposes_suspected_stale(monkeypatch, tmp_path) -> None:
    """usage_stats 顶层必须暴露 suspected_stale（doctor/datasources 消费）。"""
    import _common

    from datetime import datetime, timedelta

    def _ts(hours_ago: float) -> str:
        return (datetime.now().astimezone() - timedelta(hours=hours_ago)).isoformat(
            timespec="seconds"
        )

    recs = [
        {"ts": _ts(4), "ok": True, "source": "s", "arg": "A", "count": 1},
        {"ts": _ts(3), "ok": True, "source": "s", "arg": "B", "count": 0, "empty": True},
        {"ts": _ts(2), "ok": True, "source": "s", "arg": "C", "count": 0, "empty": True},
        {"ts": _ts(1), "ok": True, "source": "s", "arg": "D", "count": 0, "empty": True},
    ]
    monkeypatch.setattr(_common, "usage_tail", lambda n=200: recs)
    stats = _common.usage_stats(24.0)
    assert "suspected_stale" in stats
    assert "s" in stats["suspected_stale"]


def test_doctor_check_usage_includes_suspected_stale_detail(monkeypatch) -> None:
    """doctor check_usage 必须把 suspected_stale 源名与次数拼进输出，不能在 join 之后追加。"""
    from datetime import datetime, timedelta
    import _common
    import cmd_doctor

    def _ts(hours_ago: float) -> str:
        return (datetime.now().astimezone() - timedelta(hours=hours_ago)).isoformat(
            timespec="seconds"
        )

    recs = [
        {"ts": _ts(4), "ok": True, "source": "hithink", "kind": "stock", "arg": "600519", "count": 1},
        {"ts": _ts(3), "ok": True, "source": "hithink", "kind": "stock", "arg": "000858", "count": 0, "empty": True},
        {"ts": _ts(2), "ok": True, "source": "hithink", "kind": "stock", "arg": "600036", "count": 0, "empty": True},
        {"ts": _ts(1), "ok": True, "source": "hithink", "kind": "stock", "arg": "300750", "count": 0, "empty": True},
    ]
    monkeypatch.setattr(_common, "usage_tail", lambda n=200: recs)
    status, detail = cmd_doctor.check_usage()
    assert status == cmd_doctor.HEALTH_WARN
    assert "hithink" in detail
    assert "基线破位" in detail


def test_doctor_check_usage_shows_7d_summary_when_24h_empty(monkeypatch) -> None:
    """24h 无记录但 7d 内有历史记录时，保留「最近 24h 无取数」口径并附带 7d 摘要。"""
    from datetime import datetime, timedelta
    import _common
    import cmd_doctor

    ts_old = (datetime.now().astimezone() - timedelta(hours=72)).isoformat(timespec="seconds")
    recs = [{"ts": ts_old, "ok": True, "source": "hithink", "kind": "stock", "arg": "600519", "count": 1}]
    monkeypatch.setattr(_common, "usage_tail", lambda n=200: recs)
    status, detail = cmd_doctor.check_usage()
    assert status == cmd_doctor.HEALTH_PASS
    assert "最近 24h 无取数" in detail
    assert "近 7d" in detail


def test_usage_stats_counts_fallback_failed_and_disabled(monkeypatch) -> None:
    """降级成功时 failed_sources 应记入 fallback_failed，且 _emit_usage 记录 disabled 停用集。"""
    from datetime import datetime
    import _common
    from sources import route

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    recs = [{
        "ts": ts, "ok": True, "source": "eastmoney", "kind": "stock",
        "arg": "600036", "count": 1, "fallback_from": "hithink",
        "failed_sources": ["hithink"], "disabled": ["wind"],
    }]
    monkeypatch.setattr(_common, "usage_tail", lambda n=200: recs)
    stats = _common.usage_stats(24.0)
    assert stats["source"]["fallback_failed"] == {"hithink": 1}

    emitted = []
    monkeypatch.setenv("INVEST_CLI_DISABLE_SOURCES", "hithink")
    monkeypatch.setattr(_common, "usage_emit", lambda rec: emitted.append(rec) or True)
    route._emit_usage("stock", "600036", "a", {
        "ok": True, "source": "eastmoney", "data": {"p": 1},
        "fallback_from": "hithink", "fallback_error": "hithink: timeout",
    }, 0.0)
    assert emitted and emitted[0]["failed_sources"] == ["hithink"]
    assert emitted[0]["disabled"] == ["hithink"]
