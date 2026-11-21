"""基金三层分类器 golden test（全部离线：_invoke 整体替换）。

FTYPE 字符串口径全部来自真实实测（2026-09-30，ttskill TTFUND_BASE_INFOS，
天天/东财系），每条映射规则至少一个正例锁行为；规则真源 fund-classification.yaml，
改规则不改代码——golden 用例就是「改规则必须看见行为变化」的锁。
"""
from __future__ import annotations

from typing import Any, Optional

import pytest

import fund_classifier as fcl


# ---------- 假 ttskill：真实响应结构（data[0] + expansion.fund_classification） ----------

def _raw(ftype: str, shortname: str, *, traits: Optional[dict] = None,
         etfcode: str = "", rlevel: str = "") -> dict[str, Any]:
    return {
        "success": True, "errorCode": "0",
        "data": [{"FTYPE": ftype, "SHORTNAME": shortname, "ETFCODE": etfcode,
                  "RLEVEL_CX": rlevel, "DWJZ": 1.4573}],
        "expansion": {"fund_classification": {
            "market": {"category": "PUBLIC", "matched_rule": "fallback_public"},
            "public_product": {
                "traits": traits if traits is not None else {
                    "is_index_fund": False, "is_exchange_traded_fund": False,
                    "is_lof": False, "is_qdii_fund": False, "is_fof_fund": False,
                    "is_pension_fund": False, "is_public_reits": False,
                    "has_holding_restriction": False},
                "restriction": {"kind": "NONE", "subscribe_status": "开放申购",
                                "redeem_status": "开放赎回", "raw_feature_codes": []},
            },
        }},
    }


FIXTURES = {
    # FTYPE 字符串 = 2026-09-30 真实实测口径
    "005827": _raw("混合型-偏股", "易方达蓝筹精选混合"),
    "000198": _raw("货币型-普通货币", "天弘余额宝货币"),
    "159915": _raw("指数型-股票", "创业板ETF易方达",
                   traits={"is_index_fund": True, "is_exchange_traded_fund": True,
                           "is_lof": False, "is_qdii_fund": False, "is_fof_fund": False,
                           "is_pension_fund": False, "is_public_reits": False,
                           "has_holding_restriction": False}),
    "110027": _raw("债券型-混合二级", "易方达安心回报债券A", rlevel="5"),
    "110011": _raw("QDII-混合偏股", "易方达优质精选混合",
                   traits={"is_index_fund": False, "is_exchange_traded_fund": False,
                           "is_lof": False, "is_qdii_fund": True, "is_fof_fund": False,
                           "is_pension_fund": False, "is_public_reits": False,
                           "has_holding_restriction": False}),
    "006289": _raw("FOF-均衡型", "中欧预见养老2025一年持有FOF",
                   traits={"is_index_fund": False, "is_exchange_traded_fund": False,
                           "is_lof": False, "is_qdii_fund": False, "is_fof_fund": True,
                           "is_pension_fund": True, "is_public_reits": False,
                           "has_holding_restriction": True}),
    "501018": _raw("QDII-商品", "南方原油", rlevel="4"),
    "508021": _raw("Reits", "华夏北京保障房REIT",
                   traits={"is_index_fund": False, "is_exchange_traded_fund": False,
                           "is_lof": False, "is_qdii_fund": False, "is_fof_fund": False,
                           "is_pension_fund": False, "is_public_reits": True,
                           "has_holding_restriction": False}),
    "000961": _raw("指数型-股票", "天弘沪深300ETF联接A", etfcode="000961"),
    "001102": _raw("混合型-偏股", "前海开源国家比较优势混合"),
}


@pytest.fixture(autouse=True)
def fake_invoke(monkeypatch):
    """_invoke 整体替换：按 fcode 分发，未覆盖的 code 返回空 data（未找到）。"""
    import sources.ttskill as ttskill

    def fake(skill_id: str, params: dict, *a, **kw):
        code = (params or {}).get("fcode", "")
        if code in FIXTURES:
            return FIXTURES[code]
        return {"success": True, "errorCode": "0", "data": []}

    monkeypatch.setattr(ttskill, "_invoke", fake)


