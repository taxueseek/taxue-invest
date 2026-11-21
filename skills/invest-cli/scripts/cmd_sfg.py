"""sfg 子命令：透传见基行事(seefundgo) 公募基金 MCP。

用法:
    invest-cli sfg <工具或别名> --input '<json>' [--json]
    invest-cli sfg --list                       列出语义别名 → 工具名

工具名与参数口径以 `sfg://api-catalog` 与 `sfg_help` 为唯一真源，本命令不解释字段。
常用入口（别名见 --list）：profile（单只档案）、performance（业绩风险）、
holdings（持仓穿透）、manager（经理画像）、screen（选基筛选）、rankings（排行榜）、
etf（ETF 资金流/轮动）、portfolio-check（组合体检）、fund-tong（选基排名）。

出处标注：本源数据产出必须保留「数据来源：见基行事MCP（fundfof.com）」。
"""
from __future__ import annotations

import json
import sys

from sources import sfg as sfg_src


def run(tool: str, params_json: str, as_json: bool = False, list_only: bool = False,
        poll_job: str = "") -> int:
    if list_only:
        if as_json:
            print(json.dumps(sfg_src.ALIASES, ensure_ascii=False, indent=2))
            return 0
        print("\n  可用工具别名（ invest-cli sfg <别名> --input '<json>' ）\n")
        print("  单只基金：profile / performance / holdings / report / scale")
        print("  经理机构：manager / manager-history / manager-institution")
        print("  选基榜单：screen / rankings / fund-tong / compare / similar")
        print("  ETF 指数：etf / index / rotation")
        print("  组合诊断：portfolio-parse / portfolio-check / portfolio-submit /")
        print("            portfolio-result / fof-underlying / style-exposure /")
        print("            optimize / style-attribution / suitability /")
        print("            review-cadence / compliance")
        print("  市场事件：market / events / stock-funds / share-cost")
        print("  兜底：api（先读 sfg://api-catalog）/ help")
        print()
        print("  组合诊断：portfolio-submit 拿 job_id，再 --poll <job_id> 取完整结果")
        print("           （同步 portfolio-check 有 30s 服务端硬顶，多只基金会超时）")
        print()
        print(f"  也可直传完整工具名（sfg_*）；出处标注：{sfg_src.ATTRIBUTION_LINE}")
        return 0

    if not tool and not poll_job:
        print("缺少工具名或别名（invest-cli sfg --list 看清单）", file=sys.stderr)
        return 2

    ok, detail = sfg_src.detect()
    if not ok:
        print(f"见基行事 MCP 不可用: {detail}", file=sys.stderr)
        print("提示: 设置环境变量 SFG_MCP_TOKEN 或写入 ~/.config/invest-cli/sfg.env。", file=sys.stderr)
        return 1

    try:
        params = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError as e:
        print(f"--input 不是合法 JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(params, dict):
        print("--input 必须是 JSON 对象", file=sys.stderr)
        return 2

    if tool:
        try:
            tool_name = sfg_src.resolve_tool(tool)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
    else:
        tool_name = ""

    if poll_job:
        # 组合诊断轮询：submit 拿 job_id 后，用 --poll <job_id> 取完整结果
        result = sfg_src.poll_portfolio(poll_job)
    else:
        result = sfg_src.call(tool_name, params)
    if as_json:
        payload = {"source": "sfg", "tool": tool_name, **result}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if result.get("ok"):
        print(json.dumps(result.get("data"), ensure_ascii=False, indent=2))
        return 0
    print(f"见基行事调用失败: {result.get('error')}", file=sys.stderr)
    return 1
