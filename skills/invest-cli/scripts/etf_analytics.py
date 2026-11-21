#!/usr/bin/env python3
"""
ETF 深度分析模块 — 纯标准库实现，零第三方依赖。

输入：invest-cli fund/kline/quote 的 JSON 输出
输出：结构化分析结果（穿透/风险/资金流/相关性/回撤/排名）

设计原则：
- 只做计算，不做 I/O（数据由调用方传入）
- 纯标准库：statistics / math / json / csv
- 每个函数独立可测，不依赖全局状态
- 缺失数据返回 None 而非猜测
"""
from __future__ import annotations

import statistics
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════
# 1. 持仓穿透分析
# ═══════════════════════════════════════════════════════════════

def analyze_holdings(
    holdings: list[dict],
    quote_data: Optional[dict] = None,
) -> dict:
    """从持仓明细计算穿透指标。

    Args:
        holdings: fund 数据中的 holdings 列表，每项含 stock_name/ticker/hold_ratio
        quote_data: 可选，quote 行情数据（用于算加权 PE/PB）

    Returns:
        {
            "concentration": {  # 集中度
                "top1_pct": float, "top5_pct": float, "top10_pct": float,
                "hhi": float,  # 赫芬达尔指数
            },
            "industry_distribution": [  # 行业分布（如有）
                {"industry": str, "weight_pct": float}
            ],
            "weighted_valuation": {  # 加权估值（需 quote_data）
                "weighted_pe": float, "weighted_pb": float,
            },
            "holdings_count": int,
        }
    """
    if not holdings:
        return {"error": "no_holdings"}

    # 按占净值比排序（东财给的是 "9.99%" 字符串，必须经 _hold_ratio 归一）
    sorted_h = sorted(holdings, key=_hold_ratio, reverse=True)

    ratios = [_hold_ratio(h) for h in sorted_h]

    # 集中度
    top1 = ratios[0] if len(ratios) >= 1 else 0
    top5 = sum(ratios[:5])
    top10 = sum(ratios[:10])

    # HHI（赫芬达尔指数）
    hhi = sum((r / 100) ** 2 for r in ratios) * 10000 if ratios else 0

    result = {
        "concentration": {
            "top1_pct": round(top1, 2),
            "top5_pct": round(top5, 2),
            "top10_pct": round(top10, 2),
            "hhi": round(hhi, 2),
        },
        "holdings_count": len(holdings),
    }

    # 行业分布（如果 holdings 里有行业信息）
    industries = {}
    for h in holdings:
        ind = h.get("industry") or h.get("行业")
        if ind:
            # 同上：行业权重与集中度用**同一个**归一点。曾只修集中度那三行，
            # 这里的 `int + str` 在同一次调用里照样崩——修一半等于没修。
            w = _hold_ratio(h)
            industries[ind] = industries.get(ind, 0) + w
    if industries:
        result["industry_distribution"] = [
            {"industry": k, "weight_pct": round(v, 2)}
            for k, v in sorted(industries.items(), key=lambda x: -x[1])
        ]

    # 加权估值（需要 quote_data 提供 PE/PB）
    if quote_data and isinstance(quote_data, dict):
        pe_list = []
        pb_list = []
        for h in holdings:
            ticker = h.get("ticker") or h.get("thscode", "")
            ratio = _hold_ratio(h)
            q = quote_data.get(ticker) or quote_data.get(h.get("thscode", ""))
            if q:
                pe = q.get("pe") or q.get("市盈率")
                pb = q.get("pb") or q.get("市净率")
                if pe and ratio:
                    pe_list.append((pe, ratio))
                if pb and ratio:
                    pb_list.append((pb, ratio))
        if pe_list:
            total_w = sum(r for _, r in pe_list)
            result["weighted_valuation"] = {
                "weighted_pe": round(sum(pe * r for pe, r in pe_list) / total_w, 2),
            }
        if pb_list:
            total_w = sum(r for _, r in pb_list)
            result["weighted_valuation"]["weighted_pb"] = round(
                sum(pb * r for pb, r in pb_list) / total_w, 2
            )

    return result


# ═══════════════════════════════════════════════════════════════
# 2. 风险增强分析
# ═══════════════════════════════════════════════════════════════

