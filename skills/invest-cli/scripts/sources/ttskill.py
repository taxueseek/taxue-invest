#!/usr/bin/env python3
"""天天基金数据适配器（invest-cli 数据源，直连 gateway，不依赖 ttskill CLI）。

能力：公募基金结构化快照（默认深取层，对应 invest-fund/references/data-pipeline.md）：
  - 名称/代码解析（TTFUND_SEARCH）
  - 详情+业绩+风险族（夏普/波动/回撤+成立来）+费率梯度+业绩基准（TTFUND_BASE_INFOS）
  - 十大重仓/行业/资产配置 + 报告期（TTFUND_HOLDING_INFO）

约定（与 data-pipeline.md 互为镜像，改映射必须两边同步）：
  - 返回信封对齐 route.fetch：{source, kind, ok, data, error}
  - 快照 schema 对齐 cmd_fund.format_terminal（data 用中文键；holdings 用 stock_name/hold_ratio）

取数路径：**直连官方 gateway**（POST /openapi/skill/invoke），不再起 ttskill 子进程。
  - 认证沿用官方凭据存储（macOS Keychain `com.ttfund.ttskill.base`，兼容 auth/*.json 回退），
    用 ed25519 设备密钥签请求头（与官方基础包同一套认证逻辑，不新造）。
  - 不再依赖官方 CLI 二进制；只依赖「已登录一次」的凭据。

口径（110011 实测 2026-09-03，勿按旧文档改）：
  - BASE：body.expansion.comprehensive_info.fund_profile_overview.{FTYPE,SHORTNAME,FULLNAME,ENDNAV(元),ESTABDATE,JJGS,JJJL,BENCH}
  - 风险在 unique_info[0]（数组首元素，不是对象）；卡玛无直出 = 近1年收益 ÷ |近1年最大回撤|
  - 阶段涨幅 period_increase[]：title∈{Y=近1月,3Y=近3月,6Y=近6月,1N=近1年,2N,3N,5N,JN=今年来,LN=成立来}，Z=近1周不展示
  - 费率 purchase/redeem/service 在 body.expansion.trade_info.fee_rates；管理费/托管费接口不返回
  - HOLDING 有 body.data 包装；QDII 等顶层 top_holdings.stocks 可能为空 → 从 data.periods[-1] 取
"""
from __future__ import annotations

from ._http import guarded_open

# 运行期依赖声明（route.candidates 缺件摘链用，写 import 名而非 pip 名）：
# ed25519 签名用的 cryptography 在函数内延迟 import，缺件解释器上适配器
# 本体照样可导入，不声明就会排进 fund 链头、fetch 时才炸。
REQUIRED_IMPORTS = ("cryptography",)

import base64
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SOURCE_LABEL = "天天基金"

# ═══ 官方认证（沿用官方凭据存储，不新造）═══
GATEWAY = "https://skills-api.tiantianfunds.com/ai-smart-skill-service"
INVOKE_PATH = "/openapi/skill/invoke"
KEYCHAIN_SERVICE = "com.ttfund.ttskill.base"
RUNTIME_HOME = Path.home() / "Library" / "Application Support" / "TTFund" / "ttfund-skills"
SKILLS_INDEX = RUNTIME_HOME / "skills" / "index.json"
INVOKE_TIMEOUT = 30

# period_increase.title → 展示标签（110011 实测值反推；Z=近1周不进快照）
PERIOD_LABELS = {
    "Y": "近1月回报", "3Y": "近3月回报", "6Y": "近6月回报",
    "1N": "近1年回报", "2N": "近2年回报", "3N": "近3年回报",
    "5N": "近5年回报", "JN": "今年来回报", "LN": "成立来回报",
}
RISK_DISPLAY = {  # unique_info[0] 键 → cmd_fund 展示键
    "STDDEV1": "波动率", "SHARP1": "夏普比率", "MAXRETRA1": "最大回撤",
}


def _b64url(data: bytes) -> str:
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_").rstrip("=")


def _keychain_account(record: str, legacy_path: str) -> str:
    """官方 Keychain 账户名：`<record>:<legacy_path 的 sha256 前 16 位>`。"""
    return f"{record}:{hashlib.sha256(legacy_path.encode()).hexdigest()[:16]}"


