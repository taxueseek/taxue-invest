#!/usr/bin/env python3
"""invest-cli 运行时健康判据：唯一真源。

为什么存在（2026-11-04）：第七轮把 venv 从「美股专用」泛化成全场景运行时，
但「venv 可用」的判据散在三处，且没有一处校验解释器**真的能执行**：

  · wrapper      `[ -x "$SKILL_DIR/.venv/bin/python" ]`
  · mx-data      `venv_py.is_file()`
  · doctor       `venv_py.is_file()` + sys.prefix 比较

Homebrew 升级到 3.15 后 `/opt/homebrew/opt/python@3.14` 被卸载，venv 的基础
解释器软链断掉：三处各自静默回退，`fund-class` 缺 cryptography（rc=1）、
`us` 丢 yfinance 全量快照，而 doctor 仍报 PASS。这是「可用性判据」与
「实际执行前置条件」两份实现漂移的第 6 次复发（前 5 次见 check.py 注释）。

分两层，因为热路径付不起子进程：

  · cheap 层（executable / degraded_reason）：纯 stat + access，供 CLI 入口
    与 mx-data 使用，健康态零额外进程；
  · probe 层（probe_modules / health）：真起一次解释器查关键依赖，仅 doctor
    使用（doctor 本来就有子进程预算）。用 `find_spec` 而非真 import：它不执行
    目标模块，不会重演旧版「import yfinance 当探测」拖进 pandas/numpy 的
    336ms CPU / +54MB 回归（test_ensure_runtime_probe_does_not_import_yfinance）。

判据语义与 wrapper 的 shell `-x` 对齐（bash `-x` ≡ access(X_OK)），由
test_runtime_guard.py 的跨语言对账用例钉住，避免再长出第二份实现。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

# pyproject.toml 里决定「能力是否完整」的关键依赖。
# 注意写的是 import 名而非 pip 名（PyYAML → yaml）。
REQUIRED_MODULES = ("yaml", "yfinance", "cryptography")


def venv_python(skill_root: Path) -> Path:
    """venv 解释器的唯一路径定义（与 wrapper 的 VENV_PY 同址）。"""
    return Path(skill_root) / ".venv" / "bin" / "python"


def executable(py: Path) -> bool:
    """解释器可执行：断链软链 / 缺二进制 / 无 x 位一律 False。

    is_file() 已能识别断链软链；access(X_OK) 与 shell 的 `[ -x ]` 同义。
    """
    try:
        return Path(py).is_file() and os.access(str(py), os.X_OK)
    except OSError:
        return False


def degraded_reason(skill_root: Path) -> str:
    """廉价判据：返回人话原因；健康或「压根没装 venv」时返回空串。

    公开仓用户没有 .venv 是支持形态（系统 python3 + subprocess 兜底），
    不能因此报警；只有「装了却坏了」才是故障。
    """
    root = Path(skill_root)
    venv_dir = root / ".venv"
    if not venv_dir.is_dir():
        if not venv_dir.is_symlink():
            return ""
        return f"venv 目录软链失效（{venv_dir}）"
    py = venv_python(root)
    if not executable(py):
        return f"venv 解释器不可执行（{py}）"
    return ""


def warn_if_degraded(skill_root: Path) -> None:
    """入口调用：故障态往 stderr 打一行，健康态一个字节都不输出。"""
    reason = degraded_reason(skill_root)
    if reason:
        print(f"invest-cli: {reason}；已回退系统解释器，"
              "us/fund-class 等能力可能降级，请跑 `invest-cli doctor`",
              file=sys.stderr)


def probe_modules(py: Path, modules: Iterable[str] = REQUIRED_MODULES,
                  timeout: float = 10.0) -> tuple[bool, str]:
    """真起一次解释器查关键依赖是否存在（不执行目标模块）。

    subprocess 惰性导入：CLI 入口只用 cheap 层，模块级拉进 subprocess
    会给每条命令（含 --help）凭空加约 20ms 冷启动。
    """
    import subprocess

    mods = tuple(modules)
    code = ("import importlib.util as u;"
            "print(','.join(m + '=' + str(u.find_spec(m) is not None)"
            f" for m in {list(mods)!r}))")
    try:
        out = subprocess.run([str(py), "-c", code], capture_output=True,
                             text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"无法执行（{type(e).__name__}）"
    if out.returncode != 0:
        return False, "解释器启动失败"
    missing = [p.split("=")[0] for p in out.stdout.strip().split(",")
               if p.endswith("=False")]
    if missing:
        return False, "缺 " + "、".join(missing)
    return True, "关键依赖齐备"


def health(skill_root: Path,
           modules: Iterable[str] = REQUIRED_MODULES) -> tuple[str, str]:
    """完整判据：ok / missing / broken / incomplete + 人话详情。"""
    root = Path(skill_root)
    venv_dir = root / ".venv"
    if not venv_dir.is_dir():
        if venv_dir.is_symlink():
            return "broken", f"venv 目录软链失效（{venv_dir}）"
        return "missing", "未安装 venv（公开仓形态：系统 python3 + subprocess 兜底）"
    py = venv_python(root)
    if not executable(py):
        return "broken", f"venv 解释器不可执行（{py}）"
    ok, detail = probe_modules(py, modules)
    return ("ok", detail) if ok else ("incomplete", detail)
