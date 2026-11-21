"""数据源信封与状态词的单一真源。

## 为什么需要它

invest-cli 此前有两类「同一事实存多处」：

1. **信封构造 5 份**：`_envelope` 在 hithink/fmp/tiingo/tencent/bitget 各写一遍，
   fund_classifier 与 sec_edgar 又各写一份变体。信封键（ok/source/kind/data/error）
   是全链路的接口契约——route 用 `ok` 判成败、用 `tried` 判是否真发过请求、用
   `fallback_from` 记降级来源。5 份实现意味着改一个键要改 5 处，漏一处就是
   「某个源的信封 route 读不懂」的静默失配。

2. **状态词 33 处**：doctor 的 pass/warn/fail/skip 在 cmd_doctor.py 里写了 27 处
   字面量，另 6 处散落。加一个状态（如 suspected_stale）要改 N 处，漏改就是
   「分诊显示 false 而判定为 true」这类失配。

## 设计原则（与 argo engine_states.py 同构）

- 每个状态**只有一个名字**，所有模块从这里 import，不手写字面量。
- 只定义词表与纯构造函数，不碰 IO、不碰持久化。
- 词表按**机器（状态机）**组织：信封键、健康分诊态、输出契约态各一组。

## 词表边界（不要把两套词表合并）

- 信封键（`ok`/`source`/`kind`/`data`/`error`）：route 与全部适配器的契约。
- 健康分诊态（`pass`/`warn`/`fail`/`skip`）：doctor 的展示与退出码判据。
  与 argo 的 health verdict（auth_down/suspect/...）不同层，不要混用。
"""
from __future__ import annotations

from typing import Any, Optional

# ── 1. 信封键（全链路契约，route 与适配器共用）──────────────────────────────
KEY_OK = "ok"
KEY_SOURCE = "source"
KEY_KIND = "kind"
KEY_DATA = "data"
KEY_ERROR = "error"
KEY_TRIED = "tried"
KEY_FALLBACK_FROM = "fallback_from"
KEY_FALLBACK_ERROR = "fallback_error"
KEY_INPUT_ERROR = "input_error"
KEY_EMPTY = "empty"

ENVELOPE_KEYS = frozenset({
    KEY_OK, KEY_SOURCE, KEY_KIND, KEY_DATA, KEY_ERROR,
    KEY_TRIED, KEY_FALLBACK_FROM, KEY_FALLBACK_ERROR,
    KEY_INPUT_ERROR, KEY_EMPTY,
})


def envelope(
    source: str,
    kind: str,
    ok: bool,
    data: Any = None,
    error: Optional[str] = None,
    *,
    input_error: bool = False,
) -> dict[str, Any]:
    """构造标准信封。所有适配器的唯一出口。

    与旧 `_envelope(kind, ok, data, error)` 的差异：source 成为**必填**位置参
    ——5 份旧实现各自把 source 写死在自己模块里，调用方无法从签名看出「这个源的
    信封 source 是谁」。收到这里后，source 由调用点显式给出，签名即契约。

    input_error=True 时额外落 `input_error` 键（route 据此终止整条链，不换源去猜）。
    """
    env: dict[str, Any] = {
        KEY_SOURCE: source,
        KEY_KIND: kind,
        KEY_OK: ok,
        KEY_DATA: data,
        KEY_ERROR: error,
    }
    if input_error:
        env[KEY_INPUT_ERROR] = True
    return env


def ok_envelope(source: str, kind: str, data: Any = None) -> dict[str, Any]:
    return envelope(source, kind, True, data=data, error=None)


def fail_envelope(
    source: str,
    kind: str,
    error: str,
    *,
    input_error: bool = False,
) -> dict[str, Any]:
    return envelope(source, kind, False, data=None, error=error,
                    input_error=input_error)


def is_ok(env: Any) -> bool:
    """信封成败判定（route 的唯一判据）。非信封一律视为失败。"""
    return isinstance(env, dict) and bool(env.get(KEY_OK))


# ── 2. 健康分诊态（doctor 展示与退出码判据）────────────────────────────────
HEALTH_PASS = "pass"
HEALTH_WARN = "warn"
HEALTH_FAIL = "fail"
HEALTH_SKIP = "skip"

HEALTH_STATES = frozenset({HEALTH_PASS, HEALTH_WARN, HEALTH_FAIL, HEALTH_SKIP})

# doctor 的退出码判据：fail 阻塞，其余放行。
BLOCKING_STATES = frozenset({HEALTH_FAIL})

_BADGE = {
    HEALTH_PASS: "[PASS]",
    HEALTH_WARN: "[WARN]",
    HEALTH_FAIL: "[FAIL]",
    HEALTH_SKIP: "[SKIP]",
}


def badge(state: str) -> str:
    """分诊态的展示前缀。未知态按 skip 处理（不伪造通过）。"""
    return _BADGE.get(state, _BADGE[HEALTH_SKIP])


def is_blocking(state: str) -> bool:
    return state in BLOCKING_STATES


# ── 3. 空结果基线破位判据（suspected_stale，见 usage 层）────────────────────
# 判据三要素：历史曾非空 + 近期连续空 + 跨查询。三者缺一不可——
# 从未成功过的源（新接入/新凭据）不受此判据影响。
STALE_MIN_CONSECUTIVE_EMPTY = 3   # 近 N 次连续空
STALE_MIN_DISTINCT_QUERIES = 2    # 至少跨 N 个不同查询（防单查询抖动）
