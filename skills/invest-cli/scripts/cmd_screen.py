"""screen 子命令：选股（**股票**筛选）。

用法:
    invest-cli screen <条件> [--json]

数据源：路由按优先级选——妙想 mx_stocks_screener（自然语言选股，priority 55）
优先，东方财富选股 API（stock-screen，priority 50）兜底；两者按定义都只筛股票，
但结果体形状不同（妙想是 columns+items 列表，东财是 partialResults markdown），
解析层对两种都要成立。筛基金走 `invest-cli intent screen`
（带「基金/ETF/债基」等词时路由到盈米）。

本模块与 cmd_sec / cmd_info / cmd_watchlist 同构：终端排版是命令自己的事，
入口 invest_cli.py 只负责 argparse 与分发。
"""
from __future__ import annotations

import json
import sys

from _common import pick_screen_columns, strip_paren_suffix

# 终端一次最多列多少行。东财 partialResults 本来只带首页；妙想虽回全量，
# 终端同样按此截断、尾部报「还有 N 条」，完整清单走 --json。
MAX_ROWS = 15


def parse_markdown_table(md: str) -> list[dict]:
    """解析 markdown 表格为 list[dict]（东财 partialResults 的格式）。"""
    lines = [l.strip() for l in md.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:  # 跳过表头和分隔线
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _trim_result(result, d, limit: int):
    """`--limit` 的行裁剪：两种结果体各按自己的形状裁，顶层统一挂 screen_meta。

    为什么默认 20：选股一次回 40+ 行 × 20 列，JSON 30KB 起（东财 historical
    partialResults 更肥），agent 侧是纯上下文成本；`--limit 0` / `--all` 拿全量。
    不静默丢数据：total / returned / truncated 三个数一定在。
    """
    import copy

    if limit <= 0:
        return result
    out = copy.deepcopy(result)
    total = returned = 0
    if isinstance(d, list) and d:
        node = out
        for _ in range(3):  # 找到承载 items 的那层列表（妙想恒为 out["data"]）
            if isinstance(node, list):
                break
            node = node.get("data") if isinstance(node, dict) else None
        table = node[0] if isinstance(node, list) and node else {}
        items = table.get("items") or []
        total = len(items)
        returned = min(total, limit)
        table["items"] = items[:returned]
        table["items_total"] = total
        table["truncated"] = total > returned
    elif isinstance(d, dict):
        node = out
        for _ in range(3):  # 东财是 data.data，妙想是 data；逐层找到 partialResults
            if isinstance(node, dict) and "partialResults" in node:
                break
            node = node.get("data") if isinstance(node, dict) else None
        if isinstance(node, dict) and "partialResults" in node:
            rows = parse_markdown_table(node["partialResults"])
            total = int(node.get("securityCount") or len(rows))
            returned = min(len(rows), limit)
            lines = [ln for ln in node["partialResults"].strip().splitlines() if ln.strip()]
            if len(lines) >= 2 and rows:
                kept = "\n".join(lines[:2] + lines[2:2 + returned])
                node["partialResults"] = kept
            node["rows_returned"] = returned
            node["truncated"] = total > returned
    out["screen_meta"] = {
        "total": total, "returned": returned,
        "truncated": total > returned, "limit": limit,
    }
    return out


def run(condition: str, as_json: bool = False, limit: int = 20) -> int:
    from sources.route import fetch

    res = fetch("screen", condition)
    if not res.get("ok"):
        print(f"错误: {res.get('error')}", file=sys.stderr)
        return 1
    result = res.get("data") or {}

    # 「上游没答上来」与「上游答了、但没有符合条件的股票」是两件不同的事，
    # 必须分开报——旧写法把两者都落进「未找到结果，请调整筛选条件」并 rc=0。
    #
    # 实测（monkeypatch 上游回包）：`data.data` 为 null（上游业务失败）与
    # `data.data = {"securityCount": 0, "partialResults": ""}`（真的零结果）
    # 输出**一模一样**，rc 都是 0。用户/agent 于是会去改筛选条件——改一个本来
    # 没问题的条件；真实原因是这次请求根本没拿到结果体（空条件即如此）。
    #
    # 判据：有没有拿到**结果体**。东财适配器对业务失败仍返回 ok=True（它只保证
    # 传输成功），所以区分只能在解析层做。
    #
    # 结果体解包：两种胜出源、两种形态（妙想 priority 55 高于东财 50，凭据在时
    # `invest-cli screen` 恒走妙想，东财只是兜底）——
    # · 东财 stock-screen（2026-10-07 线上实测核对）：适配器原样透传上游 JSON，
    #   result = {"success":…, "data": {"requestId":…, "data": {partialResults, securityCount,…}}}，
    #   结果体要连剥**两层** .get("data")。曾试过只剥一层（把 result 当成已是
    #   内层 dict），线上任何有效条件都落进「未找到结果」且 rc=0——静默错误比
    #   崩溃更糟，勿再动这个层级。
    # · 妙想 mx_stocks_screener（2026-10-11 线上实测）：result = {"data": [ {columns, items,…} ]}，
    #   result["data"] 本身就是结果表列表。旧代码对 list 再 .get("data") 直接
    #   AttributeError，妙想可用后整条命令一次都没跑通过——解析层只按一种源写
    #   形状的代价，解包必须对两种形态都成立。
    #
    # 写法：对 dict 连剥两层 .data（东财恰好剥到结果体；妙想剥一层即遇 list
    # 停手），list/None 原样通过——前者进列表分支渲染，后者按「上游没答」报。
    d = result
    if isinstance(d, dict):
        d = d.get("data")
    if isinstance(d, dict):
        d = d.get("data")
    if not d:
        print(f"选股失败：上游未返回结果体（条件：{condition}）", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(_trim_result(result, d, limit), ensure_ascii=False, indent=2))
        return 0

    # 终端输出，两种结果体两种渲染：
    # · dict（东财 stock-screen）：partialResults 的 markdown 表格，行是 dict。
    # · list（妙想 mx_stocks_screener）：每个元素含 columns/items，行是数组、
    #   列按位置对齐。该分支最初按「东财 API 换格式」写防御，2026-10-11 起由
    #   妙想真实命中——渲染口径（挑列/表头）与 dict 分支共用 _common 一套。
    try:
        if isinstance(d, list):
            if not d:
                print("未找到结果，请调整筛选条件")
                return 0
            rs = d[0]  # 取第一个结果集
            columns = [str(c) for c in (rs.get("columns") or [])]
            items = rs.get("items") or []
            sheet_name = rs.get("sheetName", "")
            if not items:
                print("未找到结果，请调整筛选条件")
                return 0
            print(f"\n✅ 找到 {len(items)} 只符合条件的股票")
            if sheet_name:
                print(f"📋 {sheet_name}\n")
            # 挑列与 dict 分支同一套 pick_screen_columns：妙想 18 列里前 6 列
            # 是 序号/代码/名称/最新价/涨跌幅/证券类型，市盈率/市净率全被挤掉，
            # 股息率榜单连股息率都不显示；列名只用来挑位置，行仍按索引取值。
            picked = pick_screen_columns(columns, limit=6)
            idxs = [columns.index(c) for c in picked]
            headers = [strip_paren_suffix(c)[:12] for c in picked]
            print("  " + "  ".join(f"{h:<14}" for h in headers))
            print("  " + "-" * (16 * len(idxs)))
            shown = items[:MAX_ROWS]
            for row in shown:
                vals = [str(row[i])[:14] if i < len(row) else "-" for i in idxs]
                print("  " + "  ".join(f"{v:<14}" for v in vals))
            if len(items) > len(shown):
                print(f"\n  ... 还有 {len(items) - len(shown)} 条结果")
        else:
            # 旧格式：dict with partialResults/securityCount/totalCondition
            partial = d.get("partialResults") or ""
            security_count = d.get("securityCount") or 0
            total_condition = d.get("totalCondition") or ""

            rows = parse_markdown_table(partial)
            if not rows:
                # 走到这里说明上游**确实答了**（结果体非空）但没有匹配行，
                # 这时「未找到结果」才是真话。
                print("未找到结果，请调整筛选条件")
                return 0

            print(f"\n✅ 找到 {security_count} 只符合条件的股票\n")
            if total_condition:
                print(f"🔍 筛选条件: {total_condition}\n")

            # 取前 6 列展示（动态列名，不硬编码日期）
            keys = pick_screen_columns(list(rows[0].keys()), limit=6)
            short_names = [strip_paren_suffix(k)[:12] for k in keys]

            print("  " + "  ".join(f"{h:<14}" for h in short_names))
            print("  " + "-" * (16 * len(keys)))

            shown = rows[:MAX_ROWS]
            for row in shown:
                vals = [str(row.get(k, "-"))[:14] for k in keys]
                print("  " + "  ".join(f"{v:<14}" for v in vals))

            # 剩余条数必须按**实际打印的行数**算，不能按固定常量：
            # partialResults 只带首页（实测 pageSize=20 时仅 10 行），
            # 旧写法在 17 条结果时说「还有 2 条」，而实际少了 7 条。
            remaining = security_count - len(shown)
            if remaining > 0:
                print(f"\n  ... 还有 {remaining} 条结果")

    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"解析结果失败: {e}")
        return 1
    return 0


if __name__ == "__main__":  # 便于单独调试：python3 cmd_screen.py "市盈率低于10的银行股"
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "", as_json="--json" in sys.argv))
