#!/usr/bin/env python3
"""doctor 子命令的检查项单测 —— 全部离线，路径参数化。

doctor 本体是「只读体检」，测试关心的是判定边界：缓存多老算陈旧、软链什么
形态算断、DSH 副本怎么算漂移、解释器候选怎么算有兜底。联网探测（sources 的
真实探测）不在单测范围——那由 `invest-cli datasources` 的既有路径覆盖。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cmd_doctor  # noqa: E402


# ── cache ──

def test_cache_reports_counts_and_passes(tmp_path) -> None:
    for ns, n in (("snapshot", 2), ("report", 1)):
        d = tmp_path / ns
        d.mkdir()
        for i in range(n):
            (d / f"f{i}.json").write_text("{}", encoding="utf-8")
    status, detail = cmd_doctor.check_cache(cache_root=tmp_path)
    assert status == "pass"
    assert "3 文件" in detail and "3 呗" not in detail


def test_cache_warns_on_stale(tmp_path) -> None:
    f = tmp_path / "snapshot" / "old.json"
    f.parent.mkdir()
    f.write_text("{}", encoding="utf-8")
    old = time.time() - (cmd_doctor._CACHE_STALE_WARN + 86400)
    os.utime(f, (old, old))
    status, _ = cmd_doctor.check_cache(cache_root=tmp_path)
    assert status == "warn"


def test_cache_missing_dir_is_pass(tmp_path) -> None:
    assert cmd_doctor.check_cache(cache_root=tmp_path / "none")[0] == "pass"


# ── symlinks ──

def test_symlinks_pass_on_intact_registry(tmp_path) -> None:
    src = tmp_path / "src" / "skills"
    src.mkdir(parents=True)
    (src / "invest").mkdir()
    (src / "invest" / "SKILL.md").write_text("x", encoding="utf-8")
    reg = tmp_path / "reg" / "skills"
    reg.mkdir(parents=True)
    (reg / "invest").symlink_to(src / "invest", target_is_directory=True)
    status, detail = cmd_doctor.check_symlinks(skill_root=src, registry_root=reg)
    assert status == "pass" and "1 个" in detail


def test_symlinks_fail_on_broken_or_missing(tmp_path) -> None:
    src = tmp_path / "src" / "skills"
    src.mkdir(parents=True)
    for name in ("invest", "mx-data"):
        (src / name).mkdir()
    reg = tmp_path / "reg" / "skills"
    reg.mkdir(parents=True)
    (reg / "invest").symlink_to(tmp_path / "gone", target_is_directory=True)  # 断链
    # mx-data：不建 → 缺失
    status, detail = cmd_doctor.check_symlinks(skill_root=src, registry_root=reg)
    assert status == "fail"
    assert "invest" in detail and "mx-data" in detail


def test_symlinks_pass_when_registry_is_source(tmp_path) -> None:
    src = tmp_path / "skills"
    src.mkdir()
    status, _ = cmd_doctor.check_symlinks(skill_root=src, registry_root=src)
    assert status == "pass"  # 公开仓形态：真源即安装处


# ── dsh ──

def _mk_plugin(d: Path, marker: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(
        f'{{"marker": "{marker}", "files": ["dsh", "cordis.patch.yml", "README.md"]}}',
        encoding="utf-8")
    (d / "dsh").mkdir(exist_ok=True)
    (d / "dsh" / "index.js").write_text("x", encoding="utf-8")
    (d / "dsh" / "client.js").write_text(marker, encoding="utf-8")
    (d / "cordis.patch.yml").write_text("x", encoding="utf-8")
    (d / "README.md").write_text("x", encoding="utf-8")


def test_dsh_detects_drift(tmp_path) -> None:
    src = tmp_path / "plugin"
    _mk_plugin(src, "new")
    copy = tmp_path / "profiles" / "web" / "node_modules" / "@taxueseek" / "invest-cli-dsh"
    _mk_plugin(copy, "old")
    status, detail = cmd_doctor.check_dsh(profiles_root=tmp_path / "profiles",
                                          plugin_src=src)
    assert status == "warn" and "package.json" in detail


def test_dsh_pass_on_identical_copy(tmp_path) -> None:
    src = tmp_path / "plugin"
    _mk_plugin(src, "same")
    copy = tmp_path / "profiles" / "web" / "node_modules" / "@taxueseek" / "invest-cli-dsh"
    _mk_plugin(copy, "same")
    status, detail = cmd_doctor.check_dsh(profiles_root=tmp_path / "profiles",
                                          plugin_src=src)
    assert status == "pass" and "web" in detail


def test_dsh_skip_without_profiles_root(tmp_path) -> None:
    status, _ = cmd_doctor.check_dsh(profiles_root=tmp_path / "none",
                                     plugin_src=tmp_path)
    assert status == "skip"


def test_dsh_payload_follows_package_files(tmp_path) -> None:
    """装机比对面必须由 package.json `files` 推导，不能退回手工 KEYS 名单。

    doctor 曾只比 3 件而漏掉 50KB 的 dsh/client.js；sync-local.sh 比 5 件，
    两份名单各写各的。这里钉住：files 里的每个文件都进入比对面，且 client.js
    漂移能被判为 warn（旧名单下这条会通过）。
    """
    src = tmp_path / "plugin"
    _mk_plugin(src, "new")
    files = cmd_doctor._plugin_payload_files(src)
    assert "dsh/client.js" in files and "dsh/index.js" in files
    assert "cordis.patch.yml" in files and "README.md" in files
    assert "package.json" in files

    copy = tmp_path / "profiles" / "web" / "node_modules" / "@taxueseek" / "invest-cli-dsh"
    _mk_plugin(copy, "new")
    (copy / "dsh" / "client.js").write_text("OLD_BUNDLE", encoding="utf-8")
    status, detail = cmd_doctor.check_dsh(profiles_root=tmp_path / "profiles",
                                          plugin_src=src)
    assert status == "warn" and "dsh/client.js" in detail


# ── interpreters（探测细节依赖环境，只钉判定分支） ──

def test_interpreters_warn_when_only_candidate_broken() -> None:
    status, detail = cmd_doctor.check_interpreters(system_py="/nonexistent/python3")
    assert status == "warn"
    assert "兜底" in detail


def test_interpreters_pass_with_stubbed_runtimes(monkeypatch) -> None:
    monkeypatch.setattr(cmd_doctor, "_SYSTEM_RUNTIMES", ("json",))  # 标准库必在
    status, detail = cmd_doctor.check_interpreters(system_py=sys.executable)
    assert status == "pass" and "兜底齐备" in detail


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── 跨平台分支（容器实测未做——daemon 未运行，以平台模拟钉住分支） ──

def test_cache_root_linux_branch(monkeypatch, tmp_path) -> None:
    """cache_root 非 darwin 分支走 XDG 惯例 ~/.cache/invest-cli。

    本机是 macOS（走 ~/Library/Caches 分支），Linux 形态靠 monkeypatch
    sys.platform 模拟：路径逻辑全 pathlib、无平台特有调用，分支正确即可。"""
    import _common

    # conftest 的 autouse 夹具设置了 INVEST_CLI_CACHE_DIR（env 优先级最高），
    # 必须先摘掉才能验证平台分支本身。
    monkeypatch.delenv("INVEST_CLI_CACHE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_common.sys, "platform", "linux")
    assert _common.cache_root() == tmp_path / ".cache" / "invest-cli"
    monkeypatch.setattr(_common.sys, "platform", "darwin")
    assert _common.cache_root() == tmp_path / "Library" / "Caches" / "invest-cli"
