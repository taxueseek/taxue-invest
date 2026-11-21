"""cn 子命令：A股/港股市场结构数据（公告 / 一致预期 / 股东 / 披露日历 / 研报）。

定位：把 westock 透传里**最常用的五个子命令**收敛成稳定入口，并补两件事：
  1. `--json` 把 markdown 表格解析成结构化行（agent 要的是字段，不是排版）；
  2. 公告检索双通道：个股列表走 westock（完整、可翻页），关键词检索走 argo 的
     cninfo（巨潮）引擎；westock 不可用时列表回退 argo 检索。

用法:
    invest-cli cn notice <代码[,代码...]> [--type N] [--limit N] [--offset N]
    invest-cli cn notice --search "关键词" [--limit N]
    invest-cli cn consensus <代码[,代码...]>     一致预期（目标价 + 年度预测）
    invest-cli cn holders <代码[,代码...]>       股东研究（十大股东 + 变动）
    invest-cli cn disclosure <代码[,代码...]>    财报披露日历（预约披露日）
    invest-cli cn report <代码[,代码...]> [--limit N] [--offset N]   研报列表

与 westock 透传的关系：透传仍是长尾出口（chip/lhb/events/industry-chain 等
40+ 子命令），本命令只收敛高频的五个并加结构化；两者取的是同一份数据。
"""
from __future__ import annotations

import json
import sys


# 子命令 → (westock 命令前缀, kind, 默认条数)
_SPECS: dict[str, tuple[list[str], str]] = {
    "notice": (["notice", "list"], "cn_notice"),
    "consensus": (["consensus"], "cn_consensus"),
    "holders": (["shareholder"], "cn_holders"),
    "disclosure": (["disclosure"], "cn_disclosure"),
    "report": (["report", "list"], "cn_report"),
}
_TITLES = {
    "notice": "公告列表", "consensus": "一致预期", "holders": "股东研究",
    "disclosure": "财报披露日历", "report": "研报列表",
}


def _parse_output(text: str) -> dict:
    """markdown → 结构化（fail-open：解析结果始终附 raw 原文）。"""
    from md_parse import parse as md_parse

    try:
        parsed = md_parse(text)
    except Exception:  # 解析器出问题绝不能丢数据
        parsed = {"title": "", "meta": {}, "tables": [], "notes": []}
    parsed["raw"] = text
    return parsed


def _westock_envelope(action: str, args: list[str]) -> dict:
    from sources import westock
    res = westock.call(args)
    if not res.get("ok"):
        return {"source": "westock", "kind": _SPECS[action][1], "ok": False,
                "data": None, "error": res.get("error")}
    data = _parse_output(res["data"]["output"])
    data["command"] = res["data"]["command"]
    return {"source": "westock", "kind": _SPECS[action][1], "ok": True,
            "data": data, "error": None}


def _westock_envelope_cached(action: str, args: list[str], codes: str,
                             notice_type: str, limit: int, offset: int) -> dict:
    """带短 TTL 缓存的 westock 取数（失败不缓存）。

    这五个子命令取的都是**结构类**数据（公告/研报/股东/披露日历/一致预期），
    变化以小时/天计；而 `westock <prefix> <codes>` 实测 375ms/次（上游往返）。
    此前这条路径完全没有缓存，同一会话里重复问同一只股每次都要重付一遍。
    """
    try:
        from _common import CACHE_TTL_MARKET, cache_get, cache_set
    except Exception:  # 缓存不可用不该影响取数
        return _westock_envelope(action, args)
    key = f"{action}|{codes}|{notice_type}|{limit}|{offset}"
    hit = cache_get("cn", key, CACHE_TTL_MARKET)
    if isinstance(hit, dict) and hit.get("ok"):
        return {**hit, "cached": True}
    res = _westock_envelope(action, args)
    if res.get("ok"):
        try:
            cache_set("cn", key, res)
        except Exception:
            pass
    return res


