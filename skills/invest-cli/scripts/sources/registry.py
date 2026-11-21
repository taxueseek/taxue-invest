"""数据源注册表：加载配置真源 + 可用性探测（门闩）。

CLI 与分析 skill 只通过本模块判断某数据源是否可用，不自行猜测。
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from . import load_registry

# 命令/目录型探测（起子进程）已随外部 CLI 依赖一起删除：现所有数据源都走
# env / env_or_file / python / always，不再需要 shell 探针。
ENV_KEY_FALLBACK = "HITHINK_FINANCE_API_KEY"
# command/dir 探测贵（子进程），同进程 30s 内复用；env/python 本身很便宜不缓存。
_PROBE_TTL = 30.0
# 真实 HTTPS 探测预算：要远小于数据源自身的连接超时，
# 否则「探测」本身就成了新的瓶颈（Yahoo 库内写死 30s）。
HTTP_PROBE_TIMEOUT = 2.0
PROBE_USER_AGENT = "invest-cli/1.0 (reachability probe)"
# **跨进程**缓存：CLI 每次调用都是新进程，进程内 TTL 缓存救不了冷启动。
# 若不落盘，每次 `invest-cli stock ...` 都要重付一次可达性探测
# （实测 yfinance 冷探测 2.02s，占 pick() 全部耗时；热探测 0.0003s）。
#
# 成功与失败的 TTL 刻意不同（**非对称**）：
#   - 成功：缓存久一点（省探测成本，源确实好用）；
#   - 失败：缓存较短，避免把瞬时抖动放大成持续不可用；但也不能太短——
#     本探测的 False 只来自「连不上/握手失败」（HTTPError 有状态码 = 可达 = True），
#     这类网络级不可达恢复通常以分钟计。实测本机 Yahoo 不可达时，20s 负缓存
#     会让 us 链每隔 20s 就重付 2s 探测 + 0.55s 取数失败（us 冷 2.6s vs 热 0.06s），
#     提到 120s 后日常使用基本全热。可用 INVEST_CLI_PROBE_TTL_FAIL 覆盖。
_PROBE_DISK_TTL = 300.0
_PROBE_DISK_TTL_DEFAULT_FAIL = 120.0
# 凭据/命令型（adapter / command）失败判据的落盘 TTL，比 http 型短：
# 它们的 False 来自「凭据缺失/过期」「二进制不在」，补好是秒级到分钟级恢复。
#
# 这里**曾经是「False 一律不落盘」**，理由是「补凭据是秒级恢复，落 120s 负缓存
# 会让 datasources 给出 2 分钟前的旧结论」。代价当时没量：CLI 每进程独立，
# 进程内 30s 缓存救不了跨进程，于是**每个新进程都要重跑一次子进程探测**——
# 实测 `ttskill status` 145ms、`etfirst --help` 197ms，而 `fund`（链上有 ttskill）、
# `capabilities`/`datasources`（逐源探测）每次调用都重付一遍。
# 现在改成「落盘 + 短 TTL」：同一分钟内的重复调用不再重探，把「旧结论」窗口
# 从 120s 压到 60s；要即时刷新（排障）把 INVEST_CLI_PROBE_TTL_FAIL 设 0。
_PROBE_DISK_TTL_FAIL_CRED = 60.0
_PROBE_CACHE: dict[tuple[Any, ...], tuple[float, bool, str]] = {}


def _probe_disk_ttl_fail() -> float:
    """失败探测的落盘 TTL（env 可覆盖；非法值回默认）。"""
    raw = os.environ.get("INVEST_CLI_PROBE_TTL_FAIL", "").strip()
    if not raw:
        return _PROBE_DISK_TTL_DEFAULT_FAIL
    try:
        val = float(raw)
    except ValueError:
        return _PROBE_DISK_TTL_DEFAULT_FAIL
    return max(0.0, val)


def skill_roots() -> list[Path]:
    """候选 skill 根目录列表（可用 INVEST_SKILL_ROOTS 覆盖扩展，os.pathsep 分隔）。"""
    roots: list[Path] = []
    env_roots = os.environ.get("INVEST_SKILL_ROOTS", "")
    if env_roots:
        for p in env_roots.split(os.pathsep):
            if p.strip():
                roots.append(Path(p.strip()).expanduser())
    home = Path.home()
    for base in (
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".grok" / "skills",
        home / ".codex" / "skills",
    ):
        roots.append(base)
    cwd = Path.cwd()
    for base in (cwd / ".agents" / "skills", cwd / ".claude" / "skills"):
        roots.append(base)
    # 自动发现常见项目根下的数据源 skill（如 Wind 装在项目内），无需手工配环境变量
    for parent in (home / "Documents",):
        if parent.is_dir():
            for proj in parent.glob("*"):
                for base in (proj / ".agents" / "skills", proj / ".claude" / "skills"):
                    if base.is_dir() and base not in roots:
                        roots.append(base)
    return roots


def find_skill_dir(skill_name: str) -> Optional[Path]:
    """在常见 skill 根目录定位某个 skill 目录，找不到返回 None。"""
    for root in skill_roots():
        cand = root / skill_name
        if cand.is_dir():
            return cand
    return None


def _probe_env(var: str) -> tuple[bool, str]:
    from .env import read_env

    val = read_env(var)
    if val:
        return True, f"{var} 已配置"
    return False, f"缺少环境变量 {var}"


def _probe_python(module: str) -> tuple[bool, str]:
    """python 包型数据源探测：装了 ≠ 可达。

    只做 find_spec 是旧行为，它会伪造可用性：本机 Yahoo 完全不可达时，
    yfinance 仍被判「可用」并排进 us 链首位，于是每次 `us <code>` 先烧满
    yfinance 的 30s 连接超时再回退 bitget（实测 31.3s vs 1.0s）。
    「可用」的判据必须是「这个源现在真能取到数」，而不是「这个包在磁盘上」。

    为什么不是 TCP 探测：本机 TCP connect 到 Yahoo 在 0.01s 内就「成功」
    （被本地 PAC/透明代理应答），而真实 HTTPS 请求 10s 都不返回
    （curl 实测 connect=0.000000s、total=10.06s 后超时）。
    即 TCP 可达性是个假信号，会原样保留这个 bug。因此这里做**真实 HTTPS
    探测**：一次 HEAD/GET，带 2s 预算，判据是拿到 HTTP 状态码。

    结果按 _PROBE_TTL 缓存，故每个进程最多只付一次探测成本。
    探测不可判定（异常/网络栈问题）时**放行**（fail-open），
    绝不因探测本身出错而误杀一个可能好用的数据源。
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return False, f"未安装 python 模块 {module}"

    url = _probe_url_for_module(module)
    if not url:
        return True, f"模块 {module} 可用"
    reachable, detail = _cached(("http", url), lambda: _probe_http(url))
    if not reachable:
        return False, f"模块 {module} 已安装，但端点不可达（{detail}）"
    return True, f"模块 {module} 可用（{detail}）"


