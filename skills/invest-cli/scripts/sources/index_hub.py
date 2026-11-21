"""Index Hub v2.1 数据源适配器 — 易方达指数直通车 API。

通过 subprocess 调用 ~/.openclaw/workspace/skills/etf-fund-query/scripts/api_client.py，
复用其鉴权、缓存、追踪基础设施。

错误信封返回：{"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
失败时静默降级，不阻断主流程。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

# Index Hub api_client.py 路径
_INDEX_HUB_CLIENT = (
    Path.home()
    / ".openclaw"
    / "workspace"
    / "skills"
    / "etf-fund-query"
    / "scripts"
    / "api_client.py"
)

# 支持的端点
_ENDPOINTS = {
    "detail": "/skill/v2/etf/detail",
    "holdings": "/skill/v2/etf/holdings",
    "return": "/skill/v2/etf/return",
    "scale": "/skill/v2/etf/etf-scale",
    "quote": "/skill/v2/quote/etf",
    "search": "/skill/v2/search/etf",
}

# 缓存 TTL
CACHE_TTL = 3600.0  # 1 小时


def _cache_key(endpoint: str, code: str) -> str:
    return f"index_hub|{endpoint}|{code}"


def _get_from_cache(key: str) -> Optional[dict]:
    """从 invest-cli 缓存读取。"""
    try:
        from _common import cache_get, CACHE_TTL_FUNDAMENTAL
        return cache_get("index_hub", key, CACHE_TTL_FUNDAMENTAL)
    except Exception:
        return None


def _set_to_cache(key: str, value: dict) -> None:
    """写入 invest-cli 缓存。"""
    try:
        from _common import cache_set
        cache_set("index_hub", key, value)
    except Exception:
        pass


def is_available() -> bool:
    """检查 Index Hub api_client.py 是否存在。"""
    return _INDEX_HUB_CLIENT.is_file()


def detect() -> tuple[bool, str]:
    """适配器级探测：判据 = **真正的前置条件**，而不是 yaml 声明的凭据文件。

    为什么必须有这个函数：data-sources.yaml 把 index_hub 声明为
    `env_var: INDEX_HUB_API_KEY` + `files: [~/.config/index-hub/api_key]`，
    而 registry 的 env_or_file 探测在没有适配器 detect() 时会退化成
    「env 变量在吗 / 那个文件在吗」——**本模块从头到尾没读过这两个东西**
    （grep INDEX_HUB_API_KEY 零命中），真正的开关是 `_INDEX_HUB_CLIENT`
    这个脚本文件在不在。

    后果是「假可用」：本机两个路径恰好都存在，datasources 报「读到
    credentials.env → 可用」，结论对了但理由是错的；换一台只配了 key
    文件、没装 client 的机器，就会报「可用」而 fetch() 直接返回
    「Index Hub 未安装」——排障方向被带偏。

    补上 detect() 后，registry 优先走它（见 registry.detect 的 env_or_file
    分支），判据与实际行为对齐。顺带把凭据也纳入判据：client 在但没 key
    同样取不到数。
    """
    if not _INDEX_HUB_CLIENT.is_file():
        return False, f"未找到 Index Hub client: {_INDEX_HUB_CLIENT}"
    key = _load_key()
    if not key:
        return False, "Index Hub client 在，但缺少凭据（INDEX_HUB_API_KEY 或 ~/.config/index-hub/api_key）"
    return True, "Index Hub client + 凭据就绪"


def _load_key() -> str:
    """读 Index Hub 凭据：环境变量优先，其次 key 文件。

    这是本模块**第一次**真的去读 yaml 里声明的那个凭据——之前它只被
    声明、从未被使用，所以「可用性」与「实际能否取数」是两件事。
    """
    val = os.environ.get("INDEX_HUB_API_KEY", "").strip()
    if val:
        return val
    for p in (
        Path.home() / ".config" / "index-hub" / "api_key",
        Path.home() / ".openclaw" / "workspace" / "skills" / "etf-fund-query" / "api_key",
    ):
        try:
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return text
        except OSError:
            continue
    return ""


def fetch(endpoint: str, code: str, **extra_params) -> dict:
    """调用 Index Hub API。

    Args:
        endpoint: 端点名称（detail/holdings/return/scale/quote/search）
        code: ETF 代码
        **extra_params: 额外请求参数

    Returns:
        {"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
    """
    if not is_available():
        return {"ok": False, "error": "Index Hub 未安装"}

    if endpoint not in _ENDPOINTS:
        return {"ok": False, "error": f"未知端点: {endpoint}"}

    # 检查缓存
    key = _cache_key(endpoint, code)
    cached = _get_from_cache(key)
    if cached:
        return {"ok": True, "data": cached, "cached": True}

    # 构造请求体
    body = _build_body(endpoint, code, **extra_params)

    # 调用 api_client.py
    try:
        result = subprocess.run(
            [
                "python3",
                str(_INDEX_HUB_CLIENT),
                "--method", "POST",
                "--path", _ENDPOINTS[endpoint],
                "--body", json.dumps(body, ensure_ascii=False),
                "--compact",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"API 调用失败: {result.stderr.strip()[:200]}"}

        response = json.loads(result.stdout)
        if not response.get("success"):
            return {"ok": False, "error": response.get("message", "未知错误")}

        data = response.get("data")
        if data is None:
            return {"ok": False, "error": "API 返回空数据"}

        # 写缓存
        _set_to_cache(key, data)

        return {"ok": True, "data": data}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "API 超时"}
    except (json.JSONDecodeError, KeyError) as e:
        return {"ok": False, "error": f"响应解析失败: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"未知错误: {e}"}


def _build_body(endpoint: str, code: str, **extra_params) -> dict:
    """构造请求体。"""
    if endpoint == "detail":
        return {"fundCodes": [code]}
    elif endpoint == "holdings":
        return {"fundCodes": [code]}
    elif endpoint == "return":
        body = {"fundCodes": [code]}
        body.update(extra_params)
        return body
    elif endpoint == "scale":
        body = {"fundCodes": [code]}
        body.update(extra_params)
        return body
    elif endpoint == "quote":
        return {"fundCodes": [code]}
    elif endpoint == "search":
        body = {"keyword": code}
        body.update(extra_params)
        return body
    return {}


def fetch_etf_detail(code: str) -> dict:
    """获取 ETF 详情（规模、费率、跟踪指数、跟踪误差、资金流向等）。"""
    return fetch("detail", code)


def fetch_etf_holdings(code: str) -> dict:
    """获取 ETF 持仓明细。"""
    return fetch("holdings", code)


def fetch_etf_return(code: str, **params) -> dict:
    """获取 ETF 区间收益。"""
    return fetch("return", code, **params)


def fetch_etf_scale(code: str, **params) -> dict:
    """获取 ETF 规模变动（资金流）。"""
    return fetch("scale", code, **params)


def fetch_etf_quote(code: str) -> dict:
    """获取 ETF 实时行情（最新价、涨跌幅、换手率、IOPV、溢折率）。"""
    return fetch("quote", code)


def fetch_search(keyword: str, **params) -> dict:
    """搜索 ETF。"""
    return fetch("search", keyword, **params)