def analyze_risk_enhanced(
    risk_data: dict,
    returns_data: Optional[dict] = None,
    data_dict: Optional[dict] = None,
    drawdown_result: Optional[dict] = None,
) -> dict:
    """从风险数据计算增强指标。

    同时适配两种数据源：
    - hithink 源：risk_data 英文键（sharpe_1y / max_drawdown_1y / volatility_1y）
    - ttskill 源：data_dict 中文键（夏普比率 / 最大回撤 / 波动率 / 卡玛比率）
    - kline 回撤：drawdown_result（当 ttskill 不提供最大回撤时从 kline 推算）

    Args:
        risk_data: fund 数据中的 risk 部分（英文键）
        returns_data: 可选，收益数据（用于算信息比率）
        data_dict: 可选，fund 数据的 data 部分（中文键，ttskill 深取）
        drawdown_result: 可选，回撤深度分析结果（提供最大回撤）

    Returns:
        {
            "sharpe": float | None,
            "volatility": float | None,
            "max_drawdown": float | None,
            "information_ratio": float | None,
            "sortino_ratio": float | None,
            "downside_deviation": float | None,
            "calmar_ratio": float | None,
            "risk_summary": str,
        }
    """
    # 合并三个数据源，优先级：ttskill 中文键 > hithink 英文键 > kline 回撤
    merged = {}
    if risk_data:
        merged.update(risk_data)
    if data_dict:
        key_map = {
            "夏普比率": "sharpe_1y",
            "最大回撤": "max_drawdown_1y",
            "波动率": "volatility_1y",
            "卡玛比率": "calmar_ratio",
            "信息比率": "information_ratio",
        }
        for cn_key, en_key in key_map.items():
            val = data_dict.get(cn_key)
            if val is not None and val != "" and str(val) != "None":
                if en_key not in merged or merged[en_key] is None:
                    merged[en_key] = val
    # 从 kline 回撤结果补最大回撤（ttskill 不提供时）
    if drawdown_result and (merged.get("max_drawdown_1y") is None):
        dd = drawdown_result.get("max_drawdown_pct")
        if dd is not None:
            merged["max_drawdown_1y"] = dd

    if not merged:
        return {"error": "no_risk_data"}

    sharpe = merged.get("sharpe_1y")
    max_dd = merged.get("max_drawdown_1y")
    volatility = merged.get("volatility_1y")
    calmar = merged.get("calmar_ratio")
    info_ratio = merged.get("information_ratio")

    result = {}

    # 基础指标直接透传
    if sharpe is not None:
        try:
            result["sharpe"] = round(float(sharpe), 4)
        except (ValueError, TypeError):
            pass
    if volatility is not None:
        try:
            result["volatility"] = round(float(volatility), 2)
        except (ValueError, TypeError):
            pass
    if max_dd is not None:
        try:
            result["max_drawdown"] = round(float(max_dd), 2)
        except (ValueError, TypeError):
            pass

    # 信息比率
    if info_ratio is not None:
        try:
            result["information_ratio"] = round(float(info_ratio), 4)
        except (ValueError, TypeError):
            pass

    # 索提诺比率 = (收益 - 无风险利率) / |最大回撤|
    if returns_data and max_dd is not None:
        fund_ret = returns_data.get("year") or returns_data.get("近1年回报")
        if fund_ret is not None:
            try:
                fund_ret = float(fund_ret)
                max_dd_val = float(max_dd)
                rf = 2.0
                downside = abs(max_dd_val)
                if downside > 0:
                    result["sortino_ratio"] = round((fund_ret - rf) / downside, 4)
            except (ValueError, TypeError):
                pass

    # 下行波动率
    if max_dd is not None:
        try:
            result["downside_deviation"] = round(abs(float(max_dd)), 2)
        except (ValueError, TypeError):
            pass

    # 卡玛比率
    if calmar is not None:
        try:
            result["calmar_ratio"] = round(float(calmar), 4)
        except (ValueError, TypeError):
            pass

    # 风险摘要
    parts = []
    if sharpe is not None:
        try:
            sharpe_val = float(sharpe)
            if sharpe_val > 1:
                parts.append("夏普优秀")
            elif sharpe_val > 0.5:
                parts.append("夏普良好")
            else:
                parts.append("夏普偏低")
        except (ValueError, TypeError):
            pass
    if max_dd is not None:
        try:
            max_dd_val = float(max_dd)
            if abs(max_dd_val) < 20:
                parts.append("回撤可控")
            elif abs(max_dd_val) < 30:
                parts.append("回撤中等")
            else:
                parts.append("回撤较大")
        except (ValueError, TypeError):
            pass
    if volatility is not None:
        try:
            vol_val = float(volatility)
            if vol_val < 15:
                parts.append("低波动")
            elif vol_val < 25:
                parts.append("中等波动")
            else:
                parts.append("高波动")
        except (ValueError, TypeError):
            pass
    result["risk_summary"] = "；".join(parts) if parts else "数据不足"

    return result


