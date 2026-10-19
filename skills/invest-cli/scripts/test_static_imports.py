#!/usr/bin/env python3
"""静态门禁：`urllib.sub` 被用到，就必须在可见作用域里 import 过它。

为什么需要：同一个错误出现了两次，都是**静默降级**，测试全绿。

- 2026-10-07 `registry._probe_http`：只 `import urllib.error` 却用
  `urllib.request.Request`，`Request()` 必抛 `AttributeError`，探测从未发出
  请求就把 yfinance 标成「端点不可达」——美股主路静默跳过半年。
- 2026-10-15 `hithink._default_http_get`：为省 18ms 冷启动删掉模块级
  `import urllib.request/error`，只在 `_request` 里补了 `urllib.parse`，
  首次真实取数即 `NameError`——同花顺是 A 股/基金链首，整条主路静默降级，
  stock 冷取从 0.6s 变成 5.9s，两天无人发现。

两次的共同点：`import urllib.parse` **不**绑定 `urllib.request`/`urllib.error`
这两个属性；子模块必须逐个导入。`ruff` 的 F821 抓不到——`urllib` 这个名字
是绑定的，缺的是它的属性，静态检查器无从判断哪个属性存在。所以只能靠
「用到哪些子模块」与「导入了哪些子模块」逐作用域对账。

判据（可判定，不猜）：
  1. 收集 `urllib.X.Y` 形态的**属性链使用**（根名字必须是 `urllib`）；
  2. 收集可满足它的导入：`import urllib.X`、`from urllib import X`；
  3. 可见作用域 = 本函数 ∪ 所有外层（含模块级）——函数内延迟导入是本仓
     刻意采用的省冷启动手段，不许它因此被误报；
  4. 任一使用找不到导入即失败，并报出文件、行号、函数名与子模块。

别名导入（`import urllib.request as ur`）不参与判定：它就一个名字，用错会
在 import 期报错，不属于「静默」这一类。
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# urllib 之外，「包 → 子模块」型依赖里会被这样误用的只有它：其余第三方库
# 都在模块级一次导入，没有这个坑。刻意不做通用规则，避免误报把门禁逼成噪音。
_ROOT = "urllib"


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    scope: str
    dotted: str

    def __str__(self) -> str:
        return f"{self.path.name}:{self.line} {self.scope}() 用到 {self.dotted}，但未导入"


def _imported_submodules(node: ast.AST) -> set[str]:
    """一条 import 语句能提供的 `urllib.X` 全名集合。

    `import urllib.request`       → {"urllib.request"}
    `import urllib.parse, ...`    → 逐 alias 处理
    `from urllib import request`  → {"urllib.request"}（运行期同样会给包挂上属性）
    `import urllib`               → {"urllib"}（只有根名字，不提供任何子模块）
    """
    out: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.asname:  # 别名不在本判据的覆盖范围（见模块说明）
                continue
            if alias.name == _ROOT or alias.name.startswith(_ROOT + "."):
                out.add(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level or node.module != _ROOT:
            return out
        for alias in node.names:
            if not alias.asname:
                out.add(f"{_ROOT}.{alias.name}")
    return out


def _used_submodules(body: list[ast.AST]) -> list[tuple[int, str]]:
    """本作用域（不含嵌套函数体）里出现的 `urllib.X` 使用。"""
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # 嵌套作用域自己结算：它们的导入与使用在自己的帧里对账。
                continue
            if isinstance(child, ast.Attribute):
                chain = _root_chain(child)
                if chain and chain.startswith(_ROOT + "."):
                    # 只要求「包.子模块」这一层：urllib.request.Request 需要
                    # urllib.request 被导入，不需要导入 Request。
                    parts = chain.split(".")
                    if len(parts) >= 2:
                        found.append((child.lineno, ".".join(parts[:2])))
            visit(child, depth + 1)

    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, ast.Attribute):
            chain = _root_chain(stmt)
            if chain and chain.startswith(_ROOT + "."):
                parts = chain.split(".")
                if len(parts) >= 2:
                    found.append((stmt.lineno, ".".join(parts[:2])))
        visit(stmt, 0)
    # 外层属性与它的 `.value` 内层属性会链出同一个 urllib.X（同一行报两次）：
    # 去重保序，报错文本里不出现重复行。
    seen: set[tuple[int, str]] = set()
    uniq: list[tuple[int, str]] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq


def _root_chain(node: ast.Attribute) -> str:
    """把 `urllib.request.Request` 还原成点号串；根不是 Name 则返回空串。"""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return ""
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _scope_violations(
    path: Path,
    name: str,
    body: list[ast.AST],
    inherited: set[str],
) -> tuple[list[Violation], set[str]]:
    """结算一个作用域，返回（违规列表，本作用域可见的导入集合）。"""
    own: set[str] = set()
    for stmt in body:
        # 只收集**直接**语句上的 import：函数体内的 import 属于该函数自己的帧。
        own |= _imported_submodules(stmt)
    visible = inherited | own
    bad = [
        Violation(path, line, name, dotted)
        for line, dotted in _used_submodules(body)
        if dotted not in visible
    ]
    return bad, visible


def scan_source(path: Path) -> list[Violation]:
    """解析单个文件，返回全部违规。语法错误由 compileall 那道门负责。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad, module_visible = _scope_violations(path, "<module>", tree.body, set())

    def walk(body: list[ast.AST], inherited: set[str]) -> None:
        for stmt in body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            scope_bad, scope_visible = _scope_violations(path, stmt.name, stmt.body, inherited)
            bad.extend(scope_bad)
            walk(stmt.body, scope_visible)

    walk(tree.body, module_visible)
    return bad


