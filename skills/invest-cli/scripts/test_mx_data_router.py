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
from query_router import detect_scenario, looks_like_us_ticker  # noqa: E402


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


def test_ensure_runtime_is_noop_for_non_us(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    get_data._ensure_runtime("stock_a")
    assert called == []


def test_ensure_runtime_respects_opt_out(monkeypatch) -> None:
    called = []
    monkeypatch.setenv("MX_DATA_NO_REEXEC", "1")
    monkeypatch.setattr(get_data.os, "execv", lambda *a: called.append(a))
    get_data._ensure_runtime("stock_us")
    assert called == []


def test_ensure_runtime_probe_does_not_import_yfinance() -> None:
    """探测只问「装没装」，不得真 import。

    真 import 会连带 pandas/numpy：实测 336ms CPU + 54MB RSS，而随后多半
    直接命中快照缓存、根本用不上 yfinance（缓存命中路径 362ms → 30ms，
    RSS 81MB → 14MB 就是这一行）。用新进程验，避免本进程已有的 import 污染结论。
    """
    import json
    import subprocess

    code = (
        "import json, sys;"
        f"sys.path.insert(0, {str(MX_SCRIPTS)!r});"
        "import get_data;"
        "get_data._ensure_runtime('stock_us');"
        "print(json.dumps({'yfinance_imported': 'yfinance' in sys.modules}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["yfinance_imported"] is False, (
        "_ensure_runtime 把 yfinance 真 import 进来了：探测相位变成了重库加载"
    )


def test_ensure_runtime_probe_does_not_import_yfinance() -> None:
    """探测只问「装没装」，不能把 yfinance 真 import 进来。

    旧实现 `import yfinance` 当探测：连带 pandas/numpy，实测每次 336ms CPU、
    +54MB 内存，缓存命中的美股查询因此从 50ms 变成 362ms。用子进程断言，
    是因为同进程里别的用例可能已经 import 过 yfinance，sys.modules 不干净。
    """
    import os
    import subprocess

    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import get_data;"
        "get_data._ensure_runtime('stock_us'); print('yfinance' in sys.modules)"
    )
    env = {**os.environ, "MX_DATA_NO_REEXEC": "1"}
    out = subprocess.run(
        [sys.executable, "-c", code, str(MX_SCRIPTS)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
