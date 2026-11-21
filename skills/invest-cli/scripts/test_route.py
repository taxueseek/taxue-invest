#!/usr/bin/env python3
"""Runtime router tests — no live network. Locks MECE pick rules."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources.route import fetch, pick  # noqa: E402


def test_stock_a_excludes_wind_and_orders() -> None:
    ids = pick("stock", market="a")
    assert "wind" not in ids, "Wind 只有 call()，不能进快照链"
    assert "yingmi" not in ids
    assert "bitget" not in ids
    if "hithink" in ids and "eastmoney" in ids:
        assert ids.index("hithink") < ids.index("eastmoney")


def test_stock_hk_excludes_hithink() -> None:
    from sources.route import candidates

    ids = pick("stock", market="hk")
    assert "hithink" not in ids
    cands = candidates("stock", market="hk")
    assert cands.index("eastmoney") < cands.index("tencent")
    if "yfinance" in cands:
        assert cands.index("tencent") < cands.index("yfinance")


def test_fund_snapshot_skips_yingmi_ttfund() -> None:
    ids = pick("fund")
    assert "yingmi" not in ids, "盈米无 fund() 快照，诊断走 intent 另一条问题"
    assert "ttfund" not in ids
    assert "wind" not in ids
    if "hithink" in ids and "eastmoney" in ids:
        assert ids.index("hithink") < ids.index("eastmoney")


def test_us_skips_uninstalled_yfinance() -> None:
    ids = pick("us")
    assert "hithink" not in ids
    assert "eastmoney" not in ids
    assert "bitget" not in ids, "bitget 代币价不再进入美股默认快照链"
    if "yfinance" in ids and "tencent" in ids:
        assert ids.index("yfinance") < ids.index("tencent")


def test_screen_orders_mxds_before_eastmoney() -> None:
    ids = pick("screen")
    assert "hithink" not in ids
    assert "wind" not in ids
    # mxds(55) 与 eastmoney(50) 都声明 screen 能力，两者都是「配了才在」；
    # 都配置时 mxds 必须排在 eastmoney 前（与 us 链 mxds 领跑一致）
    if "mxds" in ids and "eastmoney" in ids:
        assert ids.index("mxds") < ids.index("eastmoney")


def test_fetch_first_ok_stops() -> None:
    calls: list[str] = []

    def fake(sid, kind, arg):
        calls.append(sid)
        if sid == "hithink":
            return {"source": sid, "kind": kind, "ok": False, "data": None, "error": "miss"}
        return {"source": sid, "kind": kind, "ok": True, "data": {"code": arg}, "error": None}

    res = fetch("stock", "600519", order=["hithink", "eastmoney"], invoke=fake)
    assert res["ok"] is True
    assert res["source"] == "eastmoney"
    assert res["fallback_from"] == "hithink"
    assert calls == ["hithink", "eastmoney"]


def test_fetch_all_fail_returns_tried_envelope() -> None:
    """整链失败必须返回带 tried 的信封，不得抛异常（回退语义锁定，不依赖本机环境）。"""

    def fake(sid, kind, arg):
        return {"source": sid, "kind": kind, "ok": False, "data": None, "error": "down"}

    res = fetch("stock", "600519", order=["hithink", "eastmoney"], invoke=fake)
    assert res["ok"] is False
    assert res["tried"] == ["hithink", "eastmoney"]
    assert "hithink" in res["error"] and "eastmoney" in res["error"]


def test_fetch_exception_continues_to_next() -> None:
    """单源抛异常按失败计，整单继续回退。"""
    calls: list[str] = []

    def fake(sid, kind, arg):
        calls.append(sid)
        if sid == "hithink":
            raise RuntimeError("boom")
        return {"source": sid, "kind": kind, "ok": True, "data": {"code": arg}, "error": None}

    res = fetch("stock", "600519", order=["hithink", "eastmoney"], invoke=fake)
    assert res["ok"] is True
    assert res["source"] == "eastmoney"
    assert "hithink" in res["fallback_error"]
    assert calls == ["hithink", "eastmoney"]


def test_eastmoney_missing_key_is_envelope_not_exit(monkeypatch, tmp_path) -> None:
    """缺 key 时必须返回信封（而非 sys.exit），否则 route 的回退链会被绕过。

    隔离要求：真实机器上 ~/.config/invest-cli/eastmoney.env 往往存在，
    只 pop 环境变量是不够的——load_api_key 会读到凭据文件而「假装有 key」，
    于是本用例在**已配置的机器上必挂、在未配置的机器上才过**（环境耦合）。
    这里同时屏蔽环境变量与凭据文件，让「缺 key」这一前提真正成立。
    """
    from cmd_stock import get_api_key
    from sources import eastmoney as em

    monkeypatch.delenv("EASTMONEY_APIKEY", raising=False)
    monkeypatch.setattr(em, "credential_files", lambda: [])
    monkeypatch.setattr(em, "load_api_key", lambda: "")
    # read_env 会回落到 launchctl / shell rc，同样要屏蔽
    monkeypatch.setattr("sources.env.read_env", lambda name: "")

    try:
        get_api_key()
        raise AssertionError("missing key must raise")
    except RuntimeError as e:
        assert "EASTMONEY_APIKEY" in str(e)
    except SystemExit as e:
        raise AssertionError(f"sys.exit 会绕过 route 回退: {e}") from e

    res = em.stock("600519")
    assert res["ok"] is False
    assert res["source"] == "eastmoney"
    assert "EASTMONEY" in (res.get("error") or "").upper() or "未设置" in (res.get("error") or "")


def test_fetch_does_not_mix_payloads() -> None:
    def fake(sid, kind, arg):
        return {
            "source": sid,
            "kind": kind,
            "ok": True,
            "data": {"pe": 1 if sid == "hithink" else 99},
            "error": None,
        }

    res = fetch("stock", "600519", market="a", invoke=fake)
    assert res["data"]["pe"] == 1
    assert "fallback_from" not in res


def test_fetch_empty_arg_is_rejected_before_any_probe() -> None:
    """空标的必须在取数之前拦下：旧行为是打满整条链再拼三句错误。"""
    res = fetch("stock", "   ")
    assert res["ok"] is False
    assert "空标的" in res["error"]
    assert "tried" not in res  # 没有尝试过任何源


def test_fetch_probes_sources_lazily(monkeypatch) -> None:
    """主源命中时，后面的兜底源不得被探测。

    A 股链里 yfinance 只是末位兜底，但它的探测是真实 HTTPS（实测 0.5s）。
    旧实现 pick() 一次性探测全链，于是每次查 A 股都白付一次 Yahoo 往返。
    """
    import sources.route as route

    probed: list[str] = []

    def fake_detect(conf):
        probed.append(str(conf.get("name", "?")))
        return True, "ok"

    monkeypatch.setattr(route, "detect", fake_detect)
    monkeypatch.setattr(
        route,
        "_invoke",
        lambda sid, kind, arg: {"source": sid, "kind": kind, "ok": True,
                                "data": {"sid": sid}, "error": None},
    )
    res = route.fetch("stock", "600519", market="a")
    assert res["ok"] is True
    assert res["source"] == "hithink"
    assert len(probed) == 1, f"主源已命中却探测了 {probed}"


def test_fetch_detects_next_source_when_first_unavailable(monkeypatch) -> None:
    """反向对照：主源不可用时必须继续探测下一个，不能修成一律不探测。"""
    import sources.route as route

    calls = {"n": 0}

    def fake_detect(conf):
        calls["n"] += 1
        return calls["n"] > 1, "第一个不可用" if calls["n"] == 1 else "ok"

    monkeypatch.setattr(route, "detect", fake_detect)
    monkeypatch.setattr(
        route,
        "_invoke",
        lambda sid, kind, arg: {"source": sid, "kind": kind, "ok": True,
                                "data": {"sid": sid}, "error": None},
    )
    res = route.fetch("stock", "600519", market="a")
    assert res["ok"] is True
    # 断言「链上第二位」而不是具体某个 sid：registry 增删源（如 mxds 插进
    # hithink 与 eastmoney 之间）不应碰这个测试的本意——主源不可用要落到下一位
    assert res["source"] == route.candidates("stock", market="a")[1]
    assert calls["n"] == 2, "第一个源不可用时未探测第二个"


def test_fetch_all_unavailable_keeps_original_message(monkeypatch) -> None:
    """整链都不通过探测时，结论与**前缀措辞**必须与旧 pick() 一致。

    本轮追加（场景实测发现）：只报 `kind=fund market=-` 是内部术语，用户看不出
    缺哪个 key——同一条链上的 stock 会把逐源原因列全。现在把探测失败原因接在
    原措辞之后，前缀不变，附加原因可省（`errors` 为空时保持原样）。
    """
    import sources.route as route

    monkeypatch.setattr(route, "detect", lambda conf: (False, "缺 key"))
    res = route.fetch("fund", "110011")
    assert res["ok"] is False
    assert res["error"].startswith("无可用数据源: kind=fund market=-")
    assert "缺 key" in res["error"], "报错没带逐源原因，用户不知道缺什么"
    assert res["tried"], "应给出试过哪些源"


# ── 失败信封的落盘负缓存（snapshot_fail）────────────────────────────────
# 背景：成功结果有快照缓存而失败没有，打错代码（stock zzzz）每次都付完整条
# 候选链（实测 5.2s）。这里锁三件事：失败落盘、重复查询命中不再跑链、
# INVEST_CLI_FETCH_FAIL_TTL=0 可整体关闭。


def _mount_fake_chain(monkeypatch, tmp_path, fail: bool = True):
    """把默认路由挂到一条假链上（缓存重定向到 tmp，探测全通过，单源假实现）。"""
    import sources.route as route

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(route, "candidates", lambda kind, market=None: ["fakesrc"])
    monkeypatch.setattr(route, "detect", lambda conf: (True, "ok"))
    calls = []

    def _invoke(sid, kind, arg):
        calls.append((sid, kind, arg))
        if fail:
            return {"source": sid, "kind": kind, "ok": False, "data": None,
                    "error": "fakesrc: 没有这个标的"}
        return {"source": sid, "kind": kind, "ok": True, "data": {"price": 1.0},
                "error": None}

    monkeypatch.setattr(route, "_invoke", _invoke)
    return calls


def test_failure_envelope_is_disk_cached(monkeypatch, tmp_path) -> None:
    calls = _mount_fake_chain(monkeypatch, tmp_path, fail=True)
    r1 = fetch("stock", "ZZZZ")
    assert r1["ok"] is False and len(calls) == 1
    r2 = fetch("stock", "ZZZZ")
    assert len(calls) == 1, "失败信封未落盘，第二次查询重跑了整条候选链"
    assert r2["ok"] is False and r2.get("cached") is True
    assert r2["error"] == r1["error"], "命中负缓存须原样返回错误信封"


def test_fetch_fail_ttl_zero_disables_negative_cache(monkeypatch, tmp_path) -> None:
    """INVEST_CLI_FETCH_FAIL_TTL=0 须整体关闭负缓存：第二次仍要跑链（排障语义）。"""
    calls = _mount_fake_chain(monkeypatch, tmp_path, fail=True)
    monkeypatch.setenv("INVEST_CLI_FETCH_FAIL_TTL", "0")
    fetch("stock", "ZZZZ")
    fetch("stock", "ZZZZ")
    assert len(calls) == 2, "TTL=0 时第二次查询应重新执行候选链，而不是吃到负缓存"


def test_failure_cache_expires_after_ttl(monkeypatch, tmp_path) -> None:
    """负缓存窗口有时限：TTL 内重复查询吃缓存；过期后重新跑链。

    「上游恢复能否被立刻看见」是有意取舍：90s 内恢复不会越过负缓存（与
    registry 负探测、成功快照缓存同一套有界陈旧语义）；要即时重试走
    INVEST_CLI_FETCH_FAIL_TTL=0。这里锁的是**窗口必须真的有时限**。
    """
    import os as _os
    import time as _time

    import _common

    calls = _mount_fake_chain(monkeypatch, tmp_path, fail=True)
    assert fetch("stock", "ZZZZ")["ok"] is False
    assert fetch("stock", "ZZZZ").get("cached") is True and len(calls) == 1
    fail_dir = _common.cache_root() / "snapshot_fail"
    entries = list(fail_dir.glob("*.json"))
    assert entries, "失败信封没有落盘"
    old = _time.time() - 91  # 越过默认 90s 窗口
    for p in entries:
        _os.utime(p, (old, old))
    fetch("stock", "ZZZZ")
    assert len(calls) == 2, "负缓存过期后仍命中——窗口不是有时限的"




def test_kind_fns_matches_registry_route_kinds() -> None:
    """可路由 kind 的声明必须等于配置真源（route_kinds 的并集）。

    KIND_FNS 曾写 9 种而配置里只有 4 种有链，bond/index/macro/news/notice
    是「看起来支持」的假承诺——`fetch("bond")` 恒报「无可用数据源」。
    新增可路由 kind 时改 yaml 的 route_kinds 即可，本处同步；漏改则本用例变红。
    """
    from sources import load_registry
    from sources.route import KIND_FNS

    declared: set[str] = set()
    for conf in load_registry().values():
        declared.update(conf.get("route_kinds") or ())
    assert set(KIND_FNS) == declared


def test_disabled_sources_excluded_from_candidates(monkeypatch) -> None:
    """INVEST_CLI_DISABLE_SOURCES 是「面板选择」的引擎侧原语：停用源不进路由链。

    语义是「不要自动选它」——candidates/pick/chains 全部经过 candidates，一处
    过滤三层生效；具名直调（invest-cli wind / htbr）是用户点名，不受影响。
    分隔符容忍逗号/分号/空白与大小写（面板写入的是逗号串，用户手改环境可能
    带空格或大写）。
    """
    from sources.route import candidates, disabled_sources

    monkeypatch.setenv("INVEST_CLI_DISABLE_SOURCES", "hithink, TTSKILL ;")
    assert disabled_sources() == frozenset({"hithink", "ttskill"})
    fund = candidates("fund")
    assert "hithink" not in fund and "ttskill" not in fund
    assert "eastmoney" in fund, "未停用的源必须留在链上"


def test_disabled_sources_unset_is_noop(monkeypatch) -> None:
    from sources.route import candidates, disabled_sources

    monkeypatch.delenv("INVEST_CLI_DISABLE_SOURCES", raising=False)
    assert disabled_sources() == frozenset()
    assert "hithink" in candidates("stock", market="a")


def test_disabled_sources_empty_value_is_noop(monkeypatch) -> None:
    """面板 config 的缺省值是空串——空串必须等价于未设置，不能解析出假源名。"""
    from sources.route import candidates, disabled_sources

    monkeypatch.setenv("INVEST_CLI_DISABLE_SOURCES", "")
    assert disabled_sources() == frozenset()
    # 顺手断言链上仍有源：选腾讯（零依赖免 Key）而非 yfinance——
    # 后者在缺件解释器上会被 REQUIRED_IMPORTS 判缺摘链，属环境相关断言
    assert "tencent" in candidates("us")


def test_disabled_sources_pick_and_chains_inherit(monkeypatch) -> None:
    """pick/chains 走 candidates，停用集在三层同时生效（datasources 靠它报停用态）。"""
    from sources.route import chains, pick

    monkeypatch.setenv("INVEST_CLI_DISABLE_SOURCES", "tencent,bitget")
    assert "tencent" not in pick("us")
    assert "bitget" not in chains()["us"]


def test_deps_missing_unit_and_noop() -> None:
    """REQUIRED_IMPORTS 判缺：声明了缺件依赖 → 判缺；未声明 → 永不判缺（行为不变）。"""
    from sources import tencent as tencent_mod
    from sources.route import _deps_missing

    class _FakeModule:
        REQUIRED_IMPORTS = ("nonexistent_pkg_for_route_test",)

    assert _deps_missing(_FakeModule()) == ["nonexistent_pkg_for_route_test"]
    assert _deps_missing(tencent_mod) == []


def test_candidates_drops_adapter_with_missing_dependency(monkeypatch) -> None:
    """链上效果：给腾讯声明一个不存在的依赖，us 链必须把它摘掉（缺件摘链语义）。

    这是 test_doc_source_truth「缺 yfinance 时 us 链头降级到腾讯」的机制测试——
    不管当前解释器装没装 yfinance，摘链语义本身都必须成立。
    """
    import sources.tencent as tencent_mod
    from sources.route import candidates

    monkeypatch.setattr(
        tencent_mod, "REQUIRED_IMPORTS", ("nonexistent_pkg_for_route_test",), raising=False
    )
    assert "tencent" not in candidates("us")


def test_real_third_party_dependencies_are_declared() -> None:
    """真第三方依赖必须声明在适配器层：漏声明会复活 us/fund 链头的缺件假承诺。

    yfinance 包在 cmd_us.py 函数内延迟 import；cryptography 在 ttskill.py
    函数内延迟 import——两处都是「适配器可导入 ≠ 依赖可导入」的实例。
    """
    from sources import ttskill as ttskill_mod
    from sources import yfinance as yfinance_mod

    assert "yfinance" in getattr(yfinance_mod, "REQUIRED_IMPORTS", ())
    assert "cryptography" in getattr(ttskill_mod, "REQUIRED_IMPORTS", ())


def test_fallback_from_records_primary_failed_source() -> None:
    """链上连续两源失败后第三源成功，fallback_from 应记录第一顺位主源而非最后一个失败源。"""
    from sources.route import fetch

    def fake_invoke(sid: str, kind: str, arg: str) -> dict:
        if sid in ("a", "b"):
            return {"source": sid, "kind": kind, "ok": False, "data": None, "error": f"{sid} err"}
        return {"source": sid, "kind": kind, "ok": True, "data": {"ok": 1}, "error": None}

    res = fetch("stock", "600519", order=["a", "b", "c"], invoke=fake_invoke)
    assert res["ok"] is True
    assert res["source"] == "c"
    assert res["fallback_from"] == "a"
    assert "a: a err" in res["fallback_error"]
    assert "b: b err" in res["fallback_error"]


def test_chains_reuses_precomputed_states_without_detect(monkeypatch) -> None:
    """传入 states 时，chains()/pick() 不得再调用 registry.detect。"""
    from sources import route

    def boom(*_a, **_kw):
        raise AssertionError("should not probe detect() when states is provided")

    monkeypatch.setattr(route, "detect", boom)
    fake_states = {"hithink": {"available": True}, "eastmoney": {"available": False}}
    ch = route.chains(states=fake_states)
    assert "hithink" in ch["stock_a"]
    assert "eastmoney" not in ch["stock_a"]


if __name__ == "__main__":
    # 裸跑必须真执行，而且不能与 pytest 夹具打架：本文件里
    # `test_eastmoney_missing_key_is_envelope_not_exit` 要 monkeypatch/tmp_path，
    # 手工逐个调用会在它身上抛 TypeError（旧的手工清单还引用过已改名的函数）。
    # 统一交给 pytest 收集，与 test_skill_integrity 的入口保持同一约定。
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