# 凭据在进程生命周期内不会变（CLI 每进程只跑一条命令）：缓存一次，避免每次
# `_invoke` 都重跑 `security find-generic-password`（fund 深取会调 2 次）。
_CRED_CACHE: dict[str, dict[str, Any] | None] = {}


def _read_credential(record: str) -> dict[str, Any] | None:
    """读官方凭据：macOS Keychain 优先，兼容 auth/*.json 回退。

    只读不回显；任何失败都返回 None（调用方按未登录处理）。
    注意：record 是内部名（token/deviceKey），Keychain 账户前缀是官方名（token/device-key）。
    """
    if record in _CRED_CACHE:
        return _CRED_CACHE[record]
    acct_prefix, filename = {
        "token": ("token", "token.json"),
        "deviceKey": ("device-key", "device-key.json"),
    }.get(record, (record, f"{record}.json"))
    legacy = RUNTIME_HOME / "auth" / filename
    result: dict[str, Any] | None = None
    if sys.platform == "darwin":
        acct = _keychain_account(acct_prefix, str(legacy))
        try:
            proc = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", acct, "-w"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout.strip())
                if isinstance(data, dict):
                    result = data
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            result = None
    if result is None:
        try:
            if legacy.is_file():
                data = json.loads(legacy.read_text(encoding="utf-8"))
                result = data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            result = None
    _CRED_CACHE[record] = result
    return result


def _jwt_exp(token: str) -> int:
    """从 JWT 里取 exp（不验签，只读声明）。"""
    parts = (token or "").split(".")
    if len(parts) < 2:
        return 0
    text = parts[1].replace("-", "+").replace("_", "/")
    text += "=" * (4 - len(text) % 4) if len(text) % 4 else ""
    try:
        return int(json.loads(base64.b64decode(text)).get("exp", 0) or 0)
    except Exception:
        return 0


def _token_state() -> tuple[bool, str]:
    """返回 (是否可用, 说明)。判据是「有 token 且未过期」，不是「文件在磁盘上」。"""
    token = _read_credential("token")
    if not token:
        return False, "未登录天天基金（缺 token 凭据）"
    if not _read_credential("deviceKey"):
        return False, "缺少设备密钥凭据（device-key）"
    access = token.get("access_token") or token.get("accessToken") or ""
    if not access:
        return False, "凭据里没有 access_token"
    exp = _jwt_exp(access) or int(token.get("saved_at", 0) or 0) + int(token.get("expires_in", 0) or 0)
    if exp and exp <= int(time.time()):
        return False, f"登录已过期（{time.strftime('%Y-%m-%d', time.gmtime(exp))}）"
    return True, "已登录"


def detect() -> tuple[bool, str]:
    """可用性 = 有凭据且未过期，且本机至少装了一个业务包。

    旧实现跑 `ttskill status --json` 子进程（~0.3s/次，且要 CLI 在 PATH）；
    这里直接读凭据 + 读已装包索引，零子进程。
    """
    ok, detail = _token_state()
    if not ok:
        return False, detail
    if not _installed_skills():
        return False, "已登录但未安装业务包"
    return True, detail