def _production_modules() -> list[Path]:
    mods = [p for p in _SCRIPTS.glob("*.py") if not p.name.startswith("test_")]
    mods += [p for p in (_SCRIPTS / "sources").glob("*.py") if not p.name.startswith("test_")]
    return sorted(mods)


def test_no_urllib_submodule_used_without_import() -> None:
    """全部生产模块逐作用域对账：用到 `urllib.X` 就必须导入 `urllib.X`。"""
    violations = [v for p in _production_modules() for v in scan_source(p)]
    assert not violations, (
        "以下位置用了未导入的 urllib 子模块（运行期会抛 NameError/AttributeError，"
        "而适配器会把它当成「源不可用」吞掉，形成静默降级）：\n"
        + "\n".join("  " + str(v) for v in violations)
    )


def test_checker_catches_the_two_historical_bugs(tmp_path: Path) -> None:
    """门禁自检：两条历史事故的代码形状必须被判红，否则这道门就是空转。"""
    bug = tmp_path / "mod.py"
    bug.write_text(
        "def probe():\n"                # 模块级一个 urllib 导入都没有（10-07 形状）
        "    return urllib.request.Request('https://x')\n"
        "\n"
        "def lazy():\n"
        "    import urllib.parse\n"       # 只补 parse
        "    return urllib.error.URLError('x')\n",   # 却用 error（10-15 形状）
        encoding="utf-8",
    )
    bad = {(v.scope, v.dotted) for v in scan_source(bug)}
    assert ("probe", "urllib.request") in bad
    assert ("lazy", "urllib.error") in bad


def test_checker_accepts_legit_patterns(tmp_path: Path) -> None:
    """合法写法不能被误报：模块级导入、函数内延迟导入、from-import、别名。"""
    ok = tmp_path / "mod.py"
    ok.write_text(
        "import urllib.error\n"
        "import urllib.request\n"
        "import urllib.request as _req\n"
        "from urllib import parse\n"
        "\n"
        "def module_level():\n"
        "    return urllib.request.Request('https://x'), urllib.error.URLError, urllib.parse\n"
        "\n"
        "def lazy_inside():\n"
        "    import urllib.request\n"
        "    return urllib.request.Request('https://x')\n"
        "\n"
        "def aliased():\n"
        "    return _req.Request('https://x')\n"
        "\n"
        "def nested():\n"
        "    def inner():\n"
        "        import urllib.error\n"
        "        return urllib.error.URLError('x')\n"
        "    return inner\n",
        encoding="utf-8",
    )
    assert scan_source(ok) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
