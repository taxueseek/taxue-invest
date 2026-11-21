"""SEC EDGAR 美股财报适配器（免费、无 key，SEC 官方 XBRL API）。

定位：美股财报「原文级」数据源，与 Wind / yfinance 的结构化数字交叉验证。
数据通道（全部官方公开，无需注册）：
  - company_tickers.json  ticker → CIK 映射（全市场，磁盘缓存 7 天）
  - companyfacts          单公司全量 XBRL 事实（缓存 24h；AAPL 约 3.7MB）
  - submissions           最近申报清单（缓存 6h）

口径：年报只取 form=10-K + fp=FY；时长型事实（利润表/现金流）要求
start~end 跨度 300~400 天，避免误取季度值；时点型事实（资产/权益）取最近 end。
标签存在漂移（如 Apple 的 Revenues 标签停在 2018 财年），按 METRIC_TAGS
的优先级列表逐级回退，取「优先级最高且存在」的标签。

SEC 要求 User-Agent 声明调用方身份：www.sec.gov 域强制 UA 含邮箱，否则 403
（data.sec.gov 不校验）。默认 UA 用占位邮箱通过校验，建议用 SEC_EDGAR_USER_AGENT
覆盖为真实联系方式（形如 "your-name your@email"）。
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ._http import guarded_open
from ._sec_forms import (
    _BUY_CODES as _BUY_CODES,
    _SELL_CODES as _SELL_CODES,
    _TRANSACTION_LABELS as _TRANSACTION_LABELS,
    _direction as _direction,
    _is_info_table as _is_info_table,
    _parse_13f_table as _parse_13f_table,
    _parse_form4 as _parse_form4,
    _strip_ns as _strip_ns,
    _text as _text,
    _to_number as _to_number,
)
from ._sec_xbrl import (
    ANNUAL_MAX_DAYS as ANNUAL_MAX_DAYS,
    ANNUAL_MIN_DAYS as ANNUAL_MIN_DAYS,
    DEI_TAGS as DEI_TAGS,
    DERIVED_METRICS as DERIVED_METRICS,
    METRIC_LABELS as METRIC_LABELS,
    METRIC_TAGS as METRIC_TAGS,
    QUARTER_MAX_DAYS as QUARTER_MAX_DAYS,
    QUARTER_MIN_DAYS as QUARTER_MIN_DAYS,
    _annual_rows as _annual_rows,
    _apply_derived as _apply_derived,
    _apply_derived_series as _apply_derived_series,
    _dei_metrics as _dei_metrics,
    _quarterly_flow as _quarterly_flow,
    _quarterly_instant as _quarterly_instant,
    _span_days as _span_days,
    _unit_of as _unit_of,
    extract_annual as extract_annual,
    extract_quarterly as extract_quarterly,
    extract_series as extract_series,
)

SOURCE_LABEL = "SEC EDGAR 美股财报"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{doc}"
BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"

ENV_UA = "SEC_EDGAR_USER_AGENT"
# www.sec.gov 要求 UA 含邮箱；example.com 为占位域，建议用环境变量覆盖为真实联系方式
DEFAULT_UA = "invest-cli/0.1 personal-research (contact: user@example.com)"
DEFAULT_TIMEOUT = 30
RETRIES = 3
# 形如 ticker 的输入（用于决定「按代码解析」还是「按名称检索」）
_TICKER_SHAPE = re.compile(r"^[A-Za-z][A-Za-z.\-]{0,9}$")


def detect() -> tuple[bool, str]:
    """SEC 官方 API 免费无 key；UA 声明可选。"""
    return True, f"免费无 key（SEC 官方 XBRL API；可用 {ENV_UA} 声明身份）"


_UA_HINTED = False


def _user_agent() -> str:
    from .env import read_env

    ua = read_env(ENV_UA)
    if not ua:
        global _UA_HINTED
        if not _UA_HINTED:
            _UA_HINTED = True
            import sys

            print(f"提示: SEC UA 仍用占位邮箱，建议设置 {ENV_UA}=\"你的名字 你的邮箱\"",
                  file=sys.stderr)
        return DEFAULT_UA
    return ua


def cache_dir() -> Path:
    """SEC 原始 JSON 的磁盘缓存目录（原始文件大，缓存是必需品不是优化）。

    位置收敛到 _common.cache_root()/'sec'，避免本模块与 _common 各维护
    一套平台判断（同一件事两份实现必然漂移）。
    """
    _ensure_scripts_on_path()
    from _common import cache_root

    base = cache_root() / "sec"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ensure_scripts_on_path() -> None:
    scripts = str(Path(__file__).resolve().parent.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _http_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """带重试的 GET JSON。404 立即失败，其余错误退避重试。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(), "Accept": "application/json"}
    )
    last: Optional[Exception] = None
    for attempt in range(RETRIES):
        try:
            with guarded_open(req, timeout, allowed_host=("www.sec.gov", "data.sec.gov")) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
            if e.code == 403:
                raise RuntimeError(
                    f"SEC 403（{url}）：UA 需含邮箱声明，"
                    f"请设置 {ENV_UA}（如 \"your-name your@email\"）"
                ) from e
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            last = e
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"SEC 请求失败: {url}（{last}）")