def _installed_skills() -> dict[str, str]:
    """已装业务包 {skill_id: version}，取自官方 skills/index.json（不跑 CLI）。"""
    try:
        data = json.loads(SKILLS_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    # index.json 形状为 {"skills": [...]}（旧版可能是裸数组，两种都收）
    items = data.get("skills") if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        sid = item.get("skill_id")
        if sid and str(item.get("status", "enabled")) != "disabled":
            out[str(sid)] = str(item.get("version") or "0.0.0")
    return out


def _sign_headers(method: str, path: str, body: bytes, session_id: str, private_key_pem: str) -> dict[str, str]:
    """ed25519 签名头（与官方基础包同一套认证逻辑）。"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    body_sha = hashlib.sha256(body).hexdigest()
    sign_path = path
    prefix = "/ai-smart-skill-service"
    if sign_path.startswith(prefix + "/openapi/"):
        sign_path = sign_path[len(prefix):]
    payload = f"{method.upper()}\n{sign_path}\n{body_sha}\n{timestamp}\n{nonce}\n{session_id}".encode()
    key = load_pem_private_key(private_key_pem.encode(), password=None)
    return {
        "X-Session-Id": session_id,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Body-SHA256": body_sha,
        "X-Signature": _b64url(key.sign(payload)),
    }


def _invoke(skill_id: str, body: dict[str, Any], action: str = "query") -> dict[str, Any]:
    """直连 gateway 调业务包 → body 信封。失败抛 RuntimeError。

    与 `ttskill invoke` 等价，但少一次子进程与一次 JSON 往返。
    版本从本机 index.json 取（官方 CLI 也这么做）；409 时用服务端 latest 重试一次。
    """
    token = _read_credential("token")
    key_info = _read_credential("deviceKey")
    if not token or not key_info:
        raise RuntimeError("未登录天天基金（缺凭据），请先完成一次官方登录")
    access = token.get("access_token") or token.get("accessToken") or ""
    session_id = token.get("session_id") or token.get("sessionId") or ""
    if not access or not session_id:
        raise RuntimeError("登录态无效（缺 access_token/session_id），请重新登录")
    pem = key_info.get("device_private_key_pem") or ""
    if not pem:
        raise RuntimeError("设备密钥凭据损坏（缺 device_private_key_pem），请重新登录")
    version = _installed_skills().get(skill_id, "0.0.0")

    def _post(ver: str) -> dict[str, Any]:
        payload = {**body, "skill_id": skill_id, "_skill_version": ver, "action": action}
        data = json.dumps(payload, ensure_ascii=False).encode()
        headers = {
            "Content-Type": "application/json",
            "X-TTSkill-Env": "prod",
            "Authorization": f"Bearer {access}",
            **_sign_headers("POST", INVOKE_PATH, data, session_id, pem),
        }
        req = urllib.request.Request(GATEWAY + INVOKE_PATH, data=data, headers=headers, method="POST")
        with guarded_open(req, INVOKE_TIMEOUT,
                          allowed_host="skills-api.tiantianfunds.com") as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    try:
        payload = _post(version)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise RuntimeError("天天基金登录已失效，请重新登录") from e
        if e.code == 409 and "skill_version_required" in err_body:
            # 本地版本落后于 gateway：用响应里的 latest 重试一次
            try:
                meta = json.loads(err_body)
            except json.JSONDecodeError:
                meta = {}
            latest = (meta.get("latest_version") or meta.get("skill_version_required")
                      or (meta.get("data") or {}).get("latest_version"))
            if latest and str(latest) != str(version):
                payload = _post(str(latest))
            else:
                raise RuntimeError(f"{skill_id} 业务包版本不匹配：{err_body[:200]}") from e
        else:
            raise RuntimeError(f"{skill_id} 调用失败 HTTP {e.code}: {err_body[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"天天基金 gateway 不可达: {e}") from e

    if payload.get("code") not in (0, None):
        raise RuntimeError(f"{skill_id} 调用失败: {str(payload.get('message'))[:200]}")
    raw = ((payload.get("data") or {}).get("raw_result") or {}).get("body") or {}
    ec = raw.get("errorCode")
    # 成功码各包不一：BASE/HOLDING 用 0，GOLD 等用 200；以 success=false 或 code∉{0,200} 判失败
    if raw.get("success") is False or (ec is not None and ec not in (0, 200)):
        raise RuntimeError(f"{skill_id} 业务失败: {(raw.get('message') or raw.get('firstError') or ec or '')[:200]}")
    return raw


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _common_run(a: str, b: str) -> int:
    """最长公共连续子串长度（防模糊解析 fail-open：垃圾名会被服务端配到无关基金）。"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def resolve_fcode(keyword: str) -> tuple[str, str]:
    """名称/代码 → (fcode, name)。6 位代码直通；名称 SEARCH 结果必须与查询相关。"""
    kw = (keyword or "").strip()
    if kw.isdigit() and len(kw) == 6:
        return kw, kw
    raw = _invoke("TTFUND_SEARCH", {"query": kw, "search_type": "fund", "page_index": 1, "page_size": 5})
    cands = (((raw.get("data") or {}).get("candidates")) or [])
    threshold = max(2, min(3, sum(1 for ch in kw if "\u4e00" <= ch <= "\u9fff")))
    for c in cands:
        name = c.get("name") or ""
        if (c.get("display_code") or "").isdigit() and _common_run(kw, name) >= threshold:
            return c["display_code"], name or kw
    raise RuntimeError(f"基金搜索无相关候选: {kw}")


def search_funds(query: str, page_index: int = 1, page_size: int = 50) -> dict[str, Any]:
    """TTFUND_SEARCH 分页搜索（研究管线用；候选只有名称/类别/可购状态，无业绩字段）。

    注意：query 是**名称子串匹配**，不是语义检索（2026-10-11 实测教训），
    调用方要先提炼关键词再进来。返回标准信封，data 含 candidates/total_count。
    """
    try:
        raw = _invoke("TTFUND_SEARCH", {"query": query, "search_type": "fund",
                                        "page_index": page_index, "page_size": page_size})
    except RuntimeError as e:
        return {"source": "ttskill", "ok": False, "data": None, "error": str(e)}
    return {"source": "ttskill", "ok": True, "data": raw.get("data") or {}, "error": None}


def _base_snapshot(code: str) -> dict[str, Any]:
    raw = _invoke("TTFUND_BASE_INFOS", {"fcode": code, "nav_range": "n"})
    ci = (raw.get("expansion") or {}).get("comprehensive_info") or {}
    fpo = ci.get("fund_profile_overview") or {}
    ui = (ci.get("unique_info") or [{}])[0] if isinstance(ci.get("unique_info"), list) else (ci.get("unique_info") or {})
    fees = ((raw.get("expansion") or {}).get("trade_info") or {}).get("fee_rates") or {}

    d: dict[str, Any] = {}
    for k, label in [("FTYPE", "基金类型"), ("ESTABDATE", "成立日期"), ("JJGS", "基金管理人")]:
        if fpo.get(k):
            d[label] = fpo[k]
    if fpo.get("SHORTNAME"):
        d["基金名称"] = fpo["SHORTNAME"]
    if fpo.get("ENDNAV") is not None:  # 元 → 保留数值，展示层 ≥1e8 自动换亿
        d["基金规模"] = _num(fpo["ENDNAV"])
    for t, label in PERIOD_LABELS.items():
        for row in ci.get("period_increase") or []:
            if str(row.get("title")) == t and row.get("syl") is not None:
                d[label] = _num(row["syl"])
                # 同类分位 = rank/sc（越小越好），data-pipeline.md 口径；只取风险审查最常用的两个周期
                rank, sc = row.get("rank"), row.get("sc")
                if label in ("近1年回报", "近3年回报") and rank is not None and sc is not None:
                    d[label.replace("回报", "同类分位")] = f"{rank}/{sc}"
                break
    for key, label in RISK_DISPLAY.items():
        if ui.get(key) is not None:
            d[label] = _num(ui[key])
    if ui.get("JGBL") is not None:
        # 机构占比%（fund_holder_structure[].JGBL 同源）；非风险指标，单独映射
        d["机构占比"] = _num(ui["JGBL"])
    y1 = d.get("近1年回报")
    mdd = d.get("最大回撤")
    if y1 is not None and mdd is not None and mdd:
        # 卡玛 = 近1年收益 ÷ |最大回撤幅度|：带符号（亏损期应为负），不能用 abs 抹掉
        d["卡玛比率"] = round(y1 / abs(mdd), 2)
    mgr = (fpo.get("JJJL") or "").split(",")[0].strip()
    if mgr:
        d["经理姓名"] = mgr
    if fees.get("purchase"):
        rates = [r for r in fees["purchase"] if isinstance(r, dict)]
        if rates:
            rate = rates[0].get("rate")
            src = rates[0].get("source")
            d["申购费率"] = rate if rate is not None else src
    return d


def _holding_list(code: str) -> tuple[list[dict[str, Any]], str, str]:
    raw = _invoke("TTFUND_HOLDING_INFO", {"fund_id": code, "holding_type": "stock", "period_mode": "latest"})
    data = raw.get("data") or {}
    ho = data.get("holding_overview") or {}
    report_date = ho.get("report_date") or ""
    periods = data.get("periods") or []
    top = data.get("top_holdings") or {}
    stocks = top.get("stocks") or []
    industry = data.get("industry_allocation") or []
    if not stocks and periods:
        latest = periods[-1]
        stocks = ((latest.get("top_holdings") or {}).get("stocks")) or []
        industry = latest.get("industry_allocation") or industry
        report_date = latest.get("report_date") or report_date
    industry_ratio = ""
    if industry:
        top_ind = max(industry, key=lambda r: _num(r.get("ZJZBL")) or 0)
        industry_ratio = f"{top_ind.get('HYMC', '')} {top_ind.get('ZJZBL', '')}%"
    rows = []
    for s in stocks[:10]:
        rows.append({
            "entityName": s.get("GPJC", ""),
            "stock_name": s.get("GPJC", ""),
            "hold_ratio": _num(s.get("JZBL")),
            "change": s.get("PCTNVCHGTYPE", ""),
        })
    return rows, report_date, industry_ratio


def invoke_scene(skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """通用场景透传（intent 等上层用）：调官方业务包并原样返回 body。"""
    try:
        raw = _invoke(skill_id, body)
        return {"source": "ttskill", "kind": skill_id, "ok": True, "data": raw, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"source": "ttskill", "kind": skill_id, "ok": False, "data": None, "error": str(e)}


def fund(keyword: str) -> dict[str, Any]:
    """fund 数据源入口：route.fetch 整单调用，失败抛异常由 route 回退。"""
    try:
        code, name = resolve_fcode(keyword)
        # BASE 与 HOLDING 是两条独立的 ttskill 子进程调用（各含一次 CLI 冷启动），
        # 串行等于把两段等待相加；拿到 code 后两者无依赖，并发提交。
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_base = pool.submit(_base_snapshot, code)
            f_hold = pool.submit(_holding_list, code)
            d = f_base.result()
            holdings, report_date, industry = f_hold.result()
        if not d.get("基金类型"):
            d["基金类型"] = "未知（ttskill 未返回类型）"
        data = {
            "code": code,
            "name": name if not name.isdigit() else d.get("基金名称") or name,
            "timestamp": datetime.now().isoformat(),
            "source_label": SOURCE_LABEL,
            "warnings": [
                "管理费/托管费 ttskill 不返回，需 f10 档案页补查",
                f"持仓报告期 {report_date or '未知'}（滞后一季属正常）",
            ] if report_date else ["报告期未返回"],
            "data": d,
            "holdings": holdings,
        }
        if report_date:
            data["report_date"] = report_date
        if industry:
            data["top_industry"] = industry
        return {"source": "ttskill", "kind": "fund", "ok": True, "data": data, "error": None}
    except Exception as e:  # noqa: BLE001 —— 路由层需要字符串化错误以回退
        return {"source": "ttskill", "kind": "fund", "ok": False, "data": None, "error": str(e)}


if __name__ == "__main__":  # 快速自检：python3 sources/ttskill.py 110011
    code = sys.argv[1] if len(sys.argv) > 1 else "110011"
    print(json.dumps(fund(code), ensure_ascii=False, indent=2, default=str)[:1500])


def manager_funds(manager: str) -> dict:
    """经理在管产品（ttskill MANAGER_INFO）：含任职日 FEMPDATE。

    这是 Wind search_funds 的降级替代：字段更全（规模/任职回报/1年收益），
    但**份额类别要自己从名称推**（上游给的是 FCODE+SHORTNAME），且没有「公司」入参。
    """
    from _common import CACHE_TTL_FUNDAMENTAL, cache_get, cache_set

    key = f"mgr|{manager}"
    hit = cache_get("tenure", key, CACHE_TTL_FUNDAMENTAL)
    if hit is not None:
        return hit
    try:
        raw = _invoke("TTFUND_MANAGER_INFO", {"manager_name": manager})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "rows": None, "error": str(e)}
    data = raw.get("data") or {}
    profile = data.get("manager_profile") or {}
    rows = []
    for f in data.get("managed_funds") or []:
        rows.append({
            "code": f.get("FCODE") or "",
            "name": f.get("SHORTNAME") or "",
            "appt": (f.get("FEMPDATE") or "")[:10],
            "company": profile.get("company") or "",
            "aum": _num(f.get("ENDNAV")),
        })
    if not rows:
        return {"ok": False, "rows": None, "error": f"ttskill 未返回 {manager} 的在管产品"}
    out = {"ok": True, "rows": rows, "error": None}
    cache_set("tenure", key, out)
    return out


def base_profile(code: str) -> dict[str, Any]:
    """基金档案（ttskill BASE_INFOS）：成立日 / 业绩基准 / 现任经理 / 类型 / 规模。

    相对 Wind get_fund_info 的缺口：**没有历任基金经理任职时间**（只有现任姓名），
    降级路径下「任职日」只能由 --since 显式给出、或退回成立日。这个缺口由
    cmd_tenure 在提示里说明，不假装有数据。
    """
    from _common import CACHE_TTL_FUNDAMENTAL, cache_get, cache_set

    key = f"base|{code}"
    hit = cache_get("tenure", key, CACHE_TTL_FUNDAMENTAL)
    if hit is not None:
        return hit
    try:
        raw = _invoke("TTFUND_BASE_INFOS", {"fcode": code, "nav_range": "n"})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "data": None, "error": str(e)}
    fpo = (((raw.get("expansion") or {}).get("comprehensive_info") or {})
           .get("fund_profile_overview") or {})
    if not fpo:
        return {"ok": False, "data": None, "error": "ttskill 未返回基金档案"}
    data = {
        "full_name": fpo.get("FULLNAME") or fpo.get("SHORTNAME") or "",
        "short_name": fpo.get("SHORTNAME") or "",
        "inception": fpo.get("ESTABDATE") or "",
        "benchmark": fpo.get("BENCH") or "",
        "managers": fpo.get("JJJL") or "",
        "fund_type": fpo.get("FTYPE") or "",
        "aum": _num(fpo.get("ENDNAV")),
    }
    out = {"ok": True, "data": data, "error": None}
    cache_set("tenure", key, out)
    return out


