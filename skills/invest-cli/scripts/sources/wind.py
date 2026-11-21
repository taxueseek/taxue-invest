"""万得 Wind 数据源适配器（直连 MCP，不依赖 wind-mcp-skill 的 node CLI）。

取数路径：MCP JSON-RPC over HTTP（POST，`initialize` → `tools/call`），
认证用 `Authorization: Bearer <WIND_API_KEY>`（官方同一套，不新造）。
Key 顺序与官方一致：`~/.wind-aifinmarket/config` > skill config.json > 环境变量。

旧实现每次调用起一个 node 子进程（node CLI 冷启动 + 每次重新 initialize），
这里省掉这两段固定开销。

返回值契约不变：{source, ok, data, error}；data 为 MCP 结果解析后的业务 JSON。
"""
from __future__ import annotations

from ._http import guarded_open

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

CALL_TIMEOUT = 60
SOURCE = "wind"
SKILL_VERSION = "2.0.4"
GLOBAL_CONFIG = Path.home() / ".wind-aifinmarket" / "config"

# server_type → MCP 端点（与 wind-mcp-skill 的 registry 一致；不读 skill 目录）
_ENDPOINTS = {
    "stock_data": "https://mcp.wind.com.cn/vserver_stock_data/mcp/",
    "fund_data": "https://mcp.wind.com.cn/vserver_fund_data/mcp/",
    "index_data": "https://mcp.wind.com.cn/vserver_index_data/mcp/",
    "bond_data": "https://mcp.wind.com.cn/vserver_bond_data/mcp/",
    "financial_docs": "https://mcp.wind.com.cn/vserver_financial_docs/mcp/",
    "economic_data": "https://mcp.wind.com.cn/vserver_economic_data/mcp/",
    "analytics_data": "https://mcp.wind.com.cn/vserver_analytics_data/mcp/",
}


def _paired(cols: list, row: list, what: str) -> list[tuple[Any, Any]]:
    """列名与值按位配对；长度不匹配时报错，而不是静默截断。

    Wind 的表格回包是「列名列表 + 行值列表」，两者长度必须一致。裸 zip
    在长度不匹配时静默截断到较短的一侧：列名少一个，后面的值就整体
    左移一位，「基金成立日」拿到「基金经理」的值，且 rc=0、无任何信号，
    错得无声，比报错难查得多。这类缺陷在单测里也复现不了，因为桩通常
    两边都给齐。

    只在这一层校验一次：三个调用点（基金档案 / 年度字段 / 区间收益率）
    共用，改规则只改一处。

    不用 `zip(strict=True)`：那是 3.10 才有的参数（PEP 618），而 mx-data 按
    invest-stock 文档用系统 `python3`（本机 3.9.6）启动并进程内 import 这里，
    3.9 下会直接 `TypeError: zip() takes no keyword arguments`——守卫本身成了
    故障点。显式比较长度等价，且 3.9 起全版本可用。
    """
    if len(cols) != len(row):
        # 长度相等时这条路径永不触发，正常取数零成本。
        raise ValueError(
            f"{what}：列数 {len(cols)} 与值数 {len(row)} 不一致，"
            f"拒绝配对以免字段错位"
        )
    return list(zip(cols, row))


