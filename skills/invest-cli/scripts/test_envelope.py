#!/usr/bin/env python3
"""--envelope 统一输出契约的守卫（无网络）。

背景：`--json` 顶层有十几种形状（裸载荷 / {ok,...} 信封 / 源名字典 / {data}），
agent 每接一个命令都要先猜形状。`--envelope` 是**opt-in** 的统一层：
默认输出一个字节不变，开启后恒为 `{ok, source, data, error, meta}`。

本文件钉住四件事：
1. 旗标写在子命令前/后等价（子解析器原本会 rc=2）；
2. 信封内置信封（quote/cn）→ 不二次包裹；
3. 裸载荷（stock/fund）→ 整块进 data；
4. 失败时 error 取 stderr 原因，而不是只剩一个退出码。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from invest_cli import _envelope_payload  # noqa: E402


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["INVEST_CLI_CACHE_DIR"] = env.get("PYTEST_TMPDIR", "/tmp/invest-env-cache")
    env["INVEST_CLI_STATE_DIR"] = env.get("PYTEST_TMPDIR", "/tmp/invest-env-state")
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / "invest_cli.py"), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_envelope_flag_position_independent() -> None:
    before = _run(["--envelope", "watchlist", "--json"])
    after = _run(["watchlist", "--json", "--envelope"])
    assert before.returncode == 0 and after.returncode == 0
    a, b = json.loads(before.stdout), json.loads(after.stdout)
    assert a["ok"] is True and b["ok"] is True
    assert a["meta"]["command"] == b["meta"]["command"] == "watchlist"
    assert isinstance(a["data"].get("items"), list)


def test_envelope_keeps_existing_envelope_flat() -> None:
    raw = '{"ok": true, "source": "tencent", "data": {"n": 1}, "error": null}'
    outer = _envelope_payload("quote", raw, 0, 1.0)
    assert (outer["ok"], outer["source"], outer["data"], outer["error"]) == (
        True, "tencent", {"n": 1}, None)
    assert outer["meta"]["command"] == "quote"
    assert outer["meta"]["chars"] == len(raw)


def test_envelope_wraps_bare_payload() -> None:
    outer = _envelope_payload("stock", '{"source": "hithink", "code": "600519"}', 0, 2.0)
    assert outer["ok"] is True and outer["source"] == "hithink"
    assert outer["data"] == {"source": "hithink", "code": "600519"}


def test_envelope_failure_uses_stderr_reason() -> None:
    outer = _envelope_payload("stock", "", 1, 0.5, "错误: 空标的：stock 需要代码或名称\n")
    assert outer["ok"] is False
    assert "空标的" in outer["error"]


def test_envelope_success_keeps_stderr_warning_in_meta() -> None:
    outer = _envelope_payload("sec", '{"ok": true, "source": "sec_edgar", "data": {}}', 0, 1.0,
                              "提示: SEC UA 仍用占位邮箱\n")
    assert outer["ok"] is True
    assert "SEC UA" in outer["meta"]["stderr"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
