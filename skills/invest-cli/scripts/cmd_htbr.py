"""htbr 子命令：透传华泰柏瑞 ETF 事实查询（htbr-etf-skill）。

用法:
    invest-cli htbr <api_id> --input '<json>' [--json]
    invest-cli htbr --list                      列出可用接口别名

api_id 原样传给上游 scripts/api_client.py（如 fund-basic-info），
也可用 --list 里的语义别名（如 basic / viewpoint / industry-dist）。

参数口径以 htbr 包内 references/apis/<api_id>.md 为唯一真源，本命令不解释字段。
凭证缺失/失效时上游以退出码 3 结束，本命令给出配置指引（不回显 Key）。
"""
from __future__ import annotations

import json
import sys

from sources import htbr as htbr_src


def _grouped_aliases() -> list[tuple[str, list[tuple[str, str]]]]:
    """--list 按「能力面」分组展示；分辨率入口置顶（代码口径是第一大错源）。"""
    buckets: dict[str, list[tuple[str, str]]] = {}
    for alias, target in htbr_src.API_ALIASES.items():
        if target.endswith("-resolve"):
            key = "分辨率入口（先换算代码口径再取数：净码/.OF/内码三套并存）"
        elif target.startswith("fund-manager"):
            key = "基金经理（本源独有能力面，上游 1.0.8 从 4 扩到 20）"
        elif target.startswith("index"):
            key = "指数（估值分位/估值带优先于行情）"
        elif target.startswith("etf"):
            key = "ETF 专项"
        else:
            key = "基金档案/净值/收益风险/持仓估值"
        buckets.setdefault(key, []).append((alias, target))
    order = [
        "分辨率入口（先换算代码口径再取数：净码/.OF/内码三套并存）",
        "基金经理（本源独有能力面，上游 1.0.8 从 4 扩到 20）",
        "基金档案/净值/收益风险/持仓估值",
        "ETF 专项",
        "指数（估值分位/估值带优先于行情）",
    ]
    return [(k, sorted(buckets[k])) for k in order if k in buckets]


def run(api_id: str, params_json: str, as_json: bool = False, list_only: bool = False) -> int:
    if list_only:
        if as_json:
            print(json.dumps(htbr_src.API_ALIASES, ensure_ascii=False, indent=2))
            return 0
        print("\n  可用接口别名（ invest-cli htbr <别名> --input '<json>' ）\n")
        for title, pairs in _grouped_aliases():
            print(f"  ── {title}")
            for alias, api_id_real in pairs:
                print(f"    {alias:<26} → {api_id_real}")
            print()
        print("  完整 api_id 也可直传；参数口径见 htbr 包内 references/apis/<api_id>.md。")
        print("  单指标收益接口（stage-performance/逐期收益/比率类）上游已暂停保留，")
        print("  收益风险一律走合并版 return-risk（一次出全指标）。")
        return 0

    ok, detail = htbr_src.detect()
    if not ok:
        print(f"华泰柏瑞ETF 不可用: {detail}", file=sys.stderr)
        print(
            "提示: 安装 htbr-etf-skill 并在 etf-skill 官网自助获取 API Key，"
            "再执行 python \"<SKILL_DIR>/config.py\" save-key \"<Key>\"。",
            file=sys.stderr,
        )
        return 1

    resolved = htbr_src.resolve_api_id(api_id)
    result = htbr_src.call(resolved, params_json=params_json)

    if as_json:
        payload = {
            "source": "htbr",
            "api_id": resolved,
            **result,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1

    if result.get("ok"):
        if result.get("empty"):
            print(result.get("hint") or "", file=sys.stderr)
        print(json.dumps(result.get("data"), ensure_ascii=False, indent=2, default=str))
        return 0

    err = result.get("error") or "未知错误"
    print(f"华泰柏瑞ETF 调用失败: {err}", file=sys.stderr)
    kind = result.get("error_kind")
    if kind == "quota":
        print("提示: 当日 500 次配额已用尽，今日勿再重试 htbr（重试只会得到同一错误）。", file=sys.stderr)
    elif kind == "rate_limited":
        print("提示: 请求过频（上游建议间隔 ≥3 秒、勿并发批量），稍候重试一次即可。", file=sys.stderr)
    elif kind == "scope_denied":
        print("提示: 该接口未在当前 Key 授权范围内，换接口而不是重试。", file=sys.stderr)
    elif kind == "api_not_found":
        print("提示: 检查 api_id 拼写（invest-cli htbr --list），或上游版本未放行该接口。", file=sys.stderr)
    elif kind == "degraded":
        print("提示: 上游数据源不可用；不得用历史数据/估算值替代作答。", file=sys.stderr)
    if result.get("need_key"):
        print(
            "提示: 在 etf-skill 官网自助获取 Key 后执行 "
            "python \"<SKILL_DIR>/config.py\" save-key \"<Key>\"（无需重启终端）。",
            file=sys.stderr,
        )
    return 1
