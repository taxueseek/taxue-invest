#!/usr/bin/env python3
"""静态门禁：生产代码必须能被 Python 3.9 解析，且不用 3.10+ 的 API。

为什么需要：`mx-data` 按 invest-stock 文档用**系统 `python3`** 启动（本机 3.9.6），
并在进程内 import invest-cli 的 route 层——3.9 是在用的运行时，不是假设的下限。
而 SKILL.md 曾长期写「Python 3.10+」，于是 2026-10-17 的未提交改动写下
`zip(jobs, ex.map(one, jobs), strict=True)`（PEP 618，3.10 起），在 3.9 上直接
`TypeError: zip() takes no keyword arguments`，6 条测试红了两天没人跑。

语法层用 `ast.parse(..., feature_version=(3, 9))`：它按 3.9 的语法树校验，
`match`、括号内多上下文管理器等 3.10+ 语法会被当场拒绝。API 层语法检查看不见，
所以额外盯住真正咬过人的那一个：`zip(strict=)`。

不做的事：不尝试枚举「所有 3.10+ API」。那需要一份会过期的名单，误报比漏报
更伤门禁的可信度；运行期的真凭据是全量 pytest 在 3.9 下过一遍（见 SKILL.md）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent

# 3.9 是 mx-data 实际使用的系统解释器版本；下限写死在这里，别跟着本机 venv 漂。
_TARGET = (3, 9)


def _production_modules() -> list[Path]:
    mods = [p for p in _SCRIPTS.glob("*.py") if not p.name.startswith("test_")]
    mods += [p for p in (_SCRIPTS / "sources").glob("*.py") if not p.name.startswith("test_")]
    return sorted(mods)


def test_production_code_parses_with_py39_grammar() -> None:
    """每个生产模块都要能被 3.9 语法树解析。"""
    broken: list[str] = []
    for path in _production_modules():
        src = path.read_text(encoding="utf-8")
        try:
            ast.parse(src, filename=str(path), feature_version=_TARGET)
        except SyntaxError as exc:
            broken.append(f"{path.name}:{exc.lineno} {exc.msg}")
    assert not broken, (
        f"以下文件用了 Python {_TARGET[0]}.{_TARGET[1]} 不支持的语法"
        f"（mx-data 会用系统 3.9 启动并 import 这些模块）：\n  " + "\n  ".join(broken)
    )


def test_no_zip_strict_kwarg() -> None:
    """禁止 `zip(..., strict=...)`：3.10 起才有，3.9 抛 TypeError。

    要表达「长度必须一致」时，显式比较长度（见 `sources/wind._paired`）——
    等价、可读，且 3.9 起全版本可用。
    """
    offenders: list[str] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else "")
            if name != "zip":
                continue
            if any(kw.arg == "strict" for kw in node.keywords):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "以下位置用了 `zip(..., strict=...)`（PEP 618，3.10+），"
        "在 3.9 上会 TypeError，改为显式比较长度：\n  " + "\n  ".join(offenders)
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
