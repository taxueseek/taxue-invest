"""ETFirst CLI 数据源适配器 — 首趋E指小程序数据接口。

通过 subprocess 调用 etfirst CLI，获取指数/ETF/场外聚合详情
（估值分位、风险收益比、行业分布、Wind 排名、收益走势）。

错误信封返回：{"ok": True, "data": {...}} 或 {"ok": False, "error": "..."}
失败时静默降级，不阻断主流程。
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

# etfirst CLI 路径
_ETFIRST_BIN = "etfirst"

# 缓存 TTL
CACHE_TTL = 3600.0  # 1 小时


def _cache_key(cmd: str, code: str) -> str:
    return f"etfirst|{cmd}|{code}"


def _get_from_cache(key: str) -> Optional[dict]:
    try:
        from _common import cache_get
        return cache_get("etfirst", key, CACHE_TTL)
    except Exception:
        return None


def _set_to_cache(key: str, value: dict) -> None:
    try:
        from _common import cache_set
        cache_set("etfirst", key, value)
    except Exception:
        pass


def detect() -> tuple[bool, str]:
    """适配器级探测：给 registry.detect 的 `command` 型用。

    为什么必须有它：data-sources.yaml 里 etfirst 声明 `type: command`，
    而 registry.detect 的 command 分支随 v2.6「外部 CLI 依赖清理」一起被删了，
    于是这里落到默认分支返回「未知探测方式 'command'」——**一个已装的源被
    永久判死**（实测 `datasources` 里 etfirst 恒为 False，尽管 /opt/homebrew/bin/etfirst 在）。
    适配器级探测优先于 env 判据（见 registry.detect 的 env_or_file 分支），
    所以这里补 detect() 就同时修好了可用性判据。

    判据与 westock 一致：跑一次 `--help` 确认真能执行，而不是只看文件存在。
    """
    try:
        result = subprocess.run(
            [_ETFIRST_BIN, "--help"],
            capture_output=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"etfirst CLI 无法执行: {e}"
    if result.returncode != 0:
        return False, f"etfirst CLI 异常退出 rc={result.returncode}"
    return True, "etfirst CLI 可用"


def is_available() -> bool:
    """检查 etfirst CLI 是否已安装（供直接调用方使用的布尔简写）。"""
    return detect()[0]


def _run_cli(args: list[str]) -> dict:
    """运行 etfirst CLI 命令。"""
    try:
        result = subprocess.run(
            [_ETFIRST_BIN, "--json"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"CLI 失败: {result.stderr.strip()[:200]}"}

        response = json.loads(result.stdout)
        code = response.get("code", "")
        if code not in ("00000", "0000", "000000", "0"):
            return {"ok": False, "error": response.get("message", f"未知错误码 {code}")}

        return {"ok": True, "data": response.get("data")}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "CLI 超时"}
    except (json.JSONDecodeError, KeyError) as e:
        return {"ok": False, "error": f"响应解析失败: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"未知错误: {e}"}


def fetch_etf_list(index_code: str = "", page_size: int = 100) -> dict:
    """获取 ETF 列表（含估值分位、资金流、跟踪误差）。

    Args:
        index_code: 指数代码（可选，为空则返回全部 ETF）
        page_size: 每页条数
    """
    if not is_available():
        return {"ok": False, "error": "ETFirst CLI 未安装"}

    key = _cache_key("list", index_code or "all")
    cached = _get_from_cache(key)
    if cached:
        return {"ok": True, "data": cached, "cached": True}

    args = ["index-base", "list-etf", "--type", "2"]
    if index_code:
        args += ["--index-code", index_code]
    args += ["--page-size", str(page_size)]

    result = _run_cli(args)
    if result.get("ok") and result.get("data"):
        _set_to_cache(key, result["data"])
    return result


def fetch_etf_detail(product_code: str) -> dict:
    """获取 ETF 详情聚合（估值、风险收益、行业分布、Wind 排名、收益走势）。

    Args:
        product_code: ETF 产品代码
    """
    if not is_available():
        return {"ok": False, "error": "ETFirst CLI 未安装"}

    key = _cache_key("detail", product_code)
    cached = _get_from_cache(key)
    if cached:
        return {"ok": True, "data": cached, "cached": True}

    result = _run_cli(["etf-detail", "all", "--product-code", product_code])
    if result.get("ok") and result.get("data"):
        _set_to_cache(key, result["data"])
    return result


def fetch_index_detail(index_code: str) -> dict:
    """获取指数详情聚合（估值、风险收益、行业分布、净流入趋势）。

    Args:
        index_code: 指数代码
    """
    if not is_available():
        return {"ok": False, "error": "ETFirst CLI 未安装"}

    key = _cache_key("index-detail", index_code)
    cached = _get_from_cache(key)
    if cached:
        return {"ok": True, "data": cached, "cached": True}

    result = _run_cli(["index-detail", "all", "--index-code", index_code])
    if result.get("ok") and result.get("data"):
        _set_to_cache(key, result["data"])
    return result


def fetch_otc_detail(product_code: str) -> dict:
    """获取场外基金详情聚合。

    Args:
        product_code: 场外基金代码
    """
    if not is_available():
        return {"ok": False, "error": "ETFirst CLI 未安装"}

    key = _cache_key("otc-detail", product_code)
    cached = _get_from_cache(key)
    if cached:
        return {"ok": True, "data": cached, "cached": True}

    result = _run_cli(["otc-detail", "all", "--product-code", product_code])
    if result.get("ok") and result.get("data"):
        _set_to_cache(key, result["data"])
    return result


def fetch_market_info() -> dict:
    """获取市场资讯（热议、风口、主线、快讯）。"""
    if not is_available():
        return {"ok": False, "error": "ETFirst CLI 未安装"}

    results = {}
    # 全网热议
    results["hottalk"] = _run_cli(["info", "hottalk-top"])
    # 今日风口
    results["storm"] = _run_cli(["info", "storm-today"])
    # 阶段主线
    results["stage"] = _run_cli(["info", "stage-current"])
    # 焦点看盘
    results["flash"] = _run_cli(["info", "flash-focus"])

    # 只要有任一成功就返回
    any_ok = any(v.get("ok") for v in results.values())
    if not any_ok:
        return {"ok": False, "error": "所有资讯接口均失败"}
    return {"ok": True, "data": results}
