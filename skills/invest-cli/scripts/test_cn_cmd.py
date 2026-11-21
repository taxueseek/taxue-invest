#!/usr/bin/env python3
"""cn 子命令与 markdown 解析回归 — 不联网（上游全部 monkeypatch）。

守护三件事：
1. md_parse 对 westock 的真实输出形态（标题/分页/表格/键值）解析正确，
   且**格式变了也不丢数据**（fail-open：raw 始终在）；
2. cn 命令的信封契约（kind/source/ok 与结构化行）；
3. 公告列表在 westock 通道故障时降级到 argo/cninfo，而不是把故障丢给用户。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cmd_cn  # noqa: E402
import md_parse  # noqa: E402
from sources import argo as argo_src  # noqa: E402
from sources import westock  # noqa: E402

NOTICE_OUTPUT = """共 929 条（第 1 页，每页 20 条，共 47 页）
| type | id | symbol | time | title |
| --- | --- | --- | --- | --- |
| 0 | nos1225475868 | sh600519 | 2026-08-14 20:41:29 | 贵州茅台：2026年半年度报告 |
| 0 | nos1225475864 | sh600519 | 2026-08-14 20:41:28 | 贵州茅台：关于会计政策变更的公告 |
"""

CONSENSUS_OUTPUT = """
#### sh600519 贵州茅台

目标价: 1660.5983

| year | eps | pe |
| --- | --- | --- |
| 2027 | 70.84 | 17.66 |
| 2026 | 66.78 | 18.74 |
"""


# ── 1. md_parse：真实形态 + fail-open

def test_parse_table_and_pagination() -> None:
    parsed = md_parse.parse(NOTICE_OUTPUT)
    assert parsed["meta"] == {"total": 929, "page": 1, "page_size": 20, "pages": 47}
    table = parsed["tables"][0]
    assert table["header"] == ["type", "id", "symbol", "time", "title"]
    assert table["rows"][1]["title"] == "贵州茅台：关于会计政策变更的公告"
    assert parsed["raw"] == NOTICE_OUTPUT


def test_parse_title_and_kv_meta() -> None:
    parsed = md_parse.parse(CONSENSUS_OUTPUT)
    assert parsed["title"] == "sh600519 贵州茅台"
    assert parsed["meta"]["目标价"] == "1660.5983"
    assert [r["year"] for r in parsed["tables"][0]["rows"]] == ["2027", "2026"]


def test_parse_keeps_unknown_lines_as_notes() -> None:
    parsed = md_parse.parse("[Batch] 状态=success | 总数: 2 | 成功: 2 | 失败: 0\n")
    assert parsed["tables"] == []
    assert parsed["notes"] == ["[Batch] 状态=success | 总数: 2 | 成功: 2 | 失败: 0"]


def test_parse_ragged_row_is_preserved_not_dropped() -> None:
    text = "| a | b |\n| --- | --- |\n| 1 |\n"
    rows = md_parse.parse(text)["tables"][0]["rows"]
    assert rows == [{"_": ["1"]}], "列数对不上时按原样保留，不得丢行"


def test_parse_empty_input() -> None:
    parsed = md_parse.parse("")
    assert parsed["title"] == "" and parsed["meta"] == {}
    assert parsed["tables"] == [] and parsed["notes"] == [] and parsed["raw"] == ""


# ── 2. westock 参数归一：多代码与 notice list 的代码位

def test_notice_list_code_position_is_normalized() -> None:
    assert westock.normalize_args(["notice", "list", "600519"]) == ["notice", "list", "sh600519"]


def test_normalize_codes_multi() -> None:
    assert westock.normalize_codes("600519,000858") == "sh600519,sz000858"
    assert westock.normalize_codes("") == ""
    assert westock.normalize_codes("00700") == "hk00700"


# ── 3. cn 命令：信封契约与结构化输出

def _fake_westock(output: str):
    def _call(args):
        return {"source": "westock", "kind": "cli", "ok": True,
                "data": {"command": "westock " + " ".join(args),
                         "argv_normalized": False, "output": output},
                "error": None}
    return _call


def test_cn_notice_envelope(monkeypatch, capsys) -> None:
    monkeypatch.setattr(westock, "call", _fake_westock(NOTICE_OUTPUT))
    assert cmd_cn.run("notice", ["600519"], as_json=True) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["source"] == "westock" and res["kind"] == "cn_notice" and res["ok"] is True
    assert res["data"]["tables"][0]["rows"][0]["symbol"] == "sh600519"
    assert res["data"]["raw"] == NOTICE_OUTPUT


def test_cn_consensus_terminal_prints_rows(monkeypatch, capsys) -> None:
    monkeypatch.setattr(westock, "call", _fake_westock(CONSENSUS_OUTPUT))
    assert cmd_cn.run("consensus", ["600519"]) == 0
    out = capsys.readouterr().out
    assert "一致预期" in out and "70.84" in out and "目标价=1660.5983" in out


def test_cn_notice_search_uses_cninfo_engine(monkeypatch, capsys) -> None:
    seen = {}

    def _fake_search(query, engine="eastmoney", limit=5):
        seen["engine"] = engine
        seen["query"] = query
        return {"source": "argo", "ok": True, "error": None,
                "data": {"query": query, "engine": engine,
                         "results": [{"title": "某公司关于会计政策变更的公告",
                                      "url": "https://static.cninfo.com.cn/x.pdf", "snippet": "2026-09-23"}],
                         "note": "argo 检索结果需核验"}}

    monkeypatch.setattr(argo_src, "search", _fake_search)
    assert cmd_cn.run("notice", [], as_json=True, search="会计政策变更") == 0
    res = json.loads(capsys.readouterr().out)
    assert seen["engine"] == "cninfo" and seen["query"] == "会计政策变更"
    assert res["kind"] == "cn_notice_search" and res["data"]["results"][0]["title"]


def test_cn_notice_falls_back_to_argo_when_westock_fails(monkeypatch, capsys) -> None:
    """westock 通道故障 → 公告列表降级到 argo 检索，且标明来源与局限。"""
    def _boom(args):
        return {"source": "westock", "kind": "cli", "ok": False, "data": None,
                "error": "westock 未找到（模拟通道故障）"}

    monkeypatch.setattr(westock, "call", _boom)
    monkeypatch.setattr(argo_src, "search",
                        lambda q, engine="eastmoney", limit=5: {
                            "source": "argo", "ok": True, "error": None,
                            "data": {"query": q, "engine": engine,
                                     "results": [{"title": "贵州茅台公告", "url": "u", "snippet": "s"}]}})
    assert cmd_cn.run("notice", ["600519"], as_json=True) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["source"] == "argo" and res["ok"] is True
    assert "检索" in res["data"]["note"]


def test_cn_rejects_bad_args(monkeypatch, capsys) -> None:
    monkeypatch.setattr(westock, "call", _fake_westock(NOTICE_OUTPUT))
    assert cmd_cn.run("notice", ["600519"], limit=-1) == 1
    assert "不能为负" in capsys.readouterr().err
    assert cmd_cn.run("unknown", ["600519"]) == 1
    assert "未知子命令" in capsys.readouterr().err
    assert cmd_cn.run("consensus", []) == 1, "没给代码时必须报用法，不能静默成功"
    assert "用法" in capsys.readouterr().err


if __name__ == "__main__":
    import inspect
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                if inspect.signature(fn).parameters:
                    print(f"skip (needs fixtures): {name}")
                    continue
                fn()
                print(f"ok: {name}")
            except Exception:
                failed += 1
                print(f"FAIL: {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
