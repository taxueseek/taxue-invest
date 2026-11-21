#!/usr/bin/env python3
"""research fund-rank 管线契约 — 不打外部网络。

守护方案乙（2026-10-11）落地的四个关键点：
1. 池构建的过滤/去重规则（类别、改革红利混入、份额类、别名检索、离岸/港股通）
2. 双源互证：hithink returns vs ttskill 深取字段，不一致必须显式标注（不静默）
3. 排名缺键处理 + 批量快照逐只失败隔离
4. 股息率交叉标注：A 股命中/未入集/港股集外，共识按公司名合并（A/H 同司一司）
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cmd_research as R  # noqa: E402


# ── 1. 池构建 ─────────────────────────────────────────────

def _fake_search(monkeypatch, pages: dict[str, list[dict]]) -> None:
    """pages: query → 候选列表（一次回完，<50 条让分页循环自然停）。"""
    def fake(query, page_index=1, page_size=50):
        cands = pages.get(query, [])
        if page_index > 1:
            cands = []
        return {"source": "ttskill", "ok": True,
                "data": {"candidates": cands, "total_count": len(cands)}, "error": None}

    monkeypatch.setattr("sources.ttskill.search_funds", fake)


def _cand(code, name, cat="混合型-偏股"):
    return {"display_code": code, "name": name, "category_name": cat}


def test_pool_filters_and_dedup(monkeypatch) -> None:
    _fake_search(monkeypatch, {
        "红利": [_cand("014771", "中泰红利优选一年持有混合发起"),
                 _cand("014772", "中泰红利价值一年持有混合发起"),
                 _cand("001076", "易方达改革红利混合"),          # 改革红利 → 剔
                 _cand("022153", "华泰柏瑞红利精选混合A"),
                 _cand("022154", "华泰柏瑞红利精选混合C"),        # 共享类 → 留 A
                 _cand("021513", "富国港股通红利精选混合A"),      # 港股通 → 剔
                 _cand("006259", "汇添富红利增长混合A"),
                 _cand("968001", "摩根亚洲总收益人民币现金红利"),  # 离岸 → 剔
                 _cand("007828", "创金合信信用红利债券A", "债券型-混合一级")],
        "股息": [_cand("015289", "格林高股息优选混合A"),
                 _cand("015290", "格林高股息优选混合C")],
    })
    pool, notes, partial = R.build_pool("红利主题基金", 200, exclude_hk=True)
    codes = {f["code"] for f in pool}
    assert codes == {"014771", "014772", "022153", "006259", "015289"}, f"池规则失守: {codes}"
    assert any("别名检索" in n for n in notes), "应注明别名检索"
    assert any("改革红利" not in f["name"] for f in pool)
    assert partial is False, "检索全成功时不得标注池不完整"


def test_pool_partial_on_page_failure(monkeypatch) -> None:
    """检索页重试后仍失败必须 partial=True——静默截断的宇宙会伪装成全量结论。"""
    calls = []

    def flaky(query, page_index=1, page_size=50):
        calls.append((query, page_index))
        return {"source": "ttskill", "ok": False, "data": None, "error": "HTTP 504: 下游超时"}

    monkeypatch.setattr("sources.ttskill.search_funds", flaky)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    pool, notes, partial = R.build_pool("红利", 200, exclude_hk=True)
    assert pool == [] and partial is True
    assert any("重试后仍失败" in n for n in notes), notes
    # 主词「红利」+ 别名「股息」各重试 3 次（1+2）——失败不中止另一个词
    per_query: dict = {}
    for q, pg in calls:
        per_query[q] = per_query.get(q, 0) + 1
    assert per_query == {"红利": 3, "股息": 3}, f"重试分布异常: {per_query}"


def test_pool_limit_truncates(monkeypatch) -> None:
    _fake_search(monkeypatch, {"红利": [_cand(f"{600000 + i:06d}", f"红利基金{i}A") for i in range(30)]})
    pool, notes, _ = R.build_pool("红利", 10, exclude_hk=True)
    assert len(pool) == 10 and any("截断" in n for n in notes)


def test_pool_empty_theme_fails(monkeypatch) -> None:
    _fake_search(monkeypatch, {})
    pool, _, _ = R.build_pool("不存在的主题xyz", 200, exclude_hk=False)
    assert pool == []


def test_pool_blank_keyword_returns_three_tuple() -> None:
    pool, notes, partial = R.build_pool("   ", 200, exclude_hk=False)
    assert pool == []
    assert partial is True
    assert any("为空" in n for n in notes)


# ── 2. 双源互证 ───────────────────────────────────────────

def _env(returns: dict, deep: dict | None, source="hithink") -> dict:
    env = {"name": "X基金", "source": source, "returns": returns,
           "data": dict(deep) if deep else {}, "holdings": []}
    if deep is not None:
        env["deep_source"] = "ttskill"
    return env


def test_verify_match_and_mismatch() -> None:
    ok = R.verify_dual_source(_env({"tyear": 52.18, "year": 6.94},
                                   {"近3年回报": 52.2, "近1年回报": 6.9}))
    assert ok["verified"] is True
    bad = R.verify_dual_source(_env({"tyear": 52.18}, {"近3年回报": 40.0}))
    assert bad["verified"] is False and "近3年回报" in bad["detail"]


def test_verify_na_when_deep_missing_or_same_source() -> None:
    assert R.verify_dual_source(_env({"tyear": 1.0}, None))["verified"] is None
    same = R.verify_dual_source(_env({"tyear": 1.0}, {"近3年回报": 1.0}, source="ttskill"))
    assert same["verified"] is None, "快照与深取同源时无从互证"


# ── 3. 排名与批量隔离 ─────────────────────────────────────

def test_rank_orders_and_flags_missing() -> None:
    snaps = {
        "000001": _env({"tyear": 10.0}, {}),
        "000002": _env({"tyear": 78.4}, {"近3年回报": 78.4}),
        "000003": _env({}, {}),  # 缺近3年 → 缺键名单
    }
    rows, missing = R.rank_funds(snaps, "r3y")
    assert [r["code"] for r in rows] == ["000002", "000001"]
    assert missing == ["000003"]


def test_snapshot_batch_isolates_failure(monkeypatch) -> None:
    from cmd_research import snapshot_batch

    calls = []

    def fake_fetch(keyword):
        calls.append(keyword)
        if keyword == "000666":
            raise RuntimeError("上游炸了")
        return {"name": f"基金{keyword}", "source": "hithink", "returns": {"tyear": 1.0},
                "data": {}, "holdings": []}

    import cmd_fund
    monkeypatch.setattr(cmd_fund, "fetch_fund_with_fallback", fake_fetch)
    snaps, failures = snapshot_batch(["000001", "000666", "000002"])
    assert set(snaps) == {"000001", "000002"}, "单只失败不得影响整批"
    assert len(failures) == 1 and failures[0]["code"] == "000666"
    assert "上游炸了" in failures[0]["error"]


# ── 4. 股息率交叉 ─────────────────────────────────────────

def test_cross_labels_and_company_merge() -> None:
    # 参照集只含 ≥4% 的股票（查询即「股息率大于4%」）——集外 A 股标注 <4%
    dy = {"000333": {"name": "美的集团", "dy": 5.50}}
    ranked = [
        {"name": "基金A", "code": "000001", "returns": {"tyear": 50.0},
         "holdings": {"美的集团": {"ratio": 6.9, "code": "000333"},
                      "贵州茅台": {"ratio": 5.0, "code": "600519"},
                      "工商银行": {"ratio": 4.0, "code": "01398"}}},  # H 股代码
        {"name": "基金B", "code": "000002", "returns": {"tyear": 40.0},
         "holdings": {"美的集团": {"ratio": 3.0, "code": "000333"}}},
        {"name": "基金C", "code": "000003", "returns": {"tyear": 30.0},
         "holdings": {"美的集团": {"ratio": 2.0, "code": "000333"},
                      "贵州茅台": {"ratio": 4.0, "code": "600519"}}},
    ]
    cross = R.cross_holdings(ranked, 2, dy, dy_on=True)

    a_holds = {h["name"]: h["dy"] for h in cross["top_holdings"][0]["holdings"]}
    assert a_holds["美的集团"] == "5.50%"
    assert a_holds["贵州茅台"] == "<4%"
    assert a_holds["工商银行"] == "港股·集外"

    cons = {c["name"]: c for c in cross["consensus_high_dy"]}
    assert cons["美的集团"]["fund_n"] == 3 and abs(cons["美的集团"]["dy"] - 5.50) < 1e-9
    assert "贵州茅台" not in cons, "股息率<4% 不得进高股息共识表"


def test_cross_off_when_dy_off() -> None:
    ranked = [{"name": "基金A", "code": "000001", "returns": {"tyear": 1.0},
               "holdings": {"美的集团": {"ratio": 5.0, "code": "000333"}}}]
    cross = R.cross_holdings(ranked, 1, {}, dy_on=False)
    assert cross["top_holdings"][0]["holdings"][0]["dy"] == "-"
    assert cross["consensus_mismatched"] == []


if __name__ == "__main__":
    # 与 test_skill_integrity 同约定：夹具由 pytest 注入，手工调用会在
    # `test_pool_filters_and_dedup(monkeypatch)` 上抛 TypeError（裸跑入口形同虚设）。
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
