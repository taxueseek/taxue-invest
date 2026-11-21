"""research 子命令：长程研究管线（fund-rank / etf-rank）。

用法:
    invest-cli research fund-rank <主题> [--top N] [--order r3y|r1y|ytd]
                  [--limit N] [--dy auto|on|off] [--enrich] [--out DIR] [--json]
    invest-cli research etf-rank <指数代码或名称> [--top N] [--period 1y]
                  [--components N] [--limit N] [--out DIR] [--json]

fund-rank 管线（对齐 2026-10-11 红利基金交叉分析的十轮手工调用，收敛为一条命令）：
    池构建(TTFUND_SEARCH 分页,名称子串搜索) → 份额类去重 → 批量快照
    (复用 cmd_fund.fetch_fund_with_fallback——与 `invest-cli fund` 同一条路径,
    有界并发、逐只失败隔离) → 按多期业绩排名 → 重仓×股息率交叉(公司名合并,
    A/H 同司一司) → 双源互证(hithink returns vs ttskill 深取字段,不一致显式标注)
    → 终端表 / --out 落盘(report.md + result.json) / --json 信封。

etf-rank 管线：TTFUND_INDEX_FUND_SELECTION 一次取回指数候选、同指数基金横评、
成分股与指数估值，按接口 score 排序；评分口径与 risk_note 原样透出，不在本地
重新定义。字段路径以真实回包为准，同时兼容文档写的 raw_result.body 嵌套。

设计约束：
- 本模块**只编排,不自建取数路径**：快照走 fetch_fund_with_fallback（原生体验
  同源同缓存），股息率参照集走 route.fetch("screen", …)（妙想），资讯走 argo，
  指数基金横评走 ttskill 官方业务包。
- 每个数字带 provenance（来源/口径/检索时间）；互证不一致进 warnings，不静默。
- 批量并发默认 3（INVEST_CLI_RESEARCH_CONCURRENCY 可调）。同花顺合同配额
  未知，调高前先用小池试。
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 排名键 → (envelope.returns 键, 展示名, ttskill 深取对照字段)
_ORDER_KEYS = {
    "r3y": ("tyear", "近3年", "近3年回报"),
    "r1y": ("year", "近1年", "近1年回报"),
    "ytd": ("nowyear", "今年来", "今年来回报"),
}
# 互证覆盖的全部期数（不只排序键）：returns 键 → 深取字段名
_VERIFY_PAIRS = {
    "year": "近1年回报", "twoyear": "近2年回报", "tyear": "近3年回报", "fyear": "近5年回报",
}
_VERIFY_EPS = 0.05  # 百分数口径，两位小数来源，容差 0.05 个百分点

# 通用修饰词提炼复用 intent 层同一份词表（SearchFunds 是名称子串搜索）
from cmd_intent import _fund_search_keyword  # noqa: E402


def _conc() -> int:
    raw = ""
    try:
        import os
        raw = os.environ.get("INVEST_CLI_RESEARCH_CONCURRENCY", "").strip()
    except Exception:
        pass
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, min(n, 8))


# ── 1. 池构建 ──────────────────────────────────────────────

def _alias_queries(keyword: str) -> list[str]:
    """主关键词之外补一个「股息」别名检索：红利主题的高股息基金名字里常只有
    「股息」二字（实测 格林高股息/南方高股息 均只被别名检索命中）。"""
    if any(w in keyword for w in ("红利", "股息")) and keyword != "股息":
        return [keyword, "股息"]
    return [keyword]


def build_pool(theme: str, limit: int, *, exclude_hk: bool) -> tuple[list[dict], list[str], bool]:
    """返回 (pool, notes, partial)。pool 元素 = {"code","name","category"}。

    partial=True 表示检索页失败或池被截断——宇宙不完整，必须让调用方看见。
    """
    from sources import ttskill as tts_src

    notes: list[str] = []
    keyword = _fund_search_keyword(theme)
    if not keyword:
        return [], ["主题提炼为空"], True
    queries = _alias_queries(keyword)
    if len(queries) > 1:
        notes.append("别名检索「股息」已并入（红利主题基金名常只含「股息」）")

    stop = re.compile(rf"改革{keyword}|混改{keyword}") if keyword else None
    excl_cat = re.compile(r"指数|货币|理财|QDII|债券")
    excl_name_offshore = re.compile(r"亚洲|亚太|美元|对冲|累算|派息")
    excl_name_hk = re.compile(r"港股通|沪港深|港股")

    seen: dict[str, dict] = {}
    total_seen = 0
    raw_cap = max(800, limit * 4)  # 过滤/去重后约 15-30% 保留率：池上限要放大成原始候选上限
    partial = False
    for q in queries:
        page, raw_for_q = 1, 0
        while True:
            # 页级重试：天天网关偶发 504/超时（实测 2026-10-11）。检索失败若直接
            # 放弃该词，池会被**静默截断**——研究宇宙不完整比慢更伤精度。
            res, last_err = None, ""
            for attempt in range(3):
                res = tts_src.search_funds(q, page_index=page, page_size=50)
                if res.get("ok"):
                    break
                last_err = res.get("error") or ""
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
            if not res.get("ok"):
                notes.append(f"检索「{q}」第{page}页重试后仍失败：{last_err}（池不完整）")
                partial = True
                break
            data = res.get("data") or {}
            cands = data.get("candidates") or []
            total_seen += len(cands)
            raw_for_q += len(cands)
            if not cands:
                break
            for c in cands:
                code = str(c.get("display_code") or c.get("code") or "")
                name, cat = c.get("name") or "", c.get("category_name") or ""
                if not code.isdigit() or code in seen:
                    continue
                if q != keyword and not any(w in name for w in queries):
                    continue  # 别名检索只收与主题词相关的（股息检索天然全相关）
                if excl_cat.search(cat):
                    continue
                if stop and stop.search(name):
                    continue  # 「改革红利/混改红利」是改革主题，非股息策略
                if excl_name_offshore.search(name):
                    continue  # 离岸注册互认基金（亚洲股息等），口径不同
                if exclude_hk and excl_name_hk.search(name):
                    continue  # 港股通主题：重仓在港股，A 股股息参照集不适用
                seen[code] = {"code": code, "name": name, "category": cat}
            total_count = data.get("total_count")
            try:
                exhausted = page * 50 >= int(total_count)
            except (TypeError, ValueError):
                exhausted = len(cands) < 50
            if exhausted or raw_for_q >= raw_cap:
                if raw_for_q >= raw_cap and not exhausted:
                    notes.append(f"「{q}」原始候选达安全上限 {raw_cap}，截断")
                break
            page += 1

    pool = _dedupe_share_classes(list(seen.values()))
    if len(pool) > limit:
        notes.append(f"池 {len(pool)} 只超出上限，截断到 {limit}（可用 --limit 调整）")
        pool = pool[:limit]
        partial = True
    notes.append(f"检索原始候选 {total_seen} 条 → 过滤后 {len(pool)} 只（关键词「{keyword}」）")
    return pool, notes, partial


def _dedupe_share_classes(pool: list[dict]) -> list[dict]:
    """A/C/(后端)/D/E 同基金共享类去重：优先 A 类 > 无后缀 > 名字短者。"""
    groups: dict[str, list[dict]] = {}
    for f in pool:
        base = re.sub(r"[(（]后端[)）]$", "", f["name"]).strip()
        base = re.sub(r"[ABCDE]$", "", base).strip()
        groups.setdefault(base, []).append(f)

    out = []
    for base, members in groups.items():
        members.sort(key=lambda f: (not f["name"].endswith("A"), len(f["name"]), f["code"]))
        out.append(members[0])
    out.sort(key=lambda f: f["code"])
    return out


# ── 2. 批量快照（复用 invest-cli fund 同一条路径） ─────────

def snapshot_batch(codes: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """逐只 fetch_fund_with_fallback，有界并发，单只失败不影响整批。"""
    from cmd_fund import fetch_fund_with_fallback

    snaps: dict[str, dict] = {}
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=_conc()) as ex:
        futs = {ex.submit(fetch_fund_with_fallback, c): c for c in codes}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                env = fut.result()
            except Exception as e:
                failures.append({"code": code, "error": f"{type(e).__name__}: {e}"})
                continue
            if not env or not env.get("name"):
                failures.append({"code": code, "error": "空信封"})
                continue
            snaps[code] = env
    return snaps, failures


# ── 3. 排名与互证 ─────────────────────────────────────────

def _rkey(env: dict, order: str) -> float | None:
    v = (env.get("returns") or {}).get(_ORDER_KEYS[order][0])
    return v if isinstance(v, (int, float)) else None


def rank_funds(snaps: dict[str, dict], order: str,
               full_names: dict[str, str] | None = None) -> tuple[list[dict], list[str]]:
    """返回 (ranked rows, 缺排序键的代码)。returns 已是百分数（1.3 = 1.3%）。

    full_names：池构建侧的全名映射——快照信封的 name 是短名（"红利A"，
    多基金会撞名），展示与落盘一律用全名。
    """
    _, _, deep_field = _ORDER_KEYS[order]
    rows, missing = [], []
    for code, env in snaps.items():
        v = _rkey(env, order)
        if v is None:
            missing.append(code)
            continue
        rows.append({
            "code": code,
            "name": (full_names or {}).get(code) or env.get("name"),
            "source": env.get("source"),
            "deep_source": env.get("deep_source"),
            "cached": bool(env.get("cached")),
            "scale_yi": round(((env.get("profile") or {}).get("fund_scale") or 0) / 1e8, 2),
            "returns": {k: (env.get("returns") or {}).get(k)
                        for k in ("year", "twoyear", "tyear", "fyear", "nowyear")},
            "verify": verify_dual_source(env),
            "holdings": _holdings(env),
        })
    rows.sort(key=lambda r: -r["returns"][_ORDER_KEYS[order][0]])
    return rows, sorted(missing)


def _holdings(env: dict) -> dict[str, dict]:
    """重仓 → {股票名: {"ratio": 占净值%, "code": ticker}}。"""
    out = {}
    for h in env.get("holdings") or []:
        name = h.get("stock_name") or h.get("entityName")
        ratio = h.get("hold_ratio")
        if name and isinstance(ratio, (int, float)) and ratio > 0:
            out[name] = {"ratio": ratio, "code": h.get("ticker") or ""}
    return out


def verify_dual_source(env: dict) -> dict:
    """hithink returns vs ttskill 深取字段互证（两个独立上游，单位均为百分数）。

    快照主源本身来自 ttskill 或深取缺失时无法互证 → verified=None（如实报）。
    """
    if env.get("deep_source") != "ttskill" or env.get("source") == "ttskill":
        return {"verified": None, "detail": "深取缺失，无法互证"}
    data = env.get("data") or {}
    ret = env.get("returns") or {}
    ok, bad = 0, []
    for rk, dk in _VERIFY_PAIRS.items():
        a, b = ret.get(rk), data.get(dk)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) <= _VERIFY_EPS:
                ok += 1
            else:
                bad.append(f"{dk}: {a} vs {b}")
    if bad:
        return {"verified": False, "detail": f"不一致→{'; '.join(bad)}"}
    return {"verified": True, "detail": f"一致 {ok} 项"} if ok else {"verified": None, "detail": "无可对照字段"}


# ── 4. 股息率参照集与交叉 ─────────────────────────────────

def dy_universe() -> tuple[dict[str, dict], str]:
    """妙想「股息率≥4%」参照集 → {代码: {"name","dy","price"}}。"""
    from sources.route import fetch

    res = fetch("screen", "股息率大于4%的A股，按股息率从高到低排序")
    if not res.get("ok"):
        return {}, f"参照集取数失败：{res.get('error')}"
    tables = (res.get("data") or {}).get("data") or []
    if not tables or not isinstance(tables, list):
        return {}, "参照集回包无结果表"
    t = tables[0]
    cols = [str(c) for c in (t.get("columns") or [])]
    try:
        i_code = next(i for i, c in enumerate(cols) if c == "代码")
        i_name = next(i for i, c in enumerate(cols) if c == "名称")
        i_dy = next(i for i, c in enumerate(cols) if "股息率" in c)
    except StopIteration:
        return {}, "参照集列名不含 代码/名称/股息率"
    out = {}
    for row in t.get("items") or []:
        try:
            out[str(row[i_code])] = {"name": str(row[i_name]), "dy": float(row[i_dy])}
        except (ValueError, IndexError, TypeError):
            continue
    return out, f"妙想年度股息率(2025.12.31口径)≥4% 参照集，{len(out)} 只"


def _is_hk(code: str) -> bool:
    return bool(re.fullmatch(r"\d{5}", code or "") or (code or "").upper().endswith(".HK"))


def cross_holdings(ranked: list[dict], top_n: int, dy: dict[str, dict], dy_on: bool) -> dict:
    """Top-N 重仓标注 + 全池高股息共识（按公司名合并，A/H 同司一司）。"""
    def label(name: str, code: str) -> str:
        if not dy_on:
            return "-"
        u = dy.get(code)
        if u:
            return f"{u['dy']:.2f}%"
        if _is_hk(code):
            return "港股·集外"
        return "<4%"

    top_holdings = []
    for r in ranked[:top_n]:
        items = sorted(r["holdings"].items(), key=lambda kv: -kv[1]["ratio"])[:10]
        top_holdings.append({
            "fund": f"{r['name']}（{r['code']}）",
            "holdings": [{"name": nm, "ratio": h["ratio"], "dy": label(nm, h["code"])}
                         for nm, h in items],
        })

    # 全池共识：公司名合并（同司 A/H 一司），A股代码优先用于股息率归因
    merged: dict[str, dict] = {}
    for r in ranked:
        for nm, h in r["holdings"].items():
            m = merged.setdefault(nm, {"name": nm, "a_code": "", "has_hk": False, "n": 0})
            if _is_hk(h["code"]):
                m["has_hk"] = True
            else:
                m["a_code"] = m["a_code"] or h["code"]
            m["n"] += 1
    consensus = []
    for m in merged.values():
        u = dy.get(m["a_code"]) if m["a_code"] else None
        consensus.append({
            "name": m["name"], "fund_n": m["n"], "has_hk": m["has_hk"],
            "dy": u["dy"] if u else None,
        })
    consensus.sort(key=lambda x: (-x["fund_n"], -(x["dy"] or 0)))
    hi = [c for c in consensus if c["dy"] is not None and c["dy"] >= 4 and c["fund_n"] >= 3]
    mismatched = [c for c in consensus if c["fund_n"] >= 4 and not (c["dy"] or 0) >= 4]
    return {
        "top_holdings": top_holdings,
        "consensus_high_dy": hi,
        "consensus_mismatched": mismatched if dy_on else [],
    }


# ── 5. 富化（argo 资讯，默认关） ───────────────────────────

def enrich_news(ranked: list[dict], top_n: int) -> tuple[list[dict], list[str]]:
    """Top-N 每只基金一条 argo 资讯检索。失败降级为 note，不阻断。

    引擎沿用 `invest-cli info` 的默认（eastmoney）——仓内财经检索的既定惯例。
    """
    from sources import argo as argo_src

    out, notes = [], []
    for r in ranked[:top_n]:
        res = argo_src.search(f"{r['name']} 红利", engine="eastmoney", limit=5)
        if not res.get("ok"):
            notes.append(f"{r['name']} 资讯检索失败：{res.get('error')}")
            continue
        # argo 回包键是 results（实测 2026-10-11；items 是防上游换形的兜底）
        data = res.get("data") or {}
        items = data.get("results") if isinstance(data, dict) else None
        if items is None and isinstance(data, list):
            items = data
        heads = []
        for it in (items or [])[:5]:
            if isinstance(it, dict):
                heads.append({k: it.get(k) for k in ("title", "url", "date", "published_at") if it.get(k)})
        out.append({"fund": r["name"], "engine": data.get("engine", "default")
                    if isinstance(data, dict) else "default", "items": heads})
    return out, notes


# ── 5b. 指数基金横评（TTFUND_INDEX_FUND_SELECTION） ───────

# 周期别名 → 接口 period_code（skill 文档：00近1月 / 01近3月 / 02近半年 /
# 03近1年 / 05近3年 / 06近5年）。用可读别名，避免调用方记两位码。
_ETF_PERIODS = {"1m": "00", "3m": "01", "6m": "02", "1y": "03", "3y": "05", "5y": "06"}
_ETF_PERIOD_LABELS = {"00": "近1月", "01": "近3月", "02": "近半年",
                      "03": "近1年", "05": "近3年", "06": "近5年"}
_ETF_SMALL_SCALE_YI = 2.0


def _fnum(v) -> float | None:
    """数值字段归一：非数字返回 None（接口用 null 表示缺失，不能当 0）。"""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _f1(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "-"


def _f2(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "-"


def _etf_request(theme: str, period_code: str, components: int) -> dict:
    """指数代码走 index_codes，名称/关键词走 keyword；top_n 是**成分股**条数。"""
    body: dict = {"period_codes": [period_code],
                  "top_n": max(1, min(int(components), 50))}
    if re.fullmatch(r"\d{6}", theme):
        body["index_codes"] = [theme]
    else:
        body["keyword"] = theme
    return body


def _selection_of(data) -> dict:
    """取 selection_result；兼容文档写的 data.raw_result.body 与实际 data 直挂。"""
    if not isinstance(data, dict):
        raise ValueError("回包缺少 data")
    node = data
    raw = node.get("raw_result")
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict):
        node = raw["body"]
    sr = node.get("selection_result")
    if not isinstance(sr, dict):
        raise ValueError("回包缺少 selection_result（ttskill 版本可能已变）")
    return sr


def _parse_etf(sr: dict) -> dict:
    """解析横评结果。结构缺失就报错，不返回空表——空表会被误读成「没有基金」。"""
    body = sr.get("data")
    if not isinstance(body, dict):
        raise ValueError(f"selection_result 缺少 data（{sr.get('code')}: {sr.get('message')}）")
    raw_funds = body.get("fund_items")
    if not isinstance(raw_funds, list) or not raw_funds:
        raise ValueError(f"回包 fund_items 为空（{sr.get('code')}: {sr.get('message')}）")

    funds = []
    for it in raw_funds:
        if not isinstance(it, dict) or not it.get("fund_code"):
            continue
        funds.append({
            "code": str(it.get("fund_code")),
            "name": str(it.get("fund_name") or ""),
            "company": str(it.get("fund_company") or ""),
            "scale_yi": _fnum(it.get("fund_size_yi")),
            "management_fee": _fnum(it.get("management_fee")),
            "custodian_fee": _fnum(it.get("custodian_fee")),
            "total_fee": _fnum(it.get("total_fee")),
            "tracking_error": _fnum(it.get("tracking_error")),
            "excess_return": _fnum(it.get("excess_return")),
            "information_ratio": _fnum(it.get("information_ratio")),
            "correlation": _fnum(it.get("correlation")),
            "score": _fnum(it.get("score")),
            "risk_note": str(it.get("risk_note") or ""),
            "metric_date": str(it.get("metric_date") or ""),
        })
    if not funds:
        raise ValueError("fund_items 里没有可用的基金代码")
    funds.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0),
                              -(r["scale_yi"] or 0.0), r["code"]))

    first = raw_funds[0] if isinstance(raw_funds[0], dict) else {}
    cands = [{"code": str(c.get("index_code") or ""),
              "name": str(c.get("index_name") or ""),
              "fund_count": c.get("fund_count")}
             for c in (body.get("index_candidates") or []) if isinstance(c, dict)]

    raw_comps = [c for c in (body.get("component_items") or []) if isinstance(c, dict)]
    comps = [{"code": str(c.get("stock_code") or ""),
              "name": str(c.get("stock_name") or ""),
              "weight_pct": _fnum(c.get("weight_pct"))} for c in raw_comps]
    comp0 = raw_comps[0] if raw_comps else {}
    comp_meta = {
        "trade_date": str(comp0.get("component_trade_date") or ""),
        "count": comp0.get("component_count"),
        "top10_weight_pct": _fnum(comp0.get("top10_weight_pct")),
    }

    raw_val = next((v for v in (body.get("valuation_items") or [])
                    if isinstance(v, dict)), None)
    valuation = None
    if raw_val:
        valuation = {k: raw_val.get(k) for k in (
            "trade_date", "pe_ttm", "pb", "roe_pct",
            "pe_percentile_3y", "pe_percentile_5y", "pe_percentile_10y",
            "pb_percentile_3y", "pb_percentile_5y", "pb_percentile_10y",
            "valuation_level", "quadrant", "note")}

    return {
        "index_code": str(first.get("index_code") or ""),
        "index_name": str(first.get("index_name") or ""),
        "funds": funds,
        "candidates": cands,
        "components": comps,
        "component_meta": comp_meta,
        "valuation": valuation,
        "score_note": str(body.get("score_note") or ""),
    }


def _run_etf(theme: str, *, top: int, period: str, limit: int, components: int,
             out: str, as_json: bool) -> int:
    theme = (theme or "").strip()
    if not theme:
        print("research etf-rank 错误: 需要指数代码或名称（如 000300 / 沪深300）",
              file=sys.stderr)
        return 1
    period_code = _ETF_PERIODS.get(period)
    if not period_code:
        print(f"research etf-rank 错误: --period 仅支持 {'/'.join(_ETF_PERIODS)}",
              file=sys.stderr)
        return 1
    if top < 1 or limit < 1:
        print("research etf-rank 错误: --top / --limit 必须为正整数", file=sys.stderr)
        return 1

    from sources.ttskill import invoke_scene

    raw = invoke_scene("TTFUND_INDEX_FUND_SELECTION",
                       _etf_request(theme, period_code, components))
    if not raw.get("ok"):
        print(f"research etf-rank 失败：{raw.get('error')}", file=sys.stderr)
        return 1
    try:
        parsed = _parse_etf(_selection_of(raw.get("data")))
    except ValueError as e:
        print(f"research etf-rank 失败：{e}", file=sys.stderr)
        return 1

    returned = parsed["funds"][:limit]
    for i, row in enumerate(returned, 1):
        row["rank"] = i
    result = {
        "source": "research", "scene": "etf-rank", "index": theme,
        "index_code": parsed["index_code"],
        "index_name": parsed["index_name"] or theme,
        "period": period, "period_code": period_code,
        "period_label": _ETF_PERIOD_LABELS[period_code],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top": top,
        "provenance": {
            "data_path": "ttskill:TTFUND_INDEX_FUND_SELECTION → selection_result.data",
            "score_note": parsed["score_note"],
            "score_basis": "接口 score：跟踪误差45% / 规模30% / 费率25%，未含成交额",
            "risk_note_rule": "risk_note 非空原样展示；规模<2亿单独汇总",
            "small_scale_threshold_yi": _ETF_SMALL_SCALE_YI,
        },
        "fund_count": len(parsed["funds"]),
        "returned": len(returned),
        "truncated": len(parsed["funds"]) > len(returned),
        "small_scale": [{"code": f["code"], "name": f["name"], "scale_yi": f["scale_yi"]}
                        for f in parsed["funds"]
                        if f["scale_yi"] is not None and f["scale_yi"] < _ETF_SMALL_SCALE_YI],
        "index_candidates": parsed["candidates"],
        "funds": returned,
        "component_meta": parsed["component_meta"],
        "components": parsed["components"],
        "valuation": parsed["valuation"],
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_etf_terminal(result)
    if out:
        _write_etf_out(Path(out), result)
        print(f"产物已落盘 {out}/（report.md + result.json）", file=sys.stderr)
    return 0


def _print_etf_terminal(result: dict) -> None:
    trunc = "（已截断，--limit 可调）" if result["truncated"] else ""
    shown = min(result["top"], result["returned"])
    print(f"\n✅ {result['index_name']}（{result['index_code'] or result['index']}）"
          f"指数基金横评｜周期 {result['period_label']}｜"
          f"{result['fund_count']} 只，展示前 {shown}{trunc}")
    note = result["provenance"]["score_note"]
    if note:
        print(f"   评分口径：{note}")
    print(f"\n  {'排名':<6}{'代码':<8}{'名称':<24}{'规模亿':>8}"
          f"{'跟踪误差':>9}{'总费率%':>8}{'得分':>7}")
    print("  " + "-" * 74)
    for r in result["funds"][:result["top"]]:
        print(f"  {r['rank']:<6}{r['code']:<8}{r['name']:<24}"
              f"{_f1(r['scale_yi']):>8}{_f2(r['tracking_error']):>9}"
              f"{_f2(r['total_fee']):>8}{_f1(r['score']):>7}")

    v = result["valuation"]
    if v:
        bits = []
        if v.get("pe_ttm") is not None:
            bits.append(f"PE-TTM {_f2(v['pe_ttm'])}"
                        + (f"（5年分位 {_f1(v.get('pe_percentile_5y'))}%）"
                           if v.get("pe_percentile_5y") is not None else ""))
        if v.get("pb") is not None:
            bits.append(f"PB {_f2(v['pb'])}"
                        + (f"（5年分位 {_f1(v.get('pb_percentile_5y'))}%）"
                           if v.get("pb_percentile_5y") is not None else ""))
        if v.get("valuation_level"):
            bits.append(str(v["valuation_level"]))
        if v.get("quadrant"):
            bits.append(str(v["quadrant"]))
        if bits:
            print("\n  指数估值（辅助，不是买卖信号）：" + "｜".join(bits))

    comps = result["components"]
    if comps:
        meta = result["component_meta"]
        print(f"\n  前{len(comps)}大成分（{meta.get('trade_date') or '-'}，"
              f"共 {meta.get('count') if meta.get('count') is not None else '-'} 只，"
              f"前十集中度 {_f2(meta.get('top10_weight_pct'))}%）")
        print("     " + "、".join(f"{c['name']}{_f2(c['weight_pct'])}%" for c in comps))

    risky = [r for r in result["funds"][:result["top"]] if r["risk_note"]]
    if risky:
        print("\n  ⚠ 风险提示：")
        for r in risky:
            print(f"     {r['name']}（{r['code']}）：{r['risk_note']}")

    small = result["small_scale"]
    if small:
        shown = "、".join(f"{x['name']}({x['code']})" for x in small[:8])
        more = f" 等 {len(small)} 只" if len(small) > 8 else ""
        print(f"\n  ⚠ 规模<{_ETF_SMALL_SCALE_YI:g}亿（清盘风险）：{shown}{more}")


def _write_etf_out(out_dir: Path, result: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    v = result["valuation"] or {}
    lines = [
        f"# 指数基金横评：{result['index_name']}（{result['index_code'] or result['index']}）",
        "",
        f"> 生成于 {result['generated_at']}｜周期 {result['period_label']}｜"
        f"基金 {result['fund_count']} 只，列出前 {result['returned']}",
        f"> 数据路径：{result['provenance']['data_path']}",
        f"> 评分口径：{result['provenance']['score_basis']}",
    ]
    if result["provenance"]["score_note"]:
        lines.append(f"> 接口说明：{result['provenance']['score_note']}")
    lines += ["", "## 横评", "",
              "| 排名 | 代码 | 名称 | 规模(亿) | 跟踪误差 | 总费率% | 得分 | 风险提示 |",
              "|---|---|---|---|---|---|---|---|"]
    for r in result["funds"]:
        lines.append(f"| {r['rank']} | {r['code']} | {r['name']} | {_f1(r['scale_yi'])} | "
                     f"{_f2(r['tracking_error'])} | {_f2(r['total_fee'])} | "
                     f"{_f1(r['score'])} | {r['risk_note'] or ''} |")
    if result["components"]:
        m = result["component_meta"]
        lines += ["", "## 成分与估值", "",
                  f"- 成分日期：{m.get('trade_date') or '-'}；成分数："
                  f"{m.get('count') if m.get('count') is not None else '-'}；"
                  f"前十集中度：{_f2(m.get('top10_weight_pct'))}%",
                  f"- 前十大成分：" + "、".join(
                      f"{c['name']} {_f2(c['weight_pct'])}%" for c in result["components"]),
                  f"- 指数估值：PE-TTM {_f2(v.get('pe_ttm'))}"
                  f"（5年分位 {_f1(v.get('pe_percentile_5y'))}%）；"
                  f"PB {_f2(v.get('pb'))}（5年分位 {_f1(v.get('pb_percentile_5y'))}%）；"
                  f"{v.get('valuation_level') or '-'}；{v.get('quadrant') or '-'}"]
    if result["small_scale"]:
        lines += ["", f"## 规模<{_ETF_SMALL_SCALE_YI:g}亿（清盘风险）", ""]
        lines += [f"- {x['name']}（{x['code']}）：{_f1(x['scale_yi'])} 亿"
                  for x in result["small_scale"]]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 6. 入口 ───────────────────────────────────────────────

def run(scene: str, theme: str, top: int = 8, order: str = "r3y", limit: int = 200,
        dy_mode: str = "auto", enrich: bool = False, out: str = "", as_json: bool = False,
        period: str = "1y", components: int = 10) -> int:
    t0 = datetime.now()
    if scene == "etf-rank":
        return _run_etf(theme, top=top, period=period, limit=limit,
                        components=components, out=out, as_json=as_json)
    if scene != "fund-rank":
        print(f"research 错误: 未知场景 {scene}（支持 fund-rank / etf-rank）", file=sys.stderr)
        return 1
    if order not in _ORDER_KEYS:
        print(f"research 错误: --order 仅支持 {'/'.join(_ORDER_KEYS)}", file=sys.stderr)
        return 1

    dy_on = (dy_mode == "on") or (dy_mode == "auto" and any(w in theme for w in ("红利", "股息")))
    pool, notes, pool_partial = build_pool(theme, limit, exclude_hk=dy_on)
    if not pool:
        print(f"research 失败：主题「{theme}」未筛出任何主动基金（{'; '.join(notes)}）", file=sys.stderr)
        return 1

    print(f"[1/4] 池构建完成：{len(pool)} 只（{'; '.join(notes)}）", file=sys.stderr)
    if pool_partial:
        print("⚠ 池不完整（检索页失败/截断）——排名只覆盖检索到的部分，结论勿当全量", file=sys.stderr)
    snaps, failures = snapshot_batch([f["code"] for f in pool])
    n_cached = sum(1 for s in snaps.values() if s.get("cached"))
    print(f"[2/4] 批量快照完成：{len(snaps)} 成功 / {len(failures)} 失败 / {n_cached} 命中缓存", file=sys.stderr)
    if not snaps:
        print("research 失败：全部快照失败", file=sys.stderr)
        return 1

    ranked, missing = rank_funds(snaps, order, full_names={f["code"]: f["name"] for f in pool})
    dy, dy_note = ({}, "关闭") if not dy_on else dy_universe()
    cross = cross_holdings(ranked, top, dy, dy_on)
    print(f"[3/4] 排名与交叉完成：排序键 {order}，缺键 {len(missing)} 只；{dy_note}", file=sys.stderr)

    enrich_rows, enrich_notes = ([], []) if not enrich else enrich_news(ranked, top)

    result = {
        "source": "research", "scene": "fund-rank", "theme": theme,
        "generated_at": t0.isoformat(timespec="seconds"),
        "order": order, "top": top,
        "provenance": {
            "snapshot_path": "cmd_fund.fetch_fund_with_fallback（同 invest-cli fund，缓存共享）",
            "returns_unit": "百分数（hithink 口径，1.3 = 1.3%）",
            "holdings_basis": "各基金最新披露报告期十大重仓",
            "dy_basis": dy_note if dy_on else "未启用（非股息主题）",
            "verify_rule": f"hithink returns vs ttskill 深取字段，容差 {_VERIFY_EPS}pp",
            "concurrency": _conc(), "cached_hits": n_cached,
            "pool_complete": not pool_partial,
        },
        "pool_notes": notes, "failures": failures, "missing_order_key": missing,
        "pool_size": len(pool), "ranked_size": len(ranked),
        "ranked": ranked, "cross": cross, "enrich": enrich_rows,
        "verify_summary": {
            "ok": sum(1 for r in ranked if r["verify"]["verified"] is True),
            "bad": [r["code"] for r in ranked if r["verify"]["verified"] is False],
            "na": sum(1 for r in ranked if r["verify"]["verified"] is None),
        },
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_terminal(result)

    if out:
        _write_out(Path(out), result)
        print(f"[4/4] 产物已落盘 {out}/（report.md + result.json）", file=sys.stderr)
    return 0


def _fmt(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "-"


def _print_terminal(result: dict) -> None:
    order_name = _ORDER_KEYS[result["order"]][1]
    completeness = "" if result["provenance"]["pool_complete"] else "  ⚠ 池不完整"
    print(f"\n✅ 主题「{result['theme']}」主动基金排名（按{order_name}回报，单位%）{completeness}")
    print(f"   排名 {result['ranked_size']} / 池 {result['pool_size']} 只"
          f"（缺排序键 {len(result['missing_order_key'])}，快照失败 {len(result['failures'])}）"
          f"｜与 invest-cli fund 同路径同缓存｜检索于 {result['generated_at']}\n")
    print(f"  {'代码':<8}{'名称':<26}{'规模亿':>7}{order_name + '%':>8}{'近1年%':>8}{'互证':>10}")
    print("  " + "-" * 72)
    for r in result["ranked"][:result["top"]]:
        v = r["verify"]
        vs = "✓" if v["verified"] is True else ("✗ " + v["detail"][:8] if v["verified"] is False else "-")
        print(f"  {r['code']:<8}{r['name']:<26}{r['scale_yi']:>7}"
              f"{_fmt(r['returns'].get(_ORDER_KEYS[result['order']][0])):>8}"
              f"{_fmt(r['returns'].get('year')):>8}{vs:>10}")

    for th in result["cross"]["top_holdings"]:
        print(f"\n  ▍{th['fund']} 重仓 × 股息率")
        for h in th["holdings"][:8]:
            print(f"     {h['name']:<10}{h['ratio']:>6.2f}%   股息率 {h['dy']}")

    if result["cross"]["consensus_high_dy"]:
        print(f"\n  ▍高股息机构共识（≥3 基金重仓 ∧ 股息率≥4%）")
        for c in result["cross"]["consensus_high_dy"][:15]:
            hk = "（含H）" if c["has_hk"] else ""
            print(f"     {c['name']:<10}{hk:<5}{c['dy']:>6.2f}%   基金×{c['fund_n']}")
    if result["cross"]["consensus_mismatched"]:
        print(f"\n  ▍被重仓但股息率<4%（「红利」名不副实仓位）")
        for c in result["cross"]["consensus_mismatched"][:8]:
            print(f"     {c['name']:<10}   基金×{c['fund_n']}")

    if result["failures"]:
        print(f"\n  ⚠ 快照失败 {len(result['failures'])} 只："
              + "、".join(f["code"] for f in result["failures"][:10]), file=sys.stderr)
    bad = result["verify_summary"]["bad"]
    if bad:
        print(f"  ⚠ 双源互证不一致：{'、'.join(bad)}", file=sys.stderr)


def _write_out(out_dir: Path, result: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    order_name = _ORDER_KEYS[result["order"]][1]
    lines = [
        f"# 主动基金排名研究：{result['theme']}",
        "",
        f"> 生成于 {result['generated_at']}｜排序键 {order_name}｜"
        f"快照路径 {result['provenance']['snapshot_path']}",
        f"> 池完整性：{'完整' if result['provenance']['pool_complete'] else '**部分（检索页失败/截断，结论勿当全量）**'}",
        f"> 口径：{result['provenance']['returns_unit']}；"
        f"{result['provenance']['holdings_basis']}；{result['provenance']['dy_basis']}",
        f"> 互证：{result['provenance']['verify_rule']}；"
        f"一致 {result['verify_summary']['ok']}，不一致 {len(result['verify_summary']['bad'])}，"
        f"无法互证 {result['verify_summary']['na']}",
        f"> 池备注：{'；'.join(result['pool_notes'])}",
        "",
        "## 排名",
        "",
        "| 代码 | 名称 | 规模(亿) | 近1年% | 近3年% | 互证 |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["ranked"]:
        v = r["verify"]
        vs = "✓" if v["verified"] is True else ("✗ " + v["detail"] if v["verified"] is False else "-")
        lines.append(f"| {r['code']} | {r['name']} | {r['scale_yi']} | "
                     f"{_fmt(r['returns'].get('year'))} | {_fmt(r['returns'].get('tyear'))} | {vs} |")
    lines += ["", "## Top 重仓 × 股息率", ""]
    for th in result["cross"]["top_holdings"]:
        lines.append(f"**{th['fund']}**")
        lines.append("")
        lines.append("| 股票 | 占净值% | 股息率 |")
        lines.append("|---|---|---|")
        for h in th["holdings"]:
            lines.append(f"| {h['name']} | {h['ratio']:.2f} | {h['dy']} |")
        lines.append("")
    if result["cross"]["consensus_high_dy"]:
        lines += ["## 高股息机构共识（≥3 基金 ∧ ≥4%）", "",
                  "| 股票 | 股息率% | 基金数 | 含H |", "|---|---|---|---|"]
        for c in result["cross"]["consensus_high_dy"]:
            lines.append(f"| {c['name']} | {c['dy']:.2f} | {c['fund_n']} | {'是' if c['has_hk'] else ''} |")
        lines.append("")
    if result["failures"]:
        lines += ["## 快照失败", ""] + [f"- {f['code']}: {f['error']}" for f in result["failures"]]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], sys.argv[2]))