# 需要做真实可达性校验的 python 包 → 探针 URL。
# 只登记「装了但可能连不上」的网络型包；纯本地计算包不在此列。
# 探针用**最轻的端点**（chart 接口单标的、不取字段），避免探测本身开销过大。
_PYTHON_ENDPOINTS: dict[str, str] = {
    "yfinance": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
}


def _probe_url_for_module(module: str) -> str:
    return _PYTHON_ENDPOINTS.get(module, "")


def _probe_http(url: str, timeout: float = HTTP_PROBE_TIMEOUT) -> tuple[bool, str]:
    """真实 HTTPS 可达性探测：拿到任意 HTTP 状态码即视为可达。

    只读状态码、不解析响应体；任何网络异常都视为不可达。
    """
    # 两个子模块都要显式导入：只 import urllib.error 时 urllib.request 属性
    # 不存在，下一行 Request() 必抛 AttributeError——探测从未发出请求就把
    # yfinance 标成「端点不可达」，美股主路被静默跳过（2026-10-07 实锤修复）。
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": PROBE_USER_AGENT})
    try:
        from ._http import guarded_open

        with guarded_open(req, timeout) as resp:
            return True, f"HTTP {resp.getcode()}"
    except urllib.error.HTTPError as e:
        # 有状态码 = 服务在线（401/403/405 都说明端点在应答）
        return True, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}"


def _probe_cache_key(key: tuple[Any, ...]) -> tuple[Any, ...]:
    """把缓存根目录并入探测键。

    否则进程内缓存会跨缓存目录复用：一个在 dir_A 下探到的结果，会在
    INVEST_CLI_CACHE_DIR 切到 dir_B 后继续命中——测试隔离与运行时切换
    缓存位置都会被这条「串味」的条目绕过（实测可复现）。
    """
    try:
        from _common import cache_root

        return key + (str(cache_root()),)
    except Exception:
        return key


def _probe_cache_path(key: tuple[Any, ...], *, create: bool = True) -> Optional[Path]:
    """探测结果的落盘位置（全类型跨进程复用）。

    create=False 给查表用：一次负缓存未命中不该顺手建出目录树。
    """
    try:
        from _common import cache_path

        return cache_path("probe", repr(key), create=create)
    except Exception:
        return None


