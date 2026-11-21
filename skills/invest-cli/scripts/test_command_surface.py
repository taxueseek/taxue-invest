#!/usr/bin/env python3
"""命令面的唯一真源：command_registry.py（纯离线）。

历史：`invest_cli.py` 曾把命令名写两遍（add_parser 一遍、dispatch 字典一遍），
两者并行手工维护，靠 AST 双射测试兜底；文档又手写「21 个子命令」，实际早已
24 个。第十轮把命令名收进 `command_registry.py`，parser 与 dispatch 都从它
派生，本测试只钉住「注册表能构造出完整的 parser 与 dispatch」。
"""
from __future__ import annotations

from pathlib import Path
import sys

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from command_registry import command_ids  # noqa: E402


def test_parser_and_registry_are_bijective() -> None:
    import invest_cli

    parser = invest_cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    expected = set(command_ids())
    assert expected, "注册表为空"
    assert set(sub.choices) == expected, (
        f"parser 与注册表不一致：只在 parser = {sorted(set(sub.choices) - expected)}；"
        f"只在注册表 = {sorted(expected - set(sub.choices))}"
    )


def test_dispatch_symbols_exist() -> None:
    import invest_cli

    missing = [
        name for name in command_ids()
        if not callable(getattr(invest_cli, f"cmd_{name.replace('-', '_')}", None))
    ]
    assert not missing, f"dispatch 缺实现：{missing}"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