# ═══════════════════════════════════════════════════════════════
# 3. 资金流推算
# ═══════════════════════════════════════════════════════════════

def estimate_fund_flow(
    nav_history: list[dict],
    scale_history: list[dict],
) -> dict:
    """从历史净值和规模推算份额变动。

    Args:
        nav_history: [{"date": str, "nav": float}, ...]
        scale_history: [{"date": str, "scale": float}, ...]  # 单位：元

    Returns:
        {
            "share_change_pct": float | None,  # 份额变动百分比
            "flow_direction": str,  # "inflow" / "outflow" / "stable"
            "avg_daily_flow": float | None,  # 日均申赎金额（万元）
            "flow_volatility": float | None,  # 申赎波动率
        }
    """
    if not nav_history or not scale_history:
        return {"error": "insufficient_data"}

    # 按日期对齐
    nav_map = {item["date"]: item["nav"] for item in nav_history if "date" in item and "nav" in item}
    scale_map = {item["date"]: item["scale"] for item in scale_history if "date" in item and "scale" in item}

    common_dates = sorted(set(nav_map.keys()) & set(scale_map.keys()))
    if len(common_dates) < 2:
        return {"error": "insufficient_overlap"}

    # 计算每日份额 = 规模 / 净值
    shares = []
    for d in common_dates:
        nav = nav_map[d]
        scale = scale_map[d]
        if nav > 0 and scale > 0:
            shares.append({"date": d, "shares": scale / nav})

    if len(shares) < 2:
        return {"error": "insufficient_shares"}

    # 份额变动
    first_shares = shares[0]["shares"]
    last_shares = shares[-1]["shares"]
    if first_shares > 0:
        share_change_pct = (last_shares - first_shares) / first_shares * 100
    else:
        share_change_pct = None

    # 日均申赎金额
    daily_flows = []
    for i in range(1, len(shares)):
        share_diff = shares[i]["shares"] - shares[i - 1]["shares"]
        nav = nav_map[shares[i]["date"]]
        daily_flows.append(share_diff * nav)

    avg_daily_flow = statistics.mean(daily_flows) if daily_flows else None
    flow_volatility = statistics.stdev(daily_flows) if len(daily_flows) > 1 else None

    # 判断方向
    if share_change_pct is not None:
        if share_change_pct > 5:
            flow_direction = "inflow"
        elif share_change_pct < -5:
            flow_direction = "outflow"
        else:
            flow_direction = "stable"
    else:
        flow_direction = "unknown"

    return {
        "share_change_pct": round(share_change_pct, 2) if share_change_pct is not None else None,
        "flow_direction": flow_direction,
        "avg_daily_flow": round(avg_daily_flow / 1e4, 2) if avg_daily_flow else None,  # 万元
        "flow_volatility": round(flow_volatility / 1e4, 2) if flow_volatility else None,
    }


# ═══════════════════════════════════════════════════════════════
# 4. 相关性分析
# ═══════════════════════════════════════════════════════════════

