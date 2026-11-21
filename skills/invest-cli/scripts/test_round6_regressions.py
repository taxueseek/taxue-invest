#!/usr/bin/env python3
"""第六轮回归锁：8 个已修缺陷的永久守卫（不联网）。

每个用例都**曾经红过**（2026-09-27 修复前逐一复现），修复后转绿。
保留它们的价值在于：这些都是「静默给错数据」而不是「报错」的一类缺陷，
删掉守卫就等于把错数据放回生产。

覆盖：
  F6  route.canonical_arg 吃掉真实美股代码前缀（SHEL→EL / USO→O / SHW→W）
  F8  ttskill.nav_series 缓存键缺窗口参数 → 跨窗口缓存投毒
  F9  registry.detect 缺 command 分支 → 已装的 etfirst 被永久判死
  F1  etf_analytics 解析东财 "9.99%" 持仓权重 → TypeError 崩给用户
  F17 bitget 空壳记录返回 ok=True（rc=0 假成功）
  F19 watchlist 非原子写 + 损坏文件当空列表 → 用户自选股静默丢失
  F16 westock 的 --json 被 REMAINDER 转发给子 CLI → unknown flag 报错
  F18 凭据文件不剥引号 → 带引号 key 鉴权失败但 detect 报「已配置」
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

SKILLS_ROOT = _SCRIPTS.parent.parent     # skills/


# ─────────────────────────── F6：美股代码前缀 ───────────────────────────

def test_canonical_arg_strips_cn_prefixes() -> None:
    """原有能力不能退：中文市场前缀写法仍须归一为裸代码。"""
    from sources.route import canonical_arg

    assert canonical_arg("sh600519") == "600519"
    assert canonical_arg("600519.SH") == "600519"
    assert canonical_arg("hk00700") == "00700"
    assert canonical_arg("usAAPL") == "AAPL"
    assert canonical_arg("BRK.B") == "BRK.B"


def test_canonical_arg_preserves_real_us_tickers() -> None:
    """反回归：真实美股代码的前两个字母不能被当成市场前缀。

    旧实现 `^(sh|sz|bj|hk|us)(?=[0-9A-Za-z])` re.I，把 SHEL→EL、USO→O，
    整条链 rc=0 却返回**另一家公司**的行情。字面同形时，保留原样永远对。
    """
    from sources.route import canonical_arg

    for ticker in ("SHEL", "USO", "SHW", "USB", "SHR", "USMV", "USFD", "USMOO"):
        assert canonical_arg(ticker) == ticker, f"{ticker} 被误当作前缀剥掉了"


def test_canonical_arg_us_prefix_keeps_convention() -> None:
    """us 前缀写法（小写 us + 大写代码）仍要工作。"""
    from sources.route import canonical_arg

    assert canonical_arg("usAAPL") == "AAPL"
    assert canonical_arg("usNVDA") == "NVDA"


def test_tencent_normalize_preserves_real_us_tickers() -> None:
    """腾讯适配器里**第二份**前缀剥离实现必须同样守住真实 ticker。

    route.canonical_arg 修好后 `us USO` 仍答成 Realty Income——因为
    sources/tencent.normalize_code 还有一份独立的 `if low.startswith("us"):
    return "us" + c[2:]`，把 USO 削成 O、USB 削成 B。同一个缺陷的两份实现，
    只修一处等于没修（这正是「一处修复消灭一类」的必要性）。
    """
    from sources.tencent import normalize_code

    for ticker in ("USO", "USB", "USMV", "USFD", "SHW", "SHEL", "USMOO"):
        assert normalize_code(ticker) == f"us{ticker}", f"{ticker} 被削短了"
    # 反向：前缀写法与中文市场写法不得退化
    assert normalize_code("usAAPL") == "usAAPL"
    assert normalize_code("sh600519") == "sh600519"
    assert normalize_code("600519") == "sh600519"
    assert normalize_code("hk00700") == "hk00700"
    assert normalize_code("00700") == "hk00700"
    assert normalize_code("BRK.B") == "usBRK.B"


def test_us_prefix_mixed_case_forms_all_work() -> None:
    """前缀写法的大小写变体必须全部可用（对抗验证时发现的回归）。

    曾经用「整串全大写 ⇒ 真实 ticker」做判据，结果把合法的 `USAAPL`/
    `UsAAPL`/`USaapl` 一并判成 ticker，`invest-cli us USAAPL` 直接查不到。
    现在判据是**剩余长度 ≥4**：真实 ticker 去掉 US 后最多剩 2 位（USO/USB/
    USMOO），前缀写法给 3-4 位，两边都保得住。
    """
    from sources.route import canonical_arg
    from sources.tencent import normalize_code

    for form in ("usAAPL", "UsAAPL", "USAAPL", "USaapl", "usaapl"):
        assert canonical_arg(form) == "AAPL", f"{form} 未归一为 AAPL"
        assert normalize_code(form) == "usAAPL", f"{form} 在 tencent 层未归一"
    # 真实 ticker 一律原样穿透
    for ticker in ("USO", "USB", "USMV", "USMOO", "USFD", "USNA"):
        assert canonical_arg(ticker) == ticker, f"真实代码 {ticker} 被剥了前缀"


def test_canonical_and_tencent_normalize_agree() -> None:
    """两份代码归一实现必须给出**同一个**答案（防再次漂移）。

    它们曾各写一份、各自漂移过一次：修好 route 之后 `us USO` 仍答错，
    因为 tencent 那份还在削前缀。一致性由本用例钉住。
    """
    from sources.route import canonical_arg
    from sources.tencent import normalize_code

    for t in ("USO", "USB", "USMV", "SHW", "SHEL", "AAPL", "NVDA",
              "usAAPL", "USAAPL", "us600519", "sh600519", "hk00700", "BRK.B"):
        expected = canonical_arg(t)
        got = normalize_code(t)
        # normalize_code 产出的是带市场前缀的形式；从中还原裸代码后应一致
        stripped = got[2:] if got.startswith(("us", "sh", "sz", "bj", "hk")) else got
        assert stripped == expected, (
            f"{t}: canonical_arg→{expected} 与 normalize_code→{got} 判定不一致"
        )


def test_holdings_industry_and_weighted_valuation_use_same_parser() -> None:
    """集中度 / 行业分布 / 加权估值三处必须走**同一个**权重解析点。

    首次修复只把集中度那三行换成 _hold_ratio，行业分布（`industries[ind] =
    ... + w`）和加权估值仍用裸值，于是同一次调用里照样
    `TypeError: int + str`——修一半等于没修。
    """
    from etf_analytics import analyze_holdings

    holdings = [
        {"entityName": "贵州茅台", "占净值比例": "9.99%", "industry": "白酒"},
        {"entityName": "腾讯控股", "占净值比例": "8.00%", "industry": "互联网"},
    ]
    res = analyze_holdings(holdings)
    assert "error" not in res, res
    ind = res.get("industry_distribution") or []
    assert ind and abs(ind[0]["weight_pct"] - 9.99) < 0.01, ind

    res2 = analyze_holdings(
        [{"ticker": "600519", "占净值比例": "9.99%"}],
        quote_data={"600519": {"pe": 20.0, "pb": 3.0}},
    )
    wv = res2.get("weighted_valuation") or {}
    assert wv.get("weighted_pe"), f"加权估值没算出来：{res2}"


# ─────────────────────────── F8：净值缓存投毒 ───────────────────────────

def test_nav_series_cache_not_poisoned_by_narrower_window(monkeypatch, tmp_path) -> None:
    """先查窄窗口、再查宽窗口：宽窗口必须拿到完整序列。

    旧实现把**切片后**的结果按 `ttnav|{code}` 落盘，于是第二次查询
    零网络请求直接返回窄子集，coverage.first 偏后，累计收益率与回撤
    跟着偏小——不报错的错数字。
    """
    from sources import ttskill
    import _common

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(_common, "cache_root", lambda: tmp_path)

    items = [
        {"FSRQ": "2019-06-01", "JZZZL": "1.0", "DWJZ": "1.0", "LJJZ": "1.0"},
        {"FSRQ": "2020-06-01", "JZZZL": "2.0", "DWJZ": "1.01", "LJJZ": "1.02"},
        {"FSRQ": "2022-06-01", "JZZZL": "3.0", "DWJZ": "1.02", "LJJZ": "1.04"},
        {"FSRQ": "2023-06-01", "JZZZL": "4.0", "DWJZ": "1.03", "LJJZ": "1.06"},
    ]
    calls = {"n": 0}

    def fake_invoke(_sid, _payload):
        calls["n"] += 1
        return {"data": {"nav_history": {"items": items}}}

    monkeypatch.setattr(ttskill, "_invoke", fake_invoke)

    narrow = ttskill.nav_series("001959", "2022-01-01")
    assert narrow["ok"] and narrow["series"][0][0] == "2022-06-01"
    assert calls["n"] == 1

    wide = ttskill.nav_series("001959", "2019-01-01")
    assert wide["ok"], wide
    assert wide["series"][0][0] == "2019-06-01", (
        f"宽窗口只拿到 {wide['series'][0][0]}——缓存被窄窗口的子集投毒了"
    )
    assert len(wide["series"]) == 4
    # 第二次应当命中缓存（不再打网络），但**结果**仍必须是全量
    assert calls["n"] == 1, f"宽窗口又去打了一次网络，calls={calls['n']}"


def test_nav_series_tolerates_non_numeric_sentinels(monkeypatch, tmp_path) -> None:
    """非数值哨兵（N/A / — / --）不得让 float() 抛 ValueError。

    原守卫是精确字符串白名单 `g not in ("", "--", None)`，漏一个真实出现
    的哨兵就是整条 tenure 命令 traceback。
    """
    from sources import ttskill
    import _common

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(_common, "cache_root", lambda: tmp_path)

    items = [
        {"FSRQ": "2023-01-03", "JZZZL": "1.0", "DWJZ": "1.0", "LJJZ": "1.0"},
        {"FSRQ": "2023-01-04", "JZZZL": "N/A", "DWJZ": "1.01", "LJJZ": "1.02"},
        {"FSRQ": "2023-01-05", "JZZZL": "—", "DWJZ": "1.02", "LJJZ": "1.04"},
        {"FSRQ": "2023-01-06", "JZZZL": "1.5", "DWJZ": "1.03", "LJJZ": "1.06"},
    ]
    monkeypatch.setattr(
        ttskill, "_invoke",
        lambda _s, _p: {"data": {"nav_history": {"items": items}}},
    )
    res = ttskill.nav_series("022490")
    assert res["ok"], res
    assert len(res["series"]) == 4


# ─────────────────────── F9：探测方式漂移 ───────────────────────

def test_registry_handles_command_probe_type() -> None:
    """detect() 必须认识 yaml 里声明过的每一种探测方式。

    v2.6 删掉 command 分支时，data-sources.yaml 里 etfirst 的
    `type: command` 没跟着改 → 一个**已装好的**数据源被永久判成
    「未知探测方式」，且没有任何报错。声明与判据漂移必须被测试挡住。
    """
    from sources import load_registry
    from sources.registry import detect

    declared = {
        (c.get("detect") or {}).get("type")
        for c in load_registry().values()
    }
    for conf in load_registry().values():
        avail, detail = detect(conf)
        assert "未知探测方式" not in detail, (
            f"{conf.get('name')} 用了未实现的探测方式：{detail}"
        )


def test_etfirst_detect_returns_tuple() -> None:
    """适配器级 detect 的契约：返回 (bool, str)，供 registry 缓存。"""
    from sources import etfirst

    avail, detail = etfirst.detect()
    assert isinstance(avail, bool) and isinstance(detail, str)
    assert avail == etfirst.is_available(), "detect() 与 is_available() 判据必须一致"


def test_index_hub_detect_matches_real_precondition(monkeypatch) -> None:
    """index_hub 的可用性判据必须是**真实前置条件**，不是 yaml 声明的文件。

    旧实现没有 detect()，registry 退化成「env 变量 / 那个 key 文件在吗」，
    而本模块真正依赖的是 api_client.py 脚本在不在——于是换台机器就会
    报「可用」而 fetch() 立刻返回「未安装」。这是 v2.4/v2.5 修过
    eastmoney 的同一个「假可用」类，只是漏了 index_hub。
    """
    from sources import index_hub

    # client 缺失 → 必须判不可用，哪怕凭据文件在
    monkeypatch.setattr(index_hub, "_INDEX_HUB_CLIENT", index_hub.Path("/nonexistent/api_client.py"))
    monkeypatch.setattr(index_hub, "_load_key", lambda: "some-key")
    avail, detail = index_hub.detect()
    assert avail is False, f"client 不在却判可用：{detail}"
    assert "client" in detail

    # client 在但没凭据 → 同样不可用（否则照样取不到数）
    monkeypatch.setattr(index_hub, "_INDEX_HUB_CLIENT", index_hub.Path(__file__))
    monkeypatch.setattr(index_hub, "_load_key", lambda: "")
    avail, detail = index_hub.detect()
    assert avail is False, f"无凭据却判可用：{detail}"

    # 两者齐备 → 可用
    monkeypatch.setattr(index_hub, "_load_key", lambda: "some-key")
    avail, detail = index_hub.detect()
    assert avail is True, f"前置齐备却判不可用：{detail}"


# ─────────────────────── F1：持仓权重解析 ───────────────────────

def test_analyze_holdings_parses_percent_strings() -> None:
    """东财持仓权重是 "9.99%" 字符串，不是数字。

    旧实现直接进 sorted()/sum() → `TypeError: unsupported operand type(s)
    for +: 'int' and 'str'`，在主源挂掉的回���路径上崩给用户。
    """
    from etf_analytics import analyze_holdings

    res = analyze_holdings([
        {"entityName": "贵州茅台", "占净值比例": "9.99%"},
        {"entityName": "腾讯控股", "占净值比例": "8.00%"},
        {"entityName": "招商银行", "占净值比例": "5.01%"},
    ])
    assert "error" not in res, res
    assert abs(res["concentration"]["top5_pct"] - 23.00) < 0.01


def test_safe_float_handles_units_and_sentinels() -> None:
    from etf_analytics import _safe_float

    assert _safe_float("9.99%") == 9.99
    assert _safe_float("1,234.5") == 1234.5
    assert _safe_float("") is None
    assert _safe_float("--") is None
    assert _safe_float("N/A") is None
    assert _safe_float(None) is None
    assert _safe_float(True) is None, "bool 是 int 子类，必须显式排除"


def test_etfirst_list_shaped_results_degrades_not_crashes() -> None:
    """上游回 {"results": [...]} 时必须降级为 error，而不是 AttributeError。"""
    from etf_analytics import analyze_etfirst_enhanced

    res = analyze_etfirst_enhanced({"results": [{"a": 1}]})
    assert "error" in res, res


# ─────────────────────── F17：rc=0 假成功 ───────────────────────

def test_bitget_rejects_empty_shell_record(monkeypatch) -> None:
    """空壳记录 `{"code":"00000","data":[{}]}` 不得返回 ok=True。

    旧实现只拒 `not data` 与「非 dict 行」，于是解析出一份 price/bid/ask
    全 None 的 payload 并**当成成功**返回，调用方把一张全 `-` 的表渲染
    出来且不触发回退——v2.4 给 yfinance 修过的「rc=0 假成功」，漏了 bitget。
    """
    from sources import bitget

    got = bitget.us(
        "AAPL",
        http_get=lambda _url: (200, '{"code":"00000","data":[{}]}'),
    )
    assert got.get("ok") is False, f"空壳记录被判成功：{got}"
    assert "空行情" in str(got.get("error")) or "无价格" in str(got.get("error")), got

    # 反向用例：有真实价格时必须仍判成功（守卫不能一刀切）
    good = bitget.us(
        "AAPL",
        http_get=lambda _url: (
            200,
            '{"code":"00000","data":[{"lastPr":"12.34","bidPr":"12.3",'
            '"askPr":"12.4","ts":"1750000000000"}]}',
        ),
    )
    assert good.get("ok") is True, f"真实报价被误拒：{good}"


# ─────────────────────── F19：用户数据丢失 ───────────────────────

def test_watchlist_save_is_atomic_under_crash(monkeypatch, tmp_path) -> None:
    """写入中途崩溃时，旧文件必须完好无损。

    行为级守卫：让 json.dump 在写到一半时抛错（模拟断电/被杀）。
    非原子写会把旧文件截断成半截 JSON，下一次 _load 读不出 → 返回 [] →
    任何一次 add 都把用户全部自选股换成一行，且静默无提示。
    """
    import cmd_watchlist

    wl = tmp_path / "wl.json"
    original = [{"code": "600519"}, {"code": "000858"}]
    wl.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cmd_watchlist, "watch_file", lambda: wl)

    real_dump = json.dump

    def exploding_dump(obj, fp, **kw):
        fp.write("[")  # 已落盘一半
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(json, "dump", exploding_dump)
    with pytest.raises(OSError):
        cmd_watchlist._save([{"code": "300750"}])
    monkeypatch.setattr(json, "dump", real_dump)

    assert json.loads(wl.read_text(encoding="utf-8")) == original, (
        "崩溃后原文件已被破坏——写入不是原子的"
    )


def test_watchlist_load_does_not_discard_corrupt_file(monkeypatch, tmp_path) -> None:
    """损坏文件不得被当成「空列表」然后被下一次 add 整体覆盖。

    自选股没有上游可重取：_load 返回 [] 之后任何一次 add 都会把用户全部
    标的换成一行，旧数据静默永久消失。
    """
    import cmd_watchlist

    wl = tmp_path / "wl.json"
    wl.write_text('[{"code": "600519"}, {"code": ', encoding="utf-8")  # 截断
    monkeypatch.setattr(cmd_watchlist, "watch_file", lambda: wl)

    assert cmd_watchlist._load() == []
    assert wl.with_suffix(".json.corrupt").exists(), "损坏文件被直接丢弃，没留档"


def test_watchlist_refuses_writes_while_backup_pending(monkeypatch, tmp_path) -> None:
    """有留档未恢复时，add/remove 必须**拒绝写入**（对抗验证时发现的关键缺口）。

    只留档不拦写入，用户感知到的仍是「自选股没了」：损坏 → add → 写回一条
    → 原数据被覆盖。实测复现过这条完整链路。留档必须配一道写入闸门，
    才真正阻止覆盖。
    """
    import cmd_watchlist

    wl = tmp_path / "wl.json"
    wl.write_text('[{"code": "600519"}, {"code": ', encoding="utf-8")
    monkeypatch.setattr(cmd_watchlist, "watch_file", lambda: wl)

    # 第一次 list 触发留档（真实流程：用户先看到损坏提示）
    assert cmd_watchlist._load() == []
    bak = tmp_path / "wl.json.corrupt"
    assert bak.is_file() and "600519" in bak.read_text(encoding="utf-8")

    # 留档已存在时的写入必须被拒绝
    with pytest.raises(SystemExit) as ei:
        cmd_watchlist.add("300750")
    assert "中止" in str(ei.value) or "损坏" in str(ei.value)
    # 关键：留档内容没被覆盖掉
    assert "600519" in bak.read_text(encoding="utf-8")


def test_watchlist_quarantine_does_not_clobber_earlier_backup(monkeypatch, tmp_path) -> None:
    """第二次损坏不得覆盖第一次的留档（那可能含唯一一份原始数据）。"""
    import cmd_watchlist

    wl = tmp_path / "wl.json"
    monkeypatch.setattr(cmd_watchlist, "watch_file", lambda: wl)

    wl.write_text('[{"code": "AAAA"}', encoding="utf-8")
    cmd_watchlist._load()
    first = tmp_path / "wl.json.corrupt"
    assert "AAAA" in first.read_text(encoding="utf-8")

    wl.write_text('[{"code": "BBBB"}', encoding="utf-8")
    cmd_watchlist._load()
    assert "AAAA" in first.read_text(encoding="utf-8"), "第一次的留档被覆盖了"
    others = [p for p in tmp_path.iterdir() if p.name.startswith("wl.json.corrupt")]
    assert len(others) == 2, f"第二次损坏没有另存：{others}"


# ─────────────────────── F16：--json 旗标 ───────────────────────

def test_westock_json_flag_not_forwarded_to_subcli(monkeypatch) -> None:
    """`westock chip 600519 --json` 不得把 --json 转发给子 CLI。

    行为级守卫（不是读源码找关键字）：REMAINDER 会把位置参数之后的
    `--json` 一并收进 args 转发出去，子 CLI 不认这个旗标 →
    「Error: unknown flag: --json」rc=1。旧实现只在旗标写在子命令**之前**
    时才生效，而这个顺序要求没有任何文档说明。
    """
    import argparse
    from invest_cli import cmd_westock

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    p_ws = sub.add_parser("westock", add_help=False)
    p_ws.add_argument("args", nargs=argparse.REMAINDER)
    p_ws.add_argument("-h", "--help", action="store_true", dest="ws_help")
    p_ws.add_argument("--json", action="store_true")
    args = parser.parse_args(["westock", "chip", "600519", "--json"])
    # 前提：argparse 确实把 --json 吞进了 REMAINDER（否则本用例测不到东西）
    assert "--json" in args.args and args.json is False, "前提失效：argparse 行为已变"

    seen = {}

    def fake_run(passthrough, as_json=False):
        seen["args"], seen["json"] = list(passthrough), as_json
        return 0

    monkeypatch.setattr("cmd_westock.run", fake_run)
    with pytest.raises(SystemExit):
        cmd_westock(args)
    assert "--json" not in seen["args"], f"--json 被转发给了子 CLI：{seen['args']}"
    assert seen["json"] is True, "转发时没把 --json 转成本层的 as_json"


# ─────────────────────── 路由表自洽（设计层守卫） ───────────────────────

def test_router_triggers_are_all_resolvable() -> None:
    """frontmatter triggers 里的每个词，都必须能在 SKILL.md 路由表里落地。

    守卫一个已经发生过的缺陷：「分析一下/看看这个/值得买吗/这只怎么样/
    比特币/IC报告/研报」7 个 triggers 命中不了任何一行——技能会被唤起，
    进去却无处可路由。（通用开场白那四句已由「通用开场白」段落显式兜住，
    这里断言该段落存在，不要求它们出现在表里。）
    """
    import re

    skill = SKILLS_ROOT / "invest" / "SKILL.md"
    if not skill.is_file():
        pytest.skip("invest/SKILL.md 不在（未安装该技能）")
    text = skill.read_text(encoding="utf-8")

    fm = re.search(r"^---\n(.*?)\n---", text, re.S)
    assert fm, "frontmatter 缺失"
    triggers = re.findall(r"^\s*-\s*(\S+)\s*$", fm.group(1), re.M)

    # 路由表 = **「路由逻辑」段落里**「| 「...」 | skill |」形式的行。
    #
    # 只看这一节，不扫全文件：旧实现扫全文所有含「」的表格行，于是 trigger
    # 「研报」被 deleted 之前的**示例表格**里「深度研报模式」这几个字供上了
    # 一个假通过——真正该被问责的是路由表里根本没有这一行。示例表格现已删除，
    # 但判据不能靠示例供着，故收窄到定义路由的那一节。
    section = re.search(r"## 路由逻辑\n(.*?)\n## ", text, re.S)
    table = "\n".join(
        ln for ln in (section.group(1) if section else "").splitlines()
        if ln.strip().startswith("|") and "「" in ln
    )
    generic = {"分析一下", "看看这个", "值得买吗", "这只怎么样"}
    for t in triggers:
        if t in generic:
            assert "通用开场白" in text, (
                f"通用开场白 {t} 仍无路由规则：要么进表，要么在「通用开场白」段落兜住"
            )
            continue
        assert t in table, f"trigger 「{t}」在路由表里找不到对应行——技能会被唤起却无处可路由"


def test_archived_route_rows_reference_real_commands() -> None:
    """「已归档路由」表里的「查看方式」必须是真实存在的命令或技能。

    该表历史上写着 `invest bond` / `invest commodity`（invest-cli 顶层并无
    这两个子命令，正确的是 intent deep 的子场景）和 `eastmoney 子命令`
    （连 eastmoney 技能都已删除）。因为整表带「归档」标记，指针守卫会
    跳过这一段——悬空引用就永久豁免了。这里单独钉住。
    """
    import re

    skill = SKILLS_ROOT / "invest" / "SKILL.md"
    if not skill.is_file():
        pytest.skip("invest/SKILL.md 不在（未安装该技能）")
    text = skill.read_text(encoding="utf-8")

    block = re.search(r"## 已归档路由.*?\n\n(.*?)\n\n", text, re.S)
    assert block, "找不到「已归档路由」小节"
    real_cmds = {
        "stock", "fund", "us", "quote", "kline", "sec", "cn", "screen",
        "datasources", "wind", "yingmi", "ttskill", "capabilities",
        "intent", "info", "watchlist", "tenure", "westock", "cli", "help",
    }
    for row in block.group(1).splitlines():
        if not row.strip().startswith("|"):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[1]:
            continue
        how = cells[2]
        # 只校验**带反引号的显式命令**（`invest-cli xxx` / `intent xxx`）；
        # 裸写的「invest stock」在本表里表示技能名，不是子命令。
        for cmdline in re.findall(r"`([^`]+)`", how):
            toks = cmdline.split()
            if not toks:
                continue
            head = toks[0]
            if head in ("invest-cli", "invest_cli"):
                assert len(toks) > 1 and toks[1] in real_cmds, (
                    f"悬空命令：{cmdline}（{cells[0]}）"
                )
            elif head == "intent":
                assert len(toks) > 1 and toks[1] in {
                    "deep", "screen", "portfolio", "plan", "macro", "present",
                }, f"悬空 intent 场景：{cmdline}（{cells[0]}）"
        # 裸写形式：若形如 `invest <x>`，<x> 必须是个真实技能名
        m = re.fullmatch(r"invest\s+([a-z-]+)", how.strip())
        if m:
            assert m.group(1) in {
                "stock", "fund", "asset", "macro", "allocation", "discuss",
                "analyst", "cli",
            }, f"悬空技能/命令：{how}（{cells[0]}）"

def test_credential_file_parser_strips_quotes(tmp_path) -> None:
    """带引号与不带引号必须解析出同一个值。"""
    from sources.env import read_credential_file

    q = tmp_path / "q.env"
    p = tmp_path / "p.env"
    q.write_text('EASTMONEY_APIKEY="SECRET123"\n', encoding="utf-8")
    p.write_text("EASTMONEY_APIKEY=SECRET123\n", encoding="utf-8")
    assert read_credential_file("EASTMONEY_APIKEY", [q]) == "SECRET123"
    assert read_credential_file("EASTMONEY_APIKEY", [p]) == "SECRET123"


def test_credential_file_parser_ignores_comments_and_blanks(tmp_path) -> None:
    from sources.env import read_credential_file

    f = tmp_path / "c.env"
    f.write_text("# 注释\n\nexport FOO=bar\nEASTMONEY_APIKEY=  \n", encoding="utf-8")
    assert read_credential_file("EASTMONEY_APIKEY", [f]) == ""
    assert read_credential_file("FOO", [f]) == "bar"
