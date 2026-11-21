#!/usr/bin/env python3
"""一条命令跑完 invest-cli 的硬检查（本地/CI 同一套）。

为什么需要：2026-10-15 的 F821（hithink 的 urllib 未绑定）在 550 条测试
全绿的情况下活了 2 天——测试只覆盖行为，不覆盖「代码里有没有未定义的名称」。
本脚本把四类 Python 检查串起来，任何一类失败都返回非 0：

1. pytest：行为回归（含文档源序一致性 test_doc_source_truth）；
2. ruff --select F821：未定义名称（这次回归的类别）；未安装 ruff 时 SKIP，
   不伪造通过——在 CI 里请 `pip install -r requirements-dev.txt`；
3. ruff --select F401：未用导入（死代码，与 F821 同属「静态可见但测试拦不住」）；
4. compileall：语法/编码级损坏（比 import 更早暴露）；
5. 版本记账：根 SKILL.md 的 version 与 CHANGELOG 顶部条目必须一致——
   「改了版本忘了记 CHANGELOG」从 v2.9 起反复出现（三个数并存过），第九轮
   定稿：记账本身没有门禁，就还是靠自觉，而「靠自觉」已被七轮治理证伪。

另有一项条件检查：DSH 插件的 Node 测试（插件命令面与 CLI dispatch 的一致性门禁）。
有 node 就跑，没有就 SKIP——插件是可选装机面，不该把纯 Python 环境卡死。

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


def _run(label: str, cmd: list[str], cwd: Path | None = None) -> bool:
    where = cwd or ROOT
    print(f"\n== {label}\n$ {' '.join(cmd)}", flush=True)
    ok = subprocess.run(cmd, cwd=where).returncode == 0
    print(("PASS " if ok else "FAIL ") + label, flush=True)
    return ok


def _ruff() -> list[str] | None:
    for cand in (ROOT / ".venv" / "bin" / "ruff", shutil.which("ruff")):
        if cand and Path(cand).is_file():
            return [str(cand)]
    return None


def _version_accounting() -> tuple[bool, str]:
    """版本记账单点：根 SKILL.md、CHANGELOG 顶部条目与 pyproject.toml 必须一致。

    版本号的唯一权威是根 SKILL.md frontmatter（2026-10-25 定稿）；CHANGELOG
    与 pyproject.toml 是它的跟随记录。多处各改一半的失同步不是笔误，是
    「记账无门禁」的结构缺口，本检查把它挂进每次提交。零依赖、毫秒级、纯静态。
    """
    import re

    repo = ROOT.parent.parent  # taxue-invest/
    try:
        m = re.search(r"^version:\s*(\S+)",
                      (repo / "SKILL.md").read_text(encoding="utf-8"), re.M)
        c = re.search(r"^## v(\d+(?:\.\d+)*)",
                      (repo / "skills" / "invest" / "CHANGELOG.md").read_text(encoding="utf-8"),
                      re.M)
        p = re.search(r'^version\s*=\s*"([^"]+)"',
                      (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                      re.M)
    except OSError as e:
        return False, f"记账文件读取失败: {e}"
    if not m or not c or not p:
        return False, "找不到 SKILL.md 的 version、CHANGELOG 顶部条目或 pyproject.toml 的 version"
    if not (m.group(1) == c.group(1) == p.group(1)):
        return False, (
            f"版本记账失同步：SKILL.md version={m.group(1)}，CHANGELOG 顶部={c.group(1)}，"
            f"pyproject.toml={p.group(1)}。改版本必须三处同笔提交"
        )
    return True, f"version={m.group(1)} 与 CHANGELOG / pyproject.toml 一致"


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

    ok_ver, detail = _version_accounting()
    print(f"\n== version accounting\n{detail}")
    results.append(ok_ver)

    # 命令注册表的插件产物是生成物：过期说明有人改了注册表/数据源却没同步，
    # 插件会继续显示旧命令面（2026-11-08 的 21 vs 24 就是这么来的）。
    results.append(_run("registry artifacts", [sys.executable, str(HERE / "sync_registry.py"), "--check"]))

    # 依赖清单是派生件（P5，2026-11-09）：真源在 pyproject.toml，requirements*.txt
    # 由 sync_requirements.py 派生。漂移即红——手工改清单会与 lock 脱节。
    results.append(_run("requirements artifacts",
                        [sys.executable, str(HERE / "sync_requirements.py"), "--check"]))

    # DSH 插件是同一仓库的可选装机面。它的测试里有一条「插件命令面 = CLI dispatch
    # 真源」的门禁——不跑它，插件漏命令的漂移就只能在用户装上之后才发现。
    plugin = ROOT / "packages" / "dsh-plugin"
    node = shutil.which("node")
    if node and plugin.is_dir():
        results.append(_run(
            "dsh-plugin tests",
            [node, "--test", "test/index.test.js", "test/client.test.js"],
            cwd=plugin,
        ))
    else:
        print("\n== dsh-plugin tests\nSKIP：未安装 node 或无插件目录")

    ok = all(results)
    print("\ncheck:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