def analyze_correlation(
    kline_data: dict[str, list[dict]],
) -> dict:
    """多标的 K 线相关性分析。

    Args:
        kline_data: {"标的代码": [{"date": str, "close": float}, ...], ...}

    Returns:
        {
            "correlation_matrix": {  # 相关系数矩阵
                "code1": {"code2": float, ...},
            },
            "avg_correlation": float,  # 平均相关系数
            "diversification_score": str,  # 分散化评价
        }
    """
    if not kline_data or len(kline_data) < 2:
        return {"error": "need_at_least_2_assets"}

    # 提取收盘价序列
    close_series = {}
    for code, rows in kline_data.items():
        closes = []
        for r in rows:
            c = r.get("close") or r.get("收")
            if c is not None:
                closes.append(float(c))
        if len(closes) >= 2:
            close_series[code] = closes

    if len(close_series) < 2:
        return {"error": "insufficient_close_data"}

    # 计算日收益率
    returns = {}
    for code, closes in close_series.items():
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
        if rets:
            returns[code] = rets

    codes = sorted(returns.keys())
    if len(codes) < 2:
        return {"error": "insufficient_returns"}

    # 皮尔逊相关系数
    def pearson(x: list[float], y: list[float]) -> Optional[float]:
        n = min(len(x), len(y))
        if n < 2:
            return None
        x = x[:n]
        y = y[:n]
        mx = statistics.mean(x)
        my = statistics.mean(y)
        sx = statistics.stdev(x)
        sy = statistics.stdev(y)
        if sx == 0 or sy == 0:
            return None
        cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / (n - 1)
        return cov / (sx * sy)

    matrix = {}
    correlations = []
    for i, c1 in enumerate(codes):
        matrix[c1] = {}
        for c2 in codes[i + 1:]:
            r = pearson(returns[c1], returns[c2])
            if r is not None:
                matrix[c1][c2] = round(r, 4)
                correlations.append(r)

    avg_corr = statistics.mean(correlations) if correlations else None

    # 分散化评价
    if avg_corr is not None:
        if avg_corr < 0.3:
            div_score = "优秀（低相关，分散化效果好）"
        elif avg_corr < 0.6:
            div_score = "良好（中等相关）"
        elif avg_corr < 0.8:
            div_score = "一般（高相关，分散化效果有限）"
        else:
            div_score = "较差（高度相关，分散化效果差）"
    else:
        div_score = "数据不足"

    return {
        "correlation_matrix": matrix,
        "avg_correlation": round(avg_corr, 4) if avg_corr is not None else None,
        "diversification_score": div_score,
    }


# ═══════════════════════════════════════════════════════════════
# 5. 回撤深度分析
# ═══════════════════════════════════════════════════════════════

def analyze_drawdown(kline_rows: list[dict]) -> dict:
    """从 K 线数据计算回撤深度。

    Args:
        kline_rows: [{"date": str, "close": float}, ...]

    Returns:
        {
            "max_drawdown_pct": float,  # 最大回撤百分比
            "max_drawdown_days": int,  # 最大回撤持续天数
            "recovery_days": int | None,  # 恢复天数
            "current_drawdown_pct": float,  # 当前回撤
            "drawdown_history": [  # 回撤历史
                {"peak_date": str, "trough_date": str, "depth_pct": float, "days": int},
            ],
        }
    """
    if not kline_rows or len(kline_rows) < 2:
        return {"error": "insufficient_kline"}

    # 提取收盘价
    closes = []
    dates = []
    for r in kline_rows:
        c = r.get("close") or r.get("收")
        d = r.get("date") or r.get("日期")
        if c is not None and d:
            closes.append(float(c))
            dates.append(d)

    if len(closes) < 2:
        return {"error": "insufficient_close"}

    # 计算回撤序列
    peak = closes[0]
    max_dd = 0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0
    current_dd_peak_idx = 0

    drawdown_history = []
    in_drawdown = False
    dd_start_idx = 0
    dd_trough_idx = 0
    dd_trough_val = closes[0]

    for i, c in enumerate(closes):
        if c > peak:
            # 新高，结束当前回撤（用本段真实谷底，而非恢复前一天）
            if in_drawdown:
                dd_depth = (dd_trough_val - peak) / peak * 100
                drawdown_history.append({
                    "peak_date": dates[dd_start_idx],
                    "trough_date": dates[dd_trough_idx],
                    "depth_pct": round(dd_depth, 2),
                    "days": dd_trough_idx - dd_start_idx,
                })
                in_drawdown = False
            peak = c
            current_dd_peak_idx = i
        else:
            dd = (c - peak) / peak * 100
            if dd < max_dd:
                max_dd = dd
                max_dd_peak_idx = current_dd_peak_idx
                max_dd_trough_idx = i
            if not in_drawdown and dd < 0:
                in_drawdown = True
                dd_start_idx = current_dd_peak_idx
                dd_trough_idx = i
                dd_trough_val = c
            elif in_drawdown and c < dd_trough_val:
                dd_trough_idx = i
                dd_trough_val = c

    # 最后一个回撤
    if in_drawdown:
        dd_depth = (dd_trough_val - peak) / peak * 100
        drawdown_history.append({
            "peak_date": dates[dd_start_idx],
            "trough_date": dates[dd_trough_idx],
            "depth_pct": round(dd_depth, 2),
            "days": dd_trough_idx - dd_start_idx,
        })

    # 恢复天数：从最大回撤谷底起首次重新站上该段前高所需天数；未回本为 None
    recovery_days = None
    if max_dd < 0:
        max_peak_val = closes[max_dd_peak_idx]
        for j in range(max_dd_trough_idx + 1, len(closes)):
            if closes[j] >= max_peak_val:
                recovery_days = j - max_dd_trough_idx
                break

    # 当前回撤
    current_dd = (closes[-1] - peak) / peak * 100

    return {
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_days": max_dd_trough_idx - max_dd_peak_idx if max_dd < 0 else 0,
        "recovery_days": recovery_days,
        "current_drawdown_pct": round(current_dd, 2),
        "drawdown_history": sorted(drawdown_history, key=lambda x: x["depth_pct"])[:5],
    }


