#!/usr/bin/env python3
"""一条命令跑完 invest-cli 的硬检查（本地/CI 同一套）。

为什么需要：2026-10-15 的 F821（hithink 的 urllib 未绑定）在 550 条测试
全绿的情况下活了 2 天——测试只覆盖行为，不覆盖「代码里有没有未定义的名称」。
本脚本把四类检查串起来，任何一类失败都返回非 0：

1. pytest：行为回归（含文档源序一致性 test_doc_source_truth）；
2. ruff --select F821：未定义名称（这次回归的类别）；未安装 ruff 时 SKIP，
   不伪造通过——在 CI 里请 `pip install -r requirements-dev.txt`；
3. ruff --select F401：未用导入（死代码，与 F821 同属「静态可见但测试拦不住」）；
4. compileall：语法/编码级损坏（比 import 更早暴露）。

用法：
    ./.venv/bin/python scripts/check.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _run(label: str, cmd: list[str]) -> bool:
    print(f"\n== {label}\n$ {' '.join(cmd)}", flush=True)
    ok = subprocess.run(cmd, cwd=ROOT).returncode == 0
    print(("PASS " if ok else "FAIL ") + label, flush=True)
    return ok


def _ruff() -> list[str] | None:
    for cand in (ROOT / ".venv" / "bin" / "ruff", shutil.which("ruff")):
        if cand and Path(cand).is_file():
            return [str(cand)]
    return None


def main() -> int:
    results = []
    results.append(_run("pytest", [sys.executable, "-m", "pytest", "scripts", "-q"]))

    ruff = _ruff()
    if ruff:
        results.append(_run(
            "ruff F821",
            ruff + ["check", "scripts", "--select", "F821", "--output-format", "concise"],
        ))
        results.append(_run(
            "ruff F401",
            ruff + ["check", "scripts", "--select", "F401", "--output-format", "concise"],
        ))
    else:
        print("\n== ruff F821/F401\nSKIP：未安装 ruff（pip install -r requirements-dev.txt）")

    results.append(_run("compileall", [sys.executable, "-m", "compileall", "-q", "scripts"]))
    ok = all(results)
    print("\ncheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
