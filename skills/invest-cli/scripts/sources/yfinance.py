"""Yahoo Finance (yfinance) 数据源适配器。

复用 scripts/cmd_us.py 的取数与输出，返回结构一致。
yfinance 天然支持 .SS/.SZ/.HK 后缀，因此除美股外也担当
A股/港股快照链的兜底源（route.fetch 末位；A股主路仍是同花顺/东财）。

运行期依赖声明（route.candidates 缺件摘链用，写 import 名而非 pip 名）：
真依赖 yfinance 包在 cmd_us.py 函数内延迟 import，适配器本体可导入不代表
依赖可用——不声明的话，缺件解释器仍会把本源排在 us 链头，与文档真值分家。
"""
from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_IMPORTS = ("yfinance",)

_SCRIPTS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def us(symbol: str) -> dict:
    return _fetch("us", symbol)


def stock(keyword: str) -> dict:
    """A股/港股兜底（yfinance 支持 .SS/.SZ/.HK）。"""
    return _fetch("stock", keyword)


def _fetch(kind: str, symbol: str) -> dict:
    try:
        from cmd_us import fetch_us_data
    except ImportError as e:
        return {"source": "yfinance", "kind": kind, "ok": False, "data": None,
                "error": f"yfinance 未安装: {e}"}
    try:
        return {"source": "yfinance", "kind": kind, "ok": True, "data": fetch_us_data(symbol.upper()), "error": None}
    except Exception as e:
        # 不加「yfinance 取数失败:」前缀：route 层已按 sid 标注来源，
        # 再拼一次会得到「yfinance: yfinance 取数失败: ...」的双重标签。
        return {"source": "yfinance", "kind": kind, "ok": False, "data": None, "error": str(e)}
