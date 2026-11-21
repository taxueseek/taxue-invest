"""运行时路由：同一问题选一个源，不同问题才组合。

第一性原理
- 用户要的不是「把所有 API 挂上」，而是「这个问题该问谁」。
- yaml 的 coverage / priority 是声明；适配器是否暴露 stock/fund/us/screen 才是能力。
- Wind 声明覆盖 stock，但只有 call() 透传 → 不能进默认快照链。
- 同一字段禁止跨源拼接（东财 PE + 同花顺 ROE 口径不同）。
- 组合的合法形式：行情走 A、选股走 B、资讯走 C、基金诊断走 D。

探测顺序：coverage 含 kind → hasattr(adapter, kind) → detect(conf)。
先 hasattr 再 detect，避免为没有 fund() 的源（yingmi/bitget 等）付 CLI 探测成本。
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import time
from typing import Any, Callable, Optional

from . import load_registry
from .registry import detect

# 可路由的 kind = registry 里所有 route_kinds 的并集。
# 这里曾写 9 种，其中 bond/index/macro/news/notice 从未有任何源声明进链，
# 是「看起来支持」的假承诺（实测恒空链）；test_route 钉住本元组与配置真源相等，
# 新增可路由 kind 先改 yaml 的 route_kinds，本处同步，否则门禁变红。
KIND_FNS = ("stock", "fund", "us", "screen")
# 市场对默认快照链的排除（能力边界，不是优先级）
MARKET_EXCLUDE = {
    ("stock", "hk"): frozenset({"hithink"}),
}
# 市场对默认快照链的局部优先级微调（v3.8）：
# 港股链 eastmoney(50) 覆盖 21 项基本面；一旦失败，tencent(189ms 零鉴权)
# 在境内网络远快且稳于 yfinance(2s 探测超时)，因此港股链顺序为
# eastmoney > tencent > yfinance，不影响 A 股与美股链。
MARKET_PRIORITY_OVERRIDE: dict[tuple[str, str], dict[str, int]] = {
    ("stock", "hk"): {"tencent": 41},
}


def disabled_sources() -> frozenset:
    """用户停用集（INVEST_CLI_DISABLE_SOURCES，逗号/分号/空白分隔，大小写不敏感）。

    这是「面板选择」的引擎侧原语（与 argo 的 ARGO_DISABLE_ENGINES 同构）：DSH
    插件面板把停用清单写进插件 config，spawn 时注入本环境变量，candidates/pick
    据此把源从路由里摘掉。语义是「不要自动选它」——具名直调（invest-cli wind /
    htbr）是用户点名，不受影响；datasources 会把停用源标出来。空值/未设置 =
    全员参战。每次读 env 不缓存：CLI 每次调用都是新进程，无热路径压力。
    """
    raw = os.environ.get("INVEST_CLI_DISABLE_SOURCES", "").strip()
    if not raw:
        return frozenset()
    return frozenset(
        part.strip().lower()
        for part in raw.replace(";", ",").replace("，", ",").split(",")
        if part.strip()
    )


# 代码域守卫：纯数字代码落在**确定段**却与所问的 kind 不符时，直接拒绝。
#
# 为什么放在 route 层而不是各 cmd_* 里：`stock` 有两条入口（`cmd_stock.
# fetch_stock_with_fallback` 与 `cmd_intent` 的 `deep stock`），分别加守卫必然
# 漏一条——实测 `invest-cli stock 110011` 已被拒，而
# `invest-cli intent deep stock 110011` 仍拿到那张冒牌基金快照且 rc=0。
# 这里与上面的「空标的」检查同层，都是「这个问题本身不成立」。
#
# 只拦**确定段**（`_common.kind_from_code` 的唯一真源）：`000858` 这类与基金
# 号段重叠的返回 None，仍然放行交给下游解析，避免误杀正常查询。
_DOMAIN_NAME = {"fund": "基金代码", "bond": "可转债代码", "stock": "股票代码"}
_DOMAIN_HINT = {
    "fund": "invest-cli fund {v}",
    "bond": "invest-cli intent deep bond {v}",
    "stock": "invest-cli stock {v}",
}


# 带市场前缀/后缀的写法 → **裸代码**。
#
# 为什么要收敛到裸代码：链上各源的入参口径不同 —— 同花顺/东财/ttskill/盈米要裸代码，
# 腾讯/westock 要 `sh600519`，yfinance 要 `600519.SS`。过去没人管这件事，于是同一个
# 标的换个写法就走另一条路：实测
#   stock sh600519   → 同花顺「未找到匹配标的」→ 东财同 → 一路落到腾讯，只给 29 项**纯行情**（无基本面）
#   stock hk00700    → 落到腾讯 25 项（东财的港股快照本有 21 项含年报数据）
#   fund  sh510300   → 整条链失败（同花顺、ttskill 都认不出）
#   us    usAAPL     → yfinance 认不出 → 落到腾讯
# 在 route（唯一的取数入口）把写法归一成裸代码，各适配器再各自加自己需要的前缀 ——
# 一处改动覆盖四个命令，而不是让每个源各自做一遍容错。
#
# **歧义仲裁**（同一个前缀在两个市场都合法，必须显式判）：
# 旧实现 `^(sh|sz|bj|hk|us)(?=[0-9A-Za-z])` 是 re.I + 任意字母，于是把**真实
# 美股代码的前两个字母吃掉了**——实测 SHEL→EL（壳牌）、USO→O（Realty Income）、
# SHW→W（Wayfair）、USB→B（巴里克矿业）、USMV→MV、USMOO→MOO。整条链不报错、
# rc=0，把用户问的标的答成**另一家公司**。
#
# 判据（可判定，不猜）：
#   · A 股/港股/北交所代码**全是数字** → `sh|sz|bj|hk` 后跟数字时只可能是
#     市场前缀；后跟字母时按**不动**处理（保留原样永远对，猜错一定错）。
#   · `us` 无法靠字面判定：美股 ticker 以字母开头，`usAAPL`（前缀写法）与
#     `USMOO`（真实 ETF）字面完全同形。判据是**剩余长度**：去掉 `us` 后还剩
#     ≥4 位字母才算前缀写法（`usAAPL`/`UsAAPL`/`USAAPL`），剩 ≤2 位则整串
#     就是真实代码（`USO`/`USB`/`USMOO`）。用长度而不是大小写，是因为大小写
#     判据会把合法的 `USAAPL` 误判成 ticker（实测回归）。
#     本判据与 sources/tencent.normalize_code 的同名规则**逐条对齐**——
#     两处曾各写一份并各自漂移过一次。一致性由
#     test_round6_regressions.test_canonical_and_tencent_normalize_agree 钉住，
#     改任一处必须同步另一处（输出方向不同：本函数产裸代码，tencent 产带前缀形式）。
_PREFIXED = re.compile(r"^(sh|sz|bj|hk)(?=\d)", re.I)
_PREFIXED_US = re.compile(r"^us(?=[0-9A-Za-z]{4})", re.I)
# 只认**交易所后缀**，不动美股 ticker 里的点（BRK.B 的 .B 不是交易所代码）
_SUFFIXED = re.compile(r"\.(SH|SZ|BJ|HK|US)$", re.I)


def canonical_arg(arg: str) -> str:
    """`sh600519` / `600519.SH` / `hk00700` / `usAAPL` → `600519` / `00700` / `AAPL`。

    真实美股代码原样返回：`SHEL`/`USO`/`SHW`/`USB` 不带数字尾巴，
    不能被当成 `sh`/`us` 前缀（见上方注释里被吃掉的反例）。`us` 前缀写法
    归一为**大写**裸代码（`USAAPL`→`AAPL`），与 tencent.normalize_code 对齐。
    """
    t = str(arg or "").strip()
    if not t:
        return t
    m = _SUFFIXED.search(t)
    if m:
        return t[: -len(m.group(0))]
    stripped = _PREFIXED.sub("", t)
    if stripped != t:
        return stripped
    m_us = _PREFIXED_US.match(t)
    if m_us:
        # 统一大写：下游（tencent/yfinance/bitget）都按大写 ticker 匹配，
        # `USAAPL` 不归一就会一路带着大写 US 去查，查不到（实测）。
        return t[2:].upper()
    return t


def code_domain_error(kind: str, arg: str) -> str:
    """kind 与**确定段**代码的类型不符时返回错误文案，否则返回空串。"""
    if kind not in ("stock", "fund"):
        return ""
    try:
        from _common import kind_from_code
    except Exception:
        return ""
    code_kind = kind_from_code(arg)
    if code_kind is None or code_kind == kind:
        return ""
    asked = _DOMAIN_NAME[kind]
    return (
        f"「{arg}」是{_DOMAIN_NAME.get(code_kind, code_kind)}，不是{asked.replace('代码', '')}。"
        f"请改用：{_DOMAIN_HINT.get(code_kind, '').format(v=arg)}"
    )

# 快照缓存 TTL：与 _common 的口径常量对齐。screen 的缓存 key 含条件文本，
# 相同条件 60s 内重复查询秒回、不同条件互不干扰——「条件查询不缓存」的旧
# 注释与代码不符（2026-10-11 实测命中缓存），此处对齐到代码实际行为。
_SNAPSHOT_TTL_KINDS = {"stock": "quote", "us": "quote", "fund": "fundamental", "screen": "quote"}

# 失败信封的落盘 TTL。成功结果有快照缓存而失败没有，是个不对称缺口：CLI 每次调用
# 都是独立进程，打错代码（`stock zzzz`）要**每次**付完整条候选链——实测串行 5 源
# 5.2s，重复查询一分不省。与 registry 负探测同一模式：短 TTL + env 可置 0。
# 窗口不取太长，因为这里的失败混着「确证不存在」与「上游抖动」两种语义：90s 内
# 重复查询给同一份错误可接受（错误信封自带逐源原因），换来的是 agent 探码/打错字
# 这类调用从秒级降到毫秒级。
_FETCH_FAIL_TTL = 90.0


def _fetch_fail_ttl() -> float:
    raw = os.environ.get("INVEST_CLI_FETCH_FAIL_TTL", "").strip()
    if not raw:
        return _FETCH_FAIL_TTL
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _FETCH_FAIL_TTL


def _snapshot_ttl(kind: str) -> Optional[float]:
    """该 kind 的快照缓存 TTL（秒）；不缓存的返回 None。"""
    slot = _SNAPSHOT_TTL_KINDS.get(kind)
    if slot is None:
        return None
    try:
        from _common import CACHE_TTL_FUNDAMENTAL, CACHE_TTL_QUOTE
    except Exception:
        return None
    return CACHE_TTL_QUOTE if slot == "quote" else CACHE_TTL_FUNDAMENTAL


def _adapter_module(sid: str, conf: dict[str, Any]):
    names = conf.get("adapters") or [sid]
    name = names[0]
    return importlib.import_module(f"sources.{name}")


def _deps_missing(mod) -> list[str]:
    """适配器声明的运行期依赖里，当前解释器缺哪些（import 名口径）。

    适配器把真依赖延迟到调用链深处 import（yfinance 包在 cmd_us.py:297 函数内、
    cryptography 在 ttskill.py 函数内），适配器模块本体可导入不代表依赖可用——
    candidates 若只按模块可导入性判链，缺件解释器仍会把 yfinance 排在 us 链头，
    与文档真值「缺件时降级到腾讯行情」分家（test_doc_source_truth 红测根因）。
    依赖在适配器模块层用 REQUIRED_IMPORTS 声明（写 import 名而非 pip 名），
    此处 find_spec 逐个核；未声明的适配器不判缺，行为不变。
    """
    missing: list[str] = []
    for name in getattr(mod, "REQUIRED_IMPORTS", ()) or ():
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            # 非法名（空串/悬空父包）按缺件处理：fail-closed，不进链
            missing.append(name)
    return missing


def candidates(kind: str, market: Optional[str] = None) -> list[str]:
    """按 priority 降序返回「有能力回答该问题」的源，**不做可用性探测**。

    与 pick() 的分工：探测是贵的（yfinance 要真实 HTTPS），而它大多数时候
    用不上——A 股链里 yfinance 只是末位兜底，却会在每个冷探测窗口被探一次。
    这里只做便宜的能力判定（coverage 含 kind + 适配器真有该方法 +
    声明依赖当前解释器可导入），可用性交给 fetch() 在**即将调用某个源之前**
    逐个判定。
    """
    if kind not in KIND_FNS:
        return []
    registry = load_registry()
    disabled = disabled_sources()
    overrides = MARKET_PRIORITY_OVERRIDE.get((kind, market or ""), {})
    ranked = sorted(
        registry.items(),
        key=lambda kv: overrides.get(kv[0], kv[1].get("priority", 0)),
        reverse=True,
    )
    excluded = MARKET_EXCLUDE.get((kind, market or ""), frozenset())
    out: list[str] = []
    for sid, conf in ranked:
        # route_kinds（若声明）才是「参与 route.fetch」的真值，coverage 只是展示标签：
        # wind/yingmi/argo/index_hub/etfirst 等只经具名子命令直调，从不上链；
        # 过去把两者混用一个字段，`datasources` 于是把「标签」当成了「链路能力」。
        kinds = conf.get("route_kinds", conf.get("coverage") or [])
        if kind not in kinds:
            continue
        if sid in excluded:
            continue
        if sid in disabled:
            continue
        try:
            mod = _adapter_module(sid, conf)
        except Exception:
            continue
        if _deps_missing(mod):
            continue
        if not callable(getattr(mod, kind, None)):
            continue
        out.append(sid)
    return out


def pick(
    kind: str,
    market: Optional[str] = None,
    states: Optional[dict[str, dict[str, Any]]] = None,
) -> list[str]:
    """返回该问题当前可用、且真有方法的数据源 id，priority 降序。

    供 `datasources` / `chains()` 这类需要「一次看清全链可用性」的场景；
    可选传入 `states`（如 `registry.detect_all()` 的结果）避免重复探测。
    取数主路径请用 fetch()，它在调用前才逐个探测（见 candidates 注释）。
    """
    registry = load_registry() if states is None else None
    out: list[str] = []
    for sid in candidates(kind, market=market):
        if states is not None:
            available = bool((states.get(sid) or {}).get("available"))
        else:
            available, _detail = detect((registry or {}).get(sid) or {})
        if available:
            out.append(sid)
    return out


def chains(states: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, list[str]]:
    """给 datasources / 诊断用的默认链（按当前机器可用性）。"""
    return {
        "stock_a": pick("stock", market="a", states=states),
        "stock_hk": pick("stock", market="hk", states=states),
        "fund": pick("fund", states=states),
        "us": pick("us", states=states),
        "screen": pick("screen", states=states),
    }


def _invoke(sid: str, kind: str, arg: str) -> dict[str, Any]:
    registry = load_registry()
    conf = registry.get(sid) or {}
    mod = _adapter_module(sid, conf)
    fn = getattr(mod, kind)
    return fn(arg)


def _invoke_with(registry: dict[str, Any], sid: str, kind: str, arg: str) -> dict[str, Any]:
    """与 _invoke 等价，但复用调用方已加载的 registry。

    为什么单独一个函数：_invoke 每次都要 load_registry()，而一次冷取数会对
    **每个候选源**各调一次。yaml 已按进程缓存（见 sources/__init__），但函数
    调用与 dict 查找仍在热路径上；这里直接把已加载的 dict 传下去，
    消掉「同一个 dict 反复取」这一层。
    """
    conf = registry.get(sid) or {}
    mod = _adapter_module(sid, conf)
    fn = getattr(mod, kind)
    return fn(arg)


# 原始 _invoke 的引用，用于识别「测试是否替换了它」（见 fetch 里的 use_loaded）。
_INVOKE_ORIGINAL = _invoke


def fetch(
    kind: str,
    arg: str,
    *,
    market: Optional[str] = None,
    order: Optional[list[str]] = None,
    invoke: Optional[Callable[[str, str, str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """真实取数的唯一入口：整单路由 + 运行时事实记录。

    记账只在**默认路径**（未注入 order/invoke）发生：那是用户真实发生的调用。
    测试注入链、缓存命中、输入层拒绝（空标的/代码域不符）都不写——前两者不是
    真实取数，后者没有触碰任何源，记进去只会让 failure 统计被打错字污染。
    """
    started = time.perf_counter()
    result = _fetch_impl(kind, arg, market=market, order=order, invoke=invoke)
    if invoke is None and order is None:
        _emit_usage(kind, arg, market, result, started)
    return result


def _result_row_count(result: dict[str, Any]) -> int:
    """成功信封的「交付条数」：列表取长度，dict 取 1（快照），其余 0。

    为什么不用更细的字段计数：各源 data 形状差异极大（快照 dict / 表格 list /
    嵌套 payload），逐源定义「什么算一条」会变成第二套口径。这里用**最小可用
    判据**：列表=元素数，dict=1（快照是单标的完整数据），其余=0。P3 的
    suspected_stale 只需要区分「0 条」与「非 0 条」，这个粒度足够。
    """
    data = result.get("data")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict) and data:
        return 1
    return 0


def _emit_usage(
    kind: str,
    arg: str,
    market: Optional[str],
    result: dict[str, Any],
    started: float,
) -> None:
    """一次真实取数 → 一条事实。任何异常都吞掉，绝不拖累取数。"""
    if result.get("cached"):
        return
    # 失败且没有 tried：输入层在发起任何源调用前就拒绝了（空标的、代码域不符），
    # 或候选链本身为空。它不反映数据源健康，记进去只会污染「连续失败」判据
    # （用户连打 5 次错代码就会把 doctor 打成 FAIL）。
    if not result.get("ok") and not result.get("tried"):
        return
    try:
        from _common import usage_emit

        record: dict[str, Any] = {
            "kind": kind,
            "market": market or "",
            "arg": str(arg or "")[:64],
            "ok": bool(result.get("ok")),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        if result.get("ok"):
            record["source"] = result.get("source")
            # 交付条数（P2，2026-11-09）：回答「这个源这 24h 交付了多少条数据」，
            # 用来区分「慢源拖尾」与「唯一出货」。argo 的 engine_results 同构。
            record["count"] = _result_row_count(result)
            # 空结果单独标记：ok=True 但 0 条是 suspected_stale 的判据基础
            # （P3 消费）。快照类源 data 是 dict，条数恒为 1 或 0，标记仍成立。
            if record["count"] == 0:
                record["empty"] = True
            if result.get("fallback_from"):
                record["fallback_from"] = result["fallback_from"]
                fb_err = str(result.get("fallback_error") or "")
                record["fallback_error"] = fb_err[:300]
                failed_sids = [
                    e.split(":", 1)[0].strip()
                    for e in fb_err.split("; ")
                    if ":" in e and e.split(":", 1)[0].strip()
                ]
                if failed_sids:
                    record["failed_sources"] = failed_sids
        disabled = disabled_sources()
        if disabled:
            record["disabled"] = sorted(disabled)
        else:
            record["tried"] = list(result.get("tried") or [])
            record["error"] = str(result.get("error") or "")[:300]
            # 逐源原因（"sid: 原因; sid: 原因"）拆开存：doctor 要按源统计连续失败，
            # 整串只够人读，统计还得再切一次。
            record["errors"] = [
                e.strip()[:200]
                for e in str(result.get("error") or "").split("; ")
                if e.strip()
            ][:10]
        usage_emit(record)
    except Exception:
        pass


def _fetch_impl(
    kind: str,
    arg: str,
    *,
    market: Optional[str] = None,
    order: Optional[list[str]] = None,
    invoke: Optional[Callable[[str, str, str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """按候选顺序整单取数。第一个 ok 即停，不混字段。

    order 可注入：默认走 candidates()（能力判定，不探测）；测试传显式链锁定回退逻辑。
    默认路径上每个源在**即将被调用前**才探测可用性：主源命中时，
    后面的兜底源（如 A 股链里的 yfinance）根本不会被探测，省掉一次无关的网络往返。
    成功信封走跨进程磁盘缓存（CLI 每进程都新起，进程内缓存无效）；
    仅生产默认路径（未注入 invoke/order）启用，测试注入路径保持直通语义。
    """
    if not str(arg or "").strip():
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"空标的：{kind} 需要代码或名称",
        }
    arg = canonical_arg(arg) if kind in KIND_FNS else arg
    domain_err = code_domain_error(kind, arg)
    if domain_err:
        return {"source": kind, "kind": kind, "ok": False, "data": None, "error": domain_err}
    caller = invoke or _invoke
    errors: list[str] = []
    last: dict[str, Any] | None = None
    default_path = invoke is None and order is None
    # ① 快照命中必须在**路由之前**判定。
    #
    # candidates() 看着便宜（只做能力判定、不探测），实际要读配置真源
    # （yaml.safe_load，实测 2.7ms/次）并 import 链上每个适配器模块——而
    # sources.bitget 一旦被 import 就带进 urllib.request → http.client → ssl，
    # 实测整条热路径的 import 自耗时约 50ms，其中约 20-25ms 出自这条链。
    # 缓存命中时这些全是白做的：一次 hit 重新解析配置、重新 import 一遍适配器，
    # 只为返回一个磁盘上已经躺着的 JSON。
    #
    # 为什么提前判定不改变命中语义：缓存键只由 kind/market/arg 决定，与候选链
    # 无关；ttl 只在默认路径（未注入 order/invoke）上非空，注入路径仍然直通。
    # 唯一的行为差异是「候选链为空 + 缓存新鲜」这组：旧代码先报「无可用数据源」，
    # 新代码先返回缓存。候选链为空意味着某个适配器连模块都 import 不进来，
    # 那时给一份新鲜快照显然比报「无源」更符合调用方意图。
    ttl = _snapshot_ttl(kind) if default_path else None
    cache_key = f"{kind}|{market or '-'}|{arg}"
    if ttl:
        try:
            from _common import cache_get

            hit = cache_get("snapshot", cache_key, ttl)
        except Exception:
            hit = None
        if isinstance(hit, dict) and hit.get("ok"):
            return {**hit, "cached": True}
    # 失败信封走独立命名空间（snapshot_fail）：成功/失败的 TTL 节奏不同，
    # 分开存就不用在条目里塞元数据，_common 一行不用改。仅默认路径启用。
    fail_ttl = _fetch_fail_ttl() if default_path else 0.0
    if fail_ttl:
        try:
            from _common import cache_get

            fail_hit = cache_get("snapshot_fail", cache_key, fail_ttl)
        except Exception:
            fail_hit = None
        if isinstance(fail_hit, dict) and not fail_hit.get("ok"):
            return {**fail_hit, "cached": True}
    if order is None:
        order = candidates(kind, market=market)
    if not order:
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"无可用数据源: kind={kind} market={market or '-'}",
        }
    registry = load_registry() if default_path else {}
    detected = 0
    # 复用上面已加载的 registry，不再每个源重取一次。但当调用方显式替换了
    # `_invoke`（测试注入假实现）时仍走它——那是被授权的接管点，不能绕开。
    use_loaded = default_path and invoke is None and _invoke is _INVOKE_ORIGINAL
    for sid in order:
        if default_path:
            available, detail = detect(registry.get(sid) or {})
            if not available:
                errors.append(f"{sid}: {detail}")
                continue
            detected += 1
        try:
            res = (_invoke_with(registry, sid, kind, arg) if use_loaded
                   else caller(sid, kind, arg))
        except Exception as e:
            errors.append(f"{sid}: {e}")
            continue
        last = res if isinstance(res, dict) else None
        if isinstance(res, dict) and res.get("ok"):
            if errors:
                res = {
                    **res,
                    "fallback_from": errors[0].split(":", 1)[0],
                    "fallback_error": "; ".join(errors),
                }
            if ttl:
                try:
                    from _common import cache_set

                    cache_set("snapshot", cache_key, res)
                except Exception:
                    pass
            return res
        if isinstance(res, dict) and res.get("input_error"):
            # 输入层失败（如「多个候选无法唯一消歧」）：换源解决不了，只会让下游源去猜。
            # 实测 `fund -1` 曾因此返回一只任选的基金且 rc=0、同一输入不同时刻结果不同。
            errors.append(f"{sid}: {res.get('error')}")
            break
        errors.append(f"{sid}: {(res or {}).get('error') if isinstance(res, dict) else '非信封'}")
    if default_path and not detected:
        # 整条链没有一个源通过探测：结论与前缀措辞与旧 pick() 一致，但把
        # **逐源原因**接在后面——`无可用数据源: kind=fund market=-` 是内部术语，
        # 用户看不出缺哪个 key（同一条链上的 stock 会把原因列全，实测对比过）。
        # 走到这里时每个候选都因不可用而进了 errors，故不必处理空 errors 分支。
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"无可用数据源: kind={kind} market={market or '-'}；{'; '.join(errors)}",
            "tried": order,
        }
    res_fail = {
        "source": kind,
        "kind": kind,
        "ok": False,
        "data": None,
        "error": "; ".join(errors) if errors else f"{kind} 全部失败",
        "tried": order,
        "last": last,
    }
    if fail_ttl:
        # 只落**整条链跑完**的失败。提前返回的不落：「无可用数据源」随探测恢复
        # 节奏走 registry 的负缓存，空标的/域错误是确定性输入问题，缓存无意义。
        try:
            from _common import cache_set

            cache_set("snapshot_fail", cache_key, res_fail)
        except Exception:
            pass
    return res_fail


def unwrap_snapshot(res: dict[str, Any]) -> dict[str, Any]:
    """信封 → CLI 快照。失败抛 RuntimeError。"""
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        raise RuntimeError(res.get("error") or "取数失败")
    snap = dict(res["data"])
    snap.setdefault("source", res.get("source"))
    if res.get("cached"):
        snap["cached"] = True  # 透传缓存命中标记，CLI 输出可见（接线可验证）
    if res.get("fallback_from"):
        snap["fallback_from"] = res["fallback_from"]
        snap["fallback_error"] = res.get("fallback_error")
    return snap
