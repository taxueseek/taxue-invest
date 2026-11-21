#!/usr/bin/env python3
"""test_dependency_source_gate.py — 依赖真源对账护栏（P5，2026-11-09）。

## 为什么需要这道门

2026-11-09 之前 invest-cli 的依赖声明散在两处且互不相通：
`requirements.txt` 与 `requirements-dev.txt` 各写一份，没有解析结果落盘。
同一件依赖在两份清单里可以各自漂移，而没有任何机制会红。

## 收口后的口径

- **真源**：`pyproject.toml`（运行期 dependencies、optional-dependencies、
  dependency-groups dev）+ `uv.lock`（钉死解析结果）+ `.python-version`
  （钉死解释器版本）。
- **派生清单**：`requirements.txt` / `requirements-dev.txt` 保留为「pip 用户的
  可读清单 + 文档引用」，内容必须与真源一致。
- 本文件锁三件事：
  1. `uv.lock` 存在且其 `requires-python` 与 pyproject 一致；
  2. 两份 requirements 清单里的每个依赖名都能在 pyproject 对应段落里找到
     （防「清单里有、真源里没有」）；
  3. pyproject 的依赖名都在 uv.lock 里出现（防「真源改了、lock 没重算」）。

## 为什么判据是「名字对账」而不是「全文一致」

清单里写版本号（`pytest>=8.0`）而 pyproject 里也写（`pytest>=8.0`），逐字节
比对会被注释与空行噪声淹没。名字对账回答的是真正会出问题的那一问：
「这个依赖在不在真源里」。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # 3.9/3.10 档
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PYTHON_VERSION = ROOT / ".python-version"

MANIFEST_TO_SECTION = {
    "requirements.txt": "dependencies",
    "requirements-dev.txt": "dev",
}

_SPEC_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _canon(name: str) -> str:
    """PEP 503 归一化：下划线与连字符等价，比较时统一成连字符小写。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _section_names(section: str) -> set[str]:
    """取 pyproject 里某段的依赖名集合。

    `dependencies` 在 [project] 下，`dev` 在 [dependency-groups] 下。
    """
    data = _pyproject()
    if section == "dev":
        entries = (data.get("dependency-groups") or {}).get("dev") or []
    elif section == "dependencies":
        entries = (data.get("project", {}) or {}).get("dependencies") or []
    else:
        entries = ((data.get("project", {}) or {}).get("optional-dependencies") or {}).get(section) or []
    names = set()
    for e in entries:
        if not isinstance(e, str):
            continue
        m = _SPEC_RE.match(e)
        if m:
            names.add(_canon(m.group(1)))
    return names


def _manifest_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _SPEC_RE.match(s)
        if m:
            names.add(_canon(m.group(1)))
    return names


def test_pyproject_exists_and_declares_dependencies():
    assert PYPROJECT.is_file(), "缺 pyproject.toml：依赖真源不存在"
    data = _pyproject()
    assert (data.get("project", {}) or {}).get("dependencies"), (
        "pyproject.toml 的 [project].dependencies 为空"
    )


def test_uv_lock_exists_and_matches_requires_python():
    assert UV_LOCK.is_file(), (
        "缺 uv.lock：依赖真源声明在 pyproject.toml，但解析结果没有落盘。生成：uv lock"
    )
    lock = UV_LOCK.read_text(encoding="utf-8")
    m = re.search(r'^requires-python\s*=\s*"([^"]+)"', lock, re.M)
    assert m, "uv.lock 里读不到 requires-python"
    want = _pyproject()["project"]["requires-python"]
    assert m.group(1) == want, (
        f"uv.lock 的 requires-python（{m.group(1)}）与 pyproject 的 {want} 不一致："
        "lock 过期或 pyproject 改了下限没重算。跑 uv lock"
    )


def test_manifest_deps_exist_in_pyproject():
    """清单里的每个依赖必须在 pyproject 对应段落里——否则「装了却不在锁里」。"""
    problems = []
    for rel, section in MANIFEST_TO_SECTION.items():
        path = ROOT / rel
        assert path.is_file(), f"清单不见了：{rel}"
        want = _section_names(section)
        got = _manifest_names(path)
        missing = sorted(got - want)
        if missing:
            problems.append(
                f"{rel} 里的 {missing} 不在 pyproject 的 [{section}] 段："
                "清单是派生件，改依赖请改 pyproject.toml 再重新生成清单"
            )
    assert not problems, "\n".join(problems)


def test_pyproject_deps_are_locked():
    """pyproject 各段里的依赖都必须出现在 uv.lock——否则 lock 过期。"""
    lock = UV_LOCK.read_text(encoding="utf-8")
    locked = {_canon(m) for m in re.findall(r'^name\s*=\s*"([^"]+)"', lock, re.M)}
    problems = []
    for section in ("dependencies", "dev", "xlsx"):
        for name in sorted(_section_names(section)):
            if _canon(name) not in locked:
                problems.append(
                    f"[{section}] 的 {name} 不在 uv.lock 里：lock 未重算。跑 uv lock"
                )
    assert not problems, "\n".join(problems)


def test_python_version_file_pins_one_version():
    """.python-version 是解释器版本的真源：必须只写一个版本。"""
    assert PYTHON_VERSION.is_file(), (
        "缺 .python-version：解释器版本没有真源。写当前 venv 的主.次版本即可。"
    )
    content = PYTHON_VERSION.read_text(encoding="utf-8").strip()
    assert content and "\n" not in content, (
        f".python-version 应只钉一个版本，当前内容：{content!r}"
    )
    assert re.match(r"^\d+\.\d+$", content), (
        f".python-version 内容应是 '主.次'（如 3.15），当前：{content!r}"
    )


@pytest.mark.parametrize("rel", sorted(MANIFEST_TO_SECTION))
def test_manifests_are_marked_derived(rel):
    """两份清单必须在头部声明自己是派生件——否则下一个人会去改清单。"""
    head = (ROOT / rel).read_text(encoding="utf-8")[:600]
    assert "派生清单" in head and "pyproject.toml" in head, (
        f"{rel} 头部未声明「派生清单」与真源位置"
    )


def test_sync_requirements_script_matches_manifests():
    """验证 sync_requirements.py 能够一键派生且与当前清单完全一致。"""
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import sync_requirements
    assert sync_requirements.sync(check_only=True) is True, (
        "requirements 清单与 pyproject.toml 派生结果不一致，请运行: "
        "python3 scripts/sync_requirements.py"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
