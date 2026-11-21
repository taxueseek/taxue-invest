"""命令与插件元数据的单一真源（第十轮收口）。

为什么有这一层：同一个命令事实此前散在五处——`invest_cli.py` 的 argparse 与
dispatch 表、插件 `index.js` 的 COMMANDS/CATEGORIES/TIMEOUTS，以及 `client.js`
里逐字复制的同一批常量。加一个命令要改两到三处，靠 Node 侧的 drift gate 事后
兜底；2026-11-08 的 `capabilities` 表漏掉 etf-rank、cx 注释仍写 21 个工具，
都是这一结构缺口的表现。

本模块只声明**元数据**，不声明参数语法（参数仍在 invest_cli.py，靠近解析逻辑）。
`sync_registry.py` 把它与 `data-sources.yaml` 一起生成插件侧产物；
`test_registry.py` 钉住「注册表 = parser = dispatch = 插件产物」四者相等。

改动纪律：加命令先改本文件，再补 parser/dispatch，最后跑
`python scripts/sync_registry.py` 生成插件产物。
"""
from __future__ import annotations

from typing import Any

# 分类是展示层分组，不影响路由；顺序即插件设置页顺序。
CATEGORIES: list[dict[str, str]] = [
    {"id": "quotes", "nameZh": "行情与快照", "nameEn": "Quotes & Snapshots"},
    {"id": "fundamentals", "nameZh": "财报与基本面", "nameEn": "Fundamentals & Filings"},
    {"id": "governance", "nameZh": "选股与治理", "nameEn": "Screening & Governance"},
    {"id": "institutional", "nameZh": "机构与透传", "nameEn": "Institutional & Pass-through"},
    {"id": "auxiliary", "nameZh": "宏观与辅助", "nameEn": "Macro & Utility"},
]

# 命令清单：id 必须与 argparse 子命令、dispatch 键、插件 COMMANDS 完全一致。
# direct_source 用于运行时账本：直取命令绕开 route.fetch，没有它就无法回答
# 「htbr 的 72 个接口实际被用过几次」。
COMMANDS: list[dict[str, Any]] = [
    {"id": "stock", "category": "quotes", "zh": "A股/港股快照", "en": "A/HK Stock Snapshot", "desc": "13项基本面+实时行情"},
    {"id": "fund", "category": "quotes", "zh": "公募基金快照", "en": "Mutual Fund Snapshot", "desc": "净值/重仓/收益率+评级"},
    {"id": "us", "category": "quotes", "zh": "美股行情与历史", "en": "US Stock & History", "desc": "全量快照/EOD历史"},
    {"id": "quote", "category": "quotes", "zh": "极速免鉴权行情", "en": "Fast Quotes (Keyless)", "desc": "跨市场毫秒级批量行情"},
    {"id": "kline", "category": "quotes", "zh": "K线行情", "en": "K-Line Bars", "desc": "日/周/月K线时序"},
    {"id": "sec", "category": "fundamentals", "zh": "SEC EDGAR 财报原文", "en": "SEC EDGAR Filings", "desc": "10-K/10-Q/8-K XBRL 原文及全文检索", "direct_source": "sec_edgar"},
    {"id": "fmp", "category": "fundamentals", "zh": "美股三表深取", "en": "FMP Fundamentals", "desc": "三表财务/TTM比率/评级/预测", "direct_source": "fmp"},
    {"id": "cn", "category": "fundamentals", "zh": "A股市场结构", "en": "CN Market Structure", "desc": "公告检索/一致预期/股东/研报"},
    {"id": "screen", "category": "governance", "zh": "自然语言选股", "en": "NL Stock Screener", "desc": "多因子自然语言选股"},
    {"id": "fund-class", "category": "governance", "zh": "基金三层分类", "en": "Fund Classification", "desc": "大类/风格/细分三层定性"},
    {"id": "tenure", "category": "governance", "zh": "经理任职期复盘", "en": "Manager Tenure Review", "desc": "分年度超额收益与回撤归因"},
    {"id": "research", "category": "governance", "zh": "长程研究管线", "en": "Research Pipeline", "desc": "主题基金排名 / 指数基金横评"},
    {"id": "report", "category": "institutional", "zh": "基金定期报告 PDF", "en": "Fund Report PDF", "desc": "季报/年报原文下载"},
    {"id": "westock", "category": "institutional", "zh": "微证券透传", "en": "WeStock Pass-through", "desc": "筹码/龙虎榜/资金流/产业链", "direct_source": "westock"},
    {"id": "wind", "category": "institutional", "zh": "万得透传", "en": "Wind Pass-through", "desc": "Wind 金融终端/MCP 原生能力", "direct_source": "wind"},
    {"id": "yingmi", "category": "institutional", "zh": "盈米透传", "en": "YingMi Pass-through", "desc": "且慢投顾组合与策略", "direct_source": "yingmi"},
    {"id": "ttskill", "category": "institutional", "zh": "天天基金透传", "en": "TTFund Pass-through", "desc": "37个官方业务包直连", "direct_source": "ttskill"},
    {"id": "htbr", "category": "institutional", "zh": "华泰柏瑞ETF事实查询", "en": "HTBR ETF Facts", "desc": "72 接口：经理观点/行业穿透/盈利预测", "direct_source": "htbr"},
    {"id": "sfg", "category": "institutional", "zh": "见基行事基金MCP", "en": "SeefundGo Fund MCP", "desc": "45 工具：档案/持仓/经理/选基/组合体检", "direct_source": "sfg"},
    {"id": "info", "category": "auxiliary", "zh": "财经资讯检索", "en": "Financial News", "desc": "argo 财经垂直引擎检索"},
    {"id": "watchlist", "category": "auxiliary", "zh": "自选股管理", "en": "Watchlist", "desc": "自选池增删改查"},
    {"id": "capabilities", "category": "auxiliary", "zh": "能力清单", "en": "Capabilities Matrix", "desc": "各数据源支持能力"},
    {"id": "datasources", "category": "auxiliary", "zh": "数据源状态", "en": "Data Sources Status", "desc": "源可用性与快照链优先级"},
    {"id": "intent", "category": "auxiliary", "zh": "意图路由", "en": "Intent Router", "desc": "资产类型自动识别与分流"},
    {"id": "doctor", "category": "auxiliary", "zh": "运行面自检", "en": "Runtime Health Check", "desc": "源/账本/缓存/解释器/软链/副本六面体检"},
]

