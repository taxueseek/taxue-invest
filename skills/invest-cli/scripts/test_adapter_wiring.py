#!/usr/bin/env python3
"""适配器「真实出口」接线测试 — 不联网，只验默认 getter 能被真的执行。

为什么需要这一层：2026-10-15 的冷启动优化（a1c4923）把 hithink 的模块级
`import urllib.request` 删了，却只在 `_request` 里补了 `urllib.parse`。
`_default_http_get` 仍引用 `urllib.request` / `urllib.error`，于是**首次真实取数**
就抛 `NameError`。而当时 550 条测试全部通过——因为 test_hithink 一律注入
`http_get` 桩，默认 getter 一次都没被执行过。

结论（也是本文件的存在理由）：**mock 掉的边界，就是回归能藏身的地方**。
每条适配器至少要有一次「构造 Request → 过 guarded_open → 解析响应」的真实路径，
HTTP 传输用桩替掉，但 import / 属性 / 参数形状全部走生产代码。

覆盖范围：a1c4923 动过的两个出口（hithink、tencent），以及 stock/fund 链上
mxds 的 coverage 契约（快照类工具必然返回表格 → 不得再进这两条链）。
"""
from __future__ import annotations

import importlib
import sys
import urllib.request
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _FakeResponse:
    """guarded_open 的最小响应替身：只有调用方真正用到的两个方法。"""

    def __init__(self, body: bytes, code: int = 200):
        self._body = body
        self._code = code

    def getcode(self) -> int:
        return self._code

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None


class _Recorder:
    """记录 guarded_open 收到的 URL 与 headers，并按需返回固定响应。"""

    def __init__(self, body: bytes = b'{"code": 0, "data": {}}'):
        self.body = body
        self.calls: list[dict] = []

    def __call__(self, url, timeout=None, *, allowed_host=None):
        headers = {}
        target = url
        if isinstance(url, urllib.request.Request):
            headers = {k.lower(): v for k, v in url.header_items()}
            target = url.full_url
        self.calls.append({"url": target, "headers": headers, "timeout": timeout,
                           "allowed_host": allowed_host, "is_request": isinstance(url, urllib.request.Request)})
        return _FakeResponse(self.body)


def test_hithink_default_getter_runs_end_to_end() -> None:
    """hithink 的默认 getter 必须真的能构造 Request 并解析响应（a1c4923 回归点）。"""
    from sources import hithink

    rec = _Recorder(b'{"code": 0, "message": "success", "data": {}}')
    original = hithink.guarded_open
    hithink.guarded_open = rec
    try:
        status, body = hithink._default_http_get(
            "https://fuyao.aicubes.cn/api/a-share/prices/snapshot?thscodes=600519.SH",
            {"X-api-key": "test-key"},
        )
    finally:
        hithink.guarded_open = original

    assert (status, body) == (200, '{"code": 0, "message": "success", "data": {}}')
    assert len(rec.calls) == 1
    call = rec.calls[0]
    assert call["is_request"] is True, "必须传 urllib Request（自定义头靠它带出去）"
    assert call["headers"].get("x-api-key") == "test-key"
    assert call["allowed_host"] == "fuyao.aicubes.cn"


def test_tencent_http_get_runs_end_to_end() -> None:
    """tencent 的出口是同一轮改造的另一半，一起钉住。"""
    from sources import tencent

    rec = _Recorder("v_sh600519=1~贵州茅台~600519".encode("utf-8"))
    original = tencent.guarded_open
    tencent.guarded_open = rec
    try:
        body = tencent._http_get("https://qt.gtimg.cn/q=sh600519")
    finally:
        tencent.guarded_open = original

    assert "贵州茅台" in body
    assert rec.calls[0]["is_request"] is True
    assert "User-Agent" in {k.title() for k in rec.calls[0]["headers"]}


def test_mxds_not_in_stock_or_fund_snapshot_chains() -> None:
    """妙想快照类工具只返回表格，必然被 _call_tool 拒绝 → 不得再占链位白等 2s。

    它仍保留 screen/bond/index/macro/news/notice 与 intent 直调能力，所以只断言
    「不在 stock/fund 两条快照链上」，不断言整源消失。
    """
    from sources.route import candidates

    assert "mxds" not in candidates("stock", market="a")
    assert "mxds" not in candidates("stock", market="hk")
    assert "mxds" not in candidates("fund")
    assert "mxds" in candidates("screen"), "screen 是 mxds 真实可用的能力，不能一起摘掉"


def test_all_source_adapter_modules_import() -> None:
    """所有适配器模块都能导入：懒导入改造最常见的次生伤害是模块级名字丢失。"""
    sources_dir = _SCRIPTS / "sources"
    failures: list[str] = []
    for path in sorted(sources_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod = f"sources.{path.stem}"
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 —— 汇总所有失败，一次报全
            failures.append(f"{mod}: {type(exc).__name__}: {exc}")
    assert not failures, "适配器导入失败：\n  " + "\n  ".join(failures)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_route_kinds_are_declared_and_callable() -> None:
    """`route_kinds` 是「参与 route.fetch」的真值：必须在 coverage 内且真有方法。

    这条把「声明了却不可能被调用」的噪音挡在 yaml 层：wind/yingmi/argo 等只经
    具名子命令直调，route_kinds 必须是 []；mxds 只保留 screen 这一个真快照能力。
    """
    from sources import load_registry
    from sources import route as _route

    problems: list[str] = []
    for sid, conf in load_registry().items():
        kinds = conf.get("route_kinds")
        if kinds is None:
            continue
        outside = [k for k in kinds if k not in (conf.get("coverage") or [])]
        if outside:
            problems.append(f"{sid}: route_kinds 不在 coverage 内 {outside}")
        try:
            mod = _route._adapter_module(sid, conf)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{sid}: 适配器导入失败 {exc}")
            continue
        missing = [k for k in kinds if not callable(getattr(mod, k, None))]
        if missing:
            problems.append(f"{sid}: 声明可路由但无方法 {missing}")
    assert not problems, "route_kinds 契约破损：\n  " + "\n  ".join(problems)


def test_mxds_route_kinds_is_screen_only() -> None:
    from sources import load_registry

    assert load_registry()["mxds"]["route_kinds"] == ["screen"]
