"""ETF 深度分析终端渲染层（从 etf_analytics.py 拆分，只做纯格式化输出）。"""
from __future__ import annotations

from typing import Any, Callable, Optional


def format_terminal(
    analysis: dict,
    safe_float: Callable[[Any], Optional[float]],
) -> str:
    """格式化终端输出。"""
    lines = []
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {analysis.get('fund_name', '未知')}（{analysis.get('fund_code', '-')}）— ETF 深度分析")
    lines.append(f"{'=' * 60}")

    # 持仓穿透
    ha = analysis.get("holdings_analysis")
    if ha and "error" not in ha:
        lines.append(f"\n  {'持仓穿透':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        c = ha.get("concentration", {})
        lines.append(f"  {'Top1 集中度':<14} {c.get('top1_pct', '-'):>16}")
        lines.append(f"  {'Top5 集中度':<14} {c.get('top5_pct', '-'):>16}")
        lines.append(f"  {'Top10 集中度':<14} {c.get('top10_pct', '-'):>16}")
        lines.append(f"  {'HHI 指数':<14} {c.get('hhi', '-'):>16}")
        wv = ha.get("weighted_valuation")
        if wv:
            lines.append(f"  {'加权 PE':<14} {wv.get('weighted_pe', '-'):>16}")
            lines.append(f"  {'加权 PB':<14} {wv.get('weighted_pb', '-'):>16}")

    # 风险增强
    ra = analysis.get("risk_analysis")
    if ra and "error" not in ra:
        lines.append(f"\n  {'风险增强':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        if ra.get("sharpe") is not None:
            lines.append(f"  {'夏普比率':<14} {ra['sharpe']:>16}")
        if ra.get("volatility") is not None:
            lines.append(f"  {'波动率':<14} {ra['volatility']:>16}")
        if ra.get("max_drawdown") is not None:
            lines.append(f"  {'最大回撤':<14} {ra['max_drawdown']:>16}")
        if ra.get("information_ratio") is not None:
            lines.append(f"  {'信息比率':<14} {ra['information_ratio']:>16}")
        if ra.get("sortino_ratio") is not None:
            lines.append(f"  {'索提诺比率':<14} {ra['sortino_ratio']:>16}")
        if ra.get("downside_deviation") is not None:
            lines.append(f"  {'下行波动率':<14} {ra['downside_deviation']:>16}")
        if ra.get("calmar_ratio") is not None:
            lines.append(f"  {'卡玛比率':<14} {ra['calmar_ratio']:>16}")
        lines.append(f"  {'风险摘要':<14} {ra.get('risk_summary', '-'):>16}")

    # 回撤深度
    da = analysis.get("drawdown_analysis")
    if da and "error" not in da:
        lines.append(f"\n  {'回撤深度':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        lines.append(f"  {'最大回撤':<14} {da.get('max_drawdown_pct', '-'):>16}")
        lines.append(f"  {'回撤天数':<14} {da.get('max_drawdown_days', '-'):>16}")
        if da.get("recovery_days") is not None:
            lines.append(f"  {'恢复天数':<14} {da['recovery_days']:>16}")
        lines.append(f"  {'当前回撤':<14} {da.get('current_drawdown_pct', '-'):>16}")

    # 相关性
    ca = analysis.get("correlation_analysis")
    if ca and "error" not in ca:
        lines.append(f"\n  {'相关性分析':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        if ca.get("avg_correlation") is not None:
            lines.append(f"  {'平均相关系数':<14} {ca['avg_correlation']:>16}")
        lines.append(f"  {'分散化评价':<14} {ca.get('diversification_score', '-'):>16}")

    # 排名动态
    rk = analysis.get("rank_analysis")
    if rk and "error" not in rk:
        lines.append(f"\n  {'排名动态':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        lines.append(f"  {'当前分位':<14} {rk.get('current_percentile', '-'):>16}")
        lines.append(f"  {'趋势':<14} {rk.get('trend', '-'):>16}")
        lines.append(f"  {'最佳分位':<14} {rk.get('best_percentile', '-'):>16}")
        lines.append(f"  {'最差分位':<14} {rk.get('worst_percentile', '-'):>16}")

    # 估值分析（Index Hub）
    va = analysis.get("valuation_analysis")
    if va and "error" not in va:
        lines.append(f"\n  {'估值分析':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        if va.get("pe_ttm") is not None:
            lines.append(f"  {'PE(TTM)':<14} {va['pe_ttm']:>16}")
        if va.get("pe_percentile_5y") is not None:
            lines.append(f"  {'PE 5年分位':<14} {va['pe_percentile_5y']:>16}")
        if va.get("pb_lf") is not None:
            lines.append(f"  {'PB(LF)':<14} {va['pb_lf']:>16}")
        if va.get("pb_percentile_5y") is not None:
            lines.append(f"  {'PB 5年分位':<14} {va['pb_percentile_5y']:>16}")
        if va.get("ps_ttm") is not None:
            lines.append(f"  {'PS(TTM)':<14} {va['ps_ttm']:>16}")
        if va.get("ps_percentile_5y") is not None:
            lines.append(f"  {'PS 5年分位':<14} {va['ps_percentile_5y']:>16}")
        signal_map = {"low": "低估", "moderate": "适中", "high": "高估", "unknown": "未知"}
        lines.append(f"  {'估值信号':<14} {signal_map.get(va.get('valuation_signal'), '-'):>16}")

    # 资金流分析（Index Hub）
    cf = analysis.get("capital_flow_analysis")
    if cf and "error" not in cf:
        lines.append(f"\n  {'资金流分析':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        lines.append(f"  {'累计净流入(万)':<14} {cf.get('total_net_inflow', '-'):>16}")
        lines.append(f"  {'日均净流入(万)':<14} {cf.get('avg_daily_inflow', '-'):>16}")
        lines.append(f"  {'净流入天数':<14} {cf.get('inflow_days', '-'):>16}")
        lines.append(f"  {'净流出天数':<14} {cf.get('outflow_days', '-'):>16}")
        if cf.get("recent_1w_inflow") is not None:
            lines.append(f"  {'近1周净流入(万)':<14} {cf['recent_1w_inflow']:>16}")
        if cf.get("recent_1m_inflow") is not None:
            lines.append(f"  {'近1月净流入(万)':<14} {cf['recent_1m_inflow']:>16}")
        trend_map = {"inflow": "持续流入", "outflow": "持续流出", "mixed": "混合"}
        lines.append(f"  {'资金流向':<14} {trend_map.get(cf.get('flow_trend'), '-'):>16}")

    # ETFirst 增强分析
    ea = analysis.get("etfirst_analysis")
    if ea and "error" not in ea:
        val = ea.get("valuation")
        if val:
            lines.append(f"\n  {'估值(ETFirst)':<14} {'数值':>16}")
            lines.append(f"  {'-' * 32}")
            if val.get("pe") is not None:
                lines.append(f"  {'PE':<14} {val['pe']:>16}")
            if val.get("pe_percent") is not None:
                lines.append(f"  {'PE分位':<14} {val['pe_percent']:>16}")
            if val.get("pb") is not None:
                lines.append(f"  {'PB':<14} {val['pb']:>16}")
            if val.get("pb_percent") is not None:
                lines.append(f"  {'PB分位':<14} {val['pb_percent']:>16}")
            if val.get("dividend_yield") is not None:
                lines.append(f"  {'股息率':<14} {val['dividend_yield']:>16}")

        rr = ea.get("risk_return")
        if rr:
            lines.append(f"\n  {'风险收益(ETFirst)':<14} {'数值':>16}")
            lines.append(f"  {'-' * 32}")
            if rr.get("sharpe") is not None:
                lines.append(f"  {'夏普比率':<14} {rr['sharpe']:>16}")
            if rr.get("sharpe_rank") is not None:
                lines.append(f"  {'夏普排名':<14} {rr['sharpe_rank']:>16}")
            if rr.get("volatility") is not None:
                lines.append(f"  {'波动率':<14} {rr['volatility']:>16}")
            if rr.get("volatility_rank") is not None:
                lines.append(f"  {'波动率排名':<14} {rr['volatility_rank']:>16}")
            if rr.get("max_drawdown") is not None:
                lines.append(f"  {'最大回撤':<14} {rr['max_drawdown']:>16}")
            if rr.get("max_drawdown_rank") is not None:
                lines.append(f"  {'回撤排名':<14} {rr['max_drawdown_rank']:>16}")

        if ea.get("tracking_error") is not None:
            lines.append(f"\n  {'跟踪误差(ETFirst)':<14} {ea['tracking_error']:>16}")

        ind = ea.get("industry_distribution")
        if ind:
            lines.append(f"\n  {'行业分布(ETFirst)':<14}")
            for item in ind[:8]:
                w = safe_float(item.get("weight_pct"))
                w_txt = f"{w:.2f}" if w is not None else "-"
                lines.append(f"  {item.get('industry', '-'):<18} {w_txt:>10}%")

    lines.append(f"\n  数据时间: {analysis.get('timestamp', '-')}")
    return "\n".join(lines)
