"""华泰柏瑞基金数据源适配器（invest-cli 数据源，透传 htbr-etf-skill）。

定位与边界（照 etfirst/index_hub 的同一套）：
  - 不重写 htbr-etf-skill 的鉴权、取数、回答校验逻辑，**只透传**它的
    `scripts/api_client.py invoke <api_id> '<json>'`，避免两处漂移。
  - htbr 是「事实查询」面（基金档案/费率/经理季报观点/申万一级行业穿透/
    指数盈利预测/ETF 资金两融等 72 个接口），与 invest-cli 既有源**能力互补**，
    不参与 route.fetch 快照链（route_kinds 为空），由 `invest-cli htbr` 直取。
  - 返回信封对齐 route.fetch：{source, kind, ok, data, error}。

为什么必须透传而不能内置实现：
  htbr 侧有 SKILL.md 强制的九步流程、凭证引导硬输出、finalize 校验与版本更新机制；
  复刻任何一层都会与上游包产生第二份真源。上游脚本自带 Python 3.7+ 兼容与
  内网/VPN 依赖，本模块不假设这些前提，只在 detect() 里如实报缺什么。

安全：
  - 只读 `~/.htbr/credentials.json`（htbr 自带 config.py 读，本模块不碰 Key 明文）。
  - 输出不含 api_key/token 明文；失败只报原因。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

SOURCE_LABEL = "华泰柏瑞ETF"
SKILL_DIR_NAME = "htbr-etf-skill"

# 缓存 TTL：htbr 数据变化以报告期/交易日计，比行情慢、比年报快。
CACHE_TTL = 1800.0  # 30 分钟

# 调用上游脚本的超时（秒）。上游单次请求自身 timeout=300，这里取更短的上限，
# 避免 invest-cli 调用方被单个接口长时间挂住。
INVOKE_TIMEOUT = 120


def skill_dir() -> Optional[Path]:
    """定位 htbr-etf-skill 目录。

    顺序与本机约定一致（workbuddy / agents / claude），并支持
    INVEST_SKILL_ROOTS 扩展；不硬编码单一 HOME 路径。
    """
    env_dir = os.environ.get("HTBR_SKILL_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        if (p / "scripts" / "api_client.py").is_file():
            return p

    roots: list[Path] = []
    env_roots = os.environ.get("INVEST_SKILL_ROOTS", "")
    if env_roots:
        for raw in env_roots.split(os.pathsep):
            if raw.strip():
                roots.append(Path(raw.strip()).expanduser())

    home = Path.home()
    roots += [
        home / ".workbuddy" / "skills",
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".grok" / "skills",
        home / ".codex" / "skills",
    ]
    for root in roots:
        cand = root / SKILL_DIR_NAME
        if (cand / "scripts" / "api_client.py").is_file():
            return cand
    return None


def _client_path() -> Optional[Path]:
    d = skill_dir()
    return (d / "scripts" / "api_client.py") if d else None


def detect() -> tuple[bool, str]:
    """适配器级探测：判据 = 上游脚本在 + 凭据已配置。

    为什么不只看 yaml 声明的凭据文件：htbr 的 Key 存储位置是
    `~/.htbr/credentials.json`（htbr 包内 config.py 唯一真源），
    且它**不读环境变量 HTBR_API_KEY**——把「环境变量在不在」当判据会得到
    与实际能否取数无关的结论（同 index_hub 的 detect 注释里那个坑）。
    """
    client = _client_path()
    if client is None:
        return False, f"未找到 {SKILL_DIR_NAME}/scripts/api_client.py"
    ok, detail = _credential_state()
    if not ok:
        return False, detail
    return True, f"已安装（{client.parent.parent}）+ 凭据就绪"


def _credential_state() -> tuple[bool, str]:
    """只判凭据状态，不回显 Key 内容。"""
    cred_dir = Path(os.environ.get("HTBR_HOME", "")).expanduser() if os.environ.get("HTBR_HOME") else Path.home() / ".htbr"
    cred_file = cred_dir / "credentials.json"
    if not cred_file.is_file():
        return False, f"未配置 API Key（缺 {cred_file}）"
    try:
        data = json.loads(cred_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"凭据文件损坏（{cred_file}），请删除后重新 save-key"
    key = data.get("api_key") if isinstance(data, dict) else None
    if not isinstance(key, str) or not key.strip():
        return False, f"凭据文件缺少有效 api_key（{cred_file}）"
    return True, "凭据已配置"


def is_available() -> bool:
    return detect()[0]


def _cache_key(api_id: str, params: dict) -> str:
    # 参数排序后入键：同一接口同参数才命中，避免不同口径互相污染
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return f"{api_id}|{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _get_from_cache(key: str) -> Optional[dict]:
    # 与 route.fetch 同一约定：scripts/ 已在 sys.path（invest_cli 入口与 conftest
    # 都保证），直接 from _common import；**不许**把 sources/ 目录插进 sys.path——
    # 那会让进程内随后的 `import yfinance` 命中适配器 sources/yfinance.py（模块
    # 而非包），PyPI 真包被遮蔽，test_perf_guards 六用例连跑即红（实测）。
    try:
        from _common import cache_get

        return cache_get("htbr", key, CACHE_TTL)
    except Exception:
        return None


def _set_to_cache(key: str, value: dict) -> None:
    try:
        from _common import cache_set

        cache_set("htbr", key, value)
    except Exception:
        pass


def call(api_id: str, params: Optional[dict] = None, params_json: str = "") -> dict[str, Any]:
    """透传调用 htbr 接口。

    Args:
        api_id: 接口标识，原样传给上游（如 fund-basic-info）
        params: 请求参数 dict（与 params_json 二选一，params 优先）
        params_json: 请求参数 JSON 字符串（params 为空时使用）

    Returns:
        {"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
    """
    client = _client_path()
    if client is None:
        return {"ok": False, "error": f"未找到 {SKILL_DIR_NAME}/scripts/api_client.py"}

    try:
        body = params if params is not None else (json.loads(params_json) if params_json.strip() else {})
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"参数不是合法 JSON: {e}"}
    if not isinstance(body, dict):
        return {"ok": False, "error": "参数必须是 JSON 对象"}

    cache_key = _cache_key(api_id, body)
    cached = _get_from_cache(cache_key)
    if cached is not None:
        return {"ok": True, "data": cached, "cached": True}

    try:
        result = subprocess.run(
            [sys.executable, str(client), "invoke", api_id, json.dumps(body, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=INVOKE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"调用超时（>{INVOKE_TIMEOUT}s）"}
    except OSError as e:
        return {"ok": False, "error": f"无法执行上游脚本: {e}"}

    # 上游约定：无 Key / Key 失效 → 退出码 3，stdout 为引导文案（不是错误 JSON）
    if result.returncode == 3:
        return {"ok": False, "error": "凭证不可用（未配置或已失效），请先配置 API Key", "need_key": True}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        # 只取首行，避免把上游的多行指令整段灌进错误信息
        first = detail.splitlines()[0] if detail else f"退出码 {result.returncode}"
        res: dict[str, Any] = {"ok": False, "error": first[:300]}
        kind = _error_kind(first)
        if kind:
            res["error_kind"] = kind
        return res

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"上游返回非 JSON: {result.stdout[:200]}"}

    if not isinstance(payload, dict):
        return {"ok": False, "error": "上游返回结构异常"}
    if payload.get("success") is not True:
        err = payload.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else None
        return {"ok": False, "error": msg or json.dumps(payload, ensure_ascii=False)[:300]}

    data = payload.get("data")
    if data is None:
        return {"ok": False, "error": "上游未返回数据"}

    # HTTP 200 + 空数组是正常语义非故障（catalog 口径）；但错代码口径会**静默**
    # 回 0 行不报错（研究报告 §4.8 实测）——空结果不落缓存（「部分失败不写」
    # 同一纪律，30 分钟 TTL 会把口径错误钉住），并带口径提示，防止把口径错
    # 读成「无此数据」。
    empty = data == [] or data == {} or data == ""
    if not empty:
        _set_to_cache(cache_key, data)
    res: dict[str, Any] = {"ok": True, "data": data}
    if empty:
        res["empty"] = True
        res["hint"] = ("空结果可能是代码口径不符（上游对错口径静默回 0 行不报错）："
                       "先 invest-cli htbr resolve/index-resolve/fund-resolve 换算，"
                       "或核对上游 workflows/*-code-resolution.md")
    return res


def invoke_scene(api_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """通用场景透传（供 cmd_intent 之类的上层复用），返回 route 对齐信封。"""
    res = call(api_id, params=body)
    return {
        "source": "htbr",
        "kind": api_id,
        "ok": res.get("ok", False),
        "data": res.get("data"),
        "error": res.get("error"),
    }


# ── 常用接口的语义别名（只映射到 htbr 的 api_id，不复制参数口径） ──
# 参数口径以 htbr 包内 references/apis/<api_id>.md 为唯一真源，本表只做「场景→接口」导航。
#
# 收录原则（剃刀）：完整 api_id 本来就能直传，别名只收两类——
#   ① 本源的独有能力面：基金经理 20 接口全量（1.0.8 从 4 扩到 20，是本次
#     接入相对既有源的核心增量，导航不给全等于白接）、指数 13 接口全量
#     （估值分位/估值带/资金面是既有源没有的口径）；
#   ② 分辨率入口：fund/index/company-resolve——净码/.OF/内码三套代码口径
#     并存且错口径会静默回 0 行（研究报告 §4.3 与 §4.8），分辨率必须好打。
# 明确不收录（直传仍可用，不为「凑齐」扩表——表越大，上游改名时的漂移面越大）：
#   - catalog:88-95 暂停保留的单指标接口（stage-performance/逐期收益×3/
#     return-sum/max-dd/比率×3/annual-return/annual-risk），合并版
#     fund-return-risk 才是正路；初版别名表曾把 stage-performance 当导航项，
#     属主动指路到暂停接口，已剔除（test_htbr_contract 钉住）；
#   - 低频接口（fund-drawdown/fund-nav-change/fund-index-related/etf-pr-*）。
API_ALIASES = {
    # 分辨率入口：代码口径第一大错源，先用它换算再取数
    "resolve": "company-resolve",
    "fund-resolve": "fund-resolve",
    "index-resolve": "index-resolve",
    "manager-resolve": "fund-manager-resolve",
    # 基金档案/费率/净值
    "basic": "fund-basic-info",
    "rate": "fund-rate",
    "dividend": "fund-dividend-history",
    "asset-size": "fund-asset-size",
    "company-funds": "fund-company-funds",
    "nav": "fund-nav",
    "nav-trend": "fund-nav-trend",
    "daily-quote": "fund-daily-quote",
    # 基金收益风险（合并线上接口版，一次出全指标；单指标版暂停勿调）
    "return-risk": "fund-return-risk",
    # 基金持仓/行业/估值/财报
    "holding-detail": "fund-holding-detail",
    "industry-dist": "fund-industry-dist",
    "industry-concentration": "fund-industry-concentration",
    "valuation": "fund-valuation",
    "fin-indicator": "fund-fin-indicator",
    # 基金经理（1.0.8 能力大跳：4→20 个，全量收录）
    "manager-info": "fund-manager-info",
    "manager-history": "fund-manager-history",
    "manager-tag": "fund-manager-tag",
    "manager-scale": "fund-manager-scale",
    "manager-viewpoint": "fund-manager-viewpoint",
    "viewpoint": "fund-manager-viewpoint",
    "manager-experience": "fund-manager-experience",
    "manager-products-income": "fund-manager-products-income",
    "manager-image": "fund-manager-image",
    "manager-risk-return": "fund-manager-risk-return",
    "manager-stage-revenue": "fund-manager-stage-revenue",
    "manager-revenue-statis": "fund-manager-revenue-statis",
    "manager-rank": "fund-manager-stage-revenue-rank",
    "manager-industry-fixed": "fund-manager-industry-fixed",
    "manager-industry-regular": "fund-manager-industry-regular",
    "manager-bond-concentration": "fund-manager-bond-concentration",
    "manager-position-detail": "fund-manager-position-detail",
    "manager-stock-concentration": "fund-manager-stock-concentration",
    "manager-fund-position": "fund-manager-fund-position",
    "manager-concept-position": "fund-manager-concept-position",
    # ETF 专项
    "capital-report": "etf-capital-report",
    "etf-margin": "etf-margin",
    "etf-shares-change": "etf-shares-change",
    "earning-forecast": "etf-earning-forecast",
    "etf-range-quote": "etf-range-quote",
    "etf-capital-flow": "etf-capital-flow",
    "etf-capital-flow-stats": "etf-capital-flow-stats",
    # 指数（估值分位/估值带是指数估值问题的第一入口，行情只是兜底）
    "index-info": "index-basic-info",
    "index-holdings": "index-constituents",
    "index-quote": "index-daily-quote",
    "index-valuation": "index-value-analysis",
    "index-pe-bands": "index-pe-bands",
    "index-risk": "index-return-risk",
    "index-multi-quote": "index-multi-period-quote",
    "index-margin": "index-margin",
    "index-capital-flow": "index-capital-flow",
    "index-industry-dist": "index-industry-dist",
    "index-trend": "index-performance-trend",
    "index-range-quote": "index-range-quote",
}


def resolve_api_id(name: str) -> str:
    """场景别名 → api_id；未登记的名称原样返回（便于直传完整 api_id）。"""
    return API_ALIASES.get(name, name)


# 上游错误话术 → 结构化 error_kind。上游错误以 SystemExit 中文文案走 stderr
# （api_client.py:241-304），关键词映射比解析 JSON 稳；kind 供上层决定重试
# 节奏：quota 当日勿再试、scope_denied 换接口、api_not_found 查拼写。
_ERROR_KINDS: tuple[tuple[str, str], ...] = (
    ("配额已用尽", "quota"),
    ("RATE_LIMITED", "rate_limited"),
    ("无权访问该接口", "scope_denied"),
    ("接口不存在", "api_not_found"),
    ("服务暂不可用", "degraded"),
)


def _error_kind(text: str) -> Optional[str]:
    for pattern, kind in _ERROR_KINDS:
        if pattern in text:
            return kind
    return None
