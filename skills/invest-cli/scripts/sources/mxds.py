"""妙想(MX) MCP 数据源适配器。

通过 MCP 协议（StreamableHttp）访问东方财富妙想数据服务。
11 个工具覆盖：A股/港股/美股/债券/基金/指数/宏观/选股/新闻/公告/综合。

key 读取：环境变量 EM_API_KEY（进程 / launchctl / shell rc）或凭据文件
`~/.config/invest-cli/mxds.env`。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

ENV_KEY = "EM_API_KEY"
MCP_HOST = "mxapi.eastmoney.com"
MCP_PATH = "/mxds/mcp"

# 妙想单次调用 1.2s+（服务端 NLU 主导，连接复用零收益，2026-10-11 实测），
# intent 直调路径不经 route 快照缓存——这里按查询文本缓存成功结果。
# TTL 300s：相邻调用 ≤300s 占 96.7%（第五轮治理报告 2372 次调用实测口径）。
_NL_CACHE_NS = "mxds_nl"
_NL_CACHE_TTL = 300.0

# 常见金融缩写不是美股代码信号：「PE 最低的银行股」曾被 \b[A-Za-z]{2,5}\b
# 误路由到美股工具（选股分支排在其后，永远轮不到）。
_NON_TICKER_TOKENS = {
    "PE", "PB", "ROE", "ROA", "EPS", "GDP", "CPI", "PPI", "PMI", "ETF",
    "LOF", "FOF", "QDII", "IPO", "TTM", "M1", "M2", "AH",
}

# 裸 ticker（AAPL/TSLA/BRK.A）：服务端 NLU 不识别（实测 "AAPL" 返回空数组），
# us() 对这种形态包装成查询模板再发。
_TICKER_RE = re.compile(r"^[A-Za-z]{1,5}(?:[.\-][A-Za-z]{1,4})?$")

# 快照类工具：route 快照链（stock/fund/us 三个 kind）消费的是「单一标的
# 信封」——`unwrap_snapshot` 之后 `cmd_*.format_terminal` 直接对
# `data["data"]` 做 `.get`，要求它是 dict。
#
# 妙想这些工具的服务端实现是**自然语言检索**，实测对所有输入都返回表格信封
# （`data` = `[{columns, items}, ...]`）：真实标的（600519→贵州茅台表格）、
# 不存在代码（999999→「全部A股(板块)」全市场汇总）、错别字名称
# （贵洲茅台→静默纠错成贵州茅台）无一例外——**永远**产不出 dict 快照。
# 因此快照类调用（stock/fund/us，_call_tool 显式 snapshot=True）拿到非 dict
# 快照时按「未找到」拒绝，让链路回退到下一源或给出明确错误。
#
# 注意本名单只是**缺省判据**：intent mxds 自然语言入口（auto()）的契约是
# 「表格即答案」，显式传 snapshot=False 放行（2026-10-14 审查实测：把拒绝
# 设为 _call_tool 的默认行为会误杀 auto() 的 4 条路由）。
_SNAPSHOT_TOOLS = frozenset({
    "mx_ashare_finance_data",
    "mx_hk_finance_data",
    "mx_us_finance_data",
    "mx_fund_finance_data",
})


def _ticker_like(q: str) -> bool:
    """查询里是否含「像美股代码」的大写 token（2-5 位字母，排除金融缩写）。"""
    for tok in re.findall(r"[A-Za-z]+", q):
        if not 2 <= len(tok) <= 5:
            continue
        if tok.upper() in _NON_TICKER_TOKENS:
            continue
        if tok.isupper():
            return True
    return False


def detect() -> tuple[bool, str]:
    """可用性判据 = 凭据加载器的判据。"""
    if load_api_key():
        return True, f"{ENV_KEY} 已配置"
    return False, f"缺少 {ENV_KEY}"


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "mxds.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "mxds.env",
    ]
    return [p for p in cands if p.is_file()]


def load_api_key() -> str:
    """从环境变量（进程 / launchctl / shell rc）或用户级凭据文件读取 API key。"""
    from .env import read_credential_file, read_env

    val = read_env(ENV_KEY)
    if val:
        return val
    return read_credential_file(ENV_KEY, credential_files())


def _extract_payload(body: str, content_type: str) -> str:
    """SSE 形态取最后一条 data: 行；JSON 形态原样返回。

    MCP StreamableHttp 规范（2025-06-18）：服务端可返回 SSE，客户端 MUST 双支持；
    当前服务端返回 application/json，这里兜住 SSE 形态。
    """
    if "text/event-stream" in (content_type or ""):
        data_lines = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        if not data_lines:
            raise ValueError("SSE 响应中无 data 消息")
        return data_lines[-1]
    return body


def _mcp_call(tool: str, query: str, timeout: int = 30) -> dict[str, Any]:
    """调用 MCP 工具，返回解析后的响应。

    2026-11-09 P0 收口：从裸 http.client.HTTPSConnection 改走共享安全闸
    sources/_http.guarded_request（https + host 白名单 + DNS 公网校验 + 禁重定向）。
    此前本路径完全不过闸，DNS rebinding 与重定向绕过对妙想调用完全失效。
    """
    api_key = load_api_key()
    if not api_key:
        return {"ok": False, "error": f"未设置 {ENV_KEY}"}

    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {"query": query}},
    })

    try:
        from ._http import guarded_request

        status, body_bytes, headers = guarded_request(
            f"https://{MCP_HOST}{MCP_PATH}",
            headers={
                "Content-Type": "application/json",
                "em_api_key": api_key,
                "Accept": "application/json, text/event-stream",
            },
            data=payload.encode("utf-8"),
            timeout=timeout,
            allowed_host=MCP_HOST,
        )
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    body = body_bytes.decode("utf-8", errors="replace")
    content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    if status != 200:
        # key 失效/限流的具体原因在 body 里，带前 200 字符，否则排障只见 "HTTP 4xx"
        snippet = body[:200].replace("\n", " ")
        return {"ok": False, "error": f"HTTP {status}: {snippet}"}

    try:
        body = _extract_payload(body, content_type)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON decode error: {e}"}

    if "error" in data:
        return {"ok": False, "error": f"MCP error: {data['error']}"}

    result = data.get("result", {})
    content = result.get("content", [])
    text = "".join(
        item.get("text", "")
        for item in content
        if item.get("type") == "text"
    )

    if not text:
        return {"ok": False, "error": "MCP 返回空内容"}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"MCP 返回非 JSON: {text[:200]}"}

    # 检查数据是否为空（实测多为服务端 NLU 未识别查询，如裸 ticker）
    if isinstance(parsed, dict):
        items = parsed.get("data", [])
        if not items:
            return {"ok": False, "error": f"服务端未识别查询或无数据: {query!r}", "raw": parsed}

    return {"ok": True, "data": parsed, "raw_text": text}


def _is_search_envelope(parsed: Any) -> bool:
    """妙想 NLU「检索结果信封」判据——只用于错误文案区分，**不做放行判据**。

    表格信封两种形态都算：data 是表格列表（实测主形态），或 data 本身是带
    columns/items 的 dict（防御性，实测未出现）。放行判据是 _call_tool 里的
    正向契约（快照内层 data 必须是 dict），本函数回答的只是「服务端给了检索
    结果还是形态异常」——两者排障方向不同，文案要分开。
    """
    if not isinstance(parsed, dict):
        return False
    data = parsed.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        return isinstance(first, dict) and ("columns" in first or "items" in first)
    return isinstance(data, dict) and ("columns" in data or "items" in data)


def _snapshot_shape_error(parsed: Any, keyword: str) -> str:
    """快照类调用拿到非 dict 快照时的错误文案（见 _call_tool 的契约校验）。"""
    if _is_search_envelope(parsed):
        return f"未找到匹配标的: {keyword!r}（妙想仅返回检索结果，无唯一匹配）"
    return f"未找到匹配标的: {keyword!r}（妙想返回的不是单一标的快照）"


def _call_tool(tool: str, keyword: str, *, snapshot: Optional[bool] = None) -> dict[str, Any]:
    """统一调用工具并包装为 invest-cli 信封格式。

    snapshot 控制「内层 data 必须是 dict」这一契约校验。两个消费者的需求
    截然不同，必须显式区分（2026-10-14 审查实测：藏在工具名单的默认行为里，
    intent mxds 的 4 条路由会被误杀）：
      · route 快照链（stock/fund/us）：unwrap_snapshot 之后
        `cmd_*.format_terminal` 直接对 data["data"] 做 .get，必须是 dict
        → snapshot=True；
      · intent mxds 自然语言入口（auto()）：契约就是「表格即答案」，
        SKILL.md 明文推荐 `intent mxds "AAPL 股价"` → snapshot=False；
      · 检索类工具（screen/news/notice/bond/index/macro/comprehensive）不在
        _SNAPSHOT_TOOLS，缺省 None 即放行表格。
    缺省 None 按工具名单判定，显式传值优先。

    正向判据（而不是「拒表格」的否定式）：实测妙想快照类工具对所有输入都只
    返回表格信封，但下游真正的不变量是「快照的 data 必须是 dict」。list-of-
    entity-dicts、顶层 JSON 数组、表格包 dict 三类形态同样会让 format_terminal
    崩溃或输出空表（审查实测复现），只拒带 columns 的表格漏掉它们，故按
    「不是 dict 或 dict 但内容是表格」拒绝。
    """
    result = _mcp_call(tool, keyword)
    if result.get("ok"):
        require_dict = (tool in _SNAPSHOT_TOOLS) if snapshot is None else snapshot
        if require_dict:
            payload = result["data"]
            inner = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(inner, dict) or ("columns" in inner or "items" in inner):
                return {
                    "source": "mxds",
                    "kind": tool,
                    "ok": False,
                    "data": None,
                    "error": _snapshot_shape_error(payload, keyword),
                    "raw": payload,
                }
        return {
            "source": "mxds",
            "kind": tool,
            "ok": True,
            "data": result["data"],
            "error": None,
        }
    return {
        "source": "mxds",
        "kind": tool,
        "ok": False,
        "data": None,
        "error": result.get("error", "未知错误"),
        "raw": result.get("raw"),
    }


# ── 标准方法（路由层调用） ────────────────────────────

def stock(keyword: str) -> dict[str, Any]:
    """A股/港股快照。根据代码自动判断市场。"""
    code = str(keyword).strip()
    # 港股代码：5位数字或以 hk 开头
    if code.startswith("hk") or (len(code) == 5 and code.isdigit()):
        return _call_tool("mx_hk_finance_data", keyword, snapshot=True)
    return _call_tool("mx_ashare_finance_data", keyword, snapshot=True)


def fund(keyword: str) -> dict[str, Any]:
    """基金快照。"""
    return _call_tool("mx_fund_finance_data", keyword, snapshot=True)


def us(keyword: str) -> dict[str, Any]:
    """美股快照。裸 ticker 服务端不识别，包装成查询模板（见 _TICKER_RE）。"""
    q = str(keyword).strip()
    if _TICKER_RE.match(q):
        return _call_tool("mx_us_finance_data", f"{q.upper()} 股价", snapshot=True)
    return _call_tool("mx_us_finance_data", q, snapshot=True)


def screen(condition: str) -> dict[str, Any]:
    """自然语言选股。"""
    return _call_tool("mx_stocks_screener", condition)


# ── 扩展方法（妙想独占能力） ──────────────────────────

def bond(keyword: str) -> dict[str, Any]:
    """债券数据。"""
    return _call_tool("mx_bond_finance_data", keyword)


def index(keyword: str) -> dict[str, Any]:
    """指数/板块数据。"""
    return _call_tool("mx_index_block_finance_data", keyword)


def macro(keyword: str) -> dict[str, Any]:
    """宏观数据。"""
    return _call_tool("mx_macro_data", keyword)


def news(keyword: str) -> dict[str, Any]:
    """新闻检索。"""
    return _call_tool("mx_finance_search_news", keyword)


def notice(keyword: str) -> dict[str, Any]:
    """公告检索。"""
    return _call_tool("mx_finance_search_notice", keyword)


def comprehensive(keyword: str) -> dict[str, Any]:
    """综合查询（非上市主体等）。"""
    return _call_tool("mx_comprehensive_finance_data", keyword)


# ── 自动路由（方案 E：统一自然语言入口） ────────────────

def auto(query: str) -> dict[str, Any]:
    """根据查询内容自动选择最合适的 MCP 工具。

    路由规则（按优先级）：
    1. 债券：含「债券」「国债」「转债」
    2. 指数：含「指数」「板块」「沪深300」
    3. 宏观：含「宏观」「CPI」「GDP」「利率」
    4. 新闻：含「新闻」「消息」
    5. 公告：含「公告」「披露」
    6. 基金：含「基金」「ETF」「净值」
    7. 港股：含「港股」「香港」、5 位数字，或 0 开头的 4 位数字（0700 惯写）
    8. 美股：含「美股」「美国」或大写 ticker 形态 token（排除 PE/ROE 等缩写）
    9. 选股：含「选」「筛选」「找」「市盈率」「ROE」
    10. 默认：A股

    结果按查询文本缓存（_NL_CACHE_TTL），命中带 cached=True。
    """
    q = str(query).strip()
    tool = "mx_ashare_finance_data"

    # 债券
    if any(k in q for k in ("债券", "国债", "转债", "信用债", "城投")):
        tool = "mx_bond_finance_data"
    # 指数/板块
    elif any(k in q for k in ("指数", "板块", "沪深300", "上证", "深证", "创业板")):
        tool = "mx_index_block_finance_data"
    # 宏观
    elif any(k in q for k in ("宏观", "CPI", "GDP", "利率", "通胀", "货币")):
        tool = "mx_macro_data"
    # 新闻
    elif any(k in q for k in ("新闻", "消息", "舆情")):
        tool = "mx_finance_search_news"
    # 公告
    elif any(k in q for k in ("公告", "披露", "年报", "季报")):
        tool = "mx_finance_search_notice"
    # 基金
    elif any(k in q for k in ("基金", "ETF", "LOF", "FOF", "QDII", "净值")):
        tool = "mx_fund_finance_data"
    # 港股：显式市场词、5 位数字，或 0 开头的 4 位数字（0700 惯写；
    # 年份 19xx/20xx 与「3000亿」这类金额表达都不会命中 0 前缀）
    elif (any(k in q for k in ("港股", "香港"))
            or re.search(r"(?<!\d)\d{5}(?!\d)", q)
            or re.search(r"(?<!\d)0\d{3}(?!\d)", q)):
        tool = "mx_hk_finance_data"
    # 美股：显式市场词或大写 ticker 形态 token（_ticker_like 排除金融缩写）
    elif any(k in q for k in ("美股", "美国")) or _ticker_like(q):
        tool = "mx_us_finance_data"
    # 选股（PE/PB 缩写与市盈率同义；美股分支已排除这两个缩写，落到这里是对的）
    elif any(k in q for k in ("选", "筛选", "找", "推荐", "市盈率", "市净率", "ROE", "PE", "PB")):
        tool = "mx_stocks_screener"
    # 默认：A股（tool 已初始化）

    cache_key = f"{tool}|{q}"
    try:
        from _common import cache_get, cache_set
    except ImportError:  # _common 不可用时缓存静默禁用（与 tencent.py 同模式）
        return _call_tool(tool, q, snapshot=False)

    hit = cache_get(_NL_CACHE_NS, cache_key, _NL_CACHE_TTL)
    if hit is not None:
        return {**hit, "cached": True}
    res = _call_tool(tool, q, snapshot=False)
    if res.get("ok"):
        cache_set(_NL_CACHE_NS, cache_key, res)
    return res