# ═══ 任职期复盘（tenure）净值序列 ═══
#
# 定位：**快路径 / 降级路径**，不是精确路径。实测（2026-09-23，001959/022490/019189）：
#   - range='ln' 一次回全历史（001959 十年 2582 行，0.7s），远快于 Wind 分段（12 次调用 17s）；
#   - 但**成立后前约 6 周是周频**（022490 前 6 周仅 8 行；019189 前 4 周仅 9 行），
#     日频从第 7 周起 —— 任职日贴近成立日时，头几周只有周频台阶；
#   - JZZZL（日增长率）只有 2 位小数，长区间累乘会漂移：001959 任职以来累乘 +95.44%
#     vs Wind 官方 +95.64%（偏差 0.20pct），2025 单年偏差 3.4pct（周频段丢行所致）。
# 因此默认精确路径走 sources/wind.py 的分段复权净值；本路径仅在 Wind 不可用或
# 用户显式要快时启用，并把上面的局限通过 coverage 字段带到产物里，不静默降级。

TTFUND_NAV_WEEKLY_HEAD_DAYS = 42  # 成立后前 6 周：上游给的是周频
TTFUND_NAV_MIN_HEAD_ROWS = 15     # 6 周内不足 15 行即判定为周频头段


def nav_series(code: str, begin: str = "") -> dict[str, Any]:
    """成立来净值序列 → 合成的复权净值（由官方日增长率累乘）。

    返回 {ok, series:[(日期, 合成复权净值)], coverage:{...}, error}。
    合成复权净值只用于**区间比值**（累计收益率 = 期末/基期 - 1），绝对值无意义。

    **begin 只做入参过滤，不进缓存键**——这是有意的，且是必须的：
    上游固定用 `range="ln"` 取成立来全量，`begin` 的切片发生在**取数之后**。
    旧实现把切片后的结果按 `ttnav|{code}` 落盘，于是
        nav_series("001959", "2022-01-01")  → 缓存 2022+ 的子集
        nav_series("001959", "2019-01-01")  → 零网络请求，直接拿 2022+ 的子集
    第二次调用**静默少给 3 年数据**（ok=True、coverage.first 显示 2022-06），
    而短序列会让累计收益率与最大回撤**偏小**——一个不报错的错数字。
    改为：缓存**过滤前**的全量序列，切片每次现做。缓存语义与键重新对齐，
    这一类「键缺参数」的 bug 就不存在了。
    """

    from _common import CACHE_TTL_FUNDAMENTAL, cache_get, cache_set

    key = f"ttnav|{code}"  # 全量序列的键；begin 是入参过滤器，不是身份的一部分
    hit = cache_get("tenure", key, CACHE_TTL_FUNDAMENTAL)
    if hit is not None and hit.get("full_series"):
        return _window_nav(hit, begin)
    try:
        raw = _invoke("TTFUND_NAV_INFO", {"fund_id": code, "range": "ln"})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "series": [], "coverage": None, "error": str(e)}
    items = (((raw.get("data") or {}).get("nav_history") or {}).get("items")) or []
    if not items:
        return {"ok": False, "series": [], "coverage": None, "error": "ttskill 未返回净值序列"}
    items = sorted(items, key=lambda it: it.get("FSRQ") or "")
    series: list[tuple[str, float]] = []
    level = 1.0
    missing = 0
    recovered = 0
    prev_dw = prev_lj = None
    for i, it in enumerate(items):
        g = _as_float(it.get("JZZZL"))
        dw, lj = _as_float(it.get("DWJZ")), _as_float(it.get("LJJZ"))
        if g is not None:
            level *= 1.0 + g / 100.0
        elif i == 0:
            missing += 1  # 首日无增长率：作为基准点
        elif dw is not None and lj is not None and prev_dw and prev_lj is not None:
            # 缺日增长率的日子用「累计净值差分 / 前日单位净值」复原（与官方 JZZZL 同式）：
            # 实测 2026-09-23，022490 任职以来因此从 +56.90% 回到 +50.44%（Wind 官方 +50.30%）。
            # 之所以只在缺失日用它：累计净值只有 3 位小数，逐日量化误差（±0.05pct/天）大于
            # 官方 JZZZL 的 2 位小数（±0.005pct/天），能用官方值就别用推导值。
            missing += 1
            level *= 1.0 + (lj - prev_lj) / prev_dw
            recovered += 1
        else:
            missing += 1
        series.append((it["FSRQ"], level))
        if dw is not None and lj is not None:
            prev_dw, prev_lj = dw, lj
    out = {
        "ok": True,
        "full_series": series,
        "missing": missing,
        "recovered": recovered,
        "error": None,
    }
    cache_set("tenure", key, out)
    return _window_nav(out, begin)


