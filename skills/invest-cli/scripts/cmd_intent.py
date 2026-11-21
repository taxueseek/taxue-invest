"""intent 意图层：把 69 个盈米工具 + Wind 7 类收敛为 6 个语义入口。

第一性原理：接口面要小（按意图），能力面要全（内部路由到权威源）。
外部只暴露 deep/screen/portfolio/plan/macro/present 六个意图命令，
内部按场景 + 标的类型路由到盈米/Wind/同花顺/东财/官方 ttskill 的具体工具。

数据源透传（wind/yingmi 子命令）保留为高级/调试入口，不是主用法。

使用:
    invest-cli intent deep <type> <标的> [--json]      # type: stock/fund/bond/commodity
    invest-cli intent screen <条件> [--json]
    invest-cli intent portfolio <持仓json|自然语言> [--json]
    invest-cli intent plan <家庭数据json|自然语言> [--json]
    invest-cli intent macro [--json]
    invest-cli intent present <html文件路径> [--json]   # HTML → 终端摘要
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

# 场景 → 权威源调用。内部路由，供意图层复用。
# 每个调用用现有 source 适配器（yingmi.call / wind.call / eastmoney / 官方 ttskill）。
ROUTES: dict[str, dict] = {
    "deep": {
        "fund": lambda p: ("fund_deep", p, None),
        "stock_a_hk": lambda p: ("stock_deep", p, None),
        "us": lambda p: ("yfinance", p, None),
        "bond": lambda p: ("bond_deep", p, None),
        "commodity": lambda p: ("ttskill_scene", "TTFUND_GOLD_INFO", {"query_scope": "gold"}),
    },
    "screen": {
        # v3.8（MECE 定编）：基金筛选以 sfg 多因子筛选为主路，盈米 SearchFunds 退居兜底。
        "fund": lambda p: ("fund_screen", p, None),
        "stock": lambda p: ("eastmoney_screen", p, None),
    },
    "macro": {},
    # v3.8：组合诊断优先走 sfg（异步 submit），盈米 DiagnoseFundPortfolio 退居兜底
    # （显式传盈米 JSON {"fundList":...} 时仍直达盈米，保持兼容）。
    "portfolio": {"default": lambda p: ("portfolio_check", p, None)},
    "plan": {"default": lambda p: ("yingmi", "GetAssetAllocationPlan", _plan_params(p))},
    "present": {"default": lambda p: ("present_html", p, None)},
    "mxds": {"default": lambda p: ("mxds_auto", p, None)},
    "sfg": {"default": lambda p: ("sfg_auto", p, None)},
}

# 代码域分类的唯一真源在 _common（cmd_stock / cmd_fund 也用同一判据拦
# 「代码域与子命令不匹配」）。此处只做再导出，避免同一判据出现第二份实现。
from _common import kind_from_code, looks_like_us_ticker  # noqa: E402


def _is_fund_by_yingmi(target: str) -> bool:
    """用盈米 GuessFundCode 确认是否基金（自动识别用）。失败默认非基金。

    盈米是**子串式模糊匹配**：股票简称会被配到「名字里含这几个字」的无关基金。
    实测：「中国平安」→「华银平安中国主题灵活配置混合」，
    「招商银行」→「银叶投资-招商银行-宁海工业园1号」。
    因此判据不能是「盈米返回了东西」，而必须是「返回的基金名与查询确有对应」：
    查询是基金名前缀（「易方达蓝筹精选」→「易方达蓝筹精选混合」），
    或者查询占了基金名的大部分（短名不要拿去配长名）。
    """
    try:
        from sources import yingmi as _ym
        res = _ym.call("GuessFundCode", {"fundNameOrCode": target})
    except Exception:
        return False
    if not res.get("ok"):
        return False
    data = res.get("data") or {}
    if not isinstance(data, dict):
        return False
    name = str(data.get("fundName") or data.get("name") or "").strip()
    kw = (target or "").strip()
    if not name or not kw:
        return False
    if name.startswith(kw):
        return True
    return kw in name and len(kw) >= 0.6 * len(name)


# 英文类型词精确匹配：避免裸类型词被当成美股代码或拿去问盈米
_EN_TYPE: dict[str, str] = {"bond": "bond", "gold": "commodity", "commodity": "commodity"}


def classify(target: str) -> str:
    """根据代码/名称自动识别标的类型：fund / stock / us / bond / commodity。"""
    t = target.strip()
    en = _EN_TYPE.get(t.lower())
    if en:
        return en
    # 名称关键词
    if any(k in t for k in ("基金", "混合", "ETF", "联接", "指数增强", "债基", "定开", "LOF", "FOF", "QDII")):
        return "fund"
    if any(k in t for k in ("债券", "国债", "转债", "信用债", "城投")):
        return "bond"
    if any(k in t for k in ("黄金", "白银", "原油", "商品")):
        return "commodity"
    coded = kind_from_code(t)
    if coded:
        return coded
    if re.fullmatch(r"\d{6}", t):
        return "fund" if _is_fund_by_yingmi(t) else "stock"
    # 美股字母代码（含 BRK.B / BRK-B，必须限 ASCII）：Python 里汉字也是 isalpha()，
    # 旧写法既会把中文名判成美股，又漏掉带点/横杠的类别股（BRK.B）。
    if looks_like_us_ticker(t):
        return "us"
    # 名称兜底：用盈米确认是否为基金（多数基金名不含「基金」二字）。
    # 但**短名（≤2 字）不做模糊匹配**：盈米的名称猜测是子串式的，
    # 「腾讯」会命中「银河定投宝腾讯济安指数」而被判成基金，
    # 而 2 字输入里股票/港股简称远多于基金简称（实测误配代价高于收益）。
    if len(t) >= 3 and _is_fund_by_yingmi(t):
        return "fund"
    return "stock"


def _looks_like_fund_screen(value: str) -> bool:
    return any(k in (value or "") for k in ("基金", "ETF", "债基", "LOF", "FOF", "QDII", "基金经理"))


# SearchFunds 是**基金名子串搜索**，不是语义检索：把自然语言短语原样喂进去
# 大概率零命中（实测 2026-10-11「红利主题基金」→ 0 条，「红利」→ 10 条）。
# 提炼规则只剥一小撮**通用修饰词**（确定性的词表，不做语义猜测）；剥完为空
# 则原样返回。注意不能把「混合/优选/精选」这类真名用词放进来。
_FUND_SEARCH_STOPWORDS = ("主题基金", "基金", "主题", "概念", "相关", "的")


def _fund_search_keyword(value: str) -> str:
    """自然语言基金条件 → SearchFunds 可命中的名字关键词。"""
    kw = (value or "").strip()
    for w in _FUND_SEARCH_STOPWORDS:
        kw = kw.replace(w, "")
    kw = kw.strip()
    return kw or (value or "").strip()


def _resolve_fund_code(target: str) -> str:
    """基金名 → 基金代码（用盈米 GuessFundCode）。已是 6 位代码则原样返回。"""
    t = target.strip()
    if re.fullmatch(r"\d{6}", t):
        return t
    try:
        from sources import yingmi as _ym
        res = _ym.call("GuessFundCode", {"fundNameOrCode": t})
        data = res.get("data") if res.get("ok") else None
        if isinstance(data, dict):
            for k in ("fundCode", "code", "fund_code"):
                if data.get(k):
                    return str(data[k])
    except Exception:
        pass
    return t


# 持仓简写：110011:50 / 110011=10000 / 110011:50,005827:50。
# 金额必须带显式分隔符（: ： =）：否则「110011 005827」会被贪心成 code=110011, amount=5827。
_HOLDING_ITEM = re.compile(
    r"([0-9]{6}|[A-Za-z][A-Za-z0-9.]{0,9})(?:\s*[:：=]\s*([0-9]+(?:\.[0-9]+)?))?"
)


def _portfolio_params(value: str) -> dict:
    """自然语言/简写持仓 → DiagnoseFundPortfolio 的 body {fundList:[{fundCode,amount}]}。

    SKILL 文档写明 `intent portfolio <持仓json或自然语言>`，但旧实现把整串当
    `{"input": ...}` 发出去，服务端固定回 400「基金列表不能为空」——文档承诺的
    自然语言路径实际不可用。JSON 输入仍由 run() 原样透传（含 fundList 或基金数组）。
    """
    t = (value or "").strip()
    if t.startswith(("{", "[")):
        return {}  # JSON 由 run() 解析后覆盖
    fund_list = []
    for code, amount in _HOLDING_ITEM.findall(t):
        fund_list.append({"fundCode": code, "amount": float(amount) if amount else 10000.0})
    if not fund_list:
        return {}
    return {"fundList": fund_list}


def _num_before_or_after(text: str, keyword: str) -> float | None:
    """取关键词附近的数字：同时支持「20%回撤」与「回撤 20%」两种语序。"""
    m = re.search(rf"([0-9]+(?:\.[0-9]+)?)\s*%?\s*{keyword}", text) or \
        re.search(rf"{keyword}[^0-9]{{0,6}}([0-9]+(?:\.[0-9]+)?)\s*%?", text)
    return float(m.group(1)) if m else None


def _plan_params(value: str) -> dict:
    """自然语言 → GetAssetAllocationPlan 的三个查询参数（三性至少一项）。

    支持「能承受 20% 回撤 / 5 年 / 预期年化 8%」；百分比换算成小数。
    数字在关键词前或后都能识别（中文里两种语序都常见）。
    """
    t = (value or "").strip()
    if t.startswith(("{", "[")):
        return {}
    params: dict[str, float | str] = {}
    dd = _num_before_or_after(t, "回撤")
    if dd is not None:
        params["expectedDrawdown"] = dd / 100
    ret = _num_before_or_after(t, "年化")
    if ret is not None:
        params["expectedAnnualizedReturnRate"] = ret / 100
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*年", t)
    if m:
        params["expectedInvestTime"] = f"{m.group(1)}y"
    return params


def _dispatch(scene: str, value: str) -> dict:
    """按场景 + 标的类型返回 {source:..., call:...}，失败返回 {'error':...}。"""
    if scene == "deep":
        parts = value.split(" ", 1)
        if len(parts) != 2:
            # 无显式类型 → 自动识别；但「只有类型词没有标的」是缺参数，
            # 不能把它当成标的（旧写法会把 `deep stock` 当成美股代码 STOCK）。
            target = parts[0].strip()
            # commodity/gold 的取数是固定场景（TTFUND_GOLD_INFO），本就不需要标的；
            # 其余类型词没有标的就是缺参数，不能把它当成标的（旧写法会把
            # `deep stock` 当成美股代码 STOCK）。
            if target.lower() in ("stock", "fund", "us", "bond"):
                return {"error": f"deep 缺少标的（用法: intent deep <type> <标的>）"}
            typ = classify(target)
        else:
            typ, target = parts[0], parts[1].strip()
            # 显式类型词归一：gold → commodity（与 classify 的 _EN_TYPE 同源，避免「gold 支持不了」）
            typ = _EN_TYPE.get(typ.lower(), typ)
        key = "stock_a_hk" if typ == "stock" else typ
        if typ == "us":
            key = "us"
        if typ == "fund":
            target = _resolve_fund_code(target)
        route = ROUTES["deep"].get(key) or ROUTES["deep"].get(typ)
        if not route:
            return {"error": f"deep 不支持类型 {typ}"}
        return {"scene": "deep", "type": typ, "route": route(target)}
    if scene == "screen":
        # 默认走 route 选股（妙想优先、东财兜底——与 invest-cli screen 同链）；明确基金语义才走盈米。
        key = "fund" if _looks_like_fund_screen(value) else "stock"
        return {"scene": "screen", "route": ROUTES["screen"][key](value)}
    if scene in ("portfolio", "plan", "present"):
        return {"scene": scene, "route": ROUTES[scene]["default"](value)}
    if scene == "macro":
        # 空参默认查美国净流动性（FRED WALCL/TGA/ON RRP）；含中国宏观关键词时分流至中国通道
        return {"scene": "macro", "route": ("macro_pipeline", (value or "").strip(), None)}
    if scene == "mxds":
        return {"scene": "mxds", "route": ROUTES["mxds"]["default"](value)}
    if scene == "sfg":
        # 见基行事：整串作为 question 交给 sfg 侧路由（工具选择由 sfg_help/别名表决定）
        return {"scene": "sfg", "route": ROUTES["sfg"]["default"](value)}
    return {"error": f"未知场景 {scene}"}

def _stock_with_fallback(target: str) -> dict:
    """deep stock：快照链走 route（A 股同花顺→东财，港股东财）。"""
    from cmd_stock import _looks_like_hk
    from sources.route import fetch

    market = "hk" if _looks_like_hk(target) else "a"
    return fetch("stock", target, market=market)


def _fund_with_fallback(target: str) -> dict:
    """deep fund：盈米诊断 → route 快照链 → 妙想基金事实。不混字段。

    v3.8.1：sfg 是积分制源，退出通用主路（经理画像/绩效归因/风格漂移/组合体检
    显式走 `invest-cli intent sfg` 或 `invest-cli sfg <别名>`）。
    v3.8.2：结构化快照（hithink > ttskill > eastmoney）优先于妙想自然语言表格，
    仅当快照链也失败时由妙想兜底，避免无盈米 Key 时挡住确定性结构化快照。
    """
    from sources import load_registry
    from sources.registry import detect as detect_conf
    from sources.route import code_domain_error, fetch

    # 代码域守卫：这条路径**先问盈米**（不经 route.fetch），所以 route 那层
    # 的守卫拦不到它。实测 `intent deep fund 600519` 会拿到盈米的
    # `{"ok": true, "message": "未识别到具体基金"}` 并 rc=0。
    # 用同一份判据（route.code_domain_error），不在这里另写一套。
    _err = code_domain_error("fund", target)
    if _err:
        return {"source": "fund", "kind": "fund", "ok": False, "data": None, "error": _err}

    registry = load_registry()
    conf = registry.get("yingmi")
    if conf:
        ok, _ = detect_conf(conf)
        if ok:
            try:
                from sources import yingmi as _ym

                code = _resolve_fund_code(target)
                res = _ym.call("GetFundDiagnosis", {"fundCode": code})
                if res.get("ok"):
                    return res
            except Exception:
                pass
    snap = fetch("fund", target)
    if snap.get("ok"):
        return snap
    mxds_conf = registry.get("mxds")
    if mxds_conf and detect_conf(mxds_conf)[0]:
        try:
            from sources import mxds as _mxds

            res = _mxds.auto(_fund_mx_query(target))
            if res.get("ok"):
                return res
        except Exception:
            pass
    return snap


def _fund_mx_query(target: str) -> str:
    """给妙想的查询串：标准码直接用，名称补「净值 持仓」提高命中率。"""
    t = (target or "").strip()
    if not t:
        return t
    # 6 位代码或带后缀标准码：NLU 对纯代码识别最好，不画蛇添足
    if re.fullmatch(r"\d{6}(?:\.(?:OF|SH|SZ|BJ|HK))?", t, re.I):
        return t.upper()
    return f"{t} 净值 持仓"


# 条件式筛选的判据词。**不含裸「前」**：「白酒基金前十」是排名意图而非阈值
# 筛选，旧写法把它误判成条件查询、拿不到结果（2026-11-21 实测）。
_COND_WORDS = ("大于", "高于", "低于", "小于", "超过", "不少于", "不超过",
               "夏普", "回撤", "波动率", "费率", "规模", "收益率", "年化")
_LOWER_OPS = frozenset({"低于", "小于", "不超过", "不大于", "<", "<="})


def _parse_conditions(text: str, current_year: int) -> list[dict] | None:
    """把自然语言阈值翻成 sfg_screen_funds 的 conditions 数组；翻不出返回 None。

    上游口径（实测提示）：`[{"year": 2024, "yieldMin": 0.15, "maxDrawdown": -0.20,
    "sharpeMin": 0.5}]`——year 必填且为整数年；收益/回撤/胜率用小数。

    数字、比较词与 `%` 必须**贴着该指标词**一起取：
    - 避免「近3年收益大于20%」读成 3%、「2024年夏普大于1」读成 2024；
    - 避免「年化收益大于15%且回撤低于20%」因句中含「低于」把收益反判为 yieldMax；
    - 保留 `%` 显式标记，避免「收益大于3%」「回撤低于5%」「管理费低于1.5%」漏除 100。
    """
    cond: dict[str, Any] = {}
    m_year = re.search(r"(20\d{2})\s*年", text)
    cond["year"] = int(m_year.group(1)) if m_year else current_year

    def _after(keywords: tuple[str, ...]) -> tuple[str, float, bool] | None:
        """取第一个关键词**紧邻**的 (比较词, 数值, 是否带百分号)；取不到返回 None。"""
        for kw in keywords:
            m = re.search(
                re.escape(kw)
                + r"\s*(大于|高于|低于|小于|超过|不少于|不超过|不小于|不大于|>=|<=|>|<)?\s*"
                + r"([0-9]+(?:\.[0-9]+)?)\s*(%)?",
                text,
            )
            if m:
                return (m.group(1) or "", float(m.group(2)), bool(m.group(3)))
        return None

    def _to_pct_decimal(v: float, has_pct: bool) -> float:
        """显式带 % 或大于 5 的百分数 → 小数。"""
        return v / 100 if (has_pct or v > 5) else v

    m_dd = _after(("最大回撤", "回撤"))
    if m_dd is not None:
        _, v_dd, has_pct = m_dd
        # 接口是负数口径：maxDrawdown=-0.20 表示最多跌 20%
        cond["maxDrawdown"] = -_to_pct_decimal(v_dd, has_pct)

    m_sharpe = _after(("夏普比率", "夏普"))
    if m_sharpe is not None:
        _, v_sharpe, _ = m_sharpe
        cond["sharpeMin"] = v_sharpe

    m_yield = _after(("收益率", "年化收益", "年化", "收益", "回报"))
    if m_yield is not None:
        op, v_yield, has_pct = m_yield
        key = "yieldMax" if op in _LOWER_OPS else "yieldMin"
        cond[key] = _to_pct_decimal(v_yield, has_pct)

    m_fee = _after(("管理费率", "管理费", "费率"))
    if m_fee is not None:
        _, v_fee, has_pct = m_fee
        # 基金费率日常口径均为百分数（如 0.5% / 1% / 1.5%）；仅极小裸小数（<0.05）按已是小数处理
        cond["feeMax"] = v_fee / 100 if (has_pct or v_fee >= 0.05) else v_fee

    if not any(k in cond for k in ("yieldMin", "yieldMax", "maxDrawdown", "sharpeMin", "feeMax")):
        return None
    return [cond]


def _fund_screen_with_fallback(value: str) -> dict:
    """基金筛选：显式 JSON 直达盈米 → 多因子阈值走 sfg，纯关键词直接走盈米省积分。

    v3.8.2：sfg 是积分制源，仅在解析出多因子 conditions（sfg 独有能力）时调用
    `sfg_screen_funds`；纯名称关键词（「红利主题基金」等）不再白扣 sfg 积分，直接走
    无积分墙的盈米 `SearchFunds`。
    """
    from datetime import datetime

    from sources import load_registry, yingmi as yingmi_src
    from sources.registry import detect as detect_conf

    t = (value or "").strip()
    if t.startswith("{"):
        try:
            params = json.loads(t)
            if isinstance(params, dict):
                return yingmi_src.call("SearchFunds", params=params)
        except json.JSONDecodeError:
            pass

    conditions = _parse_conditions(t, datetime.now().year) if any(
        k in t for k in _COND_WORDS) else None
    if conditions is not None:
        sfg_conf = load_registry().get("sfg")
        if sfg_conf and detect_conf(sfg_conf)[0]:
            try:
                from sources import sfg as _sfg

                res = _sfg.call("sfg_screen_funds",
                                {"conditions": conditions, "limit": 30}, question=t)
                if res.get("ok"):
                    return res
            except Exception:
                pass
    return yingmi_src.call(
        "SearchFunds",
        params={"keyword": _fund_search_keyword(t), "pageIndex": 1, "pageSize": 50},
    )


def _portfolio_with_fallback(value: str) -> dict:
    """组合诊断：显式盈米 JSON 直达盈米；否则 sfg 异步提交 → 盈米 DiagnoseFundPortfolio 兜底。

    组合体检是本源**独有**能力（妙想/盈米均无对应工具），因此保留 sfg 首选。
    v3.8.1：提交前显式判 codes 数量——单只或空 codes 直接走盈米，避免为
    「submit → 轮询」付 5 分钟（实测两只基金 succeeded 耗时 298-340s）。
    """
    from sources import load_registry, yingmi as yingmi_src
    from sources.registry import detect as detect_conf

    t = (value or "").strip()
    if t.startswith("{"):
        try:
            params = json.loads(t)
            if isinstance(params, dict):
                return yingmi_src.call("DiagnoseFundPortfolio", params=params)
        except json.JSONDecodeError:
            pass

    sfg_conf = load_registry().get("sfg")
    if sfg_conf and detect_conf(sfg_conf)[0]:
        try:
            from sources import sfg as _sfg

            codes = _sfg._extract_codes(t)
            if len(codes) >= 2:
                res = _sfg.auto(t)
                if res.get("ok"):
                    return res
                # sfg 不可用（积分耗尽/上游超时）时把原因带进兜底信封，
                # 否则排障只看到盈米结果、不知道首选源为何缺席。
                err = f"sfg: {res.get('error')}"
                fb = yingmi_src.call("DiagnoseFundPortfolio", params=_portfolio_params(t))
                if not fb.get("ok"):
                    fb["fallback_from"] = "sfg"
                    fb["fallback_error"] = err
                return fb
        except Exception as e:
            fb = yingmi_src.call("DiagnoseFundPortfolio", params=_portfolio_params(t))
            fb.setdefault("fallback_from", "sfg")
            fb.setdefault("fallback_error", f"sfg: {e}")
            return fb
    return yingmi_src.call("DiagnoseFundPortfolio", params=_portfolio_params(t))


def _bond_with_fallback(target: str) -> dict:
    """债券深取：Wind bond_data 主路 → mxds 债券自然语言兜底（无 Wind Key 时不再硬死）。"""
    from sources import load_registry, wind as wind_src
    from sources.registry import detect as detect_conf

    errors: list[str] = []
    registry = load_registry()
    w_conf = registry.get("wind")
    if w_conf and detect_conf(w_conf)[0]:
        res = wind_src.call("bond_data", "get_bond_market_data", params={"question": target})
        if res.get("ok"):
            return res
        errors.append(f"wind: {res.get('error')}")
    else:
        errors.append("wind: 未配置或不可用")

    m_conf = registry.get("mxds")
    if m_conf and detect_conf(m_conf)[0]:
        try:
            from sources import mxds as mxds_src

            res = mxds_src.bond(target) if hasattr(mxds_src, "bond") else mxds_src.auto(f"{target} 债券 估值 溢价率")
            if res.get("ok"):
                return {**res, "fallback_from": "wind", "fallback_error": "; ".join(errors)}
            errors.append(f"mxds: {res.get('error')}")
        except Exception as e:
            errors.append(f"mxds: {e}")
    return {"source": "bond", "kind": "bond", "ok": False, "data": None, "error": "; ".join(errors)}


_CN_MACRO_HINTS = (
    "中国", "国内", "央行", "社融", "M2", "LPR", "MLF", "CPI", "PPI", "PMI",
    "GDP", "统计局", "宏观经济", "城投", "国债", "SHIBOR", "DR007",
)
_US_MACRO_HINTS = (
    "美联储", "FED", "SOFR", "TGA", "RRP", "WALCL", "缩表", "流动性", "美债",
    "美元", "非农", "美国", "US",
)


def _is_cn_macro(query: str) -> bool:
    """按地区分流宏观查询，避免美国流动性失败兜底到中国统计局的口径错配。"""
    q = (query or "").strip()
    if not q:
        return False
    qu = q.upper()
    if any(k in qu for k in _US_MACRO_HINTS):
        return False
    return any(k in qu for k in _CN_MACRO_HINTS)


def _macro_pipeline(query: str) -> dict:
    """宏观分流：中国宏观走 ttskill(cn) → argo(nbs_stats)；美国/流动性走 FRED → ttskill(us) → argo(macro)。"""
    from sources import argo as argo_src, fred as fred_src, load_registry
    from sources.registry import detect as detect_conf

    registry = load_registry()
    tts_conf = registry.get("ttskill")
    tts_ready = bool(tts_conf and detect_conf(tts_conf)[0])

    if _is_cn_macro(query):
        if tts_ready:
            try:
                from sources.ttskill import invoke_scene as tts_scene

                res = tts_scene("TTFUND_MACRO_DATA", {"region": "cn"})
                if res.get("ok"):
                    return res
            except Exception:
                pass
        return argo_src.search(query or "中国 宏观经济 数据 指标", engine="nbs_stats")

    res = fred_src.liquidity()
    if res.get("ok") and (res.get("data") or {}).get("net_liquidity"):
        return res
    if tts_ready:
        try:
            from sources.ttskill import invoke_scene as tts_scene

            res_tts = tts_scene("TTFUND_MACRO_DATA", {"region": "us"})
            if res_tts.get("ok"):
                return {**res_tts, "fallback_from": "fred"}
        except Exception:
            pass
    return argo_src.search(query or "Federal Reserve net liquidity SOFR TGA ON RRP", engine="macro")


def run(scene: str, value: str, as_json: bool = False) -> int:
    from sources import argo as argo_src, yingmi as yingmi_src

    d = _dispatch(scene, value)
    if "error" in d:
        print(f"intent 错误: {d['error']}", file=sys.stderr)
        return 1

    route = d["route"]
    # route 形如 (kind, payload_a, payload_b)；按 kind 分发到 source 适配器
    kind = route[0]
    if kind == "yingmi":
        tool_name = route[1]
        params = route[2] or {}
        # 若 value 是 JSON，尝试解析作为参数覆盖
        if value.strip().startswith("{"):
            try:
                params = json.loads(value)
            except json.JSONDecodeError:
                pass
        res = yingmi_src.call(tool_name, params=params if isinstance(params, dict) else {})
    elif kind == "stock_deep":
        res = _stock_with_fallback(route[1])
    elif kind == "fund_deep":
        res = _fund_with_fallback(route[1])
    elif kind == "fund_screen":
        res = _fund_screen_with_fallback(route[1])
    elif kind == "portfolio_check":
        res = _portfolio_with_fallback(route[1])
    elif kind == "bond_deep":
        res = _bond_with_fallback(route[1])
    elif kind == "present_html":
        # 本地渲染 HTML → 终端摘要；外发 PDF 交给用户，不依赖不存在的 Wind 渲染工具
        from cmd_present import render_html_summary

        res = render_html_summary(route[1])
    elif kind == "eastmoney_screen":
        from sources.route import fetch as route_fetch

        res = route_fetch("screen", route[1])
    elif kind == "yfinance":
        from sources.route import fetch as route_fetch

        res = route_fetch("us", route[1])
    elif kind == "ttskill_scene":
        # 官方天天业务包场景（如 TTFUND_GOLD_INFO）；ttfund 老 CLI 已退役
        from sources.ttskill import invoke_scene as tts_scene

        res = tts_scene(route[1], route[2] or {})
    elif kind == "argo":
        res = argo_src.search(route[2], engine=route[1])
    elif kind == "mxds_auto":
        from sources import mxds as mxds_src
        res = mxds_src.auto(route[1])
    elif kind == "sfg_auto":
        # 见基行事自然语言入口：优先单只基金档案，多个代码/名称时走组合体检
        from sources import sfg as sfg_src
        res = sfg_src.auto(route[1])
    elif kind == "macro_pipeline":
        res = _macro_pipeline(route[1])
    else:
        res = {"source": "unknown", "ok": False, "data": None, "error": f"未知路由 {kind}"}

    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res.get("ok"):
            print(json.dumps(res.get("data"), ensure_ascii=False, indent=2))
        else:
            print(f"intent 失败: {res.get('error')}", file=sys.stderr)
    return 0 if res.get("ok") else 1