def _cached(key: tuple[Any, ...], fn, fail_ttl: float | None = None) -> tuple[bool, str]:
    """探测结果缓存（进程内 + 落盘）。fail_ttl 是「本次判据失败时」的落盘 TTL。

    fail_ttl 由**写者**声明、随条目落盘，因为恢复节奏是判据自身的属性：
    http 型失败是网络不可达（以分钟计），adapter/command 型是凭据或二进制
    （秒级到分钟级）。读侧取「env 覆盖值」与「条目自述值」中的较小者——
    排障时把 INVEST_CLI_PROBE_TTL_FAIL 设 0 即可让所有负条目立即失效。
    """
    now = time.monotonic()
    ckey = _probe_cache_key(key)
    hit = _PROBE_CACHE.get(ckey)
    if hit and now - hit[0] < _PROBE_TTL:
        return hit[1], hit[2]

    # 全类型探测一律先看跨进程落盘缓存：CLI 每次都是新进程，进程内缓存无效。
    # 旧条件只落盘 http 型，command/adapter/dir 型每进程重付一次子进程探测
    # （实测 ~0.35s/类）。探测键已并入 cache_root（_probe_cache_key），
    # 落盘对全类型安全，不会跨缓存目录串味。
    disk = _probe_cache_path(ckey, create=False)
    if disk is not None:
        try:
            if disk.is_file():
                age = time.time() - disk.stat().st_mtime
                data = json.loads(disk.read_text(encoding="utf-8"))
                was_ok = bool(data.get("ok"))
                if was_ok:
                    ttl = _PROBE_DISK_TTL
                else:
                    stored = data.get("fail_ttl")
                    stored = float(stored) if isinstance(stored, (int, float)) else _probe_disk_ttl_fail()
                    ttl = min(_probe_disk_ttl_fail(), max(0.0, stored))
                if age < ttl:
                    ok, detail = was_ok, str(data.get("detail", ""))
                    _PROBE_CACHE[ckey] = (now, ok, detail)
                    return ok, detail
        except (OSError, ValueError):
            pass

    try:
        ok, detail = fn()
    except Exception as e:
        # fail-open 的另一半：探测函数**自身**抛异常时不能外泄。
        # 可用性判据出问题绝不该让整条取数链挂掉——按不可达处理并说明原因。
        ok, detail = False, f"探测异常（{type(e).__name__}）"
    _PROBE_CACHE[ckey] = (now, ok, detail)

    if disk is not None:
        try:
            # 目录只在真正落盘时建（查表用 create=False，读路径零写副作用）
            disk.parent.mkdir(parents=True, exist_ok=True)
            # 临时名带 pid：CLI 每进程独立，共用同一个 .tmp 会让并发写者互相截断
            tmp = disk.with_name(f"{disk.name}.{os.getpid()}.tmp")
            payload = {"ok": ok, "detail": detail}
            if not ok:
                payload["fail_ttl"] = fail_ttl if fail_ttl is not None else _probe_disk_ttl_fail()
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(disk)
        except OSError:
            pass

    return ok, detail


