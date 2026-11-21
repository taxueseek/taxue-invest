#!/usr/bin/env python3
"""mx-data 美股路由：ticker 判定 / --type us / code 参与 / venv 自愈（不联网）。

背景：`--type stock --code AAPL` 曾被判成 `stock_a`，命令走 `invest-cli stock AAPL`
（东财 A 股链），输出被标成「A股基本面」，美股四维评分要的 FCF/负债全缺。
另有一个更隐蔽的坑：`venv/bin/python` 是指向基础解释器的软链，用
`sys.executable.resolve() == venv_py.resolve()` 判「是否已在 venv」会恒真，
re-exec 永不发生——必须用 `sys.prefix`。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_IC_SCRIPTS = Path(__file__).resolve().parent
if str(_IC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_IC_SCRIPTS))

# mx-data 与 invest-cli 同根；用相对路径推导，不写死 ~/.agents。
MX_SCRIPTS = _IC_SCRIPTS.parent.parent / "mx-data" / "scripts"
if str(MX_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MX_SCRIPTS))

import get_data  # noqa: E402
from query_router import (  # noqa: E402
    SCENARIO_COMMANDS,
    detect_scenario,
    looks_like_us_ticker,
    scenario_argv,
    scenario_route_kind,
)


@pytest.fixture(autouse=True)
def _no_reexec(monkeypatch):
    """本文件多数用例直接调 get_data()，而非 venv 解释器（系统 3.9）下会触发
    真 os.execv 把 pytest 进程整个换掉——实测表现为输出停在半路、无 summary。
    默认设防环标志；需要验证 re-exec 语义的 _ensure_runtime 单测自己 delenv。"""
    monkeypatch.setenv("MX_DATA_NO_REEXEC", "1")


@pytest.mark.parametrize("value,expected", [
    ("AAPL", True), ("BRK.B", True), ("BRK-B", True),
    ("600519", False), ("00700", False), ("茅台", False), ("", False),
])
def test_looks_like_us_ticker(value: str, expected: bool) -> None:
    assert looks_like_us_ticker(value) is expected


@pytest.mark.parametrize("query,type_,code,expected", [
    ("", "us", "AAPL", "stock_us"),
    ("", "stock", "AAPL", "stock_us"),
    ("", "stock", "600519", "stock_a"),
    ("", "stock", "00700", "stock_a"),  # 港股由 _looks_like_hk 在 fetch 层收窄
    ("AAPL", "", "", "stock_us"),
    ("茅台 ROE", "", "", "stock_a"),
    ("", "fund", "005827", "fund"),
])
def test_detect_scenario(query: str, type_: str, code: str, expected: str) -> None:
    assert detect_scenario(query, type_, code=code) == expected


def test_get_data_routes_us_without_explicit_type(monkeypatch) -> None:
    seen = {}

    def fake_fetch(scenario, code):
        seen.update(scenario=scenario, code=code)
        return {"status": "ok", "snapshot": {"symbol": code}, "source": "yfinance"}

    monkeypatch.setattr(get_data, "_fetch_in_process", fake_fetch)
    monkeypatch.setattr(get_data, "_ensure_scripts_on_path", lambda: True)
    out = get_data.get_data(code="AAPL")
    assert out["scenario"] == "stock_us"
    assert out["command"] == "invest-cli us AAPL --json"
    assert out["source"] == "yfinance"
    assert seen == {"scenario": "stock_us", "code": "AAPL"}


def test_get_data_keeps_a_share_on_stock_path(monkeypatch) -> None:
    seen = {}

    def fake_fetch(scenario, code):
        seen.update(scenario=scenario, code=code)
        return {"status": "ok", "snapshot": {"code": code}, "source": "hithink"}

    monkeypatch.setattr(get_data, "_fetch_in_process", fake_fetch)
    monkeypatch.setattr(get_data, "_ensure_scripts_on_path", lambda: True)
    out = get_data.get_data(code="600519")
    assert out["scenario"] == "stock_a"
    assert out["command"] == "invest-cli stock 600519 --json"
    assert seen == {"scenario": "stock_a", "code": "600519"}


def test_scenario_cmd_is_argv_list_not_string() -> None:
    """_scenario_cmd 必须返回 argv 列表。

    旧实现返回字符串再由 _fetch_subprocess 做 cmd.split()：查询词一含空格
    就被拆成多个位置参数（实测 `--type news --query "茅台 股价"` → argparse
    rc=2 把整段 usage 打给用户）。这里锁住「构造处就定界」这一形状。
    """
    assert get_data._scenario_cmd("news", "", "茅台 股价") == ["info", "茅台 股价"]
    assert get_data._scenario_cmd("stock_a", "600519", "") == ["stock", "600519", "--json"]
    assert get_data._scenario_cmd("stock_us", "AAPL", "") == ["us", "AAPL", "--json"]
    assert get_data._scenario_cmd("bond", "240001", "") == ["intent", "deep", "bond", "240001"]


def test_scenario_table_is_single_source() -> None:
    """场景状态机单源：argv 与 route_kind 都从 SCENARIO_COMMANDS 派生。

    历史缺陷：同一场景的状态散在三处（SCENARIO_COMMANDS 文档表、
    _scenario_cmd 的 argv 分支、_FETCHERS 取数映射），加场景要改三处，
    漏一处就是「文档说走 A、实际走 B」。本用例钉住三份已合一。
    """
    for key, conf in SCENARIO_COMMANDS.items():
        # macro 是无参场景，其余场景都必须有参数占位
        if key != "macro":
            assert "<code>" in conf["argv"] or "<query>" in conf["argv"], (
                f"{key} 的 argv 缺参数占位：{conf['argv']}")
        # argv 的静态部分（去掉占位）必须是真实子命令
        static = [t for t in conf["argv"] if not t.startswith("<")]
        assert static[0] in ("stock", "us", "fund", "intent", "info"), (
            f"{key} 的子命令不在白名单：{static}")
        assert conf["route_kind"] is None or isinstance(conf["route_kind"], tuple)


def test_scenario_argv_and_get_data_agree(monkeypatch) -> None:
    """get_data._scenario_cmd 必须与 scenario_argv 逐字一致（防两份实现漂移）。"""
    for key in SCENARIO_COMMANDS:
        assert get_data._scenario_cmd(key, "600519", "茅台 最新") == \
            scenario_argv(key, "600519", "茅台 最新")


def test_scenario_route_kind_matches_detect() -> None:
    """detect_scenario 产出的每个 key 都必须能在场景表里查到路由。"""
    for query, type_, code in [
        ("", "us", "AAPL"), ("", "stock", "AAPL"), ("", "stock", "600519"),
        ("", "fund", "005827"), ("", "bond", ""), ("", "news", ""),
        ("", "macro", ""), ("", "enterprise", "600519"), ("", "industry", ""),
        ("茅台 ROE", "", ""), ("港股 腾讯", "", ""), ("", "", ""),
    ]:
        key = detect_scenario(query, type_, code=code)
        assert key in SCENARIO_COMMANDS, f"detect_scenario 产出了表外 key：{key}"
        assert scenario_route_kind(key) is not None or key in (
            "bond", "news", "macro"), f"{key} 的 route_kind 与场景语义不符"


def test_fetch_subprocess_passes_argv_without_resplitting(monkeypatch) -> None:
    """子进程必须以参数列表起，不得再对字符串切分。"""
    seen = {}

    class _R:
        returncode = 0
        stdout = '{"status":"ok","snapshot":{}}'

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return _R()

    monkeypatch.setattr(get_data.subprocess, "run", fake_run)
    get_data._fetch_subprocess(["info", "茅台 股价"])
    # 含空格的查询词必须是**一个**参数
    assert seen["argv"] == ["invest-cli", "info", "茅台 股价"]


def test_display_argv_quotes_only_when_needed() -> None:
    """展示串：普通参数裸写（与历史形状一致），含空格的加引号。"""
    assert get_data._display_argv(["us", "AAPL", "--json"]) == "us AAPL --json"
    assert get_data._display_argv(["info", "茅台 股价"]) == "info '茅台 股价'"


def test_query_with_chinese_name_passes_through(monkeypatch) -> None:
    """中文名 query 必须透传为标的，而不是落到「空标的」。

    名称消歧归上游：hithink/东财支持按名称检索（实测「隆基绿能」「中芯国际」
    均直接解析出代码，都不在 cmd_stock 那 12 条硬编码映射里）。旧行为只认
    ASCII 代码，中文名整类失败——底层有能、包装层断链。
    """
    seen = {}

    def fake_fetch(scenario, code):
        seen.update(scenario=scenario, code=code)
        return {"status": "ok", "snapshot": {"code": code}, "source": "hithink"}

    monkeypatch.setattr(get_data, "_fetch_in_process", fake_fetch)
    monkeypatch.setattr(get_data, "_ensure_scripts_on_path", lambda: True)
    out = get_data.get_data(query_str="隆基绿能")
    assert out["status"] == "ok"
    assert seen["code"] == "隆基绿能"
    assert out["command"] == "invest-cli stock 隆基绿能 --json"


def test_metric_word_is_not_treated_as_ticker(monkeypatch) -> None:
    """「茅台 ROE」必须取中文名，不能把 ROE 当股票代码。

    1-3 字母段与财务指标词字面重叠，而东财/yfinance 会把它们模糊匹配到真实
    公司（实测 `stock ROE` → Astoria US Equal Weight Quality(ROE.O)、
    `stock FCF` → 第一联邦金融(FCF.N)，全部 rc=0）——静默答错标的比报错更糟。
    判据是长度（去点后 ≥4），不是名单，不预设哪几个词是指标。
    """
    seen = {}

    def fake_fetch(scenario, code):
        seen.update(scenario=scenario, code=code)
        return {"status": "ok", "snapshot": {"code": code}, "source": "hithink"}

    monkeypatch.setattr(get_data, "_fetch_in_process", fake_fetch)
    monkeypatch.setattr(get_data, "_ensure_scripts_on_path", lambda: True)
    get_data.get_data(query_str="茅台 ROE")
    assert seen["code"] == "茅台"

    get_data.get_data(query_str="隆基绿能 毛利率")
    assert seen["code"] == "隆基绿能"


def test_short_letter_query_without_chinese_fails_honestly(monkeypatch) -> None:
    """纯短字母词且无中文段时不留 code：报「空标的」，不撞上游模糊匹配。

    刻意不起真子进程：这里要断言的是「mx-data 没有把 FCF 当标的传给 invest-cli」，
    由 fake 记录收到的 argv。真跑一遍 invest-cli 会让这条用例的结论取决于
    本机有没有装 invest-cli、以及上游把空代码判成什么，换台机器就假绿或假红。
    """
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        raise FileNotFoundError("invest-cli not installed")

    monkeypatch.setattr(get_data, "_ensure_scripts_on_path", lambda: False)
    monkeypatch.setattr(get_data.subprocess, "run", fake_run)
    out = get_data.get_data(query_str="FCF", target_type="stock")
    assert out["status"] == "error"
    assert out["data"] is None
    # 关键：FCF 没有作为标的进入 argv（它被 looks_like_us_ticker 判成美股
    # ticker，故走 us 链，但 ≤3 字母不当代码，留下的只有空 code）
    assert "FCF" not in seen["argv"]
    assert seen["argv"][0] == "invest-cli"


def test_scripts_path_resolves_to_real_route_module() -> None:
    assert (get_data.INVEST_CLI_SCRIPTS / "sources" / "route.py").is_file()
    assert (get_data.INVEST_CLI_SCRIPTS.parent / ".venv" / "bin" / "python").is_file()


def _venv_root() -> "Path":
    return get_data.INVEST_CLI_SCRIPTS.parent / ".venv"


def test_ensure_runtime_noop_when_already_in_venv(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(get_data.sys, "prefix", str(_venv_root()))
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    get_data._ensure_runtime()
    assert called == []


def test_ensure_runtime_noop_when_no_venv(monkeypatch, tmp_path) -> None:
    """公开仓用户环境：没有 .venv，系统解释器（任意 3.9+）就是支持形态。"""
    called = []
    monkeypatch.setattr(get_data, "INVEST_CLI_SCRIPTS", tmp_path / "scripts")
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    get_data._ensure_runtime()
    assert called == []


def test_ensure_runtime_noop_when_venv_interpreter_broken(monkeypatch, tmp_path) -> None:
    """venv 目录在、解释器软链断：判据须与 wrapper 同为 False，不得 re-exec。

    第八轮回归：Homebrew 升级删掉 base interpreter 后旧判据只认 is_file()，
    三处各自静默回退。这里钉住 mx-data 侧不会 exec 到一个跑不起来的二进制。
    """
    called = []
    root = tmp_path / "invest-cli"
    bindir = root / ".venv" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "python").symlink_to(bindir / "python3.99-missing")
    monkeypatch.setattr(get_data, "INVEST_CLI_SCRIPTS", root / "scripts")
    monkeypatch.setattr(get_data.sys, "prefix", "/usr")
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    monkeypatch.delenv("MX_DATA_NO_REEXEC", raising=False)
    get_data._ensure_runtime()
    assert called == []


def test_ensure_runtime_reexec_when_outside_venv(monkeypatch) -> None:
    """系统解释器启动 → 升级 re-exec 进 venv（2026-10-25 起不限美股场景：
    3.9 EOL + LibreSSL 告警，本机运行时统一走 skill 自带 venv）。"""
    import os

    called = []
    monkeypatch.delenv("MX_DATA_NO_REEXEC", raising=False)
    monkeypatch.setattr(get_data.sys, "prefix", "/usr")
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    get_data._ensure_runtime()
    assert len(called) == 1
    path, args = called[0]
    assert path == str(_venv_root() / "bin" / "python")
    assert args[0] == path  # execv(prog, [prog, *sys.argv]) 约定
    assert os.environ.get("MX_DATA_NO_REEXEC") == "1", "exec 前必须设防环标志"


def test_ensure_runtime_respects_opt_out(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(get_data.sys, "prefix", "/usr")
    monkeypatch.setenv("MX_DATA_NO_REEXEC", "1")
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    get_data._ensure_runtime()
    assert called == []


def test_ensure_runtime_probe_does_not_import_yfinance() -> None:
    """升级探测只看 sys.prefix 与文件存在性，不得真 import 任何重库。

    旧实现 `import yfinance` 当探测：连带 pandas/numpy，实测每次 336ms CPU、
    +54MB 内存，缓存命中的查询因此从 50ms 变成 362ms。用子进程断言，
    是因为同进程里别的用例可能已经 import 过，sys.modules 不干净；
    子进程带 MX_DATA_NO_REEXEC=1，避免 3.9 下真的 exec 换进程。
    """
    import os
    import subprocess

    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import get_data;"
        "get_data._ensure_runtime(); print('yfinance' in sys.modules)"
    )
    env = {**os.environ, "MX_DATA_NO_REEXEC": "1"}
    out = subprocess.run(
        [sys.executable, "-c", code, str(MX_SCRIPTS)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