def _as_float(val: Any) -> Optional[float]:
    """上游数值字段 → float；非数值哨兵（""/--/N/A/—/None）一律返回 None。

    为什么必须容错：这里的守卫原本是 `g not in ("", "--", None)` 这样的
    **精确字符串白名单**，而 NAV 上游实际会返回 `"N/A"`、`"—"`、`"null"`
    等。漏一个就是 `float("N/A")` → ValueError → 整条 tenure 命令 traceback。
    数值语义上「取不到」和「不是数」是同一件事，统一成 None 让上层走
    既有的缺失分支，而不是崩在解析层。
    """
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().rstrip("%").replace(",", "")
    if not s or s in ("-", "--", "—", "N/A", "n/a", "null", "None", "无"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _window_nav(full: dict[str, Any], begin: str) -> dict[str, Any]:
    """从缓存的**全量**序列切出 [begin, ∞) 窗口，并重算 coverage。"""
    from datetime import date, timedelta

    series: list[tuple[str, float]] = list(full.get("full_series") or [])
    missing = int(full.get("missing") or 0)
    recovered = int(full.get("recovered") or 0)
    if begin:
        series = [it for it in series if it[0] >= begin]
    head = series[0][0] if series else ""
    head_rows = 0
    if head:
        try:
            limit = date.fromisoformat(head) + timedelta(days=TTFUND_NAV_WEEKLY_HEAD_DAYS)
            head_rows = sum(1 for d, _ in series if _parse_day(d) and _parse_day(d) <= limit)
        except ValueError:
            head_rows = 0
    return {
        "ok": True,
        "series": series,
        "coverage": {
            "rows": len(series), "first": head, "last": series[-1][0] if series else "",
            "missing_growth_days": missing, "recovered_growth_days": recovered,
            "weekly_head": head_rows < TTFUND_NAV_MIN_HEAD_ROWS, "head_rows_6w": head_rows,
        },
        "error": None,
    }


def _parse_day(d: str):
    from datetime import date

    try:
        return date.fromisoformat(d)
    except (TypeError, ValueError):
        return None