# 慢命令预算（毫秒）。tenure 要串「在管清单 → 逐只净值分段抓取 → 基准指数 →
# 分年度统计」，冷跑实测 >60s（Wind 净值单次硬顶 100 行，6 只基金 53 次调用）；
# report 要下载 PDF；sec 的 companyfacts 单文件约 3.7MB。默认 60s 会把它们误杀。
TIMEOUTS: dict[str, int] = {
    "tenure": 180_000,
    "research": 180_000,
    # 与 sfg.poll_portfolio 的 POLL_MAX_WAIT 对齐：组合体检实测 298-340s，
    # 给 420s 余量（旧 180s 会在结果落盘前被杀）。
    "sfg": 420_000,
    "report": 120_000,
    "sec": 90_000,
    "screen": 60_000,
    "cn": 60_000,
    "fmp": 60_000,
}

# 大结果命令的输出预算（字符）。默认 24k 只够 stock/fund/quote 这类快照；
# 实测 `us --history` 59.9k、`sec` 28.5k——按默认切会把 JSON 拦腰截断。
# 预算按命令给，而不是把全局上限抬高：后者会让每一次普通调用都多背上下文。
OUTPUT_LIMITS: dict[str, int] = {
    "sec": 80_000,
    "tenure": 80_000,
    "research": 60_000,
    "sfg": 60_000,
}

# 插件默认值。json=true 表示默认给模型结构化输出；maxArgs/maxArgChars 是
# 防呆上限（argv 直传不经 shell，无注入面）。disabledSources 是「面板选择」
# 的桥接字段：面板 checkbox 写它，spawn 时注入 INVEST_CLI_DISABLE_SOURCES
# 给 invest-cli 子进程（每次调用新进程，改完立即生效）——引擎侧原语见
# sources/route.py 的 disabled_sources()。
DEFAULTS: dict[str, Any] = {
    "timeoutMs": 60_000,
    "maxOutputChars": 24_000,
    "json": True,
    "maxArgs": 32,
    "maxArgChars": 512,
    "cliPath": "",
    "skillRoot": "",
    "disabledSources": "",
}

