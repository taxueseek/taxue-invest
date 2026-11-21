#!/usr/bin/env python3
"""信封与状态词真源的契约锁（P1，2026-11-09）。

钉住三件事：
1. 所有适配器的信封都经 sources/envelope 构造，不再各自手写键；
2. doctor 的状态词全部来自真源，手抄字面量清零；
3. 信封键集合与 route 的读取口径一致（防「新增键漏改 route」）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources.envelope import ENVELOPE_KEYS, HEALTH_STATES  # noqa: E402


def test_health_states_are_the_only_doctor_literals() -> None:
    """doctor 不得再出现 pass/warn/fail/skip 字面量（P1 收口）。"""
    src = (_SCRIPTS / "cmd_doctor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in HEALTH_STATES:
                offenders.append(f"L{node.lineno}: {node.value!r}")
    assert not offenders, (
        "cmd_doctor.py 仍有状态词手抄字面量：" + "; ".join(offenders)
        + "\n状态词唯一真源是 sources/envelope.py 的 HEALTH_* 常量。"
    )


def test_doctor_imports_health_states_from_envelope() -> None:
    src = (_SCRIPTS / "cmd_doctor.py").read_text(encoding="utf-8")
    assert "from sources.envelope import" in src
    for name in ("HEALTH_PASS", "HEALTH_WARN", "HEALTH_FAIL", "HEALTH_SKIP"):
        assert name in src, f"cmd_doctor.py 未从真源 import {name}"


def test_envelope_keys_match_route_read_keys() -> None:
    """route 读取的信封键必须是 ENVELOPE_KEYS 的子集（防新增键漏改 route）。"""
    src = (_SCRIPTS / "sources" / "route.py").read_text(encoding="utf-8")
    # route 里实际读取的键
    read_keys = set()
    for key in ("ok", "tried", "fallback_from", "fallback_error", "error", "source", "data"):
        if f'.get("{key}")' in src or f'["{key}"]' in src:
            read_keys.add(key)
    assert read_keys <= ENVELOPE_KEYS, (
        f"route 读取的键不在 ENVELOPE_KEYS 真源里：{read_keys - ENVELOPE_KEYS}"
    )


def test_adapters_use_shared_envelope() -> None:
    """适配器必须走 sources/envelope（P1 + v3.8 sfg 收口）。"""
    for name in ("hithink", "fmp", "tiingo", "tencent", "bitget", "sfg"):
        src = (_SCRIPTS / "sources" / f"{name}.py").read_text(encoding="utf-8")
        assert "from .envelope import" in src, (
            f"sources/{name}.py 的 _envelope 未收口到 sources/envelope"
        )


def test_envelope_constructor_signature() -> None:
    """信封构造的签名即契约：source 必填（防再出现写死 source 的实现）。"""
    import inspect

    from sources.envelope import envelope

    sig = inspect.signature(envelope)
    params = list(sig.parameters)
    assert params[:3] == ["source", "kind", "ok"], f"envelope 签名漂移：{params}"
