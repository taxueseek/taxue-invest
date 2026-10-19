#!/usr/bin/env python3
"""模块体积门禁，纯静态，不联网。

为什么需要：argo 公开版把「模块体积」当硬门禁（`test_module_size_gate.py`），
invest-cli 一直没有。最大文件已到 `sources/sec_edgar.py` 1297 行、
`etf_analytics.py` 1204 行，再长下去单文件的可读性与单测覆盖都会滑坡，
而这类退化没有任何现有检查会报，测试全绿、行为不变，只是越来越难改。

这里只设上限，不规定拆法：超过即失败，拆不拆、怎么拆由改动者决定。
阈值取当前最大值（1297）上方约 8%，留出正常增长空间，又能在「又长出
一个大模块」时立刻拦下。

改大阈值前先问一句：是真的需要，还是这个文件该拆了。
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent

# 只门禁生产代码（scripts/ 与 scripts/sources/），不含 test_*.py。测试文件的
# 行数是覆盖度的体现，不是复杂度的体现，两者不该用同一把尺。
# 当前最大值为 sources/sec_edgar.py 1297 行，故取 1400。
MAX_LINES = 1400


def _production_modules() -> list[Path]:
    mods = [p for p in _SCRIPTS.glob("*.py") if not p.name.startswith("test_")]
    mods += [p for p in (_SCRIPTS / "sources").glob("*.py")
             if not p.name.startswith("test_")]
    return mods


def test_no_production_module_exceeds_size_gate() -> None:
    """任何生产模块超过 MAX_LINES 即失败，并报出是哪一个、超了多少。"""
    oversized = []
    for path in _production_modules():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_LINES:
            oversized.append(f"{path.name} {lines} 行（超 {lines - MAX_LINES}）")
    assert not oversized, (
        f"生产模块超过 {MAX_LINES} 行上限：{'、'.join(oversized)}。"
        f"拆模块，或确认这个阈值确实需要上调（当前最大值见下方断言）"
    )


def test_gate_has_headroom_above_current_maximum() -> None:
    """门禁必须高于当前最大值，否则一上线就把现有代码判红。

    这条是防「阈值定得比现状还低」：那会让门禁从「防退化」变成「永久失败」，
    很快就会被后人整条删掉。
    """
    current_max = max(
        len(p.read_text(encoding="utf-8").splitlines())
        for p in _production_modules()
    )
    assert MAX_LINES >= current_max, (
        f"门禁 {MAX_LINES} 低于当前最大值 {current_max}，"
        f"这条断言会恒失败，先抬阈值或先拆模块"
    )
    # 同时不能松到没有约束：阈值应接近当前最大值，而不是它的数倍。
    # 1.5 与 docstring 里的「约 8%」是两把不同的尺：前者管「别松到离谱」，
    # 后者说明当前 1400 是怎么定出来的，不要求数值相等。
    assert MAX_LINES <= current_max * 1.5, (
        f"门禁 {MAX_LINES} 相对当前最大值 {current_max} 过于宽松，失去约束意义"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
