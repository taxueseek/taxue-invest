#!/usr/bin/env python3
"""模块体积门禁，纯静态，不联网。

为什么需要：argo 公开版把「模块体积」当硬门禁，invest-cli 一直没有。
sec_edgar.py 已到 1297 行、etf_analytics.py 1202 行，再长下去单文件的可读性
与单测覆盖都会滑坡，而这类退化没有任何现有检查会报——测试全绿、行为不变，
只是越来越难改。

这里只设上限，不规定拆法：超过即失败，拆不拆、怎么拆由改动者决定。
1400 是**固定红线**，不随「当前最大值」上漂（第九轮 2026-11-08 定稿：旧版按
「当前最大值上方约 8%」取阈值并配 1.5 倍松紧带断言，本质是把现状合法化——
1400 上线时就是照着当时的 1297 定的，三个破 1k 的存量模块因此被追溯放行）。
要抬阈值必须显式修改本文件并写明理由，让 code review 看得见；正常路径永远
是拆模块。
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent

# 只门禁生产代码（scripts/ 与 scripts/sources/），不含 test_*.py。测试文件的
# 行数是覆盖度的体现，不是复杂度的体现，两者不该用同一把尺。
MAX_LINES = 1400  # 固定红线：抬阈值必须显式 diff 并写明理由，不许随现状上漂


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
        f"拆模块；确实需要抬阈值时显式修改本文件 MAX_LINES 并写明理由"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
