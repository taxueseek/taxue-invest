"""Shared utilities for invest-cli (and investment-agent consumers).

Design goals:
- No hardcoded personal machine paths (env + sibling + common skills roots)
- Stable JSON contract: every subcommand exposes a flat ``data`` dict
- Scripts runnable from any cwd
- This module is data-adapter glue only; analysis frameworks live in invest-* skills
"""
from __future__ import annotations

import json
import os
import re
import sys
import hashlib
import time
from pathlib import Path
from typing import Any, Optional


def secret_from_file(name: str) -> str:
    """环境变量缺失时的回退：从 ~/.env.secrets 读

    为什么需要这个回退：密钥不再全局 export 到进程环境——AI agent 会把 env
    快照写进会话日志，实测密钥因此扩散到 120 处（.pi 会话日志 65、shell 快照 38…）。
    改成「工具自己需要时才读文件」，扩散面就结构性消失了。

    与 ~/.agents/skills/zhihu-archive/scripts/cli.py 的 _load_env_from_shell
    是同一约定，不另立格式。只读不回显。
    """
    env_val = os.environ.get(name, "").strip()
    if env_val:
        return env_val
    for p in (Path.home() / ".env.secrets", Path.home() / ".zsh_secrets"):
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.replace("export", "").strip() == name:
                    v = v.strip().strip('"').strip("'")
                    if v:
                        return v
        except OSError:
            pass
    return ""


def ensure_script_dir_on_path() -> Path:
    """Make sibling modules importable regardless of process cwd."""
    script_dir = Path(__file__).resolve().parent
    s = str(script_dir)
    if s not in sys.path:
        sys.path.insert(0, s)
    return script_dir


