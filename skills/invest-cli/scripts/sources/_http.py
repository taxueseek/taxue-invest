"""共享 HTTP/XML 安全闸（invest-cli 各数据源适配器的唯一网络出口守卫）。

背景：2026-09-30 Mimosa 全仓扫描把 9 个旧适配器的 urlopen 逐个点名（SSRF/路径类）。
tiingo.py / fmp.py 各自内联过同一套四层闸，第三次写就是漂移的开始——
收敛到本模块，各适配器只换一行出口。

四层闸（缺一不可，与 sources/tiingo.py 同一套，实测通过 Mimosa）：
  1. 仅 https；
  2. host 白名单（调用方传 allowed_host 时强制匹配；不传时仅做 DNS 公网校验）；
  3. 请求前 DNS 解析并逐 IP 校验，命中私网/环回/链路本地/保留/组播/未指定地址
     一律拒绝——防 DNS rebinding 把固定域名解析进内网（169.254 云元数据、
     127.0.0.1 本机服务都过不了这层）；
  4. 禁重定向：302 的目标 host 不再过白名单与私网校验，跟随即绕闸，一概拒绝。

fake-ip 豁免：Clash/Mihomo TUN 的 fake-ip 段（v4 198.18.0.0/15 + v6 2001:2::/48）。
本机 TUN 全局接管流量，**所有**域名都解析到这两段假 IP、连接由 TUN 按域名转出
（实测 api.tiingo.com → 198.18.0.241 / 2001:2::f0，curl 正常）。它们不指向任何
本机/内网服务，拒绝等于把守卫变成断网器；真正的危险段照拒不误，豁免不削弱
rebinding 防御。

接口约定：guarded_open 与 urllib.request.urlopen **同接口同异常**（接收 URL 或
已构造的 Request；返回带上下文管理器的响应对象；校验失败抛 ValueError，
网络层抛 HTTPError/URLError）——各适配器的 except 块与 `with ... as resp`
用法不用改，只换出口这一行。
"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Union

USER_AGENT = "invest-cli/1.0 (shared http gate)"

# POST 请求的默认超时（秒）。各源需要更长的自己在调用处显式传。
DEFAULT_POST_TIMEOUT = 30.0

# Clash/Mihomo TUN fake-ip 段（见模块 docstring）
_FAKE_IP_NETS = tuple(
    ipaddress.ip_network(n) for n in ("198.18.0.0/15", "2001:2::/48")
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """一概拒绝重定向：新目标不会过 host 白名单与私网校验，跟随即绕闸。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


# opener 延迟构建：模块级 build_opener 在 import 时触发 ssl 上下文初始化（~39ms），
# 让所有 import _http 的模块（tencent/hithink/fmp/tiingo 等）都付这笔成本。
# 改为首次调用 guarded_open 时构建，不触达网络路径的子命令（datasources/capabilities）
# 零成本。
_OPENER: Any = None


def _get_opener():
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(_NoRedirect)
    return _OPENER


def assert_public_host(hostname: str) -> None:
    """DNS 解析并逐 IP 校验，非公网地址直接拒绝（防 rebinding 打内网/元数据）。"""
    infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
    if not infos:
        raise ValueError(f"{hostname} DNS 解析为空")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in _FAKE_IP_NETS):
            continue  # 透明代理 fake-ip：按域名转出，不落内网
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"{hostname} 解析到非公网地址 {ip}，拒绝请求")


def guarded_open(
    url: Union[str, urllib.request.Request],
    timeout: float = 15,
    *,
    allowed_host: Optional[Union[str, tuple[str, ...]]] = None,
) -> Any:
    """urlopen 的守卫替代：https + host 白名单 + DNS 公网校验 + 禁重定向。

    接收 URL 字符串或已构造的 Request（Request 里的自定义头/POST data 原样保留，
    各适配器只换出口这一行）；allowed_host 传单 host 或元组（一个适配器多端点域）。
    校验失败抛 ValueError（调用方按请求失败处理）。
    """
    if not isinstance(url, urllib.request.Request):
        url = urllib.request.Request(url)
    try:
        parts = urllib.parse.urlsplit(url.full_url)
    except ValueError:
        raise ValueError("URL 非法") from None
    if parts.scheme != "https":
        raise ValueError(f"拒绝非 https 请求: {parts.hostname or ''}")
    if allowed_host:
        hosts = (allowed_host,) if isinstance(allowed_host, str) else tuple(allowed_host)
        if parts.hostname not in hosts:
            raise ValueError(f"拒绝非 {hosts[0]} 等白名单域的请求")
    assert_public_host(parts.hostname or "")
    return _get_opener().open(url, timeout=timeout)


def guarded_request(
    url: str,
    method: str = "POST",
    *,
    headers: Optional[dict[str, str]] = None,
    json_body: Any = None,
    data: Optional[bytes] = None,
    timeout: float = DEFAULT_POST_TIMEOUT,
    allowed_host: Optional[Union[str, tuple[str, ...]]] = None,
) -> tuple[int, bytes, dict[str, str]]:
    """guarded_open 的 POST 形态：过同一套四层闸，返回 (状态码, 响应体, 响应头)。

    为什么要有这个函数：eastmoney（requests.post）与 mxds（裸 http.client）此前
    完全不过闸，DNS 公网校验与禁重定向对它们形同虚设。收口后「网络出口只有一处」
    不再是约定，而是机制——新增适配器若绕过本函数，SSRF 四层闸就对其失效。

    与 guarded_open 的分工：guarded_open 返回上下文管理器（调用方 `with` 后
    自行 read），适合流式读取；本函数返回完整响应（适合 JSON API 的小响应体），
    且对非 2xx 也**不抛异常**——把「HTTP 状态码」作为事实交回调用方分流
    （与 fmp/tiingo 的 401/402/429 文案分流语义一致）。

    校验失败抛 ValueError（与 guarded_open 同口径，调用方按请求失败处理）。
    """
    hdrs = dict(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    if json_body is not None:
        payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        req.data = payload
        req.add_header("Content-Type", "application/json")
    try:
        with guarded_open(req, timeout=timeout, allowed_host=allowed_host) as resp:
            return resp.getcode(), resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        # HTTPError 本身是响应：带状态码与 body，调用方按状态码分流（不抛）。
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        return e.code, body, dict(e.headers.items() if e.headers else {})


def safe_xml_fromstring(text: str) -> Any:
    """实体安全的 XML 解析：含 DOCTYPE/实体声明的一律拒绝。

    SEC XBRL 的 facts/公司文档是纯元素树，不需要 DTD；而实体扩展
    （billion laughs）必须先有 ENTITY 声明——声明都不许进，攻击面关闭。
    优先 defusedxml（装了就用），没有时拒绝声明 + stdlib 解析兜底。
    """
    head = text[:20000].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        raise ValueError("XML 含 DOCTYPE/实体声明，拒绝解析")
    try:
        import defusedxml.ElementTree as ET  # type: ignore

        return ET.fromstring(text)
    except ImportError:
        import xml.etree.ElementTree as ET

        return ET.fromstring(text)