def _read_key_from_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, val = line.split("=", 1)
        if name.strip() == "WIND_API_KEY":
            return val.strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    """用户全局配置 > skill 本地 config.json > 环境变量（与官方顺序一致）。"""
    key = _read_key_from_file(GLOBAL_CONFIG)
    if key:
        return key
    skill_dir = os.environ.get("WIND_SKILL_DIR", "").strip()
    if skill_dir:
        try:
            cfg = json.loads((Path(skill_dir).expanduser() / "config.json").read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and isinstance(cfg.get("wind_api_key"), str):
                return cfg["wind_api_key"].strip()
        except (OSError, json.JSONDecodeError):
            pass
    # 最后一道回退同样走 read_env（进程环境 → launchctl → shell rc），
    # 只读 os.environ 会重演 hithink.detect 的漂移：用户把 key 配在 rc 文件里，
    # load/可用性两边结论不一致，源被静默丢掉。
    from .env import read_env

    return read_env("WIND_API_KEY")


def detect() -> tuple[bool, str]:
    if _api_key():
        return True, "WIND_API_KEY 已配置"
    return False, f"缺少 WIND_API_KEY（{GLOBAL_CONFIG} 或环境变量）"


def parse_wind_receipt(stdout: str) -> tuple[bool, Any, str]:
    """解析 MCP 回执，返回 (ok, data, error)。保留原契约供调用方复用。"""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        return False, None, f"Wind 回执非 JSON: {e}"
    if isinstance(envelope, dict) and envelope.get("isError"):
        return False, None, str(envelope.get("cli_meta", envelope))
    text = ""
    content = envelope.get("content") if isinstance(envelope, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text", "")
    if not text and isinstance(envelope, dict):
        text = envelope.get("message", "") or json.dumps(envelope, ensure_ascii=False)
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("error"):
                return False, None, f"Wind 返回错误: {parsed['error']}"
            return True, parsed, ""
        except (json.JSONDecodeError, TypeError):
            return True, text, ""
    return False, None, "Wind 回执缺少内容"


def _parse_sse(text: str) -> dict[str, Any]:
    """MCP 响应：后端正常走 SSE，部分错误场景纯 JSON。"""
    trimmed = text.strip()
    if trimmed.startswith("{"):
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            pass
    last = ""
    for line in text.splitlines():
        if line.startswith("data: "):
            last = line[6:]
    if last:
        return json.loads(last)
    raise RuntimeError(f"Wind 响应格式无法识别: {text[:200]}")


def _rpc(endpoint: str, api_key: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with guarded_open(req, CALL_TIMEOUT, allowed_host="mcp.wind.com.cn") as resp:
        payload = _parse_sse(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise RuntimeError("Wind 响应不是 JSON-RPC 对象")
    if payload.get("error"):
        err = payload["error"]
        msg = err if isinstance(err, str) else (err.get("message") or json.dumps(err, ensure_ascii=False))
        raise RuntimeError(f"Wind 接口错误: {msg}")
    return payload.get("result") or {}


def _call_raw(
    server_type: str,
    tool_name: str,
    params: Optional[dict] = None,
    params_json: Optional[str] = None,
) -> dict:
    """直连 Wind MCP 调一个契约工具。参数原样透传，不改字段名。"""
    endpoint = _ENDPOINTS.get(server_type)
    if not endpoint:
        return {"source": SOURCE, "ok": False, "data": None,
                "error": f"未知 server_type: {server_type}（可选: {'/'.join(_ENDPOINTS)}）"}
    api_key = _api_key()
    if not api_key:
        return {"source": SOURCE, "ok": False, "data": None, "error": "WIND_API_KEY 未配置"}
    if params_json is not None:
        try:
            params = json.loads(params_json) if params_json.strip() else {}
        except json.JSONDecodeError as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": f"--input 不是合法 JSON: {e}"}
    call_params = {
        "name": tool_name,
        "arguments": params or {},
        "_meta": {"clientVersion": SKILL_VERSION},
    }
    init_params = {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "invest-cli", "version": SKILL_VERSION},
    }
    try:
        # Wind 当前是无状态 MCP，tools/call 直接可用（实测省一次往返）。
        # 若上游以后要求先握手，_rpc 会抛协议/HTTP 错，下面补一次 initialize 重试。
        result = _rpc(endpoint, api_key, "tools/call", call_params)
    except RuntimeError:
        try:
            _rpc(endpoint, api_key, "initialize", init_params)
            result = _rpc(endpoint, api_key, "tools/call", call_params)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
            return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind HTTP {e.code}: {detail}"}
        except (urllib.error.URLError, OSError) as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind 网络失败: {e}"}
        except RuntimeError as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": str(e)}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
        return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind HTTP {e.code}: {detail}"}
    except (urllib.error.URLError, OSError) as e:
        return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind 网络失败: {e}"}
    ok, data, err = parse_wind_receipt(json.dumps(result, ensure_ascii=False))
    return {"source": SOURCE, "ok": ok, "data": data, "error": err or None}


# 进程内熔断：额度/鉴权类**硬失败**不可能在一条命令内自愈，继续打只是把同一个失败
# 重复 N 次（实测 Wind 积分耗尽时，6 只基金 × 4 次调用 = 24 次无谓往返，纯等网络）。
# 只熔断硬失败：网络抖动是瞬时的，必须留给下一次重试——把抖动也熔断会让整条命令
# 因为一次超时降级到快路径，那是「用错误换速度」。
_UNUSABLE = ""
_HARD_FAILURE_KEYS = ("积分", "余额不足", "未配置", "鉴权", "认证", "API key", "HTTP 401", "HTTP 403")


def _is_hard_failure(err: str) -> bool:
    return any(k in err for k in _HARD_FAILURE_KEYS)


def call(
    server_type: str,
    tool_name: str,
    params: Optional[dict] = None,
    params_json: Optional[str] = None,
) -> dict:
    """call 的对外入口：带进程内熔断（硬失败短路），其余行为与 _call_raw 完全一致。"""
    global _UNUSABLE
    if _UNUSABLE:
        return {"source": SOURCE, "ok": False, "data": None, "error": _UNUSABLE}
    res = _call_raw(server_type, tool_name, params, params_json)
    if not res.get("ok"):
        err = str(res.get("error") or "")
        if _is_hard_failure(err):
            _UNUSABLE = err
    return res


# ═══ 任职期复盘（tenure）取数原语 ═══
#
# 三个 Wind 特有的坑收敛在这里，避免每个调用方各踩一遍：
#   1. get_fund_performance 的自然语言入口**单次硬顶 100 行**（实测 2026-09-23：
#      问「全部」也只回 100 行），长序列必须分段 + 并行，段宽见 NAV_CHUNK_DAYS；
#   2. fund_data 与 index_data 的响应包装层数不同（前者多一层 data[0]），
#      统一在 _first_rows，调用方不再各写一份 try/except；
#   3. 场外基金没有场内行情（get_fund_kline 只覆盖 ETF/LOF），净值只能走 performance 族。
#
# 全部走 _common 的磁盘缓存：净值/指数/档案都是日更数据，6 小时 TTL 足够同轮复用，
# 也让「改口径重算」不再重复打 Wind（实测 6 只基金全量重取 ≈ 75s，命中缓存 <0.1s）。

NAV_CHUNK_DAYS = 120  # 120 自然日 ≈ 80 个交易日，对 100 行硬顶留 20% 余量
CACHE_TTL_TENURE = 6 * 3600.0
_TENURE_NS = "tenure"


def _first_rows(resp: dict) -> tuple[list[str], list[list]]:
    """统一取 (列名, 行)。两种包装：fund_data → data.data.data[0]；index_data → data.data。"""
    try:
        blk = resp["data"]["data"]["data"]
        if isinstance(blk, list) and blk:
            return [c["name"] for c in blk[0]["columns"]], blk[0]["rows"]
    except (KeyError, TypeError, IndexError):
        pass
    try:
        blk = resp["data"]["data"]
        if isinstance(blk, dict) and "columns" in blk:
            return [c["name"] for c in blk["columns"]], blk["rows"]
    except (KeyError, TypeError):
        pass
    return [], []


def _d(x: Any) -> str:
    """日期归一：'2022-09-13T00:00:00.000+08:00' 与 '2022-09-13' 都收敛成 ISO 日期。"""
    return str(x)[:10]


def _cached(ns_key: str, producer):
    from _common import cache_get, cache_set

    hit = cache_get(_TENURE_NS, ns_key, CACHE_TTL_TENURE)
    if hit is not None:
        return hit
    val = producer()
    if isinstance(val, dict) and val.get("ok"):
        cache_set(_TENURE_NS, ns_key, val)
    return val


def fund_nav_series(code: str, name: str, begin: str, end: str, workers: int = 4) -> dict:
    """复权单位净值日序列（分段并行）。返回 {ok, series:[(日期, 净值)], calls, error}。

    分段抓取而非一次问全：Wind 的自然语言入口有 100 行硬顶，不问「全部」是因为
    问了也只会回 100 行 —— 静默截断比报错更危险，宁可按已知硬顶分段。
    任一段重试后仍失败 → ok=False（不返回残缺序列：缺口会让累计收益率偏小且不报错）。
    """
    from concurrent.futures import ThreadPoolExecutor

    from tenure_calc import split_chunks

    def produce() -> dict:
        jobs = split_chunks(begin, end, NAV_CHUNK_DAYS)
        out: dict[str, float] = {}
        failed: list[str] = []

        def one(seg: tuple[str, str]):
            b, e = seg
            q = f"{code} {name} 从{b}到{e}的复权单位净值日序列"
            for _ in range(2):  # 一段一次重试：Wind 偶发 5xx 不值得整单失败
                res = call("fund_data", "get_fund_performance", params={"question": q})
                if res.get("ok"):
                    _, rows = _first_rows(res)
                    if rows:
                        return rows
            return None

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            # 显式校验「段与结果一一对应」这一不变量：executor.map 保序保长，
            # 长度一旦对不上说明上游行为变了，此时该炸而不是让后续
            # `seg[0]~seg[1]` 的失败归因张冠李戴。
            # 不用 `zip(strict=True)`：3.10 起才有（PEP 618），3.9 会 TypeError。
            results = list(ex.map(one, jobs))
            if len(results) != len(jobs):
                raise RuntimeError(
                    f"复权净值分段取数：{len(jobs)} 段返回 {len(results)} 份结果，"
                    f"拒绝按位配对以免失败归因错位"
                )
            for seg, rows in zip(jobs, results):
                if rows is None:
                    failed.append(f"{seg[0]}~{seg[1]}")
                    continue
                for row in rows:
                    if len(row) < 4 or row[2] is None:
                        continue
                    out[_d(row[3])] = float(row[2])
        if failed:
            return {"ok": False, "series": [], "calls": len(jobs),
                    "error": f"{len(failed)}/{len(jobs)} 段取数失败: {', '.join(failed[:3])}"}
        series = sorted(out.items())
        if not series:
            return {"ok": False, "series": [], "calls": len(jobs), "error": "Wind 未返回净值数据"}
        return {"ok": True, "series": series, "calls": len(jobs), "error": None}

    return _cached(f"nav|{code}|{begin}|{end}", produce)


def index_series(windcode: str, begin: str, end: str) -> dict:
    """指数收盘点位日序列（一次调用，无行数上限）。返回 {ok, series:[(日期, 收盘)], error}。

    仅返回有行情的交易日：含港股仓位的基金业绩基准指数（基金代码+BI.WI）在港股假期
    无行情（实测 011371BI.WI 缺 21 天），缺口由 tenure_calc.align_index 前值沿用处理。

    P3 覆盖区间复用：tenure 入口在拉指数前，先取
    [min(各基金基期) → max(各基金 end)] 的超集区间一次拉取，各基金再切片。
    同 code 的精确区间缓存（idx|<code>|<begin>|<end>）仍由 _cached 兜底。
    Wind 按调用次数计费，一次全量比 N 次分段更便宜；切片不改变任何点位口径。
    """

    def produce() -> dict:
        res = call("index_data", "get_index_kline",
                   params={"windcode": windcode, "begin_date": begin, "end_date": end})
        if not res.get("ok"):
            return {"ok": False, "series": [], "error": res.get("error") or "取数失败"}
        _, rows = _first_rows(res)
        series = sorted((_d(r[0]), float(r[2])) for r in rows if r[2] not in (None, ""))
        if not series:
            return {"ok": False, "series": [], "error": f"{windcode} 无行情数据"}
        return {"ok": True, "series": series, "error": None}

    return _cached(f"idx|{windcode}|{begin}|{end}", produce)


_PROFILE_Q = ("{code} {name} 的基金全称、基金成立日、最新现任基金经理姓名、"
              "最新现任基金经理任职日期、历任基金经理姓名和任职时间、业绩比较基准、"
              "投资类型_二级分类、基金规模合计")
_PROFILE_KEYS = {
    "证券简称": "short_name", "基金全称": "full_name", "基金成立日": "inception",
    "最新现任基金经理姓名": "managers",
    "现任基金经理姓名": "managers", "最新现任基金经理任职日期": "manager_since",
    "历任基金经理姓名和任职时间": "manager_history", "业绩比较基准": "benchmark",
    "投资类型_二级分类": "fund_type", "基金规模合计": "aum", "分级基金规模": "aum",
}


def fund_profile(code: str, name: str = "") -> dict:
    """基金档案：成立日 / 现任与历任基金经理及任职时间 / 业绩比较基准 / 类型 / 规模。"""

    def produce() -> dict:
        res = call("fund_data", "get_fund_info", params={"question": _PROFILE_Q.format(code=code, name=name)})
        if not res.get("ok"):
            return {"ok": False, "data": None, "error": res.get("error") or "取数失败"}
        cols, rows = _first_rows(res)
        if not rows:
            return {"ok": False, "data": None, "error": f"{code} 未找到基金档案"}
        row = rows[0]
        data: dict[str, Any] = {}
        for col, val in _paired(cols, row, "基金档案"):
            key = _PROFILE_KEYS.get(col)
            if key and val not in (None, ""):
                data.setdefault(key, val)
        if "inception" in data:
            data["inception"] = _d(data["inception"])
        if "manager_since" in data:
            data["manager_since"] = _d(data["manager_since"])
        return {"ok": True, "data": data, "error": None}

    return _cached(f"profile|{code}", produce)


def fund_annual_stats(code: str, name: str, years: list[int]) -> dict:
    """年度收益率 / 年度最大回撤（Wind 官方字段），返回 {ok, data:{年: {ret, mdd}}}（小数）。"""

    def produce() -> dict:
        q = f"{code} {name} 的" + "、".join(f"{y}年年度收益率、{y}年最大回撤" for y in years)
        res = call("fund_data", "get_fund_performance", params={"question": q})
        if not res.get("ok"):
            return {"ok": False, "data": None, "error": res.get("error") or "取数失败"}
        cols, rows = _first_rows(res)
        if not rows:
            return {"ok": False, "data": None, "error": "Wind 未返回年度字段"}
        row = rows[0]
        data: dict[int, dict] = {}
        for col, val in _paired(cols, row, "年度业绩字段"):
            for y in years:
                if col.startswith(f"{y}年年度收益率"):
                    data.setdefault(y, {})["ret"] = float(val) / 100.0 if val is not None else None
                elif col.startswith(f"{y}年最大回撤"):
                    data.setdefault(y, {})["mdd"] = float(val) / 100.0 if val is not None else None
        return {"ok": True, "data": data, "error": None}

    return _cached(f"annual|{code}|{'-'.join(map(str, years))}", produce)


def range_return(code: str, name: str, begin: str, end: str) -> dict:
    """区间复权净值增长率（%），用于校验本地复算的累计收益率。"""

    def produce() -> dict:
        q = f"{code} {name} 从{begin}到{end}的复权单位净值增长率（累计区间收益率，非年化）"
        res = call("fund_data", "get_fund_performance", params={"question": q})
        if not res.get("ok"):
            return {"ok": False, "value": None, "error": res.get("error") or "取数失败"}
        cols, rows = _first_rows(res)
        if not rows:
            return {"ok": False, "value": None, "error": "Wind 未返回区间收益率"}
        for col, val in _paired(cols, rows[0], "区间收益率"):
            if ("增长率" in col or "收益率" in col) and val is not None:
                return {"ok": True, "value": float(val) / 100.0, "error": None}
        return {"ok": False, "value": None, "error": "区间收益率字段缺失"}

    return _cached(f"range|{code}|{begin}|{end}", produce)


def manager_funds(manager: str, company: str = "") -> dict:
    """基金经理在管产品（含份额类别与任职日期）。返回 {ok, rows:[{code,name,appt,company}]}。"""

    def produce() -> dict:
        q = f"{company}{manager}管理的所有基金产品"
        res = call("fund_data", "search_funds", params={"question": q})
        if not res.get("ok"):
            return {"ok": False, "rows": None, "error": res.get("error") or "取数失败"}
        cols, rows = _first_rows(res)
        if not rows:
            return {"ok": False, "rows": None, "error": f"未找到 {manager} 的在管产品"}
        idx = {c: i for i, c in enumerate(cols)}
        out = []
        for row in rows:
            code = row[idx.get("基金代码", 1)]
            name = row[idx.get("基金经理在管基金名称", 2)]
            appt = row[idx.get("任职日期", 3)]
            if str(row[idx.get("基金经理姓名", 0)]).strip() != manager.strip():
                continue  # 名称模糊命中他人时剔除
            out.append({"code": code, "name": name, "appt": _d(appt),
                        "company": row[idx.get("基金经理在管基金管理人", 4)]})
        if not out:
            return {"ok": False, "rows": None, "error": f"{manager} 无在管产品"}
        return {"ok": True, "rows": out, "error": None}

    return _cached(f"manager|{manager}|{company}", produce)
