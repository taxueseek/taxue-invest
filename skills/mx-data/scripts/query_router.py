#!/usr/bin/env python3
"""Query router — 场景状态机的唯一真源。

一个场景由四件事共同定义，且只在这里定义：
  name        展示名（文档表与 route_info 共用）
  trigger     从 `--type` / 代码形态 / 中文关键词推出场景 key
  argv        该场景对应的 invest-cli argv（子命令 + 参数位）
  route_kind  走 route.fetch 的 kind 与 market（None = 不经快照链，走命令）

历史缺陷：同一场景的状态此前散在三处——`SCENARIO_COMMANDS`（文档表）、
`_scenario_cmd()`（get_data 的 argv 分支）、`_FETCHERS`（in-process 取数映射）。
三份各自维护，加一个场景要改三处，漏一处就是「文档说走 A、实际走 B」。
2026-11-09 收口为单一表：`detect_scenario` 只产出 key，argv 与 route_kind
全部从本表派生。
"""
import re
from typing import Dict, List, Optional

# 美股 ticker 的形态：1-5 位字母，允许 BRK.B / BRK-B。只用于**整个输入就是代码**
# 的场景，不拿它去扫自然语言句子（「ROE」「PE」这类缩写会被误判成 ticker）。
_US_TICKER = re.compile(r"^[A-Za-z]{1,5}(?:[.\-][A-Za-z]{1,4})?$")


def looks_like_us_ticker(value: str) -> bool:
    v = (value or "").strip()
    return bool(v) and bool(_US_TICKER.match(v))


# 场景 → {name, argv, route_kind}。argv 里的 `<code>` / `<query>` 是参数占位，
# 由 get_data 按位置替换；route_kind = (kind, market) 或 None（不经 route.fetch）。
SCENARIO_COMMANDS = {
    "stock_a": {
        "name": "A股基本面",
        "argv": ["stock", "<code>", "--json"],
        "route_kind": ("stock", "a"),
        "example": "invest-cli stock 600519 --json",
    },
    "stock_hk": {
        "name": "港股",
        "argv": ["stock", "<code>", "--json"],
        "route_kind": ("stock", "hk"),
        "example": "invest-cli stock 00700 --json",
    },
    "stock_us": {
        "name": "美股",
        "argv": ["us", "<code>", "--json"],
        "route_kind": ("us", None),
        "example": "invest-cli us AAPL --json",
    },
    "fund": {
        "name": "基金",
        "argv": ["fund", "<code>", "--json"],
        "route_kind": ("fund", None),
        "example": "invest-cli fund 005827 --json",
    },
    "bond": {
        "name": "债券",
        "argv": ["intent", "deep", "bond", "<code>"],
        "route_kind": None,
        "example": "invest-cli intent deep bond 240001",
    },
    "industry": {
        "name": "行业板块",
        "argv": ["stock", "<code>", "--json"],
        "route_kind": ("stock", "a"),
        "example": "invest-cli stock 600519 --json && invest-cli cn report 600519",
    },
    "news": {
        "name": "资讯舆情",
        "argv": ["info", "<query>"],
        "route_kind": None,
        "example": "invest-cli info 茅台 最新",
    },
    "macro": {
        "name": "宏观",
        "argv": ["intent", "macro"],
        "route_kind": None,
        "example": "invest-cli intent macro",
    },
    "enterprise": {
        "name": "企业深度",
        "argv": ["stock", "<code>", "--json"],
        "route_kind": ("stock", "a"),
        "example": "invest-cli stock 600519 --json && invest-cli cn holders 600519",
    },
}

_TYPE_TO_SCENARIO = {
    "stock": "stock_a",
    "us": "stock_us",
    "fund": "fund",
    "bond": "bond",
    "industry": "industry",
    "enterprise": "enterprise",
    "news": "news",
    "macro": "macro",
}


def detect_scenario(query: str = "", target_type: str = "", code: str = "") -> str:
    """Detect scenario from target type + code/query.

    判定顺序（先具体后泛化）：
      1. 显式 `--type us` → 美股；
      2. `--type stock` + 代码是字母 ticker → 美股（**不是** A 股）——
         旧行为把 `--type stock --code AAPL` 标成「A股基本面」并走 stock 链，
         实测拿到的是东财的 10 项扁平行情，美股四维评分要的 FCF/负债全缺；
      3. 无 type、整个输入就是 ticker → 美股；
      4. 其余按中文关键词（港股/基金/债券/…）判，默认 A 股。
    """
    probe = (code or "").strip() or (query or "").strip()
    if target_type:
        if target_type == "stock" and looks_like_us_ticker(probe):
            return "stock_us"
        return _TYPE_TO_SCENARIO.get(target_type, "stock_a")

    if looks_like_us_ticker(probe):
        return "stock_us"

    q = query.lower()
    if any(k in q for k in ["港股", "hk"]):
        return "stock_hk"
    elif any(k in q for k in ["美股", "us", "aapl", "tsla", "nvda"]):
        return "stock_us"
    elif any(k in q for k in ["基金", "etf", "fund"]):
        return "fund"
    elif any(k in q for k in ["债券", "bond", "国债", "城投"]):
        return "bond"
    elif any(k in q for k in ["行业", "板块", "industry"]):
        return "industry"
    elif any(k in q for k in ["企业", "公司深度", "enterprise"]):
        return "enterprise"
    elif any(k in q for k in ["资讯", "舆情", "新闻"]):
        return "news"
    elif any(k in q for k in ["宏观", "流动性", "fed", "macro"]):
        return "macro"
    else:
        return "stock_a"


def get_route(scenario: str) -> Dict:
    """Get routing info for scenario."""
    return SCENARIO_COMMANDS.get(scenario, {
        "name": "未知",
        "argv": ["stock", "<code>", "--json"],
        "route_kind": ("stock", "a"),
        "example": "invest-cli stock <代码> --json",
    })


def scenario_argv(scenario: str, code: str = "", query_str: str = "") -> List[str]:
    """场景 → invest-cli argv（不含 invest-cli 本身），占位符已替换。

    单一派生点：`_scenario_cmd` 的旧分支表已删除，argv 只从 SCENARIO_COMMANDS
    读。含空格的查询词按**一个参数**原样保留（返回 list，由调用方直接起进程，
    不再做字符串切分——见 get_data._fetch_subprocess 的历史坑）。
    """
    conf = SCENARIO_COMMANDS.get(scenario)
    if conf is None:
        conf = {"argv": ["stock", code, "--json"]}
    out: List[str] = []
    for token in conf["argv"]:
        if token == "<code>":
            out.append(code)
        elif token == "<query>":
            out.append(query_str)
        else:
            out.append(token)
    return out


def scenario_route_kind(scenario: str) -> Optional[tuple]:
    """场景 → (route kind, market)；None = 不经 route.fetch（走 invest-cli 命令）。"""
    conf = SCENARIO_COMMANDS.get(scenario)
    if conf is None:
        return ("stock", "a")
    return conf.get("route_kind")