def skill_root() -> Path:
    """invest-cli skill root: .../invest-cli (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def find_invest_cli() -> Path:
    """Locate invest_cli.py without hardcoding a home path.

    Priority:
      1. INVEST_CLI / INVEST_CLI_ROOT env
      2. Sibling install: investment-agent/../invest-cli/scripts/...
      3. Common skill install roots under $HOME
    """
    env_file = os.environ.get("INVEST_CLI")
    if env_file:
        p = Path(env_file).expanduser()
        if p.is_file():
            return p

    env_root = os.environ.get("INVEST_CLI_ROOT")
    if env_root:
        p = Path(env_root).expanduser() / "scripts" / "invest_cli.py"
        if p.is_file():
            return p

    # Sibling layout: <skills>/investment-agent → <skills>/invest-cli
    here = Path(__file__).resolve()
    # If called from invest-cli/scripts/_common.py
    candidate = skill_root() / "scripts" / "invest_cli.py"
    if candidate.is_file():
        return candidate

    # If imported after path injection from investment-agent, walk up
    for parent in here.parents:
        c = parent / "invest-cli" / "scripts" / "invest_cli.py"
        if c.is_file():
            return c

    home = Path.home()
    for base in (
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".grok" / "skills",
        home / ".codex" / "skills",
    ):
        c = base / "invest-cli" / "scripts" / "invest_cli.py"
        if c.is_file():
            return c

    raise FileNotFoundError(
        "invest_cli.py not found. Set INVEST_CLI or INVEST_CLI_ROOT, "
        "or install invest-cli under a standard skills directory."
    )


# ── L2 查询缓存：已删除（实测零收益的死代码）───────────────────────────────
# 2026-10-15 在这里加了进程内 l2_cache_get/l2_cache_set（10s TTL），理由是「一次
# 研究任务里同一标的的 quote 会重复出现」。实测不成立：CLI 每进程只跑一条命令，
# 唯一调用方 cmd_quote.run 在进程内只被调用一次，命中率为 0。相比跨进程缓存
# （下面这组 cache_*）它一分不省，只多一个内存字典与一套淘汰逻辑，已删除。


def json_out(data: Any, *, indent: bool = True) -> str:
    opts: dict[str, Any] = {"ensure_ascii": False}
    if indent:
        opts["indent"] = 2
    return json.dumps(data, **opts)


def strip_paren_suffix(name: str) -> str:
    """Strip trailing date/unit suffixes:
    '最新价(元)(2026.05.22)' → '最新价'；妙想的 '最新价(元)-2026.10.09'
    （单位在括号、日期挂在破折号后）同样归一到 '最新价'。"""
    import re

    name = re.sub(r"\(.*?\)", "", name)
    return re.sub(r"[-—]\s*\d{4}\.\d{1,2}\.\d{1,2}$", "", name).strip()


# ═══ 代码域分类（单一真源） ═══
#
# 为什么放在这里：这个判据有两个消费者，且**必须是同一个判据**——
#   · cmd_intent 用它把纯代码分派到不同意图（别为茅台去打盈米 CLI）；
#   · cmd_stock / cmd_fund 用它拦「代码域与子命令不匹配」（`stock 110011`
#     曾把易方达基金当成股票，返回一张全 `-` 的冒牌行情快照且 rc=0）。
# 两份实现一定会漂移，漂移的后果是「同一串代码在两个入口得到相反结论」。

# 6 位代码里能靠前缀 MECE 切开的部分。
_SH_A = re.compile(r"^(60[0135]|688|689)\d{3}$")
_CHINEXT = re.compile(r"^30[01]\d{3}$")
_FUND_6 = re.compile(r"^[15]\d{5}$")
# 可转债确定性段（盈米 GuessFundCode 实测 2026-09-03：这些段查询全部 400 查无基金）：
# 113（沪市转债 2012+）、123/127/128（深市转债）。
# 110/118 段与场外基金号段冲突（110011=易方达优质精选、118001=易方达亚洲精选，
# 盈米实测命中），保留给消歧，不在确定性段。
_BOND_6 = re.compile(r"^(113|123|127|128)\d{3}$")


def kind_from_code(t: str) -> Optional[str]:
    """纯代码的确定性分类。None = 与基金代码区间重叠，才允许外部消歧。

    返回 "stock" / "fund" / "bond" 之一，或 None（无法确定，交给上层解析）。
    """
    import re as _re

    t = (t or "").strip()
    if _re.fullmatch(r"\d{5}", t):
        return "stock"  # 港股 5 位
    if not _re.fullmatch(r"\d{6}", t):
        return None  # 非纯 6 位（名称/美股代码）不做确定性分类
    if _SH_A.match(t) or _CHINEXT.match(t):
        return "stock"
    if _BOND_6.match(t):
        return "bond"
    if _FUND_6.match(t):
        return "fund"
    return None


def looks_like_hk(keyword: str) -> bool:
    """入参是否像港股代码（5 位数字，或带 .HK 后缀）。

    为什么放在这里而不是 sources/hithink.py：判据本身只有两条正则，但它有
    **两个消费者**（cmd_stock._looks_like_hk 与 cmd_intent），而
    `sources.hithink` 在 import 期就会拉进 urllib.request → http.client →
    ssl 与 concurrent.futures。实测每条 `invest-cli stock` 命令（**包括
    纯缓存命中**）都要为这一个 2 行判断付 ~17ms 的 import，占 50ms 命中
    路径的三分之一。判据下沉到本模块后，命中路径不再 import 任何适配器。
    这与 kind_from_code 同处一室：都是「代码域判据」，都该只有一份。
    """
    t = (keyword or "").strip()
    if t.isdigit() and len(t) == 5:
        return True
    return t.upper().endswith(".HK")


_US_TICKER_RE = re.compile(r"^[A-Za-z]{1,5}(?:[.\-][A-Za-z]{1,4})?$")


def looks_like_us_ticker(value: str) -> bool:
    """入参是否像美股 ticker（1–5 位纯字母，或带 .B / -B 类别后缀如 BRK.B）。

    与 mx-data/query_router 同一口径；中文字符在 Python 里 isalpha() 为 True，
    因此必须要求 ASCII，避免把「茅台」「腾讯」判成美股代码。
    """
    v = (value or "").strip()
    return bool(v) and v.isascii() and bool(_US_TICKER_RE.match(v))


def pick_screen_columns(all_keys: list[str], limit: int = 6) -> list[str]:
    """Pick display columns without hardcoding dated header strings."""
    # 股息率排第 5：股息率筛选（妙想实测榜单整列都是它）连本列都不显示就
    # 失去了意义；不含该列的筛选结果不受影响——词表只决定挑列优先级。
    priority_stems = ("代码", "名称", "最新价", "涨跌幅", "股息率", "市盈率", "市净率", "总市值")
    picked: list[str] = []
    for stem in priority_stems:
        for k in all_keys:
            if k in picked:
                continue
            if stem in k or strip_paren_suffix(k).startswith(stem):
                picked.append(k)
                break
        if len(picked) >= limit:
            return picked[:limit]
    if not picked:
        return all_keys[:limit]
    return picked[:limit]


# ═══ 磁盘缓存（单真源） ═══
#
# 历史教训：本模块曾有一整套 _CACHE_DIR/_CACHE_TTL/_get_cache_key/get_cached/
# set_cached/parallel_execute/query_eastmoney_parallel/eastmoney_query_with_cache，
# 但**全仓零调用者**——宣称有缓存，实际每次全量重取；~/.cache/invest-cli 下
# 十几个 json 是早已过期的残留，从未被读写。同一时间 sources/sec_edgar.py 里
# 另有一份**真正在用**的 _cached_json（TTL + 原子替换 + 写失败不阻断）。
# 两份实现同一件事、只有一份生效，是典型的重复实体。
#
# 现按奥卡姆剃刀收敛为一份：下面这组函数是唯一实现，sec_edgar 也复用它。
# 设计要点（全部来自 sec_edgar 已验证的实践）：
#   - TTL 以秒计，过期即重新取数；
#   - **原子替换**（写 .tmp 再 replace），避免半截文件被后续进程读到；
#   - 缓存任何一步失败都**不阻断主流程**，只是下次还要重取。

CACHE_TTL_QUOTE = 60.0        # 行情快照：1 分钟（同一轮分析内复用足够）
CACHE_TTL_FUNDAMENTAL = 3600.0  # 财务/基本面：1 小时（变动远慢于行情）
CACHE_TTL_MACRO = 1800.0      # 宏观时序：30 分钟（FRED 序列为周度/日度，远慢于此）
# 市场结构类（公告 / 研报 / 股东 / 披露日历 / 一致预期）：变化以小时/天计，
# 远慢于行情，但比财务快——取 5 分钟。这条路径此前**完全没有缓存**，而
# `westock <cmd> <codes>` 实测 375ms/次（上游往返），同一会话里重复问同一只股
# 每次都要重付一遍。
CACHE_TTL_MARKET = 300.0
# westock 长尾透传：里面含盘中量价类命令（flow / chip / quote），所以只给一个
# 「同轮去重」级窗口——30s 足以吃掉同一会话里的重复调用，又不至于让盘中数据
# 明显陈旧（专用行情入口 `quote` 自带 10s 口径，要更实时走那条）。
CACHE_TTL_WESTOCK = 30.0
# 缓存文件的最长保留时间：TTL 只决定「读时是否算命中」，不负责删文件。
# 没有这一步，`sec`（单公司 companyfacts 约 3.7MB）会按查询过的公司数无界增长。
CACHE_MAX_AGE = 7 * 24 * 3600.0  # 7 天
# 进程内每个命名空间只清理一次：CLI 每进程只跑一条命令，避免重复 listdir。
_CACHE_PRUNED: set[str] = set()


def cache_root() -> Path:
    """invest-cli 缓存根目录（尊重 XDG/平台惯例，不硬编码个人路径）。

    纯路径计算，不创建目录：本函数也被所有**读**路径调用（cache_get、
    registry 探测负缓存查表），读一个尚不存在的缓存不该产生写副作用。
    目录由写路径负责创建（cache_path(..., create=True) / sec_edgar.cache_dir）。
    """
    env = os.environ.get("INVEST_CLI_CACHE_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "invest-cli"
    return Path.home() / ".cache" / "invest-cli"


def state_root() -> Path:
    """用户态**数据**根目录（自选股等本地状态，与缓存严格分开）。

    为什么不放 cache_root()：缓存是「删了会自动重建」的东西，系统清理
    （macOS 会清 ~/Library/Caches）或用户手删都不该丢用户数据。自选股是
    用户资产，必须落在数据目录。
    """
    env = os.environ.get("INVEST_CLI_STATE_DIR", "").strip()
    base = Path(env).expanduser() if env else Path.home() / ".config" / "invest-cli"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_path(namespace: str, key: str, *, create: bool = True) -> Path:
    """按命名空间 + 键定位缓存文件（键做散列，避免非法文件名字符）。

    create=False 供**读**路径使用：一次缓存未命中不该顺手建出目录树。
    写路径（cache_set、registry 探测负缓存落盘）保持默认 create=True。
    """
    digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:32]
    ns_dir = cache_root() / namespace
    if create:
        ns_dir.mkdir(parents=True, exist_ok=True)
    return ns_dir / f"{digest}.json"


def cache_get(namespace: str, key: str, ttl: float) -> Optional[Any]:
    """读缓存；未命中/过期/损坏一律返回 None（调用方按未命中处理）。"""
    path = cache_path(namespace, key, create=False)
    try:
        if not path.is_file():
            return None
        if (time.time() - path.stat().st_mtime) >= ttl:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _prune_namespace(ns_dir: Path) -> None:
    """删掉过期缓存与残留 .tmp，把磁盘占用收敛到「最近用过的键」。

    TTL 只在读的时候生效（过期按未命中处理），文件本身不会消失；
    调用方换一个键、或某公司只查过一次，旧文件就永久留在磁盘上。
    `sec` 的 companyfacts 单文件约 3.7MB，无界增长只是时间问题。

    进程内每命名空间只做一次（CLI 每进程一条命令），best-effort 不阻断主流程。
    """
    marker = str(ns_dir)
    if marker in _CACHE_PRUNED:
        return
    _CACHE_PRUNED.add(marker)
    now = time.time()
    try:
        for p in ns_dir.iterdir():
            try:
                age = now - p.stat().st_mtime
                if p.name.endswith(".tmp"):
                    if age > 3600:  # 崩溃残留的临时文件，1 小时后清
                        p.unlink()
                elif age > CACHE_MAX_AGE:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def cache_set(namespace: str, key: str, value: Any) -> None:
    """写缓存：原子替换；任何失败都静默跳过，绝不影响主流程。

    临时文件名带 pid：CLI 每次调用都是独立进程，两个进程写同一个键时
    若共用同一个 .tmp，后写者会把先写者的临时文件截断，先写者的 replace
    则把「半截文件」搬到正式位置（或后写者 replace 时 ENOENT 而丢缓存）。
    按进程分名后，每个写者的替换都是自洽的整文件。
    """
    path = cache_path(namespace, key)
    try:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except (OSError, TypeError, ValueError):
        return
    _prune_namespace(path.parent)


# ═══ 运行时事实层（usage log，单真源）═══
#
# 为什么需要：这个项目跨 9 轮治理反复出问题的两类根因——「判据/路由漂移」
# 与「门禁/守卫假通过」——有一个共同的盲区：651 条测试全是**静态猜**
# （AST、正则、体积、F401），没有任何一条记录「运行时到底发生了什么」。
# 于是某源配额打满连续失败 8 次、降级链被过度触发、慢源长期拖累，都只能
# 靠用户肉眼或事后写复盘报告发现。Argo 的 usage_log 正是补这一层。
#
# 纪律（开发做减法）：
#   - 只有「追加一条」与「读最近 N 条」两个操作，不做平台；
#   - 落盘复用 state_root()（用户态数据，与可删的 cache_root 严格分开），
#     测试已被 conftest 的 INVEST_CLI_STATE_DIR 自动隔离，不新增夹具；
#   - 与 cache_set 同一套原子写 + pid 临时名 + 失败静默，不引入第二套实现；
#   - 总开关 INVEST_CLI_USAGE_LOG=0 完全关闭（测试与隐私敏感场景）。
#
# 写入点只有一个：sources/route.py 的 fetch()（真实取数唯一入口）。
# 消费者是 doctor / stats / 插件诊断视图，都只读这份账本，不另建平行日志。

USAGE_LOG_MAX_BYTES = 1024 * 1024   # 单流 1 MiB
USAGE_LOG_KEEP_LINES = 2000         # 超限回缩保留最近 2000 行
USAGE_LOG_STREAM = "calls"          # 唯一流：一次取数一条


def usage_log_dir() -> Path:
    """账本目录。env 覆盖优先（与 cache_root/state_root 同一约定）。"""
    env = os.environ.get("INVEST_CLI_USAGE_LOG_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return state_root() / "usage_log"


def _usage_enabled() -> bool:
    raw = os.environ.get("INVEST_CLI_USAGE_LOG", "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def usage_emit(record: dict[str, Any]) -> bool:
    """追加一条运行时事实到 usage_log/calls.jsonl；失败静默，绝不拖累取数。

    记录内自动补 ts / version。不做字段校验：写入方（route.fetch）是唯一
    生产者，形状由它保证；多一层校验只会让「事实」变成「被猜过的东西」。
    """
    if not _usage_enabled():
        return False
    try:
        from datetime import datetime

        d = usage_log_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{USAGE_LOG_STREAM}.jsonl"
        line = json.dumps(
            {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
             "version": 1, **record},
            ensure_ascii=False,
        )
        # 回缩与追加在同一进程内串行完成；CLI 每进程一条命令，跨进程并发
        # 写同一个流文件时，回缩走带 pid 的原子替换不会截断别人的追加。
        try:
            if path.is_file() and path.stat().st_size > USAGE_LOG_MAX_BYTES:
                keep = path.read_text(encoding="utf-8").splitlines()[-USAGE_LOG_KEEP_LINES:]
                tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
                tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
                tmp.replace(path)
        except (OSError, ValueError):
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


def usage_tail(n: int = 200) -> list[dict[str, Any]]:
    """读最近 n 条事实；文件不存在/损坏返回空列表（读侧永不抛异常）。"""
    try:
        path = usage_log_dir() / f"{USAGE_LOG_STREAM}.jsonl"
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-n:]
        out: list[dict[str, Any]] = []
        for x in lines:
            if not x.strip():
                continue
            try:
                row = json.loads(x)
            except ValueError:
                continue  # 半行（进程被杀）不该让整本账作废
            if isinstance(row, dict):
                out.append(row)
        return out
    except OSError:
        return []


def usage_stats(hours: float = 24.0) -> dict[str, Any]:
    """最近 N 小时账本汇总；源级、直取级与命令级分开统计。

    这是唯一的聚合点：doctor 与 datasources 都读它，避免两处各写一遍时间窗、
    连续失败与归因逻辑。读侧永不抛异常。

    记录分三类，靠 `scope` 区分：
      - 源级（scope 缺省）：route.fetch 记录真实取数与降级链，键是 `kind`；
      - 直取级（scope="direct"）：直取命令记录绕开 route 的源调用，键是 `src`；
      - 命令级（scope="cmd"）：CLI 入口记录每次命令的 rc 与耗时，键是 `cmd`。
    """
    from datetime import datetime

    records = usage_tail(2000)
    now = datetime.now().astimezone()
    recent: list[dict[str, Any]] = []
    for r in records:
        try:
            ts = datetime.fromisoformat(str(r.get("ts")))
            age = (now - ts).total_seconds()
        except (TypeError, ValueError):
            continue
        if age <= hours * 3600:
            recent.append(r)
    source_rows = [r for r in recent if r.get("scope") not in ("cmd", "direct")]
    return {
        "window_hours": hours,
        "records": len(records),
        "source": _usage_bucket(source_rows, "kind"),
        "direct": _usage_bucket(
            [r for r in recent if r.get("scope") == "direct"], "src"
        ),
        "cmd": _usage_bucket([r for r in recent if r.get("scope") == "cmd"], "cmd"),
        # 空结果基线破位（P3）：健康引擎「突然一直空」是失效信号。
        # 判据三要素（见 sources/envelope.py 的 STALE_* 常量）：
        #   历史曾非空 + 近期连续空 ≥N + 跨 ≥M 个不同查询
        # 从未成功过的源不受影响（无基线可破）。
        "suspected_stale": _suspected_stale(source_rows),
    }


def _suspected_stale(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按源判定 suspected_stale（空结果基线破位）。

    与 argo 的 engine_health.suspected_stale 同构，但**只读账本、零新增请求**：
    每次真实取数已经把成败与交付条数落盘，判据是这些事实的纯函数。

    判定口径：
      - 该源在窗口内**从未交付过非空结果**（无基线）→ 不判（可能是新源/新凭据）；
      - 历史上交付过非空，但最近连续 ≥STALE_MIN_CONSECUTIVE_EMPTY 次空，
        且这些空结果跨 ≥STALE_MIN_DISTINCT_QUERIES 个不同查询 → suspected_stale。
    返回 {source: {"consecutive_empty": n, "distinct_queries": m, "last_nonempty": ts}}。
    """
    from sources.envelope import (
        STALE_MIN_CONSECUTIVE_EMPTY,
        STALE_MIN_DISTINCT_QUERIES,
    )

    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not r.get("ok"):
            continue
        sid = str(r.get("source") or "")
        if not sid:
            continue
        by_source.setdefault(sid, []).append(r)

    out: dict[str, dict[str, Any]] = {}
    for sid, rs in by_source.items():
        # 最近连续空（从最新往回数，遇到非空即停）。
        consecutive = 0
        queries: set[str] = set()
        for r in reversed(rs):
            if r.get("empty") or r.get("count") == 0:
                consecutive += 1
                queries.add(str(r.get("arg") or ""))
            else:
                break
        if consecutive < STALE_MIN_CONSECUTIVE_EMPTY:
            continue
        if len(queries) < STALE_MIN_DISTINCT_QUERIES:
            continue
        # 必须曾经非空（有基线可破）。
        if not any(not (r.get("empty") or r.get("count") == 0) for r in rs):
            continue
        last_nonempty = next(
            (str(r.get("ts")) for r in rs
             if not (r.get("empty") or r.get("count") == 0)),
            None,
        )
        out[sid] = {
            "consecutive_empty": consecutive,
            "distinct_queries": len(queries),
            "last_nonempty": last_nonempty,
        }
    return out