# ═══════════════════════════════════════════════════════════════
# 6. 同类排名动态
# ═══════════════════════════════════════════════════════════════

def analyze_rank_dynamics(rank_history: list[dict]) -> dict:
    """同类排名变化趋势。

    支持任意数量的排名数据点（1 个也能给出当前分位）。
    2 个点可判断方向，3 个及以上可判断趋势。

    Args:
        rank_history: [{"period": str, "rank": int, "total": int}, ...]

    Returns:
        {
            "current_percentile": float,
            "trend": str,  # "improving" / "declining" / "stable" / "insufficient_data"
            "trend_strength": str,  # "strong" / "moderate" / "weak" / "unknown"
            "volatility": float,
            "best_percentile": float,
            "worst_percentile": float,
            "data_points": int,
        }
    """
    if not rank_history:
        return {"error": "no_rank_data"}

    percentiles = []
    for item in rank_history:
        rank = item.get("rank")
        total = item.get("total")
        if rank is not None and total and total > 0:
            percentiles.append(rank / total * 100)

    if not percentiles:
        return {"error": "no_valid_ranks"}

    current = percentiles[-1]
    best = min(percentiles)
    worst = max(percentiles)
    data_points = len(percentiles)

    # 趋势判断
    if len(percentiles) >= 3:
        # 比较前半段和后半段的均值，避免 [:3] 与 [-3:] 在 3 个点时重叠
        mid = len(percentiles) // 2
        older = statistics.mean(percentiles[:mid])
        recent = statistics.mean(percentiles[mid:])
        diff = recent - older
        if diff < -10:
            trend = "improving"
        elif diff > 10:
            trend = "declining"
        else:
            trend = "stable"
        trend_strength = "strong" if abs(diff) > 20 else "moderate" if abs(diff) > 10 else "weak"
    elif len(percentiles) == 2:
        diff = percentiles[-1] - percentiles[0]
        if diff < -5:
            trend = "improving"
        elif diff > 5:
            trend = "declining"
        else:
            trend = "stable"
        trend_strength = "weak"  # 只有 2 个点，趋势强度有限
    else:
        trend = "insufficient_data"
        trend_strength = "unknown"

    # 波动率
    volatility = statistics.stdev(percentiles) if len(percentiles) > 1 else 0

    return {
        "current_percentile": round(current, 2),
        "trend": trend,
        "trend_strength": trend_strength,
        "volatility": round(volatility, 2),
        "best_percentile": round(best, 2),
        "worst_percentile": round(worst, 2),
        "data_points": data_points,
    }


# ═══════════════════════════════════════════════════════════════
# 7. 资金流分析（Index Hub 数据）
# ═══════════════════════════════════════════════════════════════

def analyze_capital_flow(scale_data: list[dict]) -> dict:
    """从 Index Hub 规模变动数据推算资金流向。

    Args:
        scale_data: etf/etf-scale 响应的 data 列表，每项含 date、fundScale、netInflow 等

    Returns:
        {
            "total_net_inflow": float,  # 累计净流入（万元）
            "avg_daily_inflow": float,  # 日均净流入（万元）
            "inflow_days": int,  # 净流入天数
            "outflow_days": int,  # 净流出天数
            "flow_trend": str,  # "inflow" / "outflow" / "mixed"
            "recent_1m_inflow": float,  # 近 1 月净流入（万元）
            "recent_1w_inflow": float,  # 近 1 周净流入（万元）
        }
    """
    if not scale_data or not isinstance(scale_data, list):
        return {"error": "no_scale_data"}

    # 按日期排序
    sorted_data = sorted(scale_data, key=lambda x: x.get("date", ""), reverse=True)
    if not sorted_data:
        return {"error": "no_valid_dates"}

    # 提取净流入数据
    inflows = []
    for item in sorted_data:
        ni = item.get("netInflow")
        if ni is not None:
            try:
                inflows.append(float(ni))
            except (ValueError, TypeError):
                pass

    if not inflows:
        return {"error": "no_inflow_data"}

    total = sum(inflows)
    avg = statistics.mean(inflows)
    inflow_days = sum(1 for x in inflows if x > 0)
    outflow_days = sum(1 for x in inflows if x < 0)

    # 近期资金流
    recent_1w = sum(inflows[:5]) if len(inflows) >= 5 else None
    recent_1m = sum(inflows[:22]) if len(inflows) >= 22 else None

    # 趋势判断
    if total > 0 and inflow_days > outflow_days:
        trend = "inflow"
    elif total < 0 and outflow_days > inflow_days:
        trend = "outflow"
    else:
        trend = "mixed"

    return {
        "total_net_inflow": round(total / 1e4, 2),  # 万元
        "avg_daily_inflow": round(avg / 1e4, 2),
        "inflow_days": inflow_days,
        "outflow_days": outflow_days,
        "flow_trend": trend,
        "recent_1w_inflow": round(recent_1w / 1e4, 2) if recent_1w is not None else None,
        "recent_1m_inflow": round(recent_1m / 1e4, 2) if recent_1m is not None else None,
    }