def _probe_binary(binary: str, timeout: float = 10.0) -> tuple[bool, str]:
    """命令型源探测：跑一次 `<bin> --help`，rc=0 即可用。

    为什么不能只判「文件存在」：westock 的旧实现就栽在这上面——目录里有
    setup.sh 却没有真二进制，「存在」为真而调用永远失败（known-issues ①）。
    `--help` 实测 ~20ms，值得付。

    **不 shell=True**：binary 来自 data-sources.yaml（受版本控制），但走
    argv 列表仍是不把任何输入拼进命令行的正确姿势；--help 固定参数，
    没有注入面。
    """
    import subprocess

    try:
        proc = subprocess.run(
            [binary, "--help"], capture_output=True, timeout=timeout,
            text=True, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{binary} 无法执行: {e}"
    if proc.returncode != 0:
        return False, f"{binary} 异常退出 rc={proc.returncode}"
    return True, f"{binary} 可用"


def detect(conf: dict[str, Any]) -> tuple[bool, str]:
    """按 conf['detect'] 探测单个数据源，返回 (available, detail)。"""
    dt = (conf.get("detect") or {}).get("type")
    if dt == "env":
        return _probe_env(conf.get("env_var", ""))
    if dt == "env_or_file":
        names = conf.get("adapters") or []
        if names:
            try:
                mod = importlib.import_module(f"sources.{names[0]}")
                fn = getattr(mod, "detect", None)
                if callable(fn):
                    # 适配器级探测多为子进程（ttskill status 等），与 command 同享缓存。
                    # **正负都落盘**：负结果用凭据型短 TTL（默认 60s）。早先这里 False
                    # 时删掉落盘条目，代价是每个新进程都重跑一次子进程探测——实测
                    # `ttskill status` 145ms，而 `fund`（链上有 ttskill）每次调用都付。
                    return _cached(("adapter", names[0]), fn, fail_ttl=_PROBE_DISK_TTL_FAIL_CRED)
            except Exception:
                pass
        ok, detail = _probe_env(conf.get("env_var", ""))
        if ok:
            return ok, detail
        files = (conf.get("detect") or {}).get("files") or []
        var = conf.get("env_var") or ENV_KEY_FALLBACK
        for raw in files:
            if Path(raw).expanduser().is_file():
                return True, "读到 credentials.env"
        return False, f"缺少环境变量 {var} 且无凭据文件"
    if dt == "python":
        return _probe_python((conf.get("detect") or {}).get("module", ""))
    if dt == "command":
        # 命令型探测：起子进程确认二进制真能跑（不是「文件存在」）。
        #
        # 这个分支曾随 v2.6「外部 CLI 依赖清理」一并删掉，但 data-sources.yaml
        # 里 etfirst 仍声明 `type: command` —— 于是一个**已装好的**数据源
        # （实测 /opt/homebrew/bin/etfirst 存在且可执行）被永久判成
        # 「未知探测方式 'command'」，`datasources` 恒报 False。声明与判据
        # 漂移的代价是静默的：链路少一个源，没有任何报错。
        #
        # 实现：优先用适配器自带的 detect()（它知道该跑 `--help` 还是
        # `--version`，比这里瞎猜一个参数可靠），没有就退回 `check` 字段
        # 指定的二进制跑 `--help`。子进程探测按 _PROBE_TTL 进程内缓存。
        name = (conf.get("adapters") or [conf.get("check") or ""])[0]
        if name:
            try:
                mod = importlib.import_module(f"sources.{name}")
                fn = getattr(mod, "detect", None)
                if callable(fn):
                    # 与 adapter 分支同一处理：正负都落盘，负结果走凭据型短 TTL。
                    # 早先 False 时删条目，代价是每个新进程重跑 `etfirst --help`
                    # （实测 197ms）。
                    return _cached(("command", name), fn, fail_ttl=_PROBE_DISK_TTL_FAIL_CRED)
            except Exception:
                pass
        # 回退：跑 `check` 指定的**二进制**。不能拿适配器模块名当二进制——
        # 模块存在但没有 detect() 时，那会得到「fakemod 无法执行」这种
        # 与真实原因无关的报错（实测）。
        binary = (conf.get("detect") or {}).get("check")
        if not binary:
            return False, "command 型探测缺少 check 配置（且适配器无 detect()）"
        return _cached(("bin", binary), lambda: _probe_binary(binary))
    if dt == "always":
        return True, "始终可用（免费无 key）"
    return False, f"未知探测方式 {dt!r}"


def detect_all() -> dict[str, dict[str, Any]]:
    """返回 {source_id: {…conf, available, detail}}。

    并行探测：各数据源的探测互相独立（env 读环境变量、command 起子进程、
    python 做 HTTPS 探测），串行执行时总耗时 = 各源之和（实测 10+ 源
    串行 ~0.9s）。改用 ThreadPoolExecutor 并行后，总耗时 ≈ 最慢单源
    （实测 ~0.2s）。
    """
    registry = load_registry()
    out: dict[str, dict[str, Any]] = {}
    if not registry:
        return out

    # 并行探测：各源探测互相独立，无共享状态（_cached 内部有进程内锁）
    from concurrent.futures import ThreadPoolExecutor

    def _probe_one(item: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        sid, conf = item
        available, detail = detect(conf)
        return sid, {**conf, "available": available, "detail": detail}

    with ThreadPoolExecutor(max_workers=min(8, len(registry))) as pool:
        results = pool.map(_probe_one, registry.items())

    for sid, state in results:
        out[sid] = state
    return out


def available_ids(states: Optional[dict[str, dict[str, Any]]] = None) -> list[str]:
    """仅返回探测可用的数据源 id，按 priority 降序。

    可传入已有的 detect_all() 结果：调用方已经探过一次时不必再探一遍
    （doctor 的 check_sources 曾因此把 0.3s 级的并行探测跑两次）。
    """
    states = detect_all() if states is None else states
    ranked = sorted(
        states.items(), key=lambda kv: kv[1].get("priority", 0), reverse=True
    )
    return [sid for sid, st in ranked if st.get("available")]