def _notice_via_argo(code: str, limit: int) -> dict:
    """westock 不可用时：用 argo 的 cninfo 引擎按名称检索该股公告。

    只做一次尝试、不猜代码对应关系：名称解析走腾讯搜索，解析不出来就把
    原始输入当检索词。结果条数少于 westock 列表（是检索不是清单），
    所以在 note 里写明来源与局限。
    """
    from sources import argo as argo_src
    from sources import tencent

    name = code
    try:
        name = tencent.resolve_name(code) or code
    except Exception:
        pass
    query = f"{name} 公告"
    res = argo_src.search(query, engine="cninfo", limit=limit or 10)
    if not res.get("ok"):
        return {"source": "argo", "kind": "cn_notice", "ok": False, "data": None,
                "error": f"westock 不可用，argo 检索也失败: {res.get('error')}"}
    data = res["data"]
    data["note"] = "来源为 argo/cninfo 关键词检索（非完整公告清单）；恢复 westock 后可看完整列表"
    return {"source": "argo", "kind": "cn_notice", "ok": True, "data": data, "error": None}


def run(action: str, targets: list[str], as_json: bool = False, search: str = "",
        notice_type: str = "", limit: int = 0, offset: int = 0) -> int:
    from sources import argo as argo_src
    from sources import westock

    if action not in _SPECS:
        print(f"未知子命令: {action}（可选: {'/'.join(_SPECS)}）", file=sys.stderr)
        return 1
    if limit < 0 or offset < 0:
        print("错误: --limit/--offset 不能为负", file=sys.stderr)
        return 1

    if action == "notice" and search.strip():
        res = argo_src.search(search.strip(), engine="cninfo", limit=limit or 10)
        if res.get("ok"):
            res = {"source": "argo", "kind": "cn_notice_search", "ok": True,
                   "data": res["data"], "error": None}
    else:
        codes = ",".join(t for t in targets if t.strip())
        codes = westock.normalize_codes(codes)
        if not codes:
            print(f"用法: invest-cli cn {action} <代码[,代码...]>"
                  + ("（或 --search 关键词）" if action == "notice" else ""), file=sys.stderr)
            return 1
        prefix = list(_SPECS[action][0])
        args = prefix + [codes]
        if action == "notice" and notice_type:
            args += ["--type", str(notice_type)]
        if limit:
            args += ["--limit", str(limit)]
        if offset:
            args += ["--offset", str(offset)]
        res = _westock_envelope_cached(action, args, codes, notice_type, limit, offset)
        if not res.get("ok") and action == "notice" and len(targets) == 1:
            # 公告列表是 CN 侧的核心能力：westock 通道故障时降级到 argo 检索，
            # 而不是把「通道挂了」直接丢给用户。
            res = _notice_via_argo(targets[0], limit)

    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if not res.get("ok"):
        print(f"cn {action} 失败: {res.get('error')}", file=sys.stderr)
        return 1
    data = res["data"]
    print(_format_terminal(action, res.get("kind", ""), data))
    return 0


def _format_terminal(action: str, kind: str, data: dict) -> str:
    if kind == "cn_notice_search":
        lines = [f"  巨潮公告检索（cninfo）· {data.get('query')}"]
        for r in data.get("results") or []:
            lines.append(f"\n  {r.get('title')}")
            lines.append(f"  {r.get('url')}")
            if r.get("snippet"):
                lines.append(f"    {r['snippet']}")
        if not (data.get("results") or []):
            lines.append("  （无结果：换关键词，或直接用 `cn notice <代码>` 看该股清单）")
        lines.append(f"\n  说明：{data.get('note', '')}")
        return "\n".join(lines)
    lines = [f"  {_TITLES.get(action, action)}（来源：{data.get('command', 'westock')}）"]
    meta = data.get("meta") or {}
    if meta:
        brief = "，".join(f"{k}={v}" for k, v in meta.items() if k != "title")
        if brief:
            lines.append(f"  {brief}")
    for table in data.get("tables") or []:
        lines.append("")
        lines.append("  " + " | ".join(str(h) for h in table["header"]))
        for row in table["rows"]:
            lines.append("  " + " | ".join(str(v) for v in row.values()))
    for note in data.get("notes") or []:
        lines.append(f"  {note}")
    if not data.get("tables"):
        # 解析不出表格时退回原文（fail-open），而不是给一个空壳
        lines.append("")
        lines.append(data.get("raw", ""))
    return "\n".join(lines)
