#!/usr/bin/env python3
"""文档里的「源序」必须与运行时链一致（纯静态，不联网）。

背景：2026-10-17 实测 `intent deep bond 019547` 返回 `source=wind`，而
`invest/SKILL.md` 的门闩表写的是「债券 → mxds」；`mx-data/SKILL.md` 写基金
「天天基金优先」，实际链首是同花顺。两处都是 agent 会照读的活文档。
根因不是笔误，是**同一事实存了三份**：yaml、chains()、文档各写各的。

本用例只钉关键结论（不做脆弱的整表 diff）：
- 基金链 hithink → ttskill → eastmoney；
- A 股链首 hithink；美股链首 yfinance、tiingo 在 bitget 前；
- 债券行提到 wind 且不再提 mxds；
- cli-runtime 不再保留「已作废」表（它们会被整段读成事实）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

SKILLS = Path.home() / ".agents" / "skills"


def _row(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(f"| {label} ") or line.strip().startswith(f"| {label}|"):
            return line
    raise AssertionError(f"找不到表格行：{label}")


def _order(chain: list[str], a: str, b: str) -> None:
    assert a in chain and b in chain, f"{a}/{b} 不在链上：{chain}"
    assert chain.index(a) < chain.index(b), f"链序错误：{a} 应在 {b} 前，实际 {chain}"


def test_fund_chain_order_matches_docs() -> None:
    from sources.route import chains

    fund = chains()["fund"]
    _order(fund, "hithink", "ttskill")
    _order(fund, "ttskill", "eastmoney")


def test_stock_and_us_chain_heads() -> None:
    from sources.route import chains

    ch = chains()
    assert ch["stock_a"][0] == "hithink"
    assert ch["us"][0] == "yfinance"
    _order(ch["us"], "tiingo", "bitget")


def test_invest_entry_bond_row_points_to_wind() -> None:
    text = (SKILLS / "invest" / "SKILL.md").read_text(encoding="utf-8")
    row = _row(text, "债券")
    assert "wind" in row.lower(), row
    # 允许在注释里说明「mxds 不支持」，但不能把它标成债券的取数源。
    assert "mxds（妙想）" not in row, f"债券行仍把 mxds 当源：{row}"


def test_invest_entry_fund_row_matches_chain() -> None:
    text = (SKILLS / "invest" / "SKILL.md").read_text(encoding="utf-8")
    row = _row(text, "基金快照")
    for sid in ("hithink", "ttskill", "eastmoney"):
        assert sid in row, f"基金行缺 {sid}：{row}"


def test_mx_data_fund_row_matches_chain() -> None:
    text = (SKILLS / "mx-data" / "SKILL.md").read_text(encoding="utf-8")
    row = _row(text, "基金")
    assert "同花顺优先" in row, row


def test_cli_runtime_has_no_obsolete_tables() -> None:
    text = (SKILLS / "invest" / "references" / "cli-runtime.md").read_text(encoding="utf-8")
    assert "本表已作废" not in text, "cli-runtime 仍保留作废表"
    assert "invest-cli datasources" in text


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
