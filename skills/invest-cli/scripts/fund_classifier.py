"""基金三层分类器引擎（方案一 · 规则映射器，invest-cli 数据能力）。

定位：**评价友好分类**——回答「这只基金像什么、跟谁比、用哪把尺」，不是
登记报送用的契约分类（公众号《基金评价底座的「基金分类器」Skill 实践》同构）。
分类器只输出**稳定的分类事实**（L1/L2/L3 + 标签 + 依据 + 口径原文），不做任何
评价结论——筛选/三关审查/同类对比/watchlist 各自消费，与消费方解耦；
「未知使用需求的普适性」就落在这一条上。

数据底座（P0 实测 2026-09-30，单请求全拿下）：
  - ttskill TTFUND_BASE_INFOS（天天/东财口径，基金链深取同一通道）：
    data[0].FTYPE    产品形态原文字符串（混合型-偏股/债券型-混合二级/指数型-股票/…）
    data[0].SHORTNAME 全称（带类型后缀：易方达蓝筹精选混合）→ L3 关键词 + 交叉复核
    data[0].ETFCODE  联接基金的目标 ETF
    data[0].RLEVEL_CX 风险等级
    expansion.fund_classification.public_product.traits  结构化布尔组
    （is_index_fund/is_exchange_traded_fund/is_lof/is_qdii_fund/is_fof_fund/
      is_pension_fund/is_public_reits/has_holding_restriction）
    expansion...restriction  申赎状态（限大额/开放赎回）
    expansion...market.matched_rule  天天自家分类引擎结论（原样透传）
  - 其余四源（hithink/eastmoney/…）**没有类型字段**（实测快照只有场内外标记），
    不做同义词表；SHORTNAME 的类型后缀当交叉复核列，冲突并列不裁决。

规则真源：fund-classification.yaml（改规则不改代码，golden 用例锁行为）。
未定语义：字段缺失/未登记时输出 None + unresolved 原因——错误分类比未分类
危害大，绝不静默猜。

缓存：FTYPE/traits 是登记口径，日内不变，CACHE_TTL_FUNDAMENTAL（1h）。
use_cache=False 供测试：不读也不写（fred 的缓存污染教训）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

SOURCE = "fund-classifier"
RULES_FILE = Path(__file__).resolve().parent.parent / "fund-classification.yaml"
ENV_HINT = "ttskill 未就绪（TTFUND_BASE_INFOS 深取通道）"

# 进程内规则表缓存（yaml 解析 ~1ms，30s 复用与 registry 同量级）
_RULES_CACHE: Optional[dict[str, Any]] = None


def _load_rules() -> dict[str, Any]:
    """规则真源加载（进程内缓存）；缺文件是配置事故，响亮报错不静默。"""
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    try:
        import yaml

        rules = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    except OSError as e:
        raise RuntimeError(f"分类规则真源缺失: {RULES_FILE}（{e}）") from e
    if not isinstance(rules, dict) or not rules.get("ftype_rules"):
        raise RuntimeError(f"分类规则真源为空或结构不对: {RULES_FILE}")
    _RULES_CACHE = rules
    return rules


def normalize_code(symbol: str) -> str:
    t = re.sub(r"\s+", "", str(symbol or "").strip())
    return t if re.fullmatch(r"\d{6}", t) else ""


def _envelope(ok: bool, data: Any = None, error: str = "") -> dict[str, Any]:
    """本源的出口。构造收口到 sources/envelope（P1，2026-11-09）。"""
    from sources.envelope import envelope

    return envelope(SOURCE, "fund_class", ok, data=data, error=error or None)


def _classify_ftype(ftype: str, rules: dict[str, Any]) -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    """FTYPE → (L1, L2, basis)。全文映射 → 前缀+资产段优先 → 未定。"""
    ftype = (ftype or "").strip()
    if not ftype:
        return None, None, {"L1": "FTYPE 缺失", "L2": "FTYPE 缺失"}
    full = rules.get("ftype_rules") or {}
    if ftype in full:
        entry = full[ftype] or {}
        return (entry.get("l1"), entry.get("l2"),
                {"L1": f"规则表全文映射 {ftype} → {entry.get('l1')}",
                 "L2": f"规则表全文映射 {ftype} → {entry.get('l2')}"})
    # 前缀兜底（最长前缀优先）
    l1 = None
    basis: dict[str, Any] = {}
    for prefix in sorted((rules.get("prefix_rules") or {}), key=len, reverse=True):
        if ftype.startswith(prefix):
            l1 = rules["prefix_rules"][prefix].get("l1")
            basis["L1"] = f"前缀兜底 {prefix} → {l1}（FTYPE「{ftype}」未登记规范名，L2 原样透传）"
            break
    # 资产段优先覆盖（指数型-商品 → 另类(商品)，不是权益类）
    segment = ftype.split("-", 1)[1].strip() if "-" in ftype else ""
    seg_rules = rules.get("asset_segment_rules") or {}
    for seg_key, seg_conf in seg_rules.items():
        if segment.startswith(seg_key):
            l1 = seg_conf.get("l1")
            basis["L1"] = f"资产段优先「{seg_key}」→ {l1}（覆盖前缀判定）"
            break
    if l1 is None:
        basis["L1"] = f"FTYPE「{ftype}」未登记且无前缀命中"
    return l1, ftype, basis  # L2 未登记 → 原样透传原口径


def _classify_l3(ftype: str, l1: Optional[str], name: str, rules: dict[str, Any]) -> tuple[Optional[str], str]:
    """L3 策略：不适用 → 指数族（名称细分被动/增强）→ 量化 → 默认主动管理。"""
    lr = rules.get("l3_rules") or {}
    if l1 in (lr.get("not_applicable_l1") or []):
        return "不适用", f"L1={l1} 无策略层"
    if any((ftype or "").startswith(p) for p in (lr.get("index_ftype_prefixes") or [])):
        for kw in lr.get("index_enhance_keywords") or []:
            if kw in (name or ""):
                return "指数增强", f"名称含「{kw}」"
        return "被动指数", f"FTYPE 前缀命中指数族且名称无增强关键词"
    for kw in lr.get("quant_keywords") or []:
        if kw in (name or ""):
            return "量化", f"名称含「{kw}」"
    return lr.get("default") or "主动管理", "默认：主动管理"


def _is_gushou_plus(ftype: str, traits: dict[str, Any], rules: dict[str, Any]) -> bool:
    """固收+：文章口径——债券为底仓、叠加股票或转债增强。以规则表为准。"""
    for prefix in rules.get("gushou_plus_ftype_prefixes") or []:
        if (ftype or "").startswith(prefix):
            return True
    return False


def _traits_and_tags(
    raw: dict[str, Any], ftype: str, name: str, etfcode: str, rules: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """traits 布尔组 + 辅助标签 + 申赎状态。traits 块缺失时名称关键词兜底。"""
    fc = (raw.get("expansion") or {}).get("fund_classification") or {}
    pp = fc.get("public_product") or {}
    traits = pp.get("traits") if isinstance(pp.get("traits"), dict) else {}
    restriction = pp.get("restriction") if isinstance(pp.get("restriction"), dict) else {}
    tags: dict[str, Any] = {}
    basis: dict[str, str] = {}

    fallback = rules.get("trait_name_fallback") or {}
    for key, conf in (rules.get("trait_tags") or {}).items():
        tag = conf.get("tag")
        if traits.get(key) is True:
            tags[tag] = True
            basis[tag] = "traits 布尔"
        elif any(kw in (name or "") for kw in fallback.get(key) or []):
            tags[tag] = True
            basis[tag] = f"名称关键词兜底（traits 块缺失）"
        else:
            tags[tag] = False
    tags["运作方式"] = ("ETF" if tags.get("ETF") else
                       "LOF" if tags.get("LOF") else "普通开放式")
    tags["固收+"] = _is_gushou_plus(ftype, traits, rules)
    basis["固收+"] = f"FTYPE「{ftype or '缺失'}」对照 gushou_plus_ftype_prefixes"
    if etfcode:
        tags["目标ETF"] = etfcode
    rlevel = (raw.get("data") or [{}])[0].get("RLEVEL_CX") if isinstance(raw.get("data"), list) and raw.get("data") else None
    if rlevel:
        tags["风险等级"] = rlevel
    if restriction.get("subscribe_status") or restriction.get("redeem_status"):
        tags["申赎状态"] = {"subscribe": restriction.get("subscribe_status"),
                           "redeem": restriction.get("redeem_status")}
    return tags, basis, {"traits": traits, "restriction": restriction, "market": fc.get("market") or {}}


def _name_conflicts(name: str, l1: Optional[str], rules: dict[str, Any]) -> list[dict[str, Any]]:
    """SHORTNAME 类型后缀 vs FTYPE 的 L1 交叉复核：冲突并列不裁决。"""
    ncr = rules.get("name_conflict_rules") or {}
    suffix_map = ncr.get("suffix_to_l1") or {}
    share_suffixes = ncr.get("share_suffixes") or []
    clean = (name or "").strip()
    clean = re.sub(r"[（(][^）)]*[）)]$", "", clean)  # 括号尾巴（QDII 等）
    for _ in range(2):  # 最多两级份额字母（「债券A」/「混合C」）
        if clean and clean[-1].upper() in share_suffixes:
            clean = clean[:-1]
    for suffix, l1_signal in suffix_map.items():
        if clean.endswith(suffix) and l1 and l1_signal != l1:
            return [{"kind": "名称后缀与FTYPE冲突", "name_l1": l1_signal,
                     "ftype_l1": l1,
                     "detail": f"「{name}」后缀「{suffix}」→ {l1_signal}，FTYPE 判 {l1}；两者并列，以 FTYPE 为准但请人工复核"}]
    return []


def classify(symbol: str, use_cache: bool = True) -> dict[str, Any]:
    """单基金三层分类。返回 envelope（{source, kind, ok, data, error}）。

    单请求设计：TTFUND_BASE_INFOS 一次拿齐 FTYPE/SHORTNAME/traits/申赎——
    其余源没有类型字段（P0 实测），不加请求。
    """
    from sources.ttskill import _invoke

    code = normalize_code(symbol)
    if not code:
        return _envelope(False, error="基金分类需要 6 位基金代码（名称解析先用 invest-cli fund <名称> 查代码）")
    if use_cache:
        try:
            from _common import CACHE_TTL_FUNDAMENTAL, cache_get

            hit = cache_get("fund_class", code, CACHE_TTL_FUNDAMENTAL)
        except Exception:
            hit = None
        if isinstance(hit, dict) and hit.get("ok"):
            return {**hit, "cached": True}

    rules = _load_rules()
    try:
        raw = _invoke("TTFUND_BASE_INFOS", {"fcode": code, "nav_range": "n"})
    except Exception as e:
        return _envelope(False, error=f"{ENV_HINT}: {type(e).__name__}: {e}")
    if not isinstance(raw, dict) or raw.get("success") is False:
        return _envelope(False, error=f"{ENV_HINT}: errorCode={raw.get('errorCode') if isinstance(raw, dict) else '?'}")
    data_list = raw.get("data") if isinstance(raw.get("data"), list) else []
    if not data_list:
        return _envelope(False, error=f"未找到基金「{code}」（TTFUND_BASE_INFOS 无数据）")
    d0 = data_list[0] or {}
    ftype = (d0.get("FTYPE") or "").strip()
    name = (d0.get("SHORTNAME") or "").strip()
    etfcode = (d0.get("ETFCODE") or "").strip()

    unresolved: list[str] = []
    l1, l2, l_basis = _classify_ftype(ftype, rules)
    if ftype:
        if l2 == ftype and ftype not in (rules.get("ftype_rules") or {}):
            unresolved.append(f"L2 规范名未登记（FTYPE「{ftype}」原样透传，建议补充规则表）")
    else:
        unresolved.append("FTYPE 缺失：L1/L2/L3 无法判定（traits 标签仍输出）")
    l3, l3_basis = _classify_l3(ftype, l1, name, rules) if ftype else (None, "FTYPE 缺失")

    tags, tag_basis, raw_blocks = _traits_and_tags(raw, ftype, name, etfcode, rules)
    # 名称后缀冲突检查只对境内大类生效：QDII/FOF/另类的名称后缀（「QDII-混合偏股」
    # 的「混合」）是段内注册形态，与段本身不矛盾——跑了就是误报（实测 110011）
    onshore = rules.get("name_conflict_rules", {}).get("onshore_l1_only") or []
    conflicts = _name_conflicts(name, l1, rules) if ftype and l1 in onshore else []

    data = {
        "code": code,
        "name": name,
        "type_raw": ftype,
        "type_source": "ttskill TTFUND_BASE_INFOS（天天/东财口径）",
        "classification": {"L1": l1, "L2": l2, "L3": l3},
        "tags": tags,
        "basis": {**l_basis, "L3": l3_basis, **{f"标签·{k}": v for k, v in tag_basis.items()}},
        "conflicts": conflicts,
        "unresolved": unresolved,
        "raw_blocks": raw_blocks,
    }
    res = _envelope(True, data=data)
    if use_cache:
        try:
            from _common import cache_set

            cache_set("fund_class", code, res)
        except Exception:
            pass
    return res


if __name__ == "__main__":  # 快速自检：python3 fund_classifier.py 005827
    import sys

    print(json.dumps(classify(sys.argv[1] if len(sys.argv) > 1 else "005827"),
                     ensure_ascii=False, indent=2, default=str)[:2500])
