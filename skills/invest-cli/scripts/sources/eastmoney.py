"""东方财富数据源适配器。

复用 scripts/ 下现有 cmd_stock / cmd_fund 的取数实现，保持 JSON 契约一致。
东财=天天（同一家），本适配器只负责东财；天天官方能力走 ttskill 源（sources/ttskill.py）。

key 读取：环境变量 EASTMONEY_APIKEY 或用户级凭据文件（env_or_file，见 data-sources.yaml）。
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

# 让 scripts/ 下的 cmd_* 模块可导入（无论进程 cwd）
_SCRIPTS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

ENV_KEY = "EASTMONEY_APIKEY"


def detect() -> tuple[bool, str]:
    """可用性判据 = 凭据加载器的判据，逐字一致。

    没有这个函数时，`env_or_file` 型会退到 registry 的通用回退——它**只看文件
    是否存在**，不看文件里有没有 key。实测：`~/.config/invest-cli/eastmoney.env`
    里只写一行注释时
        registry.detect(eastmoney) -> (True, '读到 credentials.env')
        eastmoney.load_api_key()   -> ''
    于是 `invest-cli datasources` 报「东财可用」，而每次 `screen`/港股取数都
    报「未设置 EASTMONEY_APIKEY」——排障时被这个假信号带偏。

    同花顺/Wind/盈米/天天都已在适配器里自带 detect()，东财是唯一的例外；
    补上它，也把「通用文件存在性回退」从生产路径上摘掉。
    """
    if load_api_key():
        return True, f"{ENV_KEY} 已配置"
    paths = credential_files()
    where = "、".join(str(p) for p in paths) if paths else "（无凭据文件）"
    return False, f"缺少 {ENV_KEY} 且凭据文件里没有该键：{where}"


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "eastmoney.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "eastmoney.env",
    ]
    return [p for p in cands if p.is_file()]


def load_api_key() -> str:
    """进程环境/launchctl/shell rc 优先（统一识别器），无则读用户级凭据文件。"""
    from .env import read_credential_file, read_env

    val = read_env(ENV_KEY)
    if val:
        return val
    # 凭据文件走共用解析（正确剥引号），不再内联 split(...,1)[1].strip()
    return read_credential_file(ENV_KEY, credential_files())


# 可用性探测：本模块自带 detect()（见上方），判据与 load_api_key() 逐字一致，
# 「读到 key」与「key 非空」是同一个结论。
# data-sources.yaml 里 eastmoney 声明了 `adapters: [eastmoney]`，registry 的
# env_or_file 分支因此优先 import 本模块的 detect()（registry.py:299-310），
# 那条「只看文件存在」的通用回退（registry.py:315-320）对东财到不了。
# 注意是「到不了」而不是「被删掉」：回退代码仍在 registry 里，靠的是 yaml 的
# adapters 声明走到上面这条分支，改 yaml 时别把该行去掉。


def _wrap(kind: str, snap: Any) -> dict:
    if not isinstance(snap, dict):
        return {"source": "eastmoney", "kind": kind, "ok": False, "data": None,
                "error": "东财返回非对象"}
    payload = snap.get("data")
    if not payload:
        return {"source": "eastmoney", "kind": kind, "ok": False, "data": None,
                "error": f"东财{kind}为空"}
    return {"source": "eastmoney", "kind": kind, "ok": True, "data": snap, "error": None}


def stock(keyword: str) -> dict:
    from cmd_stock import resolve_code, fetch_stock_data

    if not load_api_key():
        return {"source": "eastmoney", "kind": "stock", "ok": False, "data": None,
                "error": "未设置 EASTMONEY_APIKEY（env 或 ~/.config/invest-cli/eastmoney.env）"}
    try:
        snap = fetch_stock_data(resolve_code(keyword))
    except Exception as e:
        return {"source": "eastmoney", "kind": "stock", "ok": False, "data": None, "error": str(e)}
    return _wrap("stock", snap)


def fund(keyword: str) -> dict:
    from cmd_fund import resolve_fund_code, fetch_fund_data

    if not load_api_key():
        return {"source": "eastmoney", "kind": "fund", "ok": False, "data": None,
                "error": "未设置 EASTMONEY_APIKEY（env 或 ~/.config/invest-cli/eastmoney.env）"}
    try:
        snap = fetch_fund_data(resolve_fund_code(keyword))
    except Exception as e:
        return {"source": "eastmoney", "kind": "fund", "ok": False, "data": None, "error": str(e)}
    return _wrap("fund", snap)


# 选股回包体积说明（2026-09-21 实测，**不裁剪**，仅记录）：
#   同一条件整包 34.3KB（pretty 打印后 58KB），其中
#     partialResults 2.5KB —— markdown，**只有前 10 行**（pageSize 20 时仍截断）
#     allResults.result.columns 10.8KB —— 21 列 × 每列约 20 个版式字段（多为 null）
#     allResults.result.dataList 17.7KB —— **全部 17 行**，键是东财字段码
# 两者行集不同（10 vs 17），因此不是可安全互删的重复。唯一无损的精简是
# 去掉 columns 里那些恒为 null/false 的版式字段（约省 8.8KB / 26%），
# 收益有限而动了原样透传的契约，故本轮不改，只在此留证。


def screen(condition: str, page_size: int = 20) -> dict:
    api_key = load_api_key()
    if not api_key:
        return {"source": "eastmoney", "kind": "screen", "ok": False, "data": None,
                "error": "未设置 EASTMONEY_APIKEY（env 或 ~/.config/invest-cli/eastmoney.env）"}
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen"
    try:
        from ._http import guarded_request

        status, body, _headers = guarded_request(
            url,
            headers={"apikey": api_key, "Content-Type": "application/json"},
            json_body={"keyword": condition, "pageNo": 1, "pageSize": page_size},
            timeout=30,
            allowed_host="mkapi2.dfcfs.com",
        )
    except (ValueError, OSError, urllib.error.URLError) as e:
        return {"source": "eastmoney", "kind": "screen", "ok": False, "data": None, "error": f"东财选股失败: {e}"}
    if status < 200 or status >= 300:
        snippet = body[:200].decode("utf-8", errors="replace").replace("\n", " ")
        return {"source": "eastmoney", "kind": "screen", "ok": False, "data": None,
                "error": f"东财选股 HTTP {status}: {snippet}"}
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as e:
        return {"source": "eastmoney", "kind": "screen", "ok": False, "data": None,
                "error": f"东财选股返回非 JSON: {e}"}
    return {"source": "eastmoney", "kind": "screen", "ok": True, "data": payload, "error": None}