# 插件数据源面板的英文名与「免密」标记：yaml 是 id/优先级/覆盖/凭据的真源，
# 这两项纯展示，放在这里避免为了 UI 改数据源配置。
SOURCE_EN: dict[str, str] = {
    "wind": "Wind AI FinMarket",
    "yingmi": "YingMi Qieman",
    "index_hub": "E Fund Index Hub",
    "etfirst": "etfirst",
    "htbr": "HTBR ETF Facts",
    "sfg": "SeefundGo Fund MCP",
    "hithink": "Hithink Finance",
    "mxds": "Miaoxiang MCP",
    "ttskill": "TTFund Direct Gateway",
    "eastmoney": "Eastmoney",
    "fmp": "Financial Modeling Prep",
    "sec_edgar": "SEC EDGAR Filings",
    "yfinance": "Yahoo Finance",
    "tencent": "Tencent Quotes",
    "tiingo": "Tiingo EOD History",
    "bitget": "Bitget rToken",
    "westock": "WeStock CLI",
    "fred": "FRED Macro Series",
    "argo": "Argo Financial Search",
}
SOURCE_KEYLESS: frozenset[str] = frozenset({
    "etfirst", "ttskill", "sec_edgar", "yfinance", "tencent",
    "bitget", "westock", "fred", "argo",
})

# 凭据面板：只列需要用户配置的源；ref 必须在 data-sources.yaml 的 env_var 中出现。
SOURCE_KEYS: list[dict[str, Any]] = [
    {"ref": "HITHINK_FINANCE_API_KEY", "nameZh": "同花顺金融数据", "nameEn": "Hithink Finance", "hintZh": "同花顺金融 OpenAPI 凭据 (stock, fund)", "hintEn": "Hithink Finance credentials", "common": True},
    {"ref": "EASTMONEY_APIKEY", "nameZh": "东方财富", "nameEn": "Eastmoney", "hintZh": "东方财富数据开放平台 Key (stock, fund, screen)", "hintEn": "Eastmoney API Key", "common": True},
    {"ref": "EM_API_KEY", "nameZh": "妙想(MX) MCP", "nameEn": "Miaoxiang MCP", "hintZh": "东财妙想自然语言取数 Key (全品类覆盖)", "hintEn": "Eastmoney Miaoxiang API Key", "common": True},
    {"ref": "WIND_API_KEY", "nameZh": "万得 Wind", "nameEn": "Wind AI FinMarket", "hintZh": "万得 Wind 金融终端/MCP 密钥 (机构主力)", "hintEn": "Wind AI FinMarket Key", "common": True},
    {"ref": "YINGMI_API_KEY", "nameZh": "盈米且慢", "nameEn": "YingMi Qieman", "hintZh": "盈米基金投顾 OpenAPI Key", "hintEn": "YingMi OpenAPI Key", "common": False},
    {"ref": "FMP_API_KEY", "nameZh": "Financial Modeling Prep", "nameEn": "Financial Modeling Prep", "hintZh": "美股三表/TTM 比率/评级 Key (每日250次免费)", "hintEn": "US fundamental & ratios Key", "common": True},
    {"ref": "TIINGO_API_KEY", "nameZh": "Tiingo", "nameEn": "Tiingo", "hintZh": "Tiingo 美股复权日线与估值序列 Key", "hintEn": "Tiingo EOD & valuation Key", "common": False},
    {"ref": "FRED_API_KEY", "nameZh": "美联储 FRED", "nameEn": "Federal Reserve FRED", "hintZh": "FRED 宏观流动性 API Key (无 key 自动免密回退)", "hintEn": "FRED API Key (keyless fallback supported)", "common": False},
    {"ref": "INDEX_HUB_API_KEY", "nameZh": "易方达指数直通车", "nameEn": "E Fund Index Hub", "hintZh": "易方达指数投资服务平台 Key", "hintEn": "E Fund Index Hub Key", "common": False},
    {"ref": "SFG_MCP_TOKEN", "nameZh": "见基行事(seefundgo)", "nameEn": "SeefundGo Fund MCP", "hintZh": "见基行事公募基金 MCP Token (档案/持仓/经理/选基/组合体检)", "hintEn": "SeefundGo fund MCP Token", "common": False},
]


def command_ids() -> list[str]:
    return [c["id"] for c in COMMANDS]


def direct_sources() -> dict[str, str]:
    """命令 → 直取数据源 id（只含绕开 route.fetch 的命令）。"""
    return {c["id"]: c["direct_source"] for c in COMMANDS if c.get("direct_source")}


def categories_with_commands() -> list[dict[str, Any]]:
    """按分类聚合命令，供插件设置页与产物生成。"""
    out: list[dict[str, Any]] = []
    for cat in CATEGORIES:
        cmds = [
            {k: v for k, v in c.items() if k != "category"}
            for c in COMMANDS if c["category"] == cat["id"]
        ]
        out.append({**cat, "commands": cmds})
    return out
