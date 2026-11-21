#!/usr/bin/env python3
"""
invest-cli — 投资分析 CLI 工具（主入口）

用法:
    invest-cli stock <代码/名称>    A股/港股分析（A股同花顺优先，港股东财）
    invest-cli fund <代码/名称>     基金分析（同花顺优先，失败回退东财）
    invest-cli us <代码>            美股分析（yfinance，缺省回退腾讯行情/Bitget）
    invest-cli quote <代码...>      免鉴权实时行情（一次请求多标的、跨市场，130ms 量级）
    invest-cli kline <代码>         K线（原生 ~130ms；分钟级转 westock CLI）
    invest-cli sec <代码>           SEC EDGAR 美股数据：快照（--years 年度序列/--quarterly）
                                    / 全文检索 --search "关键词" / 内部人 --insiders
                                    / 事件 --events / 13F 持仓 --holdings
    invest-cli cn <子命令> <代码>   A股/港股市场结构：notice 公告（--search 走巨潮检索）
                                    / consensus 一致预期 / holders 股东 / disclosure 披露日历
                                    / report 研报
    invest-cli screen <条件>        选股（东财）
    invest-cli westock <args...>   透传腾讯微证券 CLI（筹码/龙虎榜/资金流/一致预期/产业链/板块…）
    invest-cli datasources          列出并探测数据源可用性
    invest-cli wind <server_type> <tool> --input '<json>'  透传万得 Wind
    invest-cli yingmi <tool> --input '<json>'              透传盈米且慢
    invest-cli ttskill <skill_id> --input '<json>'         透传天天基金官方业务包
    invest-cli htbr <api_id> --input '<json>'              透传华泰柏瑞ETF事实查询（--list 看别名）
invest-cli sfg <工具|别名> --input '<json>'           透传见基行事公募基金MCP（--list 看别名）
    invest-cli capabilities [yingmi|ttskill]               能力清单+收敛标注（发现层）
    invest-cli tenure <代码|名称> [--manager 姓名] [--excel out.xlsx]
                                                        任职期复盘（分年度业绩/回撤 + 任职以来 vs 基准）
    invest-cli tenure --manager 姓名 [--company 公司]     经理全在管产品（初始份额）复盘
    invest-cli report <基金代码> [--latest N|--year 年|--all] [--out 目录]
                                                        基金定期报告 PDF（季报/半年报/年报，东财源）

选项:
    --json      输出结构化 JSON（给 skill 层用）
    --envelope  统一信封 {ok,source,data,error,meta}（可写在任意位置；默认关闭，
                开启后 agent 只需按一种形状解析，见 SKILL.md「输出契约」）

示例:
    invest-cli stock 600519
    invest-cli stock 茅台 --json
    invest-cli fund 110011
    invest-cli tenure 001959 --manager 余懿 --excel /tmp/yu.xlsx
    invest-cli tenure --manager 余懿 --company 华商基金 --json
    invest-cli us AAPL
    invest-cli quote 600519,00700,AAPL
    invest-cli kline 600519 --period month --limit 12
    invest-cli westock chip 600519
    invest-cli sec AAPL --filings 5
    invest-cli screen "市盈率低于10的银行股"
    invest-cli datasources
    invest-cli wind stock_data get_stock_price_indicators --input '{"windcode":"600519.SH"}'
    invest-cli yingmi GetCurrentTime
    invest-cli ttskill MANAGER_INFO --input '{"manager_name":"谢治宇"}'
    invest-cli capabilities ttskill
"""

from __future__ import annotations

import sys
import os
import argparse
import warnings

# --envelope 的统一信封（opt-in；默认输出一个字节都不变）。
# 为什么需要：17 种 --json 顶层形状是 agent 解析的主要摩擦点——
# `stock/fund/us` 是裸载荷、`quote/cn/watchlist` 是 {ok,...} 信封、
# `datasources` 是源名字典。加一个开关让调用方**一次成型**，
# 而不是把所有子命令的默认契约推倒重来（那会动所有分析 skill 的取数）。
ENVELOPE_FLAG = "--envelope"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 第三方库在导入期发出的告警（典型：urllib3 2.x 在 LibreSSL 下报
# NotOpenSSLWarning）会直接写到 stderr，污染正常输出与错误信息——
# CLI 的 stderr 是给人和 agent 读的错误通道，不该被库噪音占据。
#
# category 必须写 **Warning**：该告警继承链为
#   NotOpenSSLWarning → SecurityWarning → HTTPWarning → Warning
# 与 UserWarning **无继承关系**，用 UserWarning 或 message 正则都拦不住
# （实测两者均无效，只有 Warning + module 生效）。
# 这里覆盖所有走本入口的命令；被单独执行的 cmd_*.py 在各自文件里同样装了
# 这条过滤器（entry point 不止一个，过滤器就得跟着入口走）。
warnings.filterwarnings("ignore", category=Warning, module=r"urllib3.*")


