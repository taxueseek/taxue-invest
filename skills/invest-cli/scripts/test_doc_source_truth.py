#!/usr/bin/env python3
"""文档口径只认静态真值：yaml 声明 × 适配器能力。绝不锁运行时可用性。

历史：本文件 v1 锁 sources.route.chains()，而 chains() 按「当前机器可用性」
过滤（route.py）——ttskill 凭据过期、yfinance 缺模块都会把源从链上摘掉，
「设计顺序」被「本机凭据状态」判成失败。这是跨 7 轮复发最多的「判据层
漂移」。v2（2026-11-08 接入轮）改锁 candidates()。

v3（第九轮收敛）再进一层——**文档不再承载源名**：
- invest 门闩表与 mx-data 场景表删掉数据源列，只写「场景 → 命令」；
  源名的唯一真值是 data-sources.yaml（priority/route_kinds），运行时事实
  归 `invest-cli datasources` 与 usage 账本。文档不再声明链，就没有
  「文档与运行时不一致」可言；黑名单防止源名写回文档的回潮。
- 文档断言改为三类：命令必须真实存在（对 invest_cli.py 的 add_parser）；
  mx-data 场景表与 query_router.SCENARIO_COMMANDS 一一对应；易变数字
  （venv 版本）不进文档。
- SKILLS 路径按本文件相对定位（v1/v2 硬编码 ~/.agents/skills，靠软链
  间接层工作，软链一断文档守卫全体失效）。

链序断言锁 candidates()：yaml 优先级 × route_kinds × 适配器真方法，
不调 detect()——凭据过期、网络抖动、负缓存都不再影响测试。candidates
仍要求适配器模块可导入，所以缺 yfinance 的解释器上 us 链头用降级断言
（设计真值由自带 venv 钉住，见 test_stock_us_chain_design_heads）。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# taxue-invest/skills/（本文件在 invest-cli/scripts/ 下，parents[2] 即 skills 根）
SKILLS = Path(__file__).resolve().parents[2]

# 门闩表/场景表黑名单：这些源名一旦回到文档表里，就是「同一事实存第三份」回潮。
# wind/westock/htbr 例外——它们同时是具名直调命令（invest-cli wind / westock / htbr）。
_SOURCE_BLACKLIST = (
    "hithink", "ttskill", "eastmoney", "yfinance", "tiingo", "bitget",
    "tencent", "yingmi", "mxds", "sec_edgar", "index_hub", "etfirst", "fred",
)


def _section(text: str, heading: str) -> str:
    """取 `## heading` 起始的章节正文（heading 是行的前缀，标题可带后缀说明）。"""
    m = re.search(rf"^## {re.escape(heading)}[^\n]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"找不到章节：{heading}"
    return m.group(1)


def _row(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(f"| {label} ") or line.strip().startswith(f"| {label}|"):
            return line
    raise AssertionError(f"找不到表格行：{label}")


def _order(chain: list[str], a: str, b: str) -> None:
    assert a in chain and b in chain, f"{a}/{b} 不在链上：{chain}"
    assert chain.index(a) < chain.index(b), f"链序错误：{a} 应在 {b} 前，实际 {chain}"


def _cli_commands() -> set[str]:
    src = (_SCRIPTS / "invest_cli.py").read_text(encoding="utf-8")
    return set(re.findall(r'add_parser\(\s*"([a-z0-9\-]+)"', src))


def _load_query_router():
    path = SKILLS / "mx-data" / "scripts" / "query_router.py"
    spec = importlib.util.spec_from_file_location("_mx_query_router", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- 1. 链序设计真值（yaml × 适配器能力，不探测可用性） ----------

def test_fund_chain_design_order() -> None:
    from sources.route import candidates

    fund = candidates("fund")
    # ttskill 依赖 cryptography（缺件解释器上被 REQUIRED_IMPORTS 摘链）：
    # 位次不变量只对在链成员成立，全量真值由自带 venv 钉住
    present = [s for s in ("hithink", "ttskill", "eastmoney") if s in fund]
    for a, b in zip(present, present[1:]):
        _order(fund, a, b)


def test_stock_us_chain_design_heads() -> None:
    # candidates 不做可用性探测，但要求适配器模块可导入：缺 yfinance 的解释器
    # 会把 yfinance 从 us 链上摘掉（2026-10-23 起系统 3.9 无 yfinance 属被支持
    # 形态——mx-data 生产路径有 re-exec 自愈）。设计真值由自带 venv 钉住；
    # 缺件解释器只钉降级链头。
    from sources.route import candidates

    assert candidates("stock", market="a")[0] == "hithink"
    hk = candidates("stock", market="hk")
    _order(hk, "eastmoney", "tencent")
    if "yfinance" in hk:
        _order(hk, "tencent", "yfinance")
    us = candidates("us")
    if importlib.util.find_spec("yfinance") is not None:
        assert us[0] == "yfinance"
    else:
        assert us[0] == "fmp", "缺 yfinance 时 us 链头应降级到 FMP 基本面"
    _order(us, "fmp", "tencent")
    _order(us, "tencent", "tiingo")
    assert "bitget" not in us, "Bitget 代币价不得进入美股默认快照链"


def test_candidates_never_probes_availability() -> None:
    """candidates 与 pick 的分界是本文件成立的前提：candidates 不许调 detect。

    若有人把探测塞回 candidates，凭据过期的机器会再次出现「测试红但设计没变」。
    """
    import inspect

    from sources import route

    src = inspect.getsource(route.candidates)
    assert "detect" not in src, "candidates 里出现 detect：链序断言将随凭据状态腐烂"


# ---------- 2. invest 主入口：只写「场景 → 命令」，不写数据源链 ----------

def test_invest_entry_mapping_commands_exist() -> None:
    text = (SKILLS / "invest" / "SKILL.md").read_text(encoding="utf-8")
    section = _section(text, "数据源门闩")
    tokens = set(re.findall(r"`invest-cli ([a-z][a-z0-9\-]*)", section))
    assert tokens, "门闩表里没有 invest-cli 命令"
    unknown = tokens - _cli_commands()
    assert not unknown, f"门闩表引用了不存在的子命令：{sorted(unknown)}"


def test_invest_entry_mapping_has_no_source_chains() -> None:
    text = (SKILLS / "invest" / "SKILL.md").read_text(encoding="utf-8")
    section = _section(text, "数据源门闩")
    assert " > " not in section, "门闩表出现链式写法：源序只归 yaml 与运行时输出"
    leaked = [s for s in _SOURCE_BLACKLIST if s in section]
    assert not leaked, f"门闩表回潮了源名（应只写场景与命令）：{leaked}"


def test_invest_entry_bond_row_command() -> None:
    text = (SKILLS / "invest" / "SKILL.md").read_text(encoding="utf-8")
    row = _row(_section(text, "数据源门闩"), "债券")
    assert "intent deep bond" in row, row


# ---------- 3. mx-data 场景表 ↔ query_router.SCENARIO_COMMANDS 一一对应 ----------

def test_mx_data_table_matches_query_router() -> None:
    qr = _load_query_router()
    text = (SKILLS / "mx-data" / "SKILL.md").read_text(encoding="utf-8")
    section = _section(text, "场景→invest-cli 命令映射")
    for key, conf in qr.SCENARIO_COMMANDS.items():
        row = _row(section, conf["name"])
        # 子命令（argv 首词）必须出现在文档行里；`--json` 是输出旗标，文档不写
        subcommand = conf["argv"][0]
        assert subcommand in row, f"场景 {key}（{conf['name']}）缺子命令 {subcommand}：{row}"


def test_mx_data_mapping_has_no_source_chains() -> None:
    text = (SKILLS / "mx-data" / "SKILL.md").read_text(encoding="utf-8")
    section = _section(text, "场景→invest-cli 命令映射")
    assert " > " not in section, "场景表出现链式写法"
    leaked = [s for s in _SOURCE_BLACKLIST if s in section]
    assert not leaked, f"场景表回潮了源名：{leaked}"


# ---------- 4. 易变数字不进文档 ----------

def test_no_hardcoded_interpreter_version() -> None:
    """venv 解释器版本由 doctor 自报；写死进文档必漂移（3.14.7 vs 实际 3.15.2）。"""
    for rel in ("invest-cli/SKILL.md", "mx-data/SKILL.md"):
        text = (SKILLS / rel).read_text(encoding="utf-8")
        hit = re.findall(r"venv[（(]\d+\.\d+(?:\.\d+)?[）)]", text)
        assert not hit, f"{rel} 写死了解释器版本：{hit}"


# ---------- 5. cli-runtime 无作废表（沿用） ----------

def test_cli_runtime_has_no_obsolete_tables() -> None:
    text = (SKILLS / "invest" / "references" / "cli-runtime.md").read_text(encoding="utf-8")
    assert "本表已作废" not in text, "cli-runtime 仍保留作废表"
    assert "invest-cli datasources" in text


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
