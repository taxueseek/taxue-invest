"""见基行事(seefundgo) 公募基金 MCP 数据源适配器。

定位与边界（照 htbr/wind 的同一套）：
  - 只透传 MCP 的 `tools/call`，不重写上游的字段口径与校验逻辑；
  - 覆盖全市场 14000+ 公募基金/ETF/指数、6900+ 基金经理的结构化数据
    （档案/净值/业绩/风险/持仓穿透/行业配置/经理画像/选基筛选/排行榜/
    ETF 资金流与轮动/组合体检），与 invest-cli 既有源**能力互补**；
  - **不进快照链**（route_kinds 为空）：本源是「事实查询 + 组合诊断」面，
    由 `invest-cli sfg` 具名直取，并在 intent 的基金/组合场景做补充路由。

协议要点（2025-06-18 Streamable HTTP）：
  - 服务端是**有会话**的：`initialize` 后必须在后续请求带 `mcp-session-id`，
    否则回 `-32600 Missing session ID`。会话在单次进程内复用（见 _Session）。
  - 上游强制要求每个工具调用带 `question`（后台消费记录），缺省不报错但
    必须照做；本模块统一注入，调用方不用管。
  - 响应体 `content[0].text` 是 JSON 字符串（`structuredContent` 同内容），
    两种形态都解析。

安全：
  - 所有请求走共享四层闸 `sources/_http.guarded_request`（https + host 白名单
    + DNS 公网校验 + 禁重定向），与 mxds/eastmoney 同口径；
  - 凭据只从环境变量或 `~/.config/invest-cli/sfg.env` 读，**不回显 Token**。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Optional

from .envelope import fail_envelope, ok_envelope

SOURCE_LABEL = "见基行事MCP"
ENV_KEY = "SFG_MCP_TOKEN"
MCP_HOST = "www.fundfof.com"
MCP_PATH = "/mcp"
PROTOCOL_VERSION = "2025-06-18"
CALL_TIMEOUT = 90

# 上游标注要求（服务端强制，产出必须原样保留）。
ATTRIBUTION_LINE = "数据来源：见基行事MCP（fundfof.com）"

# 单次调用缓存：CLI 每次调用都是新进程，但 intent 组合路由会在**同一进程**内
# 连查多只基金；同参数重复调用直接命中，省掉一次 1-3s 的上游往返。
_CALL_TTL = 120.0
_CALL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_FUND_SUFFIX_RE = re.compile(r"\.(OF|SH|SZ|BJ|HK)$", re.I)
_FUND_CODE_RE = re.compile(r"^\d{6}$")


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "sfg.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "sfg.env",
    ]
    return [p for p in cands if p.is_file()]


def load_token() -> str:
    """环境变量（进程 / launchctl / shell rc）优先，其次用户级凭据文件。"""
    from .env import read_credential_file, read_env

    val = read_env(ENV_KEY)
    if val:
        return val
    return read_credential_file(ENV_KEY, credential_files())


def normalize_fund_code(code: str) -> str:
    """**只**归一已是标准码的写法（去空格、大写）；不猜后缀。

    为什么不做「裸码 → .OF/.SH/.SZ」的推断：标准码后缀是**产品形态**而非号段
    规律——同一只 6 位代码可能同时有场外 `.OF` 与场内 `.SH`/`.SZ` 产品
    （实测 005827 取 `.OF`、161725 取 `.SZ`、510300 取 `.SH`、000001 取 `.OF`，
    猜后缀在另一批代码上必然取错标的，比报错危险得多）。
    裸码统一走 `resolve_fund_code()` 的搜索解析。
    """
    return str(code or "").strip().upper()


_RESOLVE_TTL = 86400.0


def resolve_fund_code(keyword: str, *, token: str = "") -> dict[str, Any]:
    """裸代码/名称 → 标准码（`sfg_search_funds` 口径），命中结果落 24h 磁盘缓存。

    返回 {code, name, candidates}；多候选时 candidates 全列，由调用方决定
    （不自动挑第一个：A/C 份额、场内外同名产品会并列）。
    """
    t = str(keyword or "").strip()
    if not t:
        return {"code": "", "name": "", "candidates": []}
    try:
        from _common import cache_get, cache_set

        cached = cache_get("sfg_resolve", t.upper(), _RESOLVE_TTL)
        if isinstance(cached, dict) and cached.get("code"):
            return cached
    except Exception:
        cache_set = None  # type: ignore[assignment]
    if not token:
        token = load_token()
    res = call("sfg_search_funds", {"keyword": t, "limit": 10}, question=t)
    if not res.get("ok"):
        return {"code": "", "name": "", "candidates": [], "error": res.get("error")}
    data = res.get("data") or {}
    # sfg_search_funds 的负载多一层 `result` 包装（与其它工具不同），统一剥掉
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    items = (data or {}).get("items") or []
    cands = [
        {"code": str(i.get("fund_symbol") or ""), "name": str(i.get("fund_name") or "")}
        for i in items
        if isinstance(i, dict) and i.get("fund_symbol")
    ]
    if not cands:
        return {"code": "", "name": "", "candidates": []}
    # 裸码查询要与标准码的**代码段**比对（005827 ↔ 005827.OF），否则精确比对
    # 恒不成立，单只查询会被误判成「多候选」。
    base = t.upper().split(".")[0]
    exact = [c for c in cands if c["code"].split(".")[0] == base]
    picked = exact[0] if exact else cands[0]
    out = {"code": picked["code"], "name": picked["name"], "candidates": cands}
    if cache_set is not None:
        try:
            cache_set("sfg_resolve", t.upper(), out)
        except Exception:
            pass
    return out


def _extract_payload(body: str, content_type: str) -> str:
    """SSE 形态取最后一条 `data:` 行；JSON 形态原样返回。

    形态判据是**body 本身**（有无 `data:` 行）优先，响应头只作参考——
    服务端可能回 `application/json` 却带 SSE 分块，或反之。
    """
    has_data_line = any(ln.startswith("data:") for ln in body.splitlines())
    if "text/event-stream" in (content_type or "") or has_data_line:
        data_lines = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        if not data_lines:
            raise ValueError("SSE 响应中无 data 消息")
        return data_lines[-1]
    return body


def _parse_result(data: dict[str, Any]) -> dict[str, Any]:
    """从 JSON-RPC 响应里取业务负载（content[0].text 优先，structuredContent 兜底）。"""
    result = data.get("result") or {}
    content = result.get("content") or []
    text = ""
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "")
            break
    structured = result.get("structuredContent")
    if structured is not None:
        # structuredContent 与 text 内容一致（实测），优先取结构化形态
        return {"payload": structured, "raw_text": text}
    if not text:
        raise ValueError("MCP 返回空内容")
    try:
        return {"payload": json.loads(text), "raw_text": text}
    except json.JSONDecodeError as e:
        raise ValueError(f"MCP 返回非 JSON: {text[:200]}") from e


class _Session:
    """进程内 MCP 会话（initialize 一次，后续复用 mcp-session-id）。

    服务端会话有寿命，过期后回 `-32600 Session not found`；这里在**同进程**内
    缓存 session id，命中失效时清掉重Initialize。不跨进程持久化——CLI 每次调用
    都是新进程，落盘只会引入「拿旧会话去试」的额外失败。
    """

    def __init__(self) -> None:
        self._sid: str = ""
        self._lock = threading.Lock()

    def _rpc(
        self,
        payload: dict[str, Any],
        token: str,
        *,
        timeout: int = CALL_TIMEOUT,
        session: str = "",
    ) -> tuple[int, bytes, dict[str, str]]:
        from ._http import guarded_request

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        }
        if session:
            headers["mcp-session-id"] = session
        return guarded_request(
            f"https://{MCP_HOST}{MCP_PATH}",
            headers=headers,
            data=json.dumps(payload).encode("utf-8"),
            timeout=timeout,
            allowed_host=MCP_HOST,
        )

    def _initialize(self, token: str) -> str:
        status, body, headers = self._rpc(
            {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "invest-cli", "version": "1.0"},
                },
            },
            token,
            timeout=30,
        )
        if status != 200:
            snippet = body[:200].decode("utf-8", errors="replace").replace("\n", " ")
            raise ValueError(f"initialize HTTP {status}: {snippet}")
        sid = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id") or ""
        if not sid:
            raise ValueError("initialize 响应缺少 mcp-session-id")
        return sid

    def call(self, tool: str, arguments: dict[str, Any], token: str) -> dict[str, Any]:
        """调一次工具，返回 {payload, raw_text}；失败抛 ValueError。"""
        payload = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        with self._lock:
            if not self._sid:
                self._sid = self._initialize(token)
            status, body, resp_headers = self._rpc(payload, token, session=self._sid)
            if status == 400:
                # 会话过期：清掉重 Initialize 一次（仅一次，避免无限重试）
                self._sid = self._initialize(token)
                status, body, resp_headers = self._rpc(payload, token, session=self._sid)
        if status != 200:
            snippet = body[:200].decode("utf-8", errors="replace").replace("\n", " ")
            raise ValueError(f"HTTP {status}: {snippet}")
        raw_text = body.decode("utf-8", errors="replace")
        # 不依赖响应头判形态：guarded_request 的头大小写不定，且 SSE 与 JSON
        # 在 body 层就能区分（SSE 必由 `data:` 行构成）。
        ctype = (resp_headers or {}).get("Content-Type") or (resp_headers or {}).get("content-type") or ""
        text = _extract_payload(raw_text, ctype)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON decode error: {e}") from e
        if "error" in data:
            raise ValueError(f"MCP error: {data['error']}")
        return _parse_result(data)


_SESSION = _Session()


def detect() -> tuple[bool, str]:
    """可用性判据 = 凭据就绪（不做网络探测：探测贵且会让 datasources 变慢）。"""
    if load_token():
        return True, f"{ENV_KEY} 已配置"
    return False, f"缺少 {ENV_KEY}（或 ~/.config/invest-cli/sfg.env）"


def call(tool: str, params: Optional[dict[str, Any]] = None, *, question: str = "") -> dict[str, Any]:
    """统一调用入口：返回 route.fetch 同构信封 {source, kind, ok, data, error}。

    `question` 是上游强制要求的用户原问题记录；缺省用工具名兜底（不空即可）。
    """
    token = load_token()
    if not token:
        return fail_envelope("sfg", tool, f"未设置 {ENV_KEY}")
    args = dict(params or {})
    args.setdefault("question", question or tool)
    cache_key = f"{tool}|{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
    import time

    hit = _CALL_CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < _CALL_TTL:
        return {**hit[1], "cached": True}
    try:
        parsed = _SESSION.call(tool, args, token)
        res = ok_envelope("sfg", tool, parsed["payload"])
    except Exception as e:
        return fail_envelope("sfg", tool, f"{type(e).__name__}: {e}")
    _CALL_CACHE[cache_key] = (time.monotonic(), res)
    return res


# ── 单只基金便捷入口（先搜后取，不猜后缀） ────────────────────

def fund(keyword: str) -> dict[str, Any]:
    """单只基金档案：名称/裸码先搜出标准码，再取档案。

    多候选不自动挑（A/C 份额、场内外同名产品并列时选错即答错标的），
    把 candidates 全列给调用方确认。
    """
    token = load_token()
    if not token:
        return fail_envelope("sfg", "fund", f"未设置 {ENV_KEY}")
    resolved = resolve_fund_code(keyword, token=token)
    if resolved.get("error"):
        return fail_envelope("sfg", "fund", str(resolved["error"]))
    if not resolved.get("code"):
        return fail_envelope("sfg", "fund", f"未找到匹配基金: {keyword!r}")
    if len(resolved.get("candidates") or []) > 1:
        env = fail_envelope(
            "sfg",
            "fund",
            "存在多个匹配，请指定标准码: "
            + ", ".join(f"{c['code']} {c['name']}" for c in resolved["candidates"]),
            input_error=True,
        )
        env["candidates"] = resolved["candidates"]
        return env
    return call("sfg_fund_profile", {"fund_code": resolved["code"]}, question=keyword)


# ── 自然语言入口（intent sfg / intent portfolio sfg） ─────────────

def auto(query: str) -> dict[str, Any]:
    """按查询形态选工具：多标的 → 组合体检；单标的 → 单只档案；否则 help。

    判据用**可数事实**而不是关键词猜测：先抽出查询里的 6 位代码/标准码个数。
    """
    q = str(query or "").strip()
    codes = _extract_codes(q)
    if len(codes) >= 2:
        # 服务端要求标准码（000001.OF / 510300.SH），裸码会回「代码格式」错误。
        # 组合诊断走**异步提交**：同步工具有 30s 服务端硬顶，实测两只基金即超时；
        # 官方指引是 submit 拿 job_id 后轮询（见 cmd_sfg.poll_portfolio）。
        resolved = [_resolve_code(c) for c in codes]
        bad = [c for c, r in zip(codes, resolved) if not r]
        if bad:
            return fail_envelope("sfg", "portfolio_check", "代码无法解析为标准码: " + ", ".join(bad))
        return call("sfg_portfolio_check_submit", {"codes": resolved}, question=q)
    if len(codes) == 1:
        return fund(codes[0])
    # 含「组合/持仓/体检/诊断」且像多只名称 → 组合；否则当单只名称
    if any(k in q for k in ("组合", "持仓", "体检", "诊断", "配置")):
        return call("sfg_portfolio_check_submit",
                    {"holdings": _parse_holdings_text(q)}, question=q)
    return fund(q)


# 上游实测：两只基金的体检 succeeded 耗时 298.9s / 340.2s（FOF 穿透是重活）。
# 旧默认 180s 会在结果落盘前返回 running，等于白提交一次——2026-11-21 复现。
# 取 420s 留出余量；CLI 侧 TIMEOUTS["sfg"] 同步抬到同值，避免调用方先被杀。
POLL_MAX_WAIT = 420


def poll_portfolio(job_id: str, *, interval: int = 5,
                   max_wait: int = POLL_MAX_WAIT) -> dict[str, Any]:
    """轮询组合诊断任务直到 succeeded/failed；超时也带 job_id 供再 poll。

    同步 sfg_portfolio_check 在服务端有 30s 硬顶，两只基金即实测超时；
    官方路径是 submit → 每 5 秒轮询。
    """
    import time as _time

    deadline = _time.monotonic() + max_wait
    last: dict[str, Any] = {}
    while _time.monotonic() < deadline:
        last = call("sfg_portfolio_check_result", {"job_id": job_id})
        payload = (last.get("data") or {}).get("result") or {}
        status = str(payload.get("status") or "")
        if status in ("succeeded", "failed", "error"):
            return last
        # 上游明确要退避多久就按它说的睡（默认 5s），不自行加密轮询
        retry = payload.get("retry_after_seconds")
        if isinstance(retry, (int, float)) and retry > 0:
            interval = max(interval, int(retry))
        _time.sleep(interval)
    # 超时不丢线索：显式置 ok=False（避免沿用 running 态的 ok=True 形成假成功），
    # 带上 job_id 与已等待时长，调用方可原样再 poll 一次。
    waited = round(_time.monotonic() - (deadline - max_wait), 1)
    return {
        **last,
        "ok": False,
        "poll_timeout": True,
        "job_id": job_id,
        "waited_seconds": waited,
        "error": f"轮询 {waited}s 后任务仍未完成（job_id={job_id}），"
                 f"可再次执行 invest-cli sfg --poll {job_id}",
    }


def _resolve_code(code: str) -> str:
    """裸码/标准码 → 标准码；解析不出返回空串（不猜后缀）。"""
    t = str(code or "").strip().upper()
    if _FUND_SUFFIX_RE.search(t):
        return t
    r = resolve_fund_code(t)
    return str((r.get("candidates") or [{}])[0].get("code") or "") if r.get("candidates") else ""


def _extract_codes(q: str) -> list[str]:
    """抽出查询里的标准码（含后缀）与裸 6 位代码，去重保序。"""
    out: list[str] = []
    for m in re.finditer(r"\b\d{6}(?:\.(?:OF|SH|SZ|BJ|HK))?\b", q, re.I):
        token = m.group(0).upper()
        if token not in out:
            out.append(token)
    return out


def _parse_holdings_text(q: str) -> list[dict[str, Any]]:
    """「005827:50,110011:50」这类文本 → holdings（权重缺省等权）。"""
    holdings: list[dict[str, Any]] = []
    for part in re.split(r"[,，;；\s]+", q):
        m = re.match(r"^(\d{6}(?:\.(?:OF|SH|SZ|BJ|HK))?)(?::([\d.]+))?$", part, re.I)
        if not m:
            continue
        code = m.group(1).upper()
        item: dict[str, Any] = {"fund_code": code}
        if m.group(2):
            item["weight"] = float(m.group(2))
        holdings.append(item)
    return holdings


# ── 语义别名（常用能力 → 工具名，供 `invest-cli sfg --list` 与 agent 路由） ──

ALIASES: dict[str, str] = {
    "help": "sfg_help",
    "search": "sfg_search_funds",
    "profile": "sfg_fund_profile",
    "performance": "sfg_fund_performance",
    "holdings": "sfg_fund_holdings",
    "report": "sfg_fund_report",
    "scale": "sfg_fund_scale_history",
    "manager-history": "sfg_fund_manager_history",
    "manager-institution": "sfg_fund_manager_institution",
    "screen": "sfg_screen_funds",
    "rankings": "sfg_rankings",
    "manager": "sfg_manager",
    "etf": "sfg_etf",
    "index": "sfg_index",
    "market": "sfg_market",
    "rotation": "sfg_rotation_strategy",
    "events": "sfg_events",
    "compare": "sfg_compare_funds",
    "share-cost": "sfg_share_cost",
    "stock-funds": "sfg_stock_funds",
    "similar": "sfg_similar_funds",
    "portfolio-parse": "sfg_portfolio_parse",
    "portfolio-check": "sfg_portfolio_check",
    "portfolio-submit": "sfg_portfolio_check_submit",
    "portfolio-result": "sfg_portfolio_check_result",
    "fof-underlying": "sfg_portfolio_fof_underlying",
    "style-exposure": "sfg_portfolio_style_exposure",
    "optimize": "sfg_portfolio_optimize_scenarios",
    "style-attribution": "sfg_portfolio_style_attribution",
    "suitability": "sfg_portfolio_suitability",
    "review-cadence": "sfg_portfolio_review_cadence",
    "compliance": "sfg_portfolio_compliance_trace",
    "fund-tong": "sfg_fund_tong",
    "api": "sfg_call_api",
}


# 未建语义别名的上游工具（45 - 34 = 11）。列出来是为了让发现层可见：
# 它们都能用完整 sfg_* 名直传调用，不登记只是没起短别名。
TOOLS_UNMAPPED: dict[str, str] = {
    "sfg_index_enhance": "指数增强筛选（按 r2/alpha/te/胜率/回撤阈值筛指数增强产品）",
    "sfg_micro_disk_overview": "微盘股概览（小市值风格观察）",
    "sfg_portfolio_report": "组合诊断报告落库（返回 report_id，需 client_id）",
    "sfg_portfolio_report_revoke": "撤销已生成的组合报告",
    # 边界外：投顾账户与客户域，invest-cli 定位只读数据分析，不消费这些
    "sfg_advisor_apply_status": "边界外：投顾资格申请状态查询",
    "sfg_advisor_apply": "边界外：投顾资格申请（写入客户联系方式）",
    "sfg_client_create": "边界外：创建投顾客户档案",
    "sfg_client_list": "边界外：投顾客户列表",
    "sfg_client_get": "边界外：投顾客户详情",
    "sfg_client_update": "边界外：更新投顾客户档案",
    "sfg_client_timeline": "边界外：投顾客户跟进时间线",
}


def resolve_tool(name: str) -> str:
    """别名/工具名归一：`profile` 与 `sfg_fund_profile` 等价；未知输入直接报错。"""
    t = str(name or "").strip()
    if not t:
        raise ValueError("缺少工具名")
    if t in ALIASES:
        return ALIASES[t]
    if t.startswith("sfg_"):
        return t
    raise ValueError(f"未知 sfg 工具或别名: {t!r}（invest-cli sfg --list 查看可用别名）")
