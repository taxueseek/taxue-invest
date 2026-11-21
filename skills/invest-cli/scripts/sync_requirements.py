#!/usr/bin/env python3
"""sync_requirements.py — 依赖派生清单生成与校验（唯一真源：pyproject.toml）

2026-11-09 P5 收口（对齐 argo v2.13.0 的 sync_requirements.py）：
依赖变更只改一处真源（pyproject.toml），派生清单自动生成，消灭手工同步。

派生关系：
  pyproject.toml（唯一真源）
    ├── requirements.txt        由 [project].dependencies 派生（运行期依赖）
    └── requirements-dev.txt   由 [dependency-groups].dev 派生（开发/测试依赖）

用法：
  python3 scripts/sync_requirements.py          # 重新生成两份派生清单
  python3 scripts/sync_requirements.py --check  # 校验派生清单是否与真源一致（不写盘）

退出码：0=一致/生成成功，1=校验不一致（--check 模式）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQ_TXT = ROOT / "requirements.txt"
DEV_TXT = ROOT / "requirements-dev.txt"

REQ_HEADER = """# invest-cli 运行期依赖（pip 用户的可读清单）
#
# ⚠️ 本文件是**派生清单**，不是依赖真源。真源在 pyproject.toml 的
#    [project].dependencies；内容与它的对应关系由
#    scripts/test_dependency_source_gate.py 机械对账，漂移即红。
#    改依赖请改 pyproject.toml，再跑：
#        python3 scripts/sync_requirements.py
#
# 本清单给「不用 uv 的 pip 用户」直接 `pip install -r requirements.txt`；
# 本机 venv（skill 自带 .venv 软链）与 CI 走 uv，见 .python-version。
"""

DEV_HEADER = """# invest-cli 开发与测试依赖（运行期不强制，只在测试/门禁里用）
#
# ⚠️ 本文件是**派生清单**，不是依赖真源。真源在 pyproject.toml 的
#    [dependency-groups].dev；内容与它的对应关系由
#    scripts/test_dependency_source_gate.py 机械对账，漂移即红。
#    改依赖请改 pyproject.toml，再跑：
#        python3 scripts/sync_requirements.py
#
# pytest 是 check.py 四门的硬前置；ruff 供 F821/F401 静态门。
"""


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _clean_entry(spec: str) -> str | None:
    """提取适合 requirements.txt 纯净书写的 spec（去掉环境标记与注释）。"""
    s = spec.strip()
    if not s or s.startswith("#"):
        return None
    s = re.sub(r";\s*python_version.*$", "", s).strip()
    return s or None


def generate_req_txt(data: dict) -> str:
    deps = (data.get("project", {}) or {}).get("dependencies") or []
    lines = [REQ_HEADER.rstrip(), ""]
    for raw in deps:
        cleaned = _clean_entry(raw)
        if cleaned:
            lines.append(cleaned)
    lines.append("")
    return "\n".join(lines)


def generate_dev_txt(data: dict) -> str:
    dev = (data.get("dependency-groups") or {}).get("dev") or []
    lines = [DEV_HEADER.rstrip(), ""]
    for raw in dev:
        cleaned = _clean_entry(raw)
        if cleaned:
            lines.append(cleaned)
    lines.append("")
    return "\n".join(lines)


def sync(check_only: bool = False) -> bool:
    data = _load_pyproject()
    req_content = generate_req_txt(data)
    dev_content = generate_dev_txt(data)

    current_req = REQ_TXT.read_text(encoding="utf-8") if REQ_TXT.is_file() else ""
    current_dev = DEV_TXT.read_text(encoding="utf-8") if DEV_TXT.is_file() else ""

    req_match = current_req.strip() == req_content.strip()
    dev_match = current_dev.strip() == dev_content.strip()

    if check_only:
        if not req_match:
            print(
                "requirements.txt 与 pyproject.toml 存在漂移，请运行: "
                "python3 scripts/sync_requirements.py",
                file=sys.stderr,
            )
        if not dev_match:
            print(
                "requirements-dev.txt 与 pyproject.toml 存在漂移，请运行: "
                "python3 scripts/sync_requirements.py",
                file=sys.stderr,
            )
        return req_match and dev_match

    REQ_TXT.write_text(req_content, encoding="utf-8")
    DEV_TXT.write_text(dev_content, encoding="utf-8")
    print(f"✔ 已由 pyproject.toml 自动派生更新: {REQ_TXT.name}, {DEV_TXT.name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="依赖派生清单同步与校验工具")
    parser.add_argument("--check", action="store_true",
                        help="校验派生清单是否与真源一致")
    args = parser.parse_args()
    return 0 if sync(check_only=args.check) else 1


if __name__ == "__main__":
    sys.exit(main())