# ---------- golden：每条映射规则的正例 ----------

@pytest.mark.parametrize("code,l1,l2,l3", [
    ("005827", "混合类", "偏股混合型", "主动管理"),      # ftype_rules 混合型-偏股
    ("000198", "货币类", "普通货币型", "不适用"),        # ftype_rules 货币型-普通货币
    ("159915", "权益类", "指数股票型", "被动指数"),      # ftype_rules 指数型-股票 + traits ETF
    ("110027", "固收类", "混合二级债基", "主动管理"),    # ftype_rules 债券型-混合二级 + 固收+
    ("110011", "跨境(QDII)", "QDII偏股混合型", "主动管理"),  # ftype_rules QDII-混合偏股
    ("006289", "FOF", "均衡型FOF", "主动管理"),          # ftype_rules FOF-均衡型 + 养老
    ("501018", "另类(商品)", "QDII商品型", "主动管理"),  # 资产优先：QDII-商品 归另类非跨境
    ("508021", "另类(REITs)", "公募REITs", "不适用"),    # ftype_rules Reits
])
def test_golden_classification(code, l1, l2, l3):
    res = fcl.classify(code, use_cache=False)
    assert res["ok"] is True, res.get("error")
    c = res["data"]["classification"]
    assert c["L1"] == l1, f"{code}: L1 {c['L1']} != {l1}"
    assert c["L2"] == l2, f"{code}: L2 {c['L2']} != {l2}"
    assert c["L3"] == l3, f"{code}: L3 {c['L3']} != {l3}"
    assert res["data"]["unresolved"] == [], f"{code}: 不应有未定 {res['data']['unresolved']}"


def test_golden_tags():
    tags = fcl.classify("159915", use_cache=False)["data"]["tags"]
    assert tags["ETF"] is True and tags["运作方式"] == "ETF" and tags["指数型"] is True
    tags = fcl.classify("110027", use_cache=False)["data"]["tags"]
    assert tags["固收+"] is True and tags["风险等级"] == "5"
    tags = fcl.classify("006289", use_cache=False)["data"]["tags"]
    assert tags["FOF"] is True and tags["养老"] is True and tags["运作方式"] == "普通开放式"


def test_link_fund_target_etf():
    """联接基金：ETFCODE → 目标ETF 标签。"""
    d = fcl.classify("000961", use_cache=False)["data"]
    assert d["tags"]["目标ETF"] == "000961"
    assert d["tags"]["指数型"] is True


# ---------- 前缀兜底与未定语义 ----------

def test_unregistered_ftype_falls_back_and_flags(monkeypatch):
    """未登记的 FTYPE：L1 走前缀+资产段，L2 原样透传并报未定，绝不静默编造。"""
    # 股票型-商品 未登记：前缀判权益类，但资产段优先覆盖为另类(商品)
    FIXTURES["999001"] = _raw("股票型-商品", "某商品基金")
    try:
        d = fcl.classify("999001", use_cache=False)["data"]
        # 资产段优先：商品 → 另类(商品)，不是前缀判的权益类
        assert d["classification"]["L1"] == "另类(商品)"
        assert d["classification"]["L2"] == "股票型-商品"  # 原样透传
        assert any("未登记" in u for u in d["unresolved"])
    finally:
        del FIXTURES["999001"]


def test_missing_ftype_is_explicit_unknown_not_failure():
    """FTYPE 缺失：字段 None + unresolved 原因——未定是合法输出不是失败。"""
    FIXTURES["999002"] = {"success": True, "errorCode": "0",
                          "data": [{"SHORTNAME": "某基金", "DWJZ": 1.0}], "expansion": {}}
    try:
        res = fcl.classify("999002", use_cache=False)
        assert res["ok"] is True
        c = res["data"]["classification"]
        assert c["L1"] is None and c["L2"] is None and c["L3"] is None
        assert any("FTYPE 缺失" in u for u in res["data"]["unresolved"])
    finally:
        del FIXTURES["999002"]


