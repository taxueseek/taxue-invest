#!/usr/bin/env python3
"""SSRF 四层闸收口门禁：所有网络出口必须过 sources/_http。

为什么需要：2026-09-30 Mimosa 全仓扫描把 9 个旧适配器的 urlopen 逐个点名
（SSRF/路径类）。此后 eastmoney 的 requests.post 与 mxds 的裸 http.client
仍不过闸——DNS 公网校验与禁重定向对这两条路径完全失效。P0 收口（2026-11-09）
把它们并入 guarded_request，本文件把「网络出口只有一处」从约定变成机制：

1. **静态守卫**：生产代码（scripts/ 与 scripts/sources/）不得出现 requests.*、
   http.client、裸 urlopen——出现即说明又开了一个旁路。
   豁免：sources/_http.py 自身（闸的实现），以及 test_*.py（打桩需要）。
2. **契约守卫**：guarded_request 必须真的过四层闸（https、host 白名单、
   DNS 公网校验、禁重定向），且非 2xx 不抛异常（交回调用方分流）。
"""
from __future__ import annotations

import ast
import io
import sys
import urllib.error
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources import _http  # noqa: E402

# 允许的裸网络实现（闸自身）。生产代码不得出现其他裸网络调用。
_ALLOWED_BARE_NET = {"sources/_http.py"}


def _production_py_files() -> list[Path]:
    """生产代码 .py（排除 test_*.py 与 conftest）。"""
    files = [p for p in _SCRIPTS.glob("*.py") if not p.name.startswith("test_")]
    files += [p for p in (_SCRIPTS / "sources").glob("*.py")
              if not p.name.startswith("test_")]
    return files


def _bare_net_calls(path: Path) -> list[str]:
    """AST 扫描：找出不过闸的裸网络调用（requests.* / http.client / urlopen）。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        # requests.post / requests.get / requests.request ...
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "requests":
                hits.append(f"L{node.lineno}: requests.{node.attr}")
        # http.client.HTTPSConnection / HTTPConnection
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            if (isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "http"
                    and node.value.attr == "client"):
                hits.append(f"L{node.lineno}: http.client.{node.attr}")
        # urllib.request.urlopen / urllib.urlopen
        if isinstance(node, ast.Attribute) and node.attr == "urlopen":
            hits.append(f"L{node.lineno}: {ast.unparse(node)}")
    return hits


def test_no_bare_network_calls_outside_gate() -> None:
    """生产代码不得绕过 _http 闸直接发网络请求。

    新增适配器若用 requests / http.client / 裸 urlopen，本用例即红——
    这正是 eastmoney 与 mxds 曾经的状态（SSRF 四层闸对它们形同虚设）。
    """
    offenders: list[str] = []
    for path in _production_py_files():
        rel = str(path.relative_to(_SCRIPTS.parent))
        if rel in _ALLOWED_BARE_NET:
            continue
        hits = _bare_net_calls(path)
        if hits:
            offenders.append(f"{path.name}: {'; '.join(hits)}")
    assert not offenders, (
        "发现绕过 _http 闸的裸网络调用：\n  " + "\n  ".join(offenders)
        + "\n\n网络出口只有一处（sources/_http）：requests/http.client/裸 urlopen "
        "不过 DNS 公网校验与禁重定向，SSRF 防御对它们失效。"
    )


def test_guarded_request_rejects_non_https() -> None:
    """http:// 必须被拒（四层闸第一层）。"""
    with pytest.raises(ValueError, match="非 https"):
        _http.guarded_request("http://example.com/x", allowed_host="example.com")


def test_guarded_request_rejects_non_whitelisted_host() -> None:
    """非白名单 host 必须被拒（四层闸第二层）。"""
    with pytest.raises(ValueError, match="白名单"):
        _http.guarded_request("https://evil.example/x", allowed_host="api.example.com")


def test_guarded_request_rejects_private_dns(monkeypatch) -> None:
    """DNS 解析到私网必须被拒（四层闸第三层，防 rebinding）。"""
    def _boom(host):
        raise ValueError(f"{host} 解析到非公网地址 10.0.0.1，拒绝请求")

    monkeypatch.setattr(_http, "assert_public_host", _boom)
    with pytest.raises(ValueError, match="非公网"):
        _http.guarded_request("https://api.example.com/x", allowed_host="api.example.com")


def test_guarded_request_http_error_does_not_raise(monkeypatch) -> None:
    """非 2xx 不抛异常，交回调用方按状态码分流（与 fmp/tiingo 文案分流同口径）。"""
    fp = io.BytesIO(b'{"error":"bad key"}')

    def _fake_open(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {"Content-Type": "application/json"}, fp
        )

    monkeypatch.setattr(_http, "assert_public_host", lambda host: None)
    monkeypatch.setattr(
        _http, "_get_opener",
        lambda: type("_O", (), {"open": staticmethod(_fake_open)})(),
    )
    status, body, headers = _http.guarded_request(
        "https://api.example.com/x", allowed_host="api.example.com"
    )
    assert status == 401
    assert b"bad key" in body


def test_eastmoney_screen_uses_gate(monkeypatch) -> None:
    """eastmoney.screen 必须走 guarded_request（P0 收口的端到端锚）。"""
    import sources.eastmoney as em

    monkeypatch.setattr(em, "load_api_key", lambda: "k")
    called = {}

    def _fake(url, **kw):
        called["url"] = url
        called["host"] = kw.get("allowed_host")
        return 200, b'{"data": []}', {}

    monkeypatch.setattr("sources._http.guarded_request", _fake)
    res = em.screen("ROE > 20")
    assert res["ok"] is True
    assert called["host"] == "mkapi2.dfcfs.com", "screen 未过闸或 host 白名单不对"


def test_mxds_mcp_call_uses_gate(monkeypatch) -> None:
    """mxds._mcp_call 必须走 guarded_request（P0 收口的端到端锚）。"""
    import sources.mxds as mx

    monkeypatch.setattr(mx, "load_api_key", lambda: "k")
    called = {}

    def _fake(url, **kw):
        called["url"] = url
        called["host"] = kw.get("allowed_host")
        text = '{"data":{"a":1}}'
        body = (
            '{"jsonrpc":"2.0","id":1,"result":{"content":'
            '[{"type":"text","text":' + '"' + text.replace('"', '\\"') + '"' + '}]}}'
        ).encode("utf-8")
        return 200, body, {"Content-Type": "application/json"}

    monkeypatch.setattr("sources._http.guarded_request", _fake)
    res = mx._mcp_call("mx_ashare_finance_data", "贵州茅台")
    assert res["ok"] is True
    assert called["host"] == mx.MCP_HOST, "MCP 调用未过闸或 host 白名单不对"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