# ═══════════════════════════════════════════════════════════════
# 8. 估值分析（Index Hub 数据）
# ═══════════════════════════════════════════════════════════════

def analyze_valuation(detail_data: dict) -> dict:
    """从 Index Hub 详情数据提取估值指标。

    Args:
        detail_data: etf/detail 响应的 data[0]，含 PETtm、PETtm5Y、PBLf、PBLf5Y 等

    Returns:
        {
            "pe_ttm": float | None,
            "pe_percentile_5y": float | None,
            "pb_lf": float | None,
            "pb_percentile_5y": float | None,
            "ps_ttm": float | None,
            "ps_percentile_5y": float | None,
            "valuation_signal": str,  # "low" / "moderate" / "high" / "unknown"
        }
    """
    if not detail_data or not isinstance(detail_data, dict):
        return {"error": "no_detail_data"}

    detail = detail_data.get("detail", detail_data)

    def _get_val(*keys):
        for k in keys:
            v = detail.get(k)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return None

    pe = _get_val("PETtm", "peTtm")
    pe_pct = _get_val("PETtm5Y", "peTtm5Y")
    pb = _get_val("PBLf", "pbLf")
    pb_pct = _get_val("PBLf5Y", "pbLf5Y")
    ps = _get_val("PSTtm", "psTtm")
    ps_pct = _get_val("PSTtm5Y", "psTtm5Y")

    # 估值信号
    signals = []
    for pct in [pe_pct, pb_pct, ps_pct]:
        if pct is not None:
            if pct < 20:
                signals.append("low")
            elif pct > 80:
                signals.append("high")
            else:
                signals.append("moderate")

    if signals:
        # 取最保守的判断
        if "high" in signals:
            valuation_signal = "high"
        elif "low" in signals:
            valuation_signal = "low"
        else:
            valuation_signal = "moderate"
    else:
        valuation_signal = "unknown"

    return {
        "pe_ttm": round(pe, 2) if pe is not None else None,
        "pe_percentile_5y": round(pe_pct, 2) if pe_pct is not None else None,
        "pb_lf": round(pb, 2) if pb is not None else None,
        "pb_percentile_5y": round(pb_pct, 2) if pb_pct is not None else None,
        "ps_ttm": round(ps, 2) if ps is not None else None,
        "ps_percentile_5y": round(ps_pct, 2) if ps_pct is not None else None,
        "valuation_signal": valuation_signal,
    }


# ═══════════════════════════════════════════════════════════════
# 9. ETFirst 增强分析
# ═══════════════════════════════════════════════════════════════