def test_unknown_fund_not_found():
    res = fcl.classify("999999", use_cache=False)
    assert res["ok"] is False and "未找到" in res["error"]


def test_bad_code_rejected_without_network():
    res = fcl.classify("蓝筹精选", use_cache=False)
    assert res["ok"] is False and "6 位" in res["error"]


# ---------- 名称后缀交叉复核：冲突并列不裁决，只对境内大类生效 ----------

def test_name_conflict_flagged_for_onshore(monkeypatch):
    """境内基金名称后缀与 FTYPE 判层矛盾 → 并列报冲突（不动 L1，交人工复核）。"""
    FIXTURES["999003"] = _raw("债券型-长债", "某灵活配置混合")  # 名称说混合，FTYPE 说债券
    try:
        res = fcl.classify("999003", use_cache=False)
        conflicts = res["data"]["conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["name_l1"] == "混合类" and conflicts[0]["ftype_l1"] == "固收类"
        assert res["data"]["classification"]["L1"] == "固收类"  # 不裁决，FTYPE 为准
    finally:
        del FIXTURES["999003"]


def test_name_conflict_skipped_for_qdii():
    """QDII 基金名称后缀「混合」是段内注册形态，不构成冲突（实测 110011 误报教训）。"""
    res = fcl.classify("110011", use_cache=False)
    assert res["data"]["conflicts"] == []
    assert res["data"]["classification"]["L1"] == "跨境(QDII)"


# ---------- 规则真源完整性（改规则必须过这几条） ----------

def test_rules_file_loads_and_enums_closed():
    rules = fcl._load_rules()
    assert rules["ftype_rules"], "规则表缺 ftype_rules"
    l1_enum = set(rules["l1_enum"])
    # 全文映射的 L1 必须都在封闭枚举里
    for ftype, conf in rules["ftype_rules"].items():
        assert conf.get("l1") in l1_enum, f"ftype_rules[{ftype}] 的 L1 {conf.get('l1')} 不在 l1_enum"
    # 前缀兜底的 L1 同理
    for prefix, conf in rules.get("prefix_rules", {}).items():
        assert conf.get("l1") in l1_enum, f"prefix_rules[{prefix}] 的 L1 不在 l1_enum"
    # 资产段优先的 L1 同理
    for seg, conf in rules.get("asset_segment_rules", {}).items():
        assert conf.get("l1") in l1_enum, f"asset_segment_rules[{seg}] 的 L1 不在 l1_enum"


def test_cached_roundtrip():
    calls = {"n": 0}

    def counting(skill_id, params, *a, **kw):
        calls["n"] += 1
        return FIXTURES[params["fcode"]]

    import sources.ttskill as ttskill

    fcl.__dict__  # noqa: B018
    import fund_classifier
    fund_classifier._RULES_CACHE = None
    monkey = pytest.MonkeyPatch()
    monkey.setattr(ttskill, "_invoke", counting)
    try:
        first = fund_classifier.classify("005827", use_cache=True)
        assert first["ok"] and not first.get("cached")
        second = fund_classifier.classify("005827", use_cache=True)
        assert second.get("cached") is True and calls["n"] == 1  # 第二次零网络
        fresh = fund_classifier.classify("005827", use_cache=False)
        assert fresh.get("cached") is None and calls["n"] == 2  # 逃生舱不读也不写
    finally:
        monkey.undo()


# ---------- 真实通道（默认跳过；INVEST_LIVE=1 时跑） ----------

@pytest.mark.live
def test_live_multi_type():
    if __import__("os").environ.get("INVEST_LIVE") != "1":
        pytest.skip("INVEST_LIVE!=1")
    for code, l1 in [("005827", "混合类"), ("000198", "货币类"), ("159915", "权益类"),
                     ("110027", "固收类"), ("110011", "跨境(QDII)"), ("006289", "FOF"),
                     ("501018", "另类(商品)"), ("508021", "另类(REITs)")]:
        res = fcl.classify(code, use_cache=False)
        assert res["ok"] is True and res["data"]["classification"]["L1"] == l1, code


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