def _relax_output_encoding() -> None:
    """把 stdout/stderr 的编码错误处理放宽为 replace，避免整条命令崩掉。

    实测：`PYTHONIOENCODING=ascii invest-cli stock 600519` 直接抛
    `UnicodeEncodeError: 'ascii' codec can't encode characters ...` 并打出完整
    traceback（在一轮 78 次真实调用里，这是**唯一**一条 traceback）。

    CLI 的输出契约是「中文指标名 + 数值」：环境编码表达不了中文时，正确行为是
    **降级输出**（不可编码字符替成 `?`）并保持 rc=0，而不是抛异常、丢掉整份数据、
    把栈帧倒给用户。只在编码确实非 UTF-8 时才动，正常环境零影响。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc and enc.replace("-", "") != "utf8":
                stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def cmd_stock(args):
    from cmd_stock import fetch_stock_with_fallback, format_terminal
    try:
        data = fetch_stock_with_fallback(args.keyword)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_fund(args):
    import json
    from cmd_fund import fetch_fund_analytics, fetch_fund_with_fallback, format_terminal
    try:
        if getattr(args, "analytics", False):
            analysis = fetch_fund_analytics(args.keyword)
            if args.json:
                print(json.dumps(analysis, ensure_ascii=False, indent=2))
            else:
                from etf_analytics import format_terminal as fmt_analytics
                print(fmt_analytics(analysis))
            return
        data = fetch_fund_with_fallback(args.keyword)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_us(args):
    if getattr(args, "history", False):
        from cmd_us import print_eod_history

        sys.exit(print_eod_history(args.symbol, years=getattr(args, "years", 1.0),
                                   as_json=args.json, brief=getattr(args, "brief", False)))
    from cmd_us import fetch_us_with_fallback, format_terminal
    try:
        data = fetch_us_with_fallback(args.symbol)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_quote(args):
    from cmd_quote import run
    sys.exit(run(args.symbols, as_json=args.json))


def cmd_kline(args):
    from cmd_kline import run
    sys.exit(run(args.code, period=args.period, limit=args.limit, as_json=args.json))


def cmd_westock(args):
    from cmd_westock import run
    if getattr(args, "ws_help", False):
        sys.exit(run(["--help"], as_json=False))
    # `westock` 的参数用 argparse.REMAINDER 收集，位置参数之后的 `--json`
    # 会一并落进 args 并被原样转发给子 CLI，而子 CLI 不认这个旗标 →
    # 「Error: unknown flag: --json」，rc=1。只有把旗标写在子命令之前
    # （`westock --json chip 600519`）才生效，这个顺序要求没有任何文档说明。
    # 与 cmd_intent 同一套处理：在这里摘掉，行为与书写顺序无关。
    passthrough = list(args.args)
    as_json = args.json
    while "--json" in passthrough:
        passthrough.remove("--json")
        as_json = True
    sys.exit(run(passthrough, as_json=as_json))


def cmd_sec(args):
    from cmd_sec import run
    sys.exit(run(args.ticker, forms=args.forms, limit=args.filings, as_json=args.json,
                 years=args.years, quarterly=args.quarterly, search=args.search,
                 from_ym=args.from_ym, to_ym=args.to_ym, insiders=args.insiders,
                 events_flag=args.events, holdings=args.holdings, days=args.days,
                 rows_limit=args.limit, brief=getattr(args, "brief", False)))


def cmd_fmp(args):
    from cmd_fmp import run

    sys.exit(run(args))


def cmd_fund_class(args):
    from cmd_fund_class import run

    sys.exit(run(args))


def cmd_cn(args):
    from cmd_cn import run
    sys.exit(run(args.action, list(args.target or []), as_json=args.json,
                 search=args.search, notice_type=args.notice_type,
                 limit=args.limit, offset=args.offset))


def cmd_screen(args):
    from cmd_screen import run
    limit = 0 if getattr(args, "all_rows", False) else getattr(args, "limit", 20)
    sys.exit(run(args.condition, as_json=args.json, limit=limit))


def cmd_datasources(args):
    from cmd_datasources import run
    sys.exit(run(as_json=args.json))


def cmd_wind(args):
    from cmd_wind import run
    sys.exit(run(args.server_type, args.tool_name, args.input, as_json=args.json))


def cmd_yingmi(args):
    from cmd_yingmi import run
    sys.exit(run(args.tool_name, args.input, as_json=args.json))


def cmd_ttskill(args):
    from cmd_ttskill import run
    sys.exit(run(args.skill_id, args.input, as_json=args.json))


def cmd_htbr(args):
    from cmd_htbr import run
    sys.exit(run(args.api_id, args.input, as_json=args.json, list_only=args.list))


def cmd_sfg(args):
    from cmd_sfg import run
    sys.exit(run(args.tool, args.input, as_json=args.json, list_only=args.list,
                 poll_job=args.poll))


def cmd_capabilities(args):
    from cmd_capabilities import run
    sys.exit(run(args.source, as_json=args.json))


def cmd_intent(args):
    from cmd_intent import run
    value = list(args.value)
    as_json = args.json
    if "--json" in value:
        value.remove("--json")
        as_json = True
    sys.exit(run(args.scene, " ".join(value), as_json=as_json))


def cmd_info(args):
    from cmd_info import run
    sys.exit(run(args.query, engine=args.engine, as_json=args.json))


def _research_limit(scene: str, value: int | None) -> int:
    """research 的 --limit 默认值按场景分：筛选上限 vs 返回行数不是一回事。"""
    if value is not None:
        return value
    return 50 if scene == "etf-rank" else 200


def cmd_research(args):
    from cmd_research import run

    # 场景默认值不同：fund-rank 的池上限是筛选上限（200），etf-rank 是返回行数
    # （50，单行含成分股，200 行会越过插件 60k 输出预算）。
    limit = _research_limit(args.scene, args.limit)
    sys.exit(run(args.scene, args.theme, top=args.top, order=args.order, limit=limit,
                 dy_mode=args.dy, enrich=args.enrich, out=args.out, as_json=args.json,
                 period=args.period, components=args.components))


def cmd_watchlist(args):
    from cmd_watchlist import run
    sys.exit(run(args.action, code=args.code, name=getattr(args, "name", ""),
                 typ=getattr(args, "type", ""), with_quote=getattr(args, "with_quote", False),
                 as_json=args.json))


def cmd_tenure(args):
    from cmd_tenure import run
    sys.exit(run(keyword=args.keyword, manager=args.manager, company=args.company,
                 since=args.since, benchmark=args.benchmark, prefer=args.source,
                 years=args.years, excel=args.excel, csv_dir=args.csv_dir,
                 brief=args.brief, as_json=args.json))


def cmd_report(args):
    from cmd_report import run
    sys.exit(run(args.code, latest=args.latest, year=args.year,
                 all_reports=args.all_reports, out_dir=args.out,
                 limit=args.limit, as_json=args.json))


def cmd_doctor(args):
    from cmd_doctor import run
    sys.exit(run(as_json=args.json))


def _pop_flag(argv: list[str], flag: str) -> bool:
    """从 argv 摘掉一个全局旗标（任意位置），返回是否出现过。

    子命令用的 argparse 子解析器不认主解析器的旗标——`stock 600519 --envelope`
    会直接 rc=2。与 `westock` 处理 `--json` 同一套思路：在解析前摘掉，
    行为与书写顺序无关。`intent` 的 REMAINDER 也不会再把这个旗标透传给下游。
    """
    seen = False
    while flag in argv:
        argv.remove(flag)
        seen = True
    return seen


# 诊断命令自己读账本，若把自身调用也记进去，每跑一次 doctor 就多一条噪声，
# 还会让「命令级连续失败」的判据被自检动作自我干扰。
_DIAGNOSTIC_COMMANDS = frozenset({"doctor", "datasources", "capabilities"})
_DIRECT_SOURCES: dict[str, str] | None = None


def _direct_source_of(command: str) -> str:
    """直取命令 → 数据源 id；无则空串。注册表是唯一真源。"""
    global _DIRECT_SOURCES
    if _DIRECT_SOURCES is None:
        from command_registry import direct_sources

        _DIRECT_SOURCES = direct_sources()
    return _DIRECT_SOURCES.get(command, "")


def _log_command_usage(command: str, started: float, rc: int, err: str = "") -> None:
    """记一条命令级事实（rc 与耗时）；直取命令再加一条源级事实。

    直取命令（wind/yingmi/ttskill/htbr/westock/sec/fmp）绕开 route.fetch，
    不补这一条，账本只能回答「快照链用了谁」，回答不了「htbr 的 72 个接口
    到底被用过几次」。两条记录共用一本账，靠 scope 区分。
    """
    if command in _DIAGNOSTIC_COMMANDS:
        return
    import time

    try:
        from _common import usage_emit

        elapsed = int((time.perf_counter() - started) * 1000)
        src = _direct_source_of(command)
        if src:
            direct = {
                "scope": "direct",
                "src": src,
                "cmd": command,
                "ok": rc == 0,
                "elapsed_ms": elapsed,
            }
            if err.strip():
                direct["error"] = err.strip()[:300]
            usage_emit(direct)
        rec = {
            "scope": "cmd",
            "cmd": command,
            "ok": rc == 0,
            "rc": rc,
            "elapsed_ms": elapsed,
        }
        if err.strip():
            rec["error"] = err.strip()[:300]
        usage_emit(rec)
    except Exception:
        pass


def _envelope_payload(command: str, text: str, rc: int, elapsed_ms: float,
                      err_text: str = "") -> dict:
    """把子命令 stdout 收进统一信封 `{ok, source, data, error, meta}`。

    · 已是信封形状（含 `ok` 键）→ 取它的 data/error/source；
    · 裸载荷（stock/fund/us/fund-class）→ 整个载荷进 data；
    · 非 JSON（人读表格）→ `{"text": ...}` 进 data，ok 由退出码决定。
    """
    import json

    payload = None
    if text.strip():
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            payload = None
    if isinstance(payload, dict) and "ok" in payload:
        ok = bool(payload.get("ok"))
        source = payload.get("source")
        data = payload.get("data")
        error = payload.get("error")
    else:
        ok = rc == 0
        source = payload.get("source") if isinstance(payload, dict) else None
        # 非 JSON（终端表格）：原文放进 data.text，别还一个 null 让调用方以为没输出。
        data = {"text": text} if payload is None and text.strip() else payload
        error = None
    stderr_tail = "\n".join(err_text.strip().splitlines()[-3:]).strip()
    if not ok and not error:
        # 失败原因通常只走 stderr（「错误: ...」），信封里不能只剩一个退出码。
        error = stderr_tail or f"命令退出码 {rc}"
    meta = {
        "command": command,
        "chars": len(text),
        "elapsed_ms": round(elapsed_ms, 1),
    }
    if ok and stderr_tail:
        meta["stderr"] = stderr_tail  # 成功但有提示（如 SEC UA 建议），不丢
    return {
        "ok": ok,
        "source": source,
        "data": data,
        "error": error,
        "meta": meta,
    }


def build_parser() -> argparse.ArgumentParser:
    """构造子命令树。命令名集合与插件、dispatch 共享 command_registry。

    测试直接调用本函数做集合比对；这里再留一道运行时校验，避免注册表加了
    命令却忘了补 parser 时，插件先看到、CLI 到运行期才报 unknown command。
    """
    parser = argparse.ArgumentParser(
        description="invest-cli — 投资分析 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # stock
    p_stock = subparsers.add_parser("stock", help="A股/港股分析")
    p_stock.add_argument("keyword", help="股票代码或名称")
    p_stock.add_argument("--json", action="store_true")

    # fund
    p_fund = subparsers.add_parser("fund", help="基金分析")
    p_fund.add_argument("keyword", help="基金代码或名称")
    p_fund.add_argument("--json", action="store_true")
    p_fund.add_argument("--analytics", action="store_true",
                        help="ETF 深度分析（穿透/风险/回撤/排名）")

    # us
    p_us = subparsers.add_parser("us", help="美股分析")
    p_us.add_argument("symbol", help="美股代码")
    p_us.add_argument("--history", action="store_true",
                      help="EOD 历史专项（Tiingo）：复权日线 + 分红/拆股/回撤摘要")
    p_us.add_argument("--years", type=float, default=1.0, help="--history 的年数（默认 1）")
    p_us.add_argument("--brief", action="store_true",
                      help="--history --json 时省略逐日 bars，只留摘要（载荷 60KB→几 KB）")
    p_us.add_argument("--json", action="store_true")

    # quote（免鉴权批量实时行情：一次请求、跨市场、130ms 量级）
    p_quote = subparsers.add_parser("quote", help="免鉴权多标的实时行情（一次请求，跨市场）")
    p_quote.add_argument("symbols", help="一个或多个标的，逗号分隔：600519,00700,AAPL 或 贵州茅台")
    p_quote.add_argument("--json", action="store_true")

    # kline（K线：原生快路径 + CLI 兜底）
    p_kl = subparsers.add_parser("kline", help="K线（原生快路径，分钟级自动转 westock CLI）")
    p_kl.add_argument("code", help="标的代码或名称")
    p_kl.add_argument("--period", default="day",
                      help="day/week/month/year 或 m1/m5/m15/m30/m60/m120（默认 day）")
    p_kl.add_argument("--limit", type=int, default=60, help="根数（默认 60）")
    p_kl.add_argument("--json", action="store_true")

    # westock（腾讯微证券 CLI 长尾能力透传：筹码/龙虎榜/资金流/一致预期/板块…）
    p_ws = subparsers.add_parser("westock", add_help=False,
                                 help="透传腾讯微证券 CLI（筹码/龙虎榜/资金流/一致预期/ESG/产业链/板块估值…）")
    # add_help=False：不加的话 `invest-cli westock --help` 会被本层 argparse 截获，
    # 只打出 5 行自己的 usage，而用户要的是 westock 那 19 组 / 85 行命令树。
    # 让 `--help` 透传给真实 CLI（`invest-cli westock -h` 的语义因此与直接敲
    # `westock --help` 一致），本层的参数说明由 `--json` 与文档承担。
    p_ws.add_argument("args", nargs=argparse.REMAINDER,
                      help="westock 子命令与参数，如 chip sh600519 / lhb / screen strategy --list")
    # 自己接住 --help 并转发给真实 CLI：add_help=False 只是关掉本层帮助，
    # 不定义这个旗标的话 argparse 会报 "unrecognized arguments: --help"，
    # 用户就再也看不到 westock 那 19 组 / 85 行命令树了。
    p_ws.add_argument("-h", "--help", action="store_true", dest="ws_help",
                      help="透传 westock CLI 的帮助（真实命令树）")
    p_ws.add_argument("--json", action="store_true")

    # sec（SEC EDGAR 原文级数据，免费官方源；一次只做一件事）
    p_sec = subparsers.add_parser(
        "sec", help="SEC EDGAR 美股数据（快照/全文检索/内部人/事件/13F持仓）")
    p_sec.add_argument("ticker", help="美股代码（AAPL/BRK.B）；--holdings 时也可传机构名或 CIK")
    p_sec.add_argument("--forms", default="",
                       help="申报类型过滤（逗号分隔）；快照默认 10-K,10-Q,8-K，全文检索默认不过滤")
    p_sec.add_argument("--filings", type=int, default=5, help="快照：返回最近申报条数（默认 5）")
    p_sec.add_argument("--years", type=int, default=5, help="快照：年度序列年数（默认 5；0=不输出序列）")
    p_sec.add_argument("--quarterly", action="store_true", help="快照：附季度序列（Q4 为推导值，标 derived）")
    p_sec.add_argument("--search", default="", help="全文检索：在**该公司申报正文**里找原文段落")
    p_sec.add_argument("--from", dest="from_ym", default="", help="检索起始月 YYYY-MM")
    p_sec.add_argument("--to", dest="to_ym", default="", help="检索截止月 YYYY-MM")
    p_sec.add_argument("--insiders", action="store_true", help="内部人交易（Form 4 逐笔）")
    p_sec.add_argument("--events", action="store_true", help="公司事件（8-K 逐事项 + 13D/13G）")
    p_sec.add_argument("--holdings", action="store_true", help="13F 机构持仓（ticker 视为申报机构）")
    p_sec.add_argument("--days", type=int, default=-1,
                       help="--insiders/--events 回看天数（默认：内部人 180 天，事件不限）")
    p_sec.add_argument("--limit", type=int, default=0, help="新动作的条数上限（默认：检索 10/内部人 20/事件 20/持仓 40）")
    p_sec.add_argument("--brief", action="store_true",
                       help="快照 --json 时省略 5 年年度序列（series），只留最新指标与申报清单")
    p_sec.add_argument("--json", action="store_true")

    # fmp（Financial Modeling Prep 深取：三表 JSON/TTM 比率/结构化评级/年度预测；
    # 免费档 250 次/天，深取专项不进快照链，与 `sec` 的原文级数据分工）
    p_fmp = subparsers.add_parser(
        "fmp", help="FMP 美股深取（三表/TTM 比率/结构化评级/年度分析师预测）")
    p_fmp.add_argument("symbol", help="美股代码（AAPL/BRK.B）")
    p_fmp.add_argument("--estimates", action="store_true", help="年度分析师预测（EPS/营收 低/均/高）")
    p_fmp.add_argument("--statements", action="store_true", help="三表（income/balance/cash-flow）")
    p_fmp.add_argument("--dividends", action="store_true", help="分红历史")
    p_fmp.add_argument("--period", default="annual", help="三表口径 annual/quarterly（默认 annual）")
    p_fmp.add_argument("--limit", type=int, default=2, help="三表期数（默认 2）")
    p_fmp.add_argument("--json", action="store_true")

    # fund-class（基金三层分类器：L1 大类资产/L2 产品形态/L3 投资策略 + 辅助标签；
    # 评价友好分类，规则真源 fund-classification.yaml，数据底座 ttskill 深取）
    p_fc = subparsers.add_parser(
        "fund-class", help="基金三层分类（评价友好分类：它像什么、跟谁比、用哪把尺）")
    p_fc.add_argument("code", help="6 位基金代码，如 005827")
    p_fc.add_argument("--json", action="store_true")

    # cn（A股/港股市场结构：公告/一致预期/股东/披露日历/研报；westock 高频子命令的收敛入口）
    p_cn = subparsers.add_parser(
        "cn", help="A股/港股市场结构数据（notice/consensus/holders/disclosure/report）")
    p_cn.add_argument("action", choices=["notice", "consensus", "holders", "disclosure", "report"],
                      help="notice 公告 / consensus 一致预期 / holders 股东 / disclosure 披露日历 / report 研报")
    p_cn.add_argument("target", nargs="*", help="代码或名称，可多个（逗号或空格分隔）")
    p_cn.add_argument("--search", default="", help="notice：关键词检索（走 argo 的 cninfo 巨潮引擎）")
    p_cn.add_argument("--type", dest="notice_type", default="", help="notice：公告类型编号（0=全部）")
    p_cn.add_argument("--limit", type=int, default=0, help="条数上限（默认按子命令）")
    p_cn.add_argument("--offset", type=int, default=0, help="翻页偏移")
    p_cn.add_argument("--json", action="store_true")

    # screen
    p_screen = subparsers.add_parser("screen", help="选股")
    p_screen.add_argument("condition", help="选股条件")
    p_screen.add_argument("--limit", type=int, default=20,
                          help="最多返回多少行（默认 20；0=全部，等价 --all）")
    p_screen.add_argument("--all", dest="all_rows", action="store_true", help="返回全部行")
    p_screen.add_argument("--json", action="store_true")

    # datasources
    p_ds = subparsers.add_parser("datasources", help="列出并探测数据源可用性")
    p_ds.add_argument("--json", action="store_true")

    # wind（万得透传）
    p_wind = subparsers.add_parser("wind", help="透传万得 Wind 数据源")
    p_wind.add_argument("server_type", help="server_type，如 stock_data/fund_data/index_data")
    p_wind.add_argument("tool_name", help="工具名，如 get_stock_price_indicators")
    p_wind.add_argument("--input", default="{}", help="参数 JSON")
    p_wind.add_argument("--json", action="store_true")

    # yingmi（盈米透传）
    p_ym = subparsers.add_parser("yingmi", help="透传盈米且慢数据源")
    p_ym.add_argument("tool_name", help="工具名，如 GuessFundCode/GetFundDiagnosis")
    p_ym.add_argument("--input", default="{}", help="参数 JSON")
    p_ym.add_argument("--json", action="store_true")

    # ttskill（天天基金官方透传，37 包可达）
    p_tt = subparsers.add_parser("ttskill", help="透传天天基金官方业务包（如 MANAGER_INFO/NAV_INFO/STOCK_PRICE_QUERY）")
    p_tt.add_argument("skill_id", help="业务包 ID，如 TTFUND_MANAGER_INFO")
    p_tt.add_argument("--input", default="{}", help="参数 JSON")
    p_tt.add_argument("--json", action="store_true")

    # htbr（华泰柏瑞ETF事实查询透传，72 接口；不进快照链，直取）
    p_hb = subparsers.add_parser("htbr", help="透传华泰柏瑞ETF事实查询（--list 看语义别名）")
    p_hb.add_argument("api_id", nargs="?", default="", help="api_id 或语义别名（如 basic / viewpoint / industry-dist）")
    p_hb.add_argument("--input", default="{}", help="参数 JSON")
    p_hb.add_argument("--list", action="store_true", help="列出可用语义别名")
    p_hb.add_argument("--json", action="store_true")

    # sfg（见基行事 seefundgo 公募基金 MCP 透传，45 工具；不进快照链，直取）
    p_sfg = subparsers.add_parser("sfg", help="透传见基行事(seefundgo)公募基金MCP（--list 看语义别名）")
    p_sfg.add_argument("tool", nargs="?", default="", help="工具名或别名（如 profile / holdings / manager / portfolio-check）")
    p_sfg.add_argument("--input", default="{}", help="参数 JSON")
    p_sfg.add_argument("--list", action="store_true", help="列出可用语义别名")
    p_sfg.add_argument("--poll", default="", help="轮询组合诊断任务：--poll <job_id>")
    p_sfg.add_argument("--json", action="store_true")

    # capabilities（能力发现层）
    p_cap = subparsers.add_parser("capabilities", help="列出外部数据源能力清单与收敛状态（yingmi/ttskill/空=总览）")
    p_cap.add_argument("source", nargs="?", default="", help="yingmi / ttskill / 空=总览")
    p_cap.add_argument("--json", action="store_true")

    # intent（意图层，收敛接口面）
    p_int = subparsers.add_parser("intent", help="按意图取数（deep/screen/portfolio/plan/macro/present）")
    p_int.add_argument("scene", help="语义场景：deep/screen/portfolio/plan/macro/present")
    p_int.add_argument("value", nargs=argparse.REMAINDER, help="场景参数（deep 为 <type> <标的>）")
    p_int.add_argument("--json", action="store_true")

    # research（长程研究管线：编排既取数入口，不自建数据路径）
    p_res = subparsers.add_parser(
        "research", help="长程研究管线（fund-rank 主题基金 / etf-rank 指数基金横评）")
    p_res.add_argument("scene", help="研究场景：fund-rank（主题基金）/ etf-rank（指数基金横评）")
    p_res.add_argument("theme", help="fund-rank 填主题（如 红利）；etf-rank 填指数代码或名称（如 000300 / 沪深300）")
    p_res.add_argument("--top", type=int, default=8, help="展示/重仓/富化的 Top-N（默认 8）")
    p_res.add_argument("--order", default="r3y", choices=["r3y", "r1y", "ytd"],
                       help="fund-rank 排名键：r3y=近3年（默认）/ r1y=近1年 / ytd=今年来")
    p_res.add_argument("--limit", type=int, default=None,
                       help="池/返回上限（fund-rank 默认 200；etf-rank 默认 50，插件输出预算内）")
    p_res.add_argument("--dy", default="auto", choices=["auto", "on", "off"],
                       help="fund-rank 股息率交叉：auto=红利/股息主题自动开启（默认）")
    p_res.add_argument("--enrich", action="store_true", help="fund-rank 给 Top-N 附 argo 资讯（较慢）")
    p_res.add_argument("--period", default="1y", help="etf-rank 跟踪指标周期：1m/3m/6m/1y/3y/5y（默认 1y）")
    p_res.add_argument("--components", type=int, default=10,
                       help="etf-rank 返回成分股条数（1-50，默认 10）")
    p_res.add_argument("--out", default="", help="产物目录（落 report.md + result.json；缺省只输出不写盘）")
    p_res.add_argument("--json", action="store_true")

    # info（财经检索，走 argo）
    p_info = subparsers.add_parser("info", help="财经检索/资讯/舆情（走 argo，省配额）")
    p_info.add_argument("query", help="检索词")
    p_info.add_argument("--engine", default="eastmoney", help="argo 引擎名（如 eastmoney/zhihu/cninfo/anysearch；清单见 argo search.py --list-engines）")
    p_info.add_argument("--json", action="store_true")

    # watchlist（本地自选股）
    p_wl = subparsers.add_parser("watchlist", help="本地自选股（add/remove/list）")    # action 默认 list：真实调用里 `watchlist`（不带 action）比 `watchlist list` 更多，
    # 而旧定义要求它必填 —— 最常见的写法直接吃 argparse 的 rc=2 + usage。
    # 「看自选股」是这条命令的自然默认意图，与 `docker ps`、`git branch` 同类。
    p_wl.add_argument("action", nargs="?", default="list", help="add/remove/list（默认 list）")
    p_wl.add_argument("code", nargs="?", default="", help="标的代码（add/remove 用）")
    p_wl.add_argument("--name", default="", help="自选名称")
    p_wl.add_argument("--type", default="", help="fund/stock")
    p_wl.add_argument("--with-quote", action="store_true", help="列表时附行情")
    p_wl.add_argument("--json", action="store_true")

    # tenure（任职期复盘：分年度业绩/回撤 + 任职以来逐日收益 vs 业绩基准指数）
    p_tn = subparsers.add_parser("tenure", help="基金经理任职期复盘（分年度业绩/回撤 + 任职以来 vs 基准）")
    p_tn.add_argument("keyword", nargs="?", default="", help="基金代码或名称；配合 --manager 时留空=全在管产品")
    p_tn.add_argument("--manager", default="", help="基金经理姓名（取其任职日起算，并可扫全部在管产品）")
    p_tn.add_argument("--company", default="", help="基金公司（配合 --manager 收窄在管清单）")
    p_tn.add_argument("--since", default="", help="手动指定任职日 YYYY-MM-DD（默认按 --manager 任职记录/成立日）")
    p_tn.add_argument("--benchmark", default="auto", help="基准指数代码，默认 auto = 基金代码+BI.WI")
    p_tn.add_argument("--source", default="auto", choices=["auto", "wind", "ttskill"],
                      help="净值源：auto=Wind 精确（默认），ttskill=快路径（精度见提示）")
    p_tn.add_argument("--years", type=int, default=5, help="年度表跨度（默认近 5 年含当年）")
    p_tn.add_argument("--excel", default="", help="导出工作簿路径（概览/明细/数据来源；无 openpyxl 时自动落 CSV）")
    p_tn.add_argument("--csv", dest="csv_dir", default="", help="导出 CSV 目录（每张表一个文件，免 openpyxl）")
    # 注意：argparse 的 help 里出现裸 % 会抛 "badly formed help string"（test_cli_guards 会抓到），
    # 所以这里不写百分号。
    p_tn.add_argument("--brief", action="store_true", help="--json 时省略逐日序列（逐日明细占体积大头，结论场景建议开启）")
    p_tn.add_argument("--json", action="store_true")

    # report（基金定期报告 PDF：东财公告清单 + pdf.dfcfw.com 直链；默认仅列出）
    p_rep = subparsers.add_parser(
        "report", help="基金定期报告 PDF（季报/半年报/年报；--latest N 下载最新 N 期）")
    p_rep.add_argument("code", help="6 位基金代码，如 005827")
    p_rep.add_argument("--latest", type=int, default=0, help="下载最新 N 期（默认 0=仅列出）")
    p_rep.add_argument("--year", type=int, default=0, help="下载指定年份发布的报告")
    p_rep.add_argument("--all", dest="all_reports", action="store_true", help="下载全部历史")
    p_rep.add_argument("--out", default="", help="输出目录（默认 state 目录 reports/<代码>/）")
    p_rep.add_argument("--limit", type=int, default=10, help="仅列出时的条数（默认 10）")
    p_rep.add_argument("--json", action="store_true")

    p_doc = subparsers.add_parser(
        "doctor", help="运行面健康自检（数据源/缓存/解释器/软链/DSH 插件副本）")
    p_doc.add_argument("--json", action="store_true")

    from command_registry import command_ids

    expected = set(command_ids())
    actual = set(subparsers.choices)
    if expected != actual:
        raise SystemExit(
            f"命令注册表与 parser 不一致：注册表缺 {sorted(actual - expected)}，"
            f"parser 缺 {sorted(expected - actual)}（改 command_registry.py 后同步 build_parser）"
        )
    return parser


def main():
    _relax_output_encoding()
    # 运行时降级的唯一告警点：判据与 doctor/mx-data 共用 runtime_guard。
    # 只有「当前不在 venv 里」才需要查——由 venv 自身启动就已证明解释器能跑，
    # 这条自检连一次模块导入都不该占。断链时 wrapper 回退系统解释器才会走到
    # 这里，往 stderr 打一行，免得能力静默缺字段又要靠几天后的人工体检发现。
    if sys.prefix == sys.base_prefix:
        from runtime_guard import warn_if_degraded

        warn_if_degraded(os.path.dirname(SCRIPT_DIR))
    # 任意位置都认：`--envelope stock 600519` 与 `stock 600519 --envelope` 等价。
    envelope = _pop_flag(sys.argv, ENVELOPE_FLAG)
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # dispatch 从注册表派生：加命令只改 command_registry.py，不再维护第二份名单。
    # 注册表声明了命令但没有实现时给可读报错，而不是让用户看到裸 KeyError。
    from command_registry import command_ids

    dispatch: dict = {}
    missing_impl: list[str] = []
    for name in command_ids():
        impl = globals().get(f"cmd_{name.replace('-', '_')}")
        if impl is None:
            missing_impl.append(f"{name}（缺 cmd_{name.replace('-', '_')}）")
        else:
            dispatch[name] = impl
    if missing_impl:
        raise SystemExit(
            "command_registry 声明了命令但没有实现："
            + "、".join(missing_impl)
            + "。补实现，或从注册表摘除该命令。"
        )

    if not envelope:
        import time

        started = time.perf_counter()
        try:
            dispatch[args.command](args)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            _log_command_usage(args.command, started, rc)
            raise
        except BaseException:
            _log_command_usage(args.command, started, 1)
            raise
        _log_command_usage(args.command, started, 0)
        return

    # 信封模式：把子命令的 stdout 收进缓冲区再统一打包。子命令大量使用
    # sys.exit(rc)，所以必须接 SystemExit 才能既拿到输出又保住退出码。
    import contextlib
    import io
    import json
    import time

    started = time.perf_counter()
    buf = io.StringIO()
    err = io.StringIO()
    rc = 0
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            dispatch[args.command](args)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out = _envelope_payload(args.command, buf.getvalue(), rc,
                            (time.perf_counter() - started) * 1000, err.getvalue())
    _log_command_usage(args.command, started, rc, err.getvalue())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(rc)


if __name__ == "__main__":
    main()