def analyze_etfirst_enhanced(etfirst_data: dict) -> dict:
    """从 ETFirst etf-detail 响应中提取增强指标。

    Args:
        etfirst_data: etf-detail all 的 results 字段

    Returns:
        {
            "valuation": {  # 估值分位
                "pe": float, "pe_percent": float,
                "pb": float, "pb_percent": float,
                "dividend_yield": float,
            },
            "risk_return": {  # 风险收益特征（近1年）
                "sharpe": float, "sharpe_rank": float,
                "volatility": float, "volatility_rank": float,
                "max_drawdown": float, "max_drawdown_rank": float,
            },
            "tracking_error": float,  # 跟踪误差（%）
            "wind_rank": [  # Wind 排名
                {"period": str, "rank": str, "percentile": str},
            ],
            "industry_distribution": [  # 行业分布
                {"industry": str, "weight_pct": float},
            ],
        }
    """
    if not etfirst_data or not isinstance(etfirst_data, dict):
        return {"error": "no_etfirst_data"}

    results = etfirst_data.get("results", etfirst_data)
    if not results:
        return {"error": "no_etfirst_results"}
    if not isinstance(results, dict):
        # 上游 schema 变化时会回 `{"results": [...]}`（列表）。旧实现直接
        # `results.get(...)` → AttributeError，把一个可降级的数据源变成
        # 整条命令的 traceback。形状不是字典就当作拿不到，返回明确错误。
        return {"error": f"etfirst results 形状异常: {type(results).__name__}"}

    result = {}

    # 估值数据（从 getMarketIndicatorData 提取）
    market_data = results.get("getMarketIndicatorData", {})
    if market_data:
        result["valuation"] = {
            "pe": _safe_float(market_data.get("pe")),
            "pe_percent": _safe_float(market_data.get("pePercent")),
            "pb": _safe_float(market_data.get("pb")),
            "pb_percent": _safe_float(market_data.get("pbPercent")),
            "dividend_yield": _safe_float(market_data.get("dp")),
        }

    # 风险收益特征（从 getRiskReturnCharacter 提取，取近1年）
    risk_data = results.get("getRiskReturnCharacter", {})
    if risk_data:
        # 可能是列表或字典
        if isinstance(risk_data, list):
            for item in risk_data:
                if item.get("dateRange") == 12:  # 近1年
                    result["risk_return"] = {
                        "sharpe": _safe_float(item.get("sharpeRatio")),
                        "sharpe_rank": _safe_float(item.get("rankSharpeRatio")),
                        "volatility": _safe_float(item.get("standardDeviation")),
                        "volatility_rank": _safe_float(item.get("rankStandardDeviation")),
                        "max_drawdown": _safe_float(item.get("maximumBack")),
                        "max_drawdown_rank": _safe_float(item.get("rankMaximumBack")),
                    }
                    break
        elif isinstance(risk_data, dict):
            result["risk_return"] = {
                "sharpe": _safe_float(risk_data.get("sharpeRatio")),
                "sharpe_rank": _safe_float(risk_data.get("rankSharpeRatio")),
                "volatility": _safe_float(risk_data.get("standardDeviation")),
                "volatility_rank": _safe_float(risk_data.get("rankStandardDeviation")),
                "max_drawdown": _safe_float(risk_data.get("maximumBack")),
                "max_drawdown_rank": _safe_float(risk_data.get("rankMaximumBack")),
            }

    # 跟踪误差
    if market_data and market_data.get("trackError") is not None:
        result["tracking_error"] = _safe_float(market_data.get("trackError"))

    # Wind 排名
    wind_rank = results.get("getProductWindRank", [])
    if wind_rank and isinstance(wind_rank, list):
        result["wind_rank"] = [
            {
                "period": item.get("period", ""),
                "rank": item.get("rank", ""),
                "percentile": item.get("percentile", ""),
            }
            for item in wind_rank[:5]  # 最多取5条
        ]

    # 行业分布
    industry_data = results.get("getIndustryDistribution", {})
    if industry_data and isinstance(industry_data, dict):
        # 取一级行业
        first_industry = industry_data.get("firstWeightList", industry_data.get("first", []))
        if first_industry and isinstance(first_industry, list):
            result["industry_distribution"] = [
                {
                    "industry": item.get("industryName", ""),
                    "weight_pct": _safe_float(item.get("industryRatio", item.get("weight", 0))),
                }
                for item in first_industry[:10]
            ]

    return result


