#!/usr/bin/env python3
"""第八轮守卫：读路径零写副作用 / 探测只跑一次 / 运行时判据单一真源。

三条都对应「改动后不靠人工体检也能发现回归」：
1. 读缓存不该顺手建目录（曾让纯缓存命中的 fund 热路径付 7 次 mkdir）；
2. doctor 的 check_sources 曾因 available_ids() 内部又探测而付两次并行探测；
3. venv 解释器软链断掉时，wrapper / doctor / mx-data / CLI 入口必须同判，
   且故障态必须可见（旧版三份判据各自静默回退，能力降级数天无人发现）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _common  # noqa: E402
import cmd_doctor  # noqa: E402
import runtime_guard  # noqa: E402
from sources import registry  # noqa: E402


def _broken_venv(skill_root: Path) -> Path:
    """造一个「装了 venv、但基础解释器软链已断」的 fixture。"""
    bindir = skill_root / ".venv" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    py = bindir / "python"
    py.symlink_to(bindir / "python3.99-missing")
    return py


# ── 读路径零写副作用 ──

def test_read_paths_never_create_cache_dirs(monkeypatch, tmp_path) -> None:
    root = tmp_path / "cache"
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(root))
    assert _common.cache_get("ns", "k", 60) is None
    assert _common.cache_root() == root
    assert registry._probe_cache_path(
        registry._probe_cache_key(("adapter", "x")), create=False) is not None
    assert not root.exists(), "一次缓存未命中不该产生建目录的写副作用"
    _common.cache_set("ns", "k", {"v": 1})
    assert _common.cache_get("ns", "k", 60) == {"v": 1}, "写路径仍要能自建目录"
    assert root.is_dir()


def test_read_path_makes_zero_mkdir_calls(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    original = Path.mkdir
    monkeypatch.setattr(
        Path, "mkdir",
        lambda self, *a, **k: calls.append(str(self)) or original(self, *a, **k),
    )
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path / "cache"))
    assert _common.cache_get("ns", "k", 60) is None
    registry._probe_cache_path(registry._probe_cache_key(("http", "u")), create=False)
    assert calls == [], f"读路径触发了 mkdir：{calls}"


# ── doctor 只探测一次 ──

def test_check_sources_detects_once(monkeypatch) -> None:
    calls: list[int] = []
    real = registry.detect_all
    monkeypatch.setattr(registry, "detect_all",
                        lambda: calls.append(1) or real())
    cmd_doctor.check_sources()
    assert len(calls) == 1, "check_sources 不得把 0.3s 级并行探测跑两遍"


# ── 运行时判据：单一真源 + 故障可见 ──

def test_broken_venv_is_detected_and_warned(tmp_path, capsys) -> None:
    py = _broken_venv(tmp_path)
    assert runtime_guard.executable(py) is False
    assert runtime_guard.health(tmp_path)[0] == "broken"
    assert runtime_guard.degraded_reason(tmp_path)
    runtime_guard.warn_if_degraded(tmp_path)
    assert "venv" in capsys.readouterr().err
    capsys.readouterr()


def test_missing_venv_is_supported_not_warned(tmp_path, capsys) -> None:
    """公开仓用户没有 .venv 是支持形态，不能误报、不能多打印一个字节。"""
    assert runtime_guard.health(tmp_path)[0] == "missing"
    assert runtime_guard.degraded_reason(tmp_path) == ""
    runtime_guard.warn_if_degraded(tmp_path)
    assert capsys.readouterr().err == ""


def test_probe_modules_reports_missing_dependency() -> None:
    """probe 用 find_spec 判存在性，不执行目标模块（不会拖进 pandas/numpy）。"""
    ok, detail = runtime_guard.probe_modules(
        Path(sys.executable), ("json", "no_such_module_xyz"))
    assert ok is False and "no_such_module_xyz" in detail
    ok, _ = runtime_guard.probe_modules(Path(sys.executable), ("json",))
    assert ok is True


def test_doctor_fails_on_broken_venv(tmp_path) -> None:
    _broken_venv(tmp_path)
    status, detail = cmd_doctor.check_interpreters(
        system_py=sys.executable, skill_root=tmp_path)
    assert status == "fail", "venv 断链是能力故障，不许再判 pass"
    assert "venv" in detail


def test_doctor_keeps_public_repo_shape_without_venv(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cmd_doctor, "_SYSTEM_RUNTIMES", ("json",))
    status, detail = cmd_doctor.check_interpreters(
        system_py=sys.executable, skill_root=tmp_path)
    assert status == "pass" and "兜底齐备" in detail


def test_shell_minus_x_matches_shared_criterion(tmp_path) -> None:
    """wrapper 的 `[ -x ]` 与 runtime_guard.executable 必须同判（跨语言对账）。"""
    good = tmp_path / "good-python"
    good.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    good.chmod(0o755)
    broken = _broken_venv(tmp_path)
    for path in (good, broken):
        out = subprocess.run(
            ["bash", "-c", '[ -x "$1" ] && echo yes || echo no', "_", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        assert (out.stdout.strip() == "yes") == runtime_guard.executable(path), path


def test_wrapper_falls_back_and_warns_end_to_end(tmp_path) -> None:
    """端到端：wrapper 遇断链 venv 回退系统 python3，CLI 入口打一行告警，
    而 stdout 仍保持原样（原生输出格式没有被自检污染）。"""
    wrapper = Path.home() / ".local" / "bin" / "invest-cli"
    if not wrapper.is_file():
        pytest.skip("本机无 wrapper（公开仓形态）")
    skill = tmp_path / "skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    _broken_venv(skill)
    shutil.copy(_SCRIPTS / "runtime_guard.py", scripts / "runtime_guard.py")
    (scripts / "invest_cli.py").write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
        "from runtime_guard import warn_if_degraded\n"
        "warn_if_degraded(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "print('{\"ok\": true}')\n",
        encoding="utf-8",
    )
    env = {**os.environ, "INVEST_CLI_ROOT": str(skill)}
    out = subprocess.run([str(wrapper), "--json"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == '{"ok": true}'
    assert "venv" in out.stderr, "回退必须可见，不能静默降级"