def _usage_bucket(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """一组记录的成败/降级/尾部连续失败/逐源归因/交付条数（P2）。

    交付条数按源聚合：回答「这个源这 24h 交付了多少条数据」，与耗时配对后
    才能区分「慢源拖尾」与「唯一出货」（argo engine_results 同构）。
    空结果数（ok=True 但 count=0）单列，是 suspected_stale 的判据基础（P3）。
    """
    total = len(rows)
    ok = sum(1 for r in rows if r.get("ok"))
    fallback = sum(1 for r in rows if r.get("fallback_from"))
    consecutive: dict[str, int] = {}
    for r in reversed(rows):
        if r.get("ok"):
            break
        name = str(r.get(key) or "?")
        consecutive[name] = consecutive.get(name, 0) + 1
    by_source: dict[str, int] = {}
    fallback_failed: dict[str, int] = {}
    for r in rows:
        for sid in (r.get("failed_sources") or []):
            s = str(sid).strip()
            if s:
                fallback_failed[s] = fallback_failed.get(s, 0) + 1
        if r.get("ok"):
            continue
        for msg in r.get("errors") or []:
            sid = str(msg).split(":", 1)[0].strip()
            if sid.isidentifier():
                by_source[sid] = by_source.get(sid, 0) + 1
    # 交付条数与空结果（仅成功记录有 count；失败记录不计入分母）。
    delivered: dict[str, int] = {}
    empty: dict[str, int] = {}
    for r in rows:
        if not r.get("ok"):
            continue
        name = str(r.get("source") or r.get(key) or "?")
        n = r.get("count")
        if isinstance(n, int) and n >= 0:
            delivered[name] = delivered.get(name, 0) + n
        if r.get("empty"):
            empty[name] = empty.get(name, 0) + 1
    return {
        "total": total,
        "ok": ok,
        "failed": total - ok,
        "fallback": fallback,
        "consecutive": consecutive,
        "by_source": by_source,
        "fallback_failed": fallback_failed,
        "delivered": delivered,
        "empty": empty,
    }


# 【已删除】parallel_execute / query_eastmoney_parallel / eastmoney_query_with_cache
#
# 这三个函数同样是零调用者的死代码，且与在用实现重复：
#   - parallel_execute 的有界并发，sources/hithink.py 的 _request_many 已实现
#     得更好（支持 http_get 注入以便单测保序、MAX_PARALLEL 封顶、异常不外泄）；
#   - query_eastmoney_parallel / eastmoney_query_with_cache 直连东财 claw 端点，
#     而该端点现有唯一入口是 sources/eastmoney.py + cmd_stock.query_eastmoney，
#     再留一条旁路只会让「东财请求怎么发」出现第二种写法。
# 删除即消灭一类 bug：同一件事的第二份实现，是漂移与误用的源头。