def _safe_float(val: Any) -> Optional[float]:
    """安全转 float，失败返回 None。

    必须处理**带单位的百分数字符串**：东财的持仓字段是 `"占净值比例": "9.99%"`，
    不是数字。旧实现直接 `float(val)` → ValueError；调用方 analyze_holdings 又
    拿它 `sum()`/`sorted()`，于是 `fund --analytics` 在东财回落路径上直接
    `TypeError: unsupported operand type(s) for +: 'int' and 'str'` 崩给用户
    （主源 hithink/ttskill 都挂掉才会走这条路，属可达路径）。

    统一在这里处理：百分号、千位分隔符、常见非数值哨兵一律归一，
    「取不到」和「不是数」都返回 None，让上层走既有的缺失分支。
    """
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("，", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    if not s or s in ("-", "--", "—", "N/A", "n/a", "null", "None", "无", "暂无"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _hold_ratio(h: dict) -> float:
    """持仓权重（百分数，如 9.99 表示 9.99%）；取不到记 0。

    为什么不直接 `h.get("hold_ratio", h.get("占净值比例", 0))`：东财给的是
    带 % 的字符串，直接参与排序/求和必崩。统一收口到一个转换点，
    就不必在每个消费处各写一遍防护。
    """
    raw = h.get("hold_ratio")
    if raw is None:
        raw = h.get("占净值比例")
    val = _safe_float(raw)
    return val if val is not None else 0.0


# ═══════════════════════════════════════════════════════════════
# 主入口：综合分析
# ═══════════════════════════════════════════════════════════════

def analyze_etf(
    fund_data: dict,
    kline_data: Optional[list[dict]] = None,
    quote_data: Optional[dict] = None,
    multi_kline: Optional[dict[str, list[dict]]] = None,
    index_hub_data: Optional[dict] = None,
    etfirst_data: Optional[dict] = None,
) -> dict:
    """ETF 综合分析主入口。

    Args:
        fund_data: invest-cli fund 的 JSON 输出
        kline_data: 可选，该 ETF 的 K 线数据
        quote_data: 可选，持仓股的行情数据
        multi_kline: 可选，多标的 K 线（用于相关性分析）
        index_hub_data: 可选，Index Hub API 返回的数据（detail/holdings/scale/quote）
        etfirst_data: 可选，ETFirst CLI 返回的数据（etf-detail all 的 results）

    Returns:
        综合分析结果
    """
    result = {
        "fund_code": fund_data.get("code"),
        "fund_name": fund_data.get("name"),
        "timestamp": fund_data.get("timestamp"),
    }

    # 1. 持仓穿透
    holdings = fund_data.get("holdings") or []
    if holdings:
        result["holdings_analysis"] = analyze_holdings(holdings, quote_data)

    # 2. 回撤深度（需在风险增强之前，风险增强依赖最大回撤）
    if kline_data:
        result["drawdown_analysis"] = analyze_drawdown(kline_data)

    # 3. 风险增强（依赖回撤深度结果）
    risk = fund_data.get("risk") or {}
    returns = fund_data.get("returns") or {}
    data_dict = fund_data.get("data") or {}
    drawdown_result = result.get("drawdown_analysis")
    if risk or data_dict:
        result["risk_analysis"] = analyze_risk_enhanced(risk, returns, data_dict, drawdown_result)

    # 4. 相关性分析
    if multi_kline:
        result["correlation_analysis"] = analyze_correlation(multi_kline)

    # 5. 同类排名
    data = fund_data.get("data") or {}
    rank_1y = data.get("近1年同类分位")
    rank_3y = data.get("近3年同类分位")
    if rank_1y or rank_3y:
        rank_history = []
        # 按时间从短到长排列，便于趋势判断
        for period_key, label in [("近1月同类分位", "近1月"), ("近3月同类分位", "近3月"),
                                   ("近6月同类分位", "近6月"), ("近1年同类分位", "近1年"),
                                   ("近2年同类分位", "近2年"), ("近3年同类分位", "近3年"),
                                   ("近5年同类分位", "近5年"), ("成立来同类分位", "成立来")]:
            val = data.get(period_key)
            if val:
                try:
                    r, t = str(val).split("/")
                    rank_history.append({"period": label, "rank": int(r), "total": int(t)})
                except (ValueError, AttributeError):
                    pass
        if rank_history:
            result["rank_analysis"] = analyze_rank_dynamics(rank_history)

    # 6. Index Hub 增强分析
    if index_hub_data and isinstance(index_hub_data, dict):
        # 6a. 估值分析
        ih_detail = index_hub_data.get("detail")
        if ih_detail:
            result["valuation_analysis"] = analyze_valuation(ih_detail)

        # 6b. 资金流分析
        ih_scale = index_hub_data.get("scale")
        if ih_scale and isinstance(ih_scale, list):
            result["capital_flow_analysis"] = analyze_capital_flow(ih_scale)

    # 7. ETFirst 增强分析
    if etfirst_data and isinstance(etfirst_data, dict):
        result["etfirst_analysis"] = analyze_etfirst_enhanced(etfirst_data)

    return result


def format_terminal(analysis: dict) -> str:
    """格式化终端输出（实现已下沉至 _etf_render.py）。"""
    from _etf_render import format_terminal as _render

    return _render(analysis, _safe_float)