def _cached_json(cache_name: str, url: str, ttl_hours: float) -> Any:
    """磁盘缓存统一走 _common.cache_get/cache_set（单真源），本函数只负责回源。

    TTL 对调用方保持小时口径，内部换算成统一层的秒；缓存名并入键，
    不同端点互不命中。缓存读写失败不阻断取数（统一层本身 fail-open）。
    旧版自实现的「TTL + 原子写」与统一层是同一件事的两份实现，已收敛。
    """
    _ensure_scripts_on_path()
    from _common import cache_get, cache_set

    key = f"{cache_name}|{url}"
    hit = cache_get("sec", key, ttl_hours * 3600)
    if hit is not None:
        return hit
    data = _http_json(url)
    cache_set("sec", key, data)
    return data


def _norm_ticker(ticker: str) -> str:
    """BRK.B → BRK-B（SEC 用连字符）。"""
    return (ticker or "").strip().upper().replace(".", "-")


def _ticker_index(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for item in (mapping or {}).values():
        if not isinstance(item, dict):
            continue
        tk = (item.get("ticker") or "").upper()
        if tk:
            idx.setdefault(tk, item)
            # 连字符与点号两种写法互相兼容（SEC 文件用 BRK-B，用户可能写 BRK.B）
            idx.setdefault(tk.replace(".", "-"), item)
            if "-" in tk:
                idx.setdefault(tk.replace("-", "."), item)
    return idx


def resolve_cik(ticker: str) -> tuple[str, str]:
    """ticker → (10 位 CIK, 公司名)。找不到抛 RuntimeError。"""
    mapping = _cached_json("company_tickers.json", TICKERS_URL, ttl_hours=24 * 7)
    hit = _ticker_index(mapping).get(_norm_ticker(ticker))
    if not hit:
        raise RuntimeError(f"SEC 未收录该 ticker: {ticker}（仅美股发行人）")
    return _cik10(hit["cik_str"]), str(hit.get("title") or ticker.upper())


def _cik10(cik: Any) -> str:
    return f"{int(cik):010d}"


def _err(message: str, kind: str = "us_fundamentals") -> dict[str, Any]:
    """本源的失败出口。构造收口到 sources/envelope（P1，2026-11-09）。"""
    from .envelope import fail_envelope

    return fail_envelope("sec_edgar", kind, message)


def fundamentals(ticker: str) -> dict[str, Any]:
    """年报关键指标（10-K XBRL）。返回 invest-cli 信封。"""
    try:
        cik, title = resolve_cik(ticker)
        facts = _cached_json(f"companyfacts_{cik}.json", FACTS_URL.format(cik=cik), ttl_hours=24)
    except RuntimeError as e:
        return _err(str(e))
    metrics = extract_annual(facts)
    # 判据看的是「有没有 10-K 口径的事实」，不是「metrics 非空」：dei 的流通股数
    # 来自 20-F/6-K，单独一条也会让 metrics 非空，于是 20-F 主体（实测 TSM）
    # 拿到一个只有流通股数的空壳快照、rc=0 —— 静默的「假成功」。
    if not any(str(m.get("form") or "") == "10-K" for m in metrics.values()):
        return _err(f"{title} 无可用 10-K 年报事实（可能为外国私人发行人 20-F 或新上市）")
    # 财年只认 10-K 口径：dei 的流通股数来自 10-Q（fy 已是下一财年），
    # 混进来会把「最新年报」标成还没发生的年份（实测 AAPL 显示 FY2026）。
    # default=0 是必须的：20-F 主体（如 TSM）一条 10-K 都没有，空序列会抛 ValueError。
    fy = max(((m.get("fy") or 0) for m in metrics.values()
              if str(m.get("form") or "") == "10-K"), default=0) or None
    return {
        "source": "sec_edgar",
        "kind": "us_fundamentals",
        "ok": True,
        "data": {
            "ticker": _norm_ticker(ticker),
            "cik": cik,
            "name": title,
            "fiscal_year": fy,
            "metrics": metrics,
            "source_url": BROWSE_URL.format(cik=cik),
        },
        "error": None,
    }


def _filing_url(cik: str, accn: str, doc: str) -> str:
    """申报原文链接（有主文档给直达链接，没有给目录链接）。"""
    if accn and doc:
        return ARCHIVES_URL.format(cik_int=int(cik), accession=accn.replace("-", ""), doc=doc)
    if accn:
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"
    return BROWSE_URL.format(cik=cik)


def filings(ticker: str, forms: Optional[list[str]] = None, limit: int = 5) -> dict[str, Any]:
    """最近申报清单（默认 10-K/10-Q/8-K 取前 N 条，带原文链接）。"""
    try:
        cik, title = resolve_cik(ticker)
        subs = _cached_json(f"submissions_{cik}.json", SUBMISSIONS_URL.format(cik=cik), ttl_hours=6)
    except RuntimeError as e:
        return _err(str(e), kind="filings")
    recent = ((subs.get("filings") or {}).get("recent")) or {}
    forms_set = {f.strip().upper() for f in (forms or []) if f and f.strip()}
    rows: list[dict[str, Any]] = []
    total = len(recent.get("form") or [])
    for i in range(total):
        form = (recent.get("form") or [""])[i]
        if forms_set and str(form).upper() not in forms_set:
            continue
        accn = ((recent.get("accessionNumber") or [""])[i] or "").strip()
        doc = ((recent.get("primaryDocument") or [""])[i] or "").strip()
        rows.append({
            "form": form,
            "filing_date": ((recent.get("filingDate") or [""])[i] or ""),
            "accession": accn,
            "url": _filing_url(cik, accn, doc),
        })
        if len(rows) >= max(1, limit):
            break
    return {
        "source": "sec_edgar",
        "kind": "filings",
        "ok": True,
        "data": {"ticker": _norm_ticker(ticker), "cik": cik, "name": title, "filings": rows},
        "error": None,
    }


def _submissions_recent(ticker: str) -> tuple[str, str, dict[str, Any]]:
    """ticker → (cik, 公司名, submissions.recent)。供各动作共用，抛 RuntimeError。"""
    cik, title = resolve_cik(ticker)
    subs = _cached_json(f"submissions_{cik}.json", SUBMISSIONS_URL.format(cik=cik), ttl_hours=6)
    return cik, title, (((subs.get("filings") or {}).get("recent")) or {})


def _recent_index(recent: dict[str, Any], i: int, key: str) -> str:
    return str(((recent.get(key) or [""])[i] or "")).strip()


def _cutoff_date(days: int) -> str:
    """今天往前 days 天的 YYYY-MM-DD（days<=0 返回空串 = 不过滤）。"""
    if days <= 0:
        return ""
    from datetime import timedelta

    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")



# ── 全文检索：EDGAR full-text search（2001 年起全部申报的正文）──────────────
#
# 与 drillr 的 filing-search 同类：回答「命中在哪个申报、原文在哪」，
# 而不是把整份 10-K 拉下来让人自己翻。命中段落（snippet）按需从原文抽取，
# 抽不到就留空 —— 宁可少给，不给编造的上下文。
FTS_URL = "https://efts.sec.gov/LATEST/search-index"
# 接口每次最多回 100 条，且**忽略 size 参数**（实测 size=2/5/20/100 都回 100 条），
# 所以「返回几条」只能自己截断；分页用 `from`，本实现不做分页（100 条足够定位）。
FTS_MAX_SIZE = 100
SNIPPET_TOP = 5             # 只为前 N 条命中抽原文段落（每条一次文档请求）
SNIPPET_RADIUS = 160        # 段落半径（字符）
SNIPPET_DOC_LIMIT = 3 * 1024 * 1024  # 单文档最多读 3MB 做段落抽取


def _fts_quote(query: str) -> str:
    """多词自动按短语检索（引号可选）。

    EDGAR FTS 里 `supply commitments` 是「两个词都出现」，`"supply commitments"`
    才是短语。用户问「供应承诺」时想要的是后者；要宽匹配就自己写引号或单词。
    """
    q = (query or "").strip()
    if not q or '"' in q:
        return q
    return f'"{q}"' if any(ch.isspace() for ch in q) else q


def _strip_html(text: str) -> str:
    """粗剥 HTML/XML 标签与实体，用于段落抽取（不做完整解析，够用即可）。"""
    import html as _html
    import re as _re

    text = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = _re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return _re.sub(r"\s+", " ", text)


def _cached_text(url: str, ttl_hours: float) -> str:
    """文档原文的磁盘缓存（按 URL 键，申报原文不可变，可长缓存）。"""
    _ensure_scripts_on_path()
    from _common import cache_get, cache_set

    key = f"doc|{url}"
    hit = cache_get("sec", key, ttl_hours * 3600)
    if isinstance(hit, str):
        return hit
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with guarded_open(req, DEFAULT_TIMEOUT, allowed_host="www.sec.gov") as resp:
            raw = resp.read(SNIPPET_DOC_LIMIT + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"SEC 文档请求失败: {url}（{e}）") from e
    text = raw.decode("utf-8", errors="replace")
    cache_set("sec", key, text)
    return text


def _snippet_for(url: str, terms: list[str]) -> Optional[str]:
    """从申报原文抽取命中段落；抽不到返回 None（绝不编造上下文）。

    定位顺序：整句短语 → 最长词 → 其余词。先匹配最短词会抽到无关段落
    （实测 "data center" 会先命中 "Interactive Data File" 里的 data）。
    """
    try:
        raw = _cached_text(url, ttl_hours=24 * 7)
    except RuntimeError:
        return None
    text = _strip_html(raw[:SNIPPET_DOC_LIMIT])
    low = text.lower()
    candidates = []
    phrase = " ".join(terms).strip()
    if len(terms) > 1 and phrase:
        candidates.append(phrase)
    candidates.extend(sorted(terms, key=len, reverse=True))
    pos = -1
    hit_term = ""
    for term in candidates:
        if not term:
            continue
        pos = low.find(term.lower())
        if pos >= 0:
            hit_term = term
            break
    if pos < 0:
        return None
    start = max(0, pos - SNIPPET_RADIUS)
    end = min(len(text), pos + len(hit_term) + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def filing_search(
    ticker: str,
    query: str,
    forms: Optional[list[str]] = None,
    from_ym: str = "",
    to_ym: str = "",
    limit: int = 10,
    snippets: bool = True,
) -> dict[str, Any]:
    """在**该公司的申报正文**里全文检索（EDGAR full-text search）。

    - from_ym/to_ym 为 YYYY-MM（含首尾月），空 = 不限；
    - snippets=True 时只为前 SNIPPET_TOP 条命中拉原文抽段落（每条一次请求，
      原文按 URL 长缓存）；抽不到就留 None，不编造。
    """
    try:
        cik, title = resolve_cik(ticker)
    except RuntimeError as e:
        return _err(str(e), kind="filing_search")
    if not (query or "").strip():
        return _err("检索词为空", kind="filing_search")
    params: dict[str, str] = {
        "q": _fts_quote(query),
        "ciks": cik,
    }
    if forms:
        params["forms"] = ",".join(f.strip() for f in forms if f.strip())
    # 日期过滤必须**成对**给：实测只传 startdt 会被完全忽略（total 不变），
    # 两个都给才生效。所以单边给了就补另一边（早端 2001-01-01 = 全文索引起点，
    # 晚端 = 今天）。
    from_ym_s, to_ym_s = from_ym.strip(), to_ym.strip()
    if from_ym_s or to_ym_s:
        start = f"{from_ym_s}-01" if len(from_ym_s) == 7 else (from_ym_s or "2001-01-01")
        end = f"{to_ym_s}-31" if len(to_ym_s) == 7 else (to_ym_s or datetime.now().strftime("%Y-%m-%d"))
        params["startdt"], params["enddt"] = start, end
    url = FTS_URL + "?" + urllib.parse.urlencode(params)
    try:
        payload = _cached_json(f"fts_{url}", url, ttl_hours=1)
    except RuntimeError as e:
        return _err(str(e), kind="filing_search")
    hits = (((payload.get("hits") or {}).get("hits")) or [])[:max(1, min(limit, FTS_MAX_SIZE))]
    total = ((payload.get("hits") or {}).get("total") or {}).get("value")
    terms = [t for t in (query or "").replace('"', " ").split() if t]
    rows: list[dict[str, Any]] = []
    for i, h in enumerate(hits):
        src = h.get("_source") or {}
        _id = str(h.get("_id") or "")
        accn, _, doc = _id.partition(":")
        hit_cik = str((src.get("ciks") or [cik])[0])
        row: dict[str, Any] = {
            "form": src.get("form") or src.get("file_type") or "",
            "filing_date": src.get("file_date") or "",
            "period_ending": src.get("period_ending") or "",
            "accession": accn,
            "doc": doc,
            "url": _filing_url(hit_cik, accn, doc),
            "display_name": (src.get("display_names") or [""])[0],
            "snippet": None,
        }
        if snippets and i < SNIPPET_TOP:
            row["snippet"] = _snippet_for(row["url"], terms)
        rows.append(row)
    return {
        "source": "sec_edgar",
        "kind": "filing_search",
        "ok": True,
        "data": {
            "ticker": _norm_ticker(ticker),
            "cik": cik,
            "name": title,
            "query": query,
            "forms": forms or [],
            "total_hits": total,
            "returned": len(rows),
            "results": rows,
            "note": "命中范围为公司自身申报（EDGAR 全文索引 2001 年起）",
        },
        "error": None,
    }


# ── Form 4：内部人交易（3/4/5 体系里的 4 号表）────────────────────────────
INSIDER_FORMS = ("4", "4/A")

def insider_trades(ticker: str, days: int = 180, limit: int = 20) -> dict[str, Any]:
    """内部人交易：近 N 天内的 Form 4 申报，逐笔展开（日期倒序）。

    每份 Form 4 一次文档请求（原文长缓存）；limit 限制**申报份数**，
    一份里可能有多笔交易（都返回）。days<=0 = 不限时间。
    """
    try:
        cik, title, recent = _submissions_recent(ticker)
    except RuntimeError as e:
        return _err(str(e), kind="insider_trades")
    cutoff = _cutoff_date(days)
    picks: list[int] = []
    for i in range(len(recent.get("form") or [])):
        form = str((recent.get("form") or [""])[i])
        if form not in INSIDER_FORMS:
            continue
        date = _recent_index(recent, i, "filingDate")
        if cutoff and date < cutoff:
            continue
        picks.append(i)
        if len(picks) >= max(1, limit):
            break
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for i in picks:
        accn = _recent_index(recent, i, "accessionNumber")
        doc = _recent_index(recent, i, "primaryDocument")
        filing_date = _recent_index(recent, i, "filingDate")
        xml_doc = doc.split("/")[-1] or "form4.xml"
        try:
            parsed = _parse_form4(_cached_text(_filing_url(cik, accn, xml_doc), ttl_hours=24 * 7))
        except RuntimeError as e:
            errors.append(f"{accn}: {e}")
            continue
        for tx in parsed["transactions"]:
            rows.append({
                **tx,
                "owner": parsed["owner"]["name"],
                "owner_role": parsed["owner"]["role"],
                "owner_title": parsed["owner"]["title"],
                "filing_date": filing_date,
                "accession": accn,
                "url": _filing_url(cik, accn, doc),
            })
    rows.sort(key=lambda r: (r.get("date") or "", r.get("filing_date") or ""), reverse=True)
    return {
        "source": "sec_edgar",
        "kind": "insider_trades",
        "ok": True,
        "data": {
            "ticker": _norm_ticker(ticker),
            "cik": cik,
            "name": title,
            "days": days,
            "filings_scanned": len(picks),
            "transactions": rows,
            "errors": errors,
            "note": "Form 4 由内部人自行申报，口径为申报原文；direction 按交易代码归类",
        },
        "error": None,
    }


# ── 13F：机构持仓（按申报机构看「它持有什么」）────────────────────────────
_THIRTEENF_FORMS = ("13F-HR", "13F-HR/A")


def _name_norm(s: str) -> str:
    """名称归一（比对用）：小写 + 非字母数字压成单空格。"""
    import re as _re

    return _re.sub(r"\s+", " ", _re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _ticker_ci_family(ticker: str) -> Optional[tuple[str, str]]:
    """类别股回退：`BRK` 不在映射表里，但 `BRK-A/BRK-B` 是同一 CIK。

    只在「同一 CIK 的全部命中」时才接受，避免把 `A` 这类前缀误扩成一大批公司。
    """
    try:
        mapping = _cached_json("company_tickers.json", TICKERS_URL, ttl_hours=24 * 7)
    except RuntimeError:
        return None
    idx = _ticker_index(mapping)
    prefix = f"{_norm_ticker(ticker)}-"
    hits = {str(v.get("cik_str")) for k, v in idx.items() if k.startswith(prefix)}
    if len(hits) != 1:
        return None
    item = next(v for v in idx.values() if str(v.get("cik_str")) in hits)
    return _cik10(item["cik_str"]), str(item.get("title") or ticker.upper())


def _resolve_13f_filer(investor: str) -> tuple[str, str]:
    """投资人（ticker / 名称 / CIK）→ (CIK, 名称)。抛 RuntimeError。

    解析顺序（每一步都要求「确实报过 13F」）：
      1. 纯数字 = CIK；
      2. ticker 精确命中（含 BRK→BRK-B 类别股回退）；
      3. 名称：EDGAR 全文检索限定 forms=13F-HR，且命中机构的 display name
         必须**包含**查询词 —— 不做这一步，`BRK` 会落到某份提到 BRK 的
         无关机构的 13F 上（实测踩过：返回了 Integral Derivatives 的 2018 年表）。
    """
    raw = (investor or "").strip()
    if not raw:
        raise RuntimeError("投资人不能为空")
    if raw.isdigit():
        return _cik10(raw), f"CIK {_cik10(raw)}"
    looked_like_ticker = False
    try:
        cik, name = resolve_cik(raw)
        looked_like_ticker = True
        if _has_13f(cik):
            return cik, name
    except RuntimeError:
        pass
    if looked_like_ticker or _TICKER_SHAPE.fullmatch(raw):
        fam = _ticker_ci_family(raw)
        if fam and _has_13f(fam[0]):
            return fam
        if looked_like_ticker or fam:
            raise RuntimeError(f"{raw} 没有 13F-HR 申报记录（13F 由机构/基金申报，个股主体多数不报）")
    # 名称检索：候选必须「名字对得上」且真的报过 13F
    url = (FTS_URL + "?" + urllib.parse.urlencode(
        {"q": f'"{raw}"', "forms": "13F-HR", "size": "10"}))
    try:
        payload = _cached_json(f"13f_filer_{url}", url, ttl_hours=24)
    except RuntimeError as e:
        raise RuntimeError(f"13F 申报人检索失败: {e}") from e
    hits = ((payload.get("hits") or {}).get("hits")) or []
    qn = _name_norm(raw)
    for h in hits:
        src = h.get("_source") or {}
        display = (src.get("display_names") or [""])[0]
        ciks = src.get("ciks") or []
        if not ciks or qn not in _name_norm(display):
            continue
        cik = _cik10(ciks[0])
        if not _has_13f(cik):
            continue
        name = display.split("  (")[0].strip() or raw
        return cik, name
    raise RuntimeError(f"未找到 13F 申报人: {investor}（可传机构全名/CIK/上市代码）")


def _has_13f(cik: str) -> bool:
    try:
        subs = _cached_json(f"submissions_{cik}.json", SUBMISSIONS_URL.format(cik=cik), ttl_hours=6)
    except RuntimeError:
        return False
    forms = ((subs.get("filings") or {}).get("recent") or {}).get("form") or []
    return any(str(f).startswith("13F-HR") for f in forms)


def _13f_period(cik: str, accn: str, files: list[str]) -> str:
    """从 13F 封面（primary_doc.xml）取报告期（归一到 YYYY-MM-DD）；取不到返回空串。

    封面里的日期是 MM-DD-YYYY（实测 `<periodOfReport>06-30-2026</periodOfReport>`），
    不归一的话与 ISO 日期没法比较，「2023 年前为千美元」的口径判断会错。
    """
    if "primary_doc.xml" not in files:
        return ""
    try:
        text = _cached_text(_filing_url(cik, accn, "primary_doc.xml"), ttl_hours=24 * 7)
    except RuntimeError:
        return ""
    m = re.search(r"<periodOfReport>\s*([0-9-]+)\s*</periodOfReport>", text)
    if not m:
        return ""
    raw = m.group(1)
    us = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", raw)
    return f"{us.group(3)}-{us.group(1)}-{us.group(2)}" if us else raw


def institutional_holdings(investor: str, limit: int = 40) -> dict[str, Any]:
    """机构最新 13F 持仓（按发行人聚合，按市值降序）。

    口径：13F 只含美国多头与期权（不含空头、不含海外持仓）；2023 年起
    申报金额单位为美元（此前为千美元，本实现只取最新一期，故按美元标注）。
    """
    try:
        cik, name = _resolve_13f_filer(investor)
        subs = _cached_json(f"submissions_{cik}.json", SUBMISSIONS_URL.format(cik=cik), ttl_hours=6)
    except RuntimeError as e:
        return _err(str(e), kind="institutional_holdings")
    recent = ((subs.get("filings") or {}).get("recent")) or {}
    pick = None
    for i in range(len(recent.get("form") or [])):
        if str((recent.get("form") or [""])[i]) in _THIRTEENF_FORMS:
            pick = i
            break
    if pick is None:
        return _err(f"{name} 没有 13F-HR 申报记录", kind="institutional_holdings")
    accn = _recent_index(recent, pick, "accessionNumber")
    filing_date = _recent_index(recent, pick, "filingDate")
    accn_nd = accn.replace("-", "")
    try:
        index = _cached_json(
            f"index_{accn}.json",
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_nd}/index.json",
            ttl_hours=24 * 7)
    except RuntimeError as e:
        return _err(str(e), kind="institutional_holdings")
    files = [str(f.get("name") or "") for f in ((index.get("directory") or {}).get("item") or [])]
    xmls = [f for f in files if f.lower().endswith(".xml") and f.lower() != "primary_doc.xml"]
    xmls.sort(key=lambda f: (0 if "info" in f.lower() else 1, f))
    table: Optional[list[dict[str, Any]]] = None
    table_file = ""
    for f in xmls:
        try:
            text = _cached_text(_filing_url(cik, accn, f), ttl_hours=24 * 7)
        except RuntimeError:
            continue
        if _is_info_table(text):
            table = _parse_13f_table(text)
            table_file = f
            break
    if table is None:
        return _err(f"未找到 13F 持仓表（{name}，{accn}）", kind="institutional_holdings")
    period = _13f_period(cik, accn, files)
    # 同一 CUSIP 可能由多个子管理人分行申报：按 (cusip, put_call) 合并
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for row in table:
        key = (row["cusip"], row.get("put_call") or "")
        cur = agg.setdefault(key, {**row, "value": 0.0, "shares": 0.0})
        cur["value"] += row.get("value") or 0.0
        cur["shares"] += row.get("shares") or 0.0
    holdings = sorted(agg.values(), key=lambda r: -(r.get("value") or 0.0))
    total = sum(r.get("value") or 0.0 for r in holdings)
    for r in holdings:
        r["pct"] = round((r.get("value") or 0.0) / total * 100, 2) if total else None
    # 金额单位随申报期变：SEC 2023-01 起要求 13F 以美元申报，此前为千美元。
    # 不标注单位会把「577」读成 577 美元或 577 亿，两种都错。
    value_unit = "USD" if (period or "") >= "2023-01-01" else "USD_thousands"
    return {
        "source": "sec_edgar",
        "kind": "institutional_holdings",
        "ok": True,
        "data": {
            "filer": name,
            "filer_cik": cik,
            "form": "13F-HR",
            "filed": filing_date,
            "period": period,
            "table_file": table_file,
            "value_unit": value_unit,
            "holdings_count": len(holdings),
            "total_value": total,
            "holdings": holdings[:max(1, limit)],
            "note": "13F 只含美国多头与期权（不含空头）；金额单位为"
                    + ("美元（2023 年起申报口径）" if value_unit == "USD" else "千美元（2023 年前申报口径）"),
        },
        "error": None,
    }


# ── 事件：8-K 事项 + 权益变动申报（13D/13G）─────────────────────────────
ITEM_LABELS: dict[str, str] = {
    "1.01": "签署重大协议", "1.02": "重大协议终止", "1.03": "破产或接管",
    "2.01": "完成收购或处置资产", "2.02": "业绩与财务状况发布",
    "2.03": "新增重大财务义务", "2.04": "触发加速或增加义务的事项",
    "2.05": "退出/处置活动成本", "2.06": "重大减值",
    "3.01": "退市通知或上市标准未达标", "3.02": "未注册证券的出售",
    "3.03": "证券持有人权利的重大修改",
    "4.01": "会计师事务所变更", "4.02": "前期财务报表不可依赖",
    "5.01": "控制权变更", "5.02": "高管或董事变动",
    "5.03": "章程或内部规章修改", "5.04": "员工福利计划修改",
    "5.05": "道德准则修改", "5.06": "壳公司状态变更", "5.07": "股东表决事项提交",
    "6.01": "ABS 相关", "6.02": "ABS 相关", "6.03": "ABS 相关",
    "7.01": "公平披露（Reg FD）", "8.01": "其他事项", "9.01": "财务报表与附件",
}
EVENT_FORMS = ("8-K", "8-K/A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A")


def events(ticker: str, limit: int = 20, days: int = 0) -> dict[str, Any]:
    """公司事件：8-K 逐事项展开 + 13D/13G 权益变动（日期倒序）。

    days<=0 = 不限时间（受 submissions.recent 窗口限制，约近千条申报）。
    13D/G 的申报人名称在正文里，本层不额外抓取，只给类型与链接。
    """
    try:
        cik, title, recent = _submissions_recent(ticker)
    except RuntimeError as e:
        return _err(str(e), kind="events")
    cutoff = _cutoff_date(days)
    rows: list[dict[str, Any]] = []
    for i in range(len(recent.get("form") or [])):
        form = str((recent.get("form") or [""])[i])
        if form not in EVENT_FORMS:
            continue
        date = _recent_index(recent, i, "filingDate")
        if cutoff and date < cutoff:
            continue
        items_raw = _recent_index(recent, i, "items")
        items = [
            {"code": c.strip(), "label": ITEM_LABELS.get(c.strip(), "其他事项")}
            for c in items_raw.split(",") if c.strip()
        ]
        accn = _recent_index(recent, i, "accessionNumber")
        doc = _recent_index(recent, i, "primaryDocument")
        rows.append({
            "date": date,
            "form": form,
            "kind": "ownership" if form.startswith("SC 13") else "8-k",
            "items": items,
            "accession": accn,
            "url": _filing_url(cik, accn, doc),
        })
        if len(rows) >= max(1, limit):
            break
    return {
        "source": "sec_edgar",
        "kind": "events",
        "ok": True,
        "data": {
            "ticker": _norm_ticker(ticker),
            "cik": cik,
            "name": title,
            "events": rows,
            "note": "8-K 事项按申报 items 字段解析；13D/13G 为 5% 以上权益变动申报",
        },
        "error": None,
    }


def snapshot(ticker: str, forms: Optional[list[str]] = None, limit: int = 5,
             years: int = 5, quarterly: bool = False) -> dict[str, Any]:
    """年报指标 + 最近申报（可选年度序列/季度序列），一次取全（给 CLI 的单一入口）。

    years>0 时附 `series`（近 N 年年度序列，三关趋势表直接用）；quarterly=True
    时附 `quarterly`（近 8 季，Q4 为推导值并标注 derived）。
    """
    fund = fundamentals(ticker)
    if not fund.get("ok"):
        return fund
    fil = filings(ticker, forms=forms, limit=limit)
    data = dict(fund["data"])
    data["filings"] = (fil.get("data") or {}).get("filings") if fil.get("ok") else []
    if not fil.get("ok"):
        data["filings_error"] = fil.get("error")
    if years and years > 0:
        try:
            cik = str(data.get("cik") or "")
            facts = _cached_json(f"companyfacts_{cik}.json", FACTS_URL.format(cik=cik), ttl_hours=24)
            data["series"] = extract_series(facts, years=years)
            if quarterly:
                data["quarterly"] = extract_quarterly(facts)
        except RuntimeError as e:
            data["series_error"] = str(e)
    return {"source": "sec_edgar", "kind": "us_fundamentals", "ok": True, "data": data, "error": None}


if __name__ == "__main__":  # 快速自检：在 scripts/ 目录下 python3 -m sources.sec_edgar AAPL
    import json as _json

    _t = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(_json.dumps(snapshot(_t), ensure_ascii=False, indent=2, default=str)[:3000])
