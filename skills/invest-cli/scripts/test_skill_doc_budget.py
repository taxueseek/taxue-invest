#!/usr/bin/env python3
"""门禁：两份常驻 SKILL.md 的体积上限（防「删了又长回来」）。

为什么需要：`invest/SKILL.md` 与 `invest-cli/SKILL.md` 是每次会话都会进上下文的
常驻层，它们的每一行都在每一轮对话里重复计费。2026-10-19 第六轮实测这两份里
约 1.6K token 是纯重复（同一张表的另一个方向、示例表重复路由表、架构说明重复
图谱）——删掉后路由行为逐条对照不变。但删完没有任何机制阻止它再长回来：
新增一段说明、补一张表，测试全绿、行为不变，只是上下文又胖了。

判据是**字符数**而不是 token：字符数确定、无依赖、跨机器一致；中文 1 字≈1 token，
英文 3-4 字符≈1 token，作为「体积哨兵」足够，不追求精确计费。
阈值取当前值上方约 10%：正常补充不误伤，重新长出千字级重复段落时会失败。

阈值上调前先问一句：这段是路由必需，还是又一次把别处的表抄了一遍。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
_SKILLS = _SCRIPTS.parent.parent  # .../skills
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# 只门禁**常驻层的两份入口 SKILL.md**。子技能的 references/ 是按需加载的，
# 体积大不构成每轮成本，不在本门禁范围。
BUDGETS = {
    "invest/SKILL.md": 5100,        # 2026-10-19 瘦身实测 4622 字符
    "invest-cli/SKILL.md": 16200,   # 2026-10-19 瘦身实测 14753 字符
}


def _size(rel: str) -> int:
    p = _SKILLS / rel
    return len(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel,budget", sorted(BUDGETS.items()))
def test_always_loaded_skill_stays_within_budget(rel: str, budget: int) -> None:
    p = _SKILLS / rel
    if not p.is_file():
        pytest.skip(f"{rel} 不在当前安装里")
    size = _size(rel)
    assert size <= budget, (
        f"{rel} 已 {size} 字符，超过常驻层预算 {budget}（每轮上下文都付这份钱）。"
        f"先把重复段落删掉（同一张表的另一方向、示例重复路由表、架构说明重复图谱），"
        f"确实需要扩写再调 BUDGETS 并说明理由"
    )


def test_budgets_have_headroom_above_current_size() -> None:
    """预算必须高于现状：定得比现状还低会让门禁恒失败，很快被整条删掉。"""
    for rel, budget in BUDGETS.items():
        p = _SKILLS / rel
        if not p.is_file():
            continue
        size = _size(rel)
        assert size <= budget <= int(size * 1.35), (
            f"{rel}：现状 {size} 字符、预算 {budget}，两者关系不合理"
            f"（预算应略高于现状，而不是高出一倍或低于现状）"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
