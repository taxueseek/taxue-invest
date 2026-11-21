#!/usr/bin/env python3
"""etf_analytics 单元测试 — 纯标准库，零第三方依赖。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from etf_analytics import (
    analyze_holdings,
    analyze_risk_enhanced,
    analyze_drawdown,
    analyze_correlation,
    analyze_rank_dynamics,
    estimate_fund_flow,
    analyze_capital_flow,
    analyze_valuation,
    analyze_etfirst_enhanced,
    analyze_etf,
    format_terminal,
)


class TestAnalyzeHoldings(unittest.TestCase):
    def test_basic_concentration(self):
        holdings = [
            {"stock_name": "A", "ticker": "000001", "hold_ratio": 10},
            {"stock_name": "B", "ticker": "000002", "hold_ratio": 8},
            {"stock_name": "C", "ticker": "000003", "hold_ratio": 5},
        ]
        result = analyze_holdings(holdings)
        self.assertEqual(result["concentration"]["top1_pct"], 10)
        self.assertAlmostEqual(result["concentration"]["top5_pct"], 23)
        self.assertEqual(result["holdings_count"], 3)

    def test_empty_holdings(self):
        result = analyze_holdings([])
        self.assertEqual(result["error"], "no_holdings")

    def test_hhi_calculation(self):
        holdings = [{"stock_name": "A", "hold_ratio": 50}, {"stock_name": "B", "hold_ratio": 50}]
        result = analyze_holdings(holdings)
        self.assertEqual(result["concentration"]["hhi"], 5000)

    def test_chinese_field_names(self):
        holdings = [
            {"stock_name": "A", "占净值比例": 15},
            {"stock_name": "B", "占净值比例": 10},
        ]
        result = analyze_holdings(holdings)
        self.assertEqual(result["concentration"]["top1_pct"], 15)


class TestAnalyzeRiskEnhanced(unittest.TestCase):
    def test_basic_risk(self):
        risk = {"sharpe_1y": 1.2, "max_drawdown_1y": -15, "volatility_1y": 18}
        returns = {"year": 12}
        result = analyze_risk_enhanced(risk, returns)
        self.assertIn("risk_summary", result)
        self.assertIn("夏普优秀", result["risk_summary"])

    def test_no_risk_data(self):
        result = analyze_risk_enhanced({})
        self.assertEqual(result["error"], "no_risk_data")

    def test_sortino_calculation(self):
        risk = {"max_drawdown_1y": -20}
        returns = {"year": 10}
        result = analyze_risk_enhanced(risk, returns)
        self.assertAlmostEqual(result["sortino_ratio"], 0.4)

    def test_null_risk_fields(self):
        risk = {"sharpe_1y": None, "max_drawdown_1y": None, "volatility_1y": None}
        result = analyze_risk_enhanced(risk, {})
        self.assertEqual(result["risk_summary"], "数据不足")

    def test_ttskill_chinese_keys(self):
        """ttskill 深取返回的中文键名应被正确识别。"""
        risk = {"max_drawdown_1y": None, "max_drawdown_3y": None}
        returns = {"year": 5.59}
        data_dict = {"夏普比率": 0.1369, "最大回撤": None, "波动率": 29.8704, "卡玛比率": 0.22}
        result = analyze_risk_enhanced(risk, returns, data_dict)
        self.assertEqual(result["sharpe"], 0.1369)
        self.assertEqual(result["volatility"], 29.87)
        self.assertEqual(result["calmar_ratio"], 0.22)

    def test_drawdown_from_kline(self):
        """ttskill 不提供最大回撤时，从 kline 回撤结果推算。"""
        risk = {"max_drawdown_1y": None}
        returns = {"year": 5.59}
        data_dict = {"夏普比率": 0.1369, "最大回撤": None, "波动率": 29.8704}
        drawdown_result = {"max_drawdown_pct": -25.33}
        result = analyze_risk_enhanced(risk, returns, data_dict, drawdown_result)
        self.assertEqual(result["max_drawdown"], -25.33)
        self.assertAlmostEqual(result["sortino_ratio"], 0.1417, places=3)
        self.assertEqual(result["downside_deviation"], 25.33)

    def test_full_risk_pipeline(self):
        """完整数据流：ttskill 中文键 + kline 回撤 → 全指标输出。"""
        risk = {"max_drawdown_1y": None, "max_drawdown_3y": None, "drawdowns": {}}
        returns = {"year": 5.59}
        data_dict = {"夏普比率": 0.1369, "最大回撤": None, "波动率": 29.8704, "卡玛比率": 0.22, "信息比率": None}
        drawdown_result = {"max_drawdown_pct": -25.33, "max_drawdown_days": 54}
        result = analyze_risk_enhanced(risk, returns, data_dict, drawdown_result)
        self.assertEqual(result["sharpe"], 0.1369)
        self.assertEqual(result["volatility"], 29.87)
        self.assertEqual(result["max_drawdown"], -25.33)
        self.assertAlmostEqual(result["sortino_ratio"], 0.1417, places=3)
        self.assertEqual(result["downside_deviation"], 25.33)
        self.assertEqual(result["calmar_ratio"], 0.22)
        self.assertIn("夏普偏低", result["risk_summary"])
        self.assertIn("高波动", result["risk_summary"])


class TestAnalyzeDrawdown(unittest.TestCase):
    def test_basic_drawdown(self):
        kline = [
            {"date": "2026-01-01", "close": 100},
            {"date": "2026-01-02", "close": 110},
            {"date": "2026-01-03", "close": 90},
            {"date": "2026-01-04", "close": 95},
        ]
        result = analyze_drawdown(kline)
        self.assertEqual(result["max_drawdown_pct"], -18.18)
        self.assertEqual(result["max_drawdown_days"], 1)

    def test_insufficient_data(self):
        result = analyze_drawdown([])
        self.assertEqual(result["error"], "insufficient_kline")

    def test_chinese_field_names(self):
        kline = [
            {"日期": "2026-01-01", "收": 100},
            {"日期": "2026-01-02", "收": 80},
        ]
        result = analyze_drawdown(kline)
        self.assertEqual(result["max_drawdown_pct"], -20)

    def test_recovery_days(self):
        kline = [
            {"date": "2026-01-01", "close": 100},
            {"date": "2026-01-02", "close": 80},
            {"date": "2026-01-03", "close": 100},
        ]
        result = analyze_drawdown(kline)
        self.assertEqual(result["recovery_days"], 1)

    def test_drawdown_history_uses_actual_trough_and_stops_at_recovery(self):
        kline = [
            {"date": "2026-01-01", "close": 100},
            {"date": "2026-01-02", "close": 60},   # 真实谷底 -40%
            {"date": "2026-01-03", "close": 95},   # 恢复前一天（旧实现误用它）
            {"date": "2026-01-04", "close": 105},  # 创新高，第 2 天回本
            {"date": "2026-01-05", "close": 110},
        ]
        result = analyze_drawdown(kline)
        self.assertEqual(result["recovery_days"], 2)
        self.assertEqual(result["drawdown_history"][0]["depth_pct"], -40.0)
        self.assertEqual(result["drawdown_history"][0]["trough_date"], "2026-01-02")
        self.assertEqual(result["drawdown_history"][0]["days"], 1)

    def test_unrecovered_drawdown_returns_none_recovery_days(self):
        kline = [
            {"date": "2026-01-01", "close": 100},
            {"date": "2026-01-02", "close": 70},
            {"date": "2026-01-03", "close": 85},
        ]
        result = analyze_drawdown(kline)
        self.assertIsNone(result["recovery_days"])
        self.assertEqual(result["drawdown_history"][0]["depth_pct"], -30.0)
        self.assertEqual(result["drawdown_history"][0]["trough_date"], "2026-01-02")


class TestAnalyzeCorrelation(unittest.TestCase):
    def test_basic_correlation(self):
        kline_data = {
            "A": [{"date": "2026-01-01", "close": 100}, {"date": "2026-01-02", "close": 110}],
            "B": [{"date": "2026-01-01", "close": 100}, {"date": "2026-01-02", "close": 105}],
        }
        result = analyze_correlation(kline_data)
        self.assertIn("correlation_matrix", result)
        self.assertIn("A", result["correlation_matrix"])

    def test_insufficient_assets(self):
        result = analyze_correlation({"A": [{"date": "2026-01-01", "close": 100}]})
        self.assertEqual(result["error"], "need_at_least_2_assets")


class TestAnalyzeRankDynamics(unittest.TestCase):
    def test_basic_rank(self):
        rank_history = [
            {"period": "近1年", "rank": 100, "total": 500},
            {"period": "近3年", "rank": 200, "total": 400},
        ]
        result = analyze_rank_dynamics(rank_history)
        self.assertEqual(result["current_percentile"], 50)
        self.assertEqual(result["best_percentile"], 20)

    def test_no_rank_data(self):
        result = analyze_rank_dynamics([])
        self.assertEqual(result["error"], "no_rank_data")

    def test_two_points_trend(self):
        """2 个数据点可判断方向。"""
        rank_history = [
            {"period": "近1年", "rank": 200, "total": 400},
            {"period": "近3年", "rank": 100, "total": 400},
        ]
        result = analyze_rank_dynamics(rank_history)
        self.assertEqual(result["trend"], "improving")
        self.assertEqual(result["trend_strength"], "weak")

    def test_three_points_trend(self):
        """3 个数据点可判断趋势。"""
        rank_history = [
            {"period": "近1月", "rank": 300, "total": 400},
            {"period": "近1年", "rank": 200, "total": 400},
            {"period": "近3年", "rank": 100, "total": 400},
        ]
        result = analyze_rank_dynamics(rank_history)
        self.assertEqual(result["trend"], "improving")
        self.assertEqual(result["trend_strength"], "strong")

    def test_declining_trend(self):
        rank_history = [
            {"period": "近1年", "rank": 100, "total": 400},
            {"period": "近3年", "rank": 300, "total": 400},
        ]
        result = analyze_rank_dynamics(rank_history)
        self.assertEqual(result["trend"], "declining")


class TestEstimateFundFlow(unittest.TestCase):
    def test_basic_flow(self):
        nav_history = [
            {"date": "2026-01-01", "nav": 1.0},
            {"date": "2026-01-02", "nav": 1.1},
        ]
        scale_history = [
            {"date": "2026-01-01", "scale": 1e9},
            {"date": "2026-01-02", "scale": 1.2e9},
        ]
        result = estimate_fund_flow(nav_history, scale_history)
        self.assertIn("share_change_pct", result)
        self.assertIn("flow_direction", result)

    def test_insufficient_data(self):
        result = estimate_fund_flow([], [])
        self.assertEqual(result["error"], "insufficient_data")


class TestAnalyzeEtf(unittest.TestCase):
    def test_full_analysis(self):
        fund_data = {
            "code": "510300",
            "name": "沪深300ETF",
            "timestamp": "2026-09-27T00:00:00",
            "holdings": [
                {"stock_name": "A", "hold_ratio": 5},
                {"stock_name": "B", "hold_ratio": 3},
            ],
            "risk": {"sharpe_1y": 0.8, "max_drawdown_1y": -15},
            "returns": {"year": 10},
            "data": {"近1年同类分位": "200/400"},
        }
        kline = [
            {"date": "2026-01-01", "close": 100},
            {"date": "2026-01-02", "close": 95},
        ]
        result = analyze_etf(fund_data, kline_data=kline)
        self.assertEqual(result["fund_code"], "510300")
        self.assertIn("holdings_analysis", result)
        self.assertIn("risk_analysis", result)
        self.assertIn("drawdown_analysis", result)
        self.assertIn("rank_analysis", result)

    def test_minimal_data(self):
        result = analyze_etf({"code": "000001", "name": "Test"})
        self.assertEqual(result["fund_code"], "000001")


class TestAnalyzeCapitalFlow(unittest.TestCase):
    def test_basic_flow(self):
        scale_data = [
            {"date": "2026-01-01", "netInflow": 1000000},
            {"date": "2026-01-02", "netInflow": 2000000},
            {"date": "2026-01-03", "netInflow": -500000},
        ]
        result = analyze_capital_flow(scale_data)
        self.assertEqual(result["flow_trend"], "inflow")
        self.assertEqual(result["inflow_days"], 2)
        self.assertEqual(result["outflow_days"], 1)

    def test_no_data(self):
        result = analyze_capital_flow([])
        self.assertEqual(result["error"], "no_scale_data")

    def test_outflow_trend(self):
        scale_data = [
            {"date": "2026-01-01", "netInflow": -1000000},
            {"date": "2026-01-02", "netInflow": -2000000},
        ]
        result = analyze_capital_flow(scale_data)
        self.assertEqual(result["flow_trend"], "outflow")


class TestAnalyzeValuation(unittest.TestCase):
    def test_basic_valuation(self):
        detail_data = {
            "detail": {
                "PETtm": 15.5,
                "PETtm5Y": 25.0,
                "PBLf": 2.1,
                "PBLf5Y": 30.0,
            }
        }
        result = analyze_valuation(detail_data)
        self.assertEqual(result["pe_ttm"], 15.5)
        self.assertEqual(result["pe_percentile_5y"], 25.0)
        self.assertEqual(result["pb_lf"], 2.1)
        self.assertEqual(result["valuation_signal"], "moderate")

    def test_high_valuation(self):
        detail_data = {
            "detail": {
                "PETtm": 35.0,
                "PETtm5Y": 85.0,
            }
        }
        result = analyze_valuation(detail_data)
        self.assertEqual(result["valuation_signal"], "high")

    def test_no_data(self):
        result = analyze_valuation({})
        self.assertEqual(result["error"], "no_detail_data")


class TestIndexHubIntegration(unittest.TestCase):
    def test_analyze_etf_with_index_hub(self):
        """analyze_etf 主函数应正确整合 Index Hub 数据。"""
        fund_data = {
            "code": "510300",
            "name": "沪深300ETF",
            "timestamp": "2026-09-27T00:00:00",
            "holdings": [{"stock_name": "A", "hold_ratio": 5}],
            "risk": {},
            "returns": {"year": 10},
            "data": {},
        }
        index_hub_data = {
            "detail": {
                "detail": {
                    "PETtm": 15.5,
                    "PETtm5Y": 25.0,
                    "PBLf": 2.1,
                    "PBLf5Y": 30.0,
                }
            },
            "scale": [
                {"date": "2026-01-01", "netInflow": 1000000},
                {"date": "2026-01-02", "netInflow": 2000000},
            ],
        }
        result = analyze_etf(fund_data, index_hub_data=index_hub_data)
        self.assertIn("valuation_analysis", result)
        self.assertIn("capital_flow_analysis", result)
        self.assertEqual(result["valuation_analysis"]["pe_ttm"], 15.5)
        self.assertEqual(result["capital_flow_analysis"]["flow_trend"], "inflow")

    def test_analyze_etf_without_index_hub(self):
        """无 Index Hub 数据时，分析结果不包含 valuation/capital_flow。"""
        fund_data = {
            "code": "510300",
            "name": "沪深300ETF",
            "timestamp": "2026-09-27T00:00:00",
            "holdings": [{"stock_name": "A", "hold_ratio": 5}],
            "risk": {},
            "returns": {"year": 10},
            "data": {},
        }
        result = analyze_etf(fund_data)
        self.assertNotIn("valuation_analysis", result)
        self.assertNotIn("capital_flow_analysis", result)


class TestAnalyzeETFirstEnhanced(unittest.TestCase):
    def test_basic_etfirst(self):
        etfirst_data = {
            "results": {
                "getMarketIndicatorData": {
                    "pe": 13.34,
                    "pePercent": 65.34,
                    "pb": 1.4,
                    "pbPercent": 35.08,
                    "dp": 2.65,
                    "trackError": 0.36,
                },
                "getRiskReturnCharacter": [
                    {
                        "dateRange": 12,
                        "sharpeRatio": 0.85,
                        "rankSharpeRatio": 45.0,
                        "standardDeviation": 18.5,
                        "rankStandardDeviation": 50.0,
                        "maximumBack": -22.3,
                        "rankMaximumBack": 40.0,
                    },
                    {
                        "dateRange": 36,
                        "sharpeRatio": 0.72,
                    },
                ],
                "getIndustryDistribution": {
                    "firstWeightList": [
                        {"industryName": "金融", "industryRatio": "30.5"},
                        {"industryName": "科技", "industryRatio": "20.3"},
                    ]
                },
            }
        }
        result = analyze_etfirst_enhanced(etfirst_data)
        self.assertEqual(result["valuation"]["pe"], 13.34)
        self.assertEqual(result["valuation"]["pe_percent"], 65.34)
        self.assertEqual(result["risk_return"]["sharpe"], 0.85)
        self.assertEqual(result["tracking_error"], 0.36)
        self.assertEqual(len(result["industry_distribution"]), 2)
        self.assertEqual(result["industry_distribution"][0]["industry"], "金融")

    def test_no_data(self):
        result = analyze_etfirst_enhanced({})
        self.assertEqual(result["error"], "no_etfirst_data")

    def test_risk_return_dict_format(self):
        """风险收益特征也可能是字典格式（非列表）。"""
        etfirst_data = {
            "results": {
                "getRiskReturnCharacter": {
                    "dateRange": 12,
                    "sharpeRatio": 0.90,
                    "rankSharpeRatio": 30.0,
                    "standardDeviation": 15.0,
                    "rankStandardDeviation": 35.0,
                    "maximumBack": -18.0,
                    "rankMaximumBack": 25.0,
                },
            }
        }
        result = analyze_etfirst_enhanced(etfirst_data)
        self.assertEqual(result["risk_return"]["sharpe"], 0.90)
        self.assertEqual(result["risk_return"]["sharpe_rank"], 30.0)


class TestETFirstIntegration(unittest.TestCase):
    def test_analyze_etf_with_etfirst(self):
        """analyze_etf 主函数应正确整合 ETFirst 数据。"""
        fund_data = {
            "code": "510300",
            "name": "沪深300ETF",
            "timestamp": "2026-09-27T00:00:00",
            "holdings": [{"stock_name": "A", "hold_ratio": 5}],
            "risk": {},
            "returns": {"year": 10},
            "data": {},
        }
        etfirst_data = {
            "results": {
                "getMarketIndicatorData": {
                    "pe": 13.34,
                    "pePercent": 65.34,
                    "trackError": 0.36,
                },
                "getRiskReturnCharacter": [
                    {"dateRange": 12, "sharpeRatio": 0.85},
                ],
            }
        }
        result = analyze_etf(fund_data, etfirst_data=etfirst_data)
        self.assertIn("etfirst_analysis", result)
        self.assertEqual(result["etfirst_analysis"]["valuation"]["pe"], 13.34)
        self.assertEqual(result["etfirst_analysis"]["tracking_error"], 0.36)

    def test_analyze_etf_without_etfirst(self):
        """无 ETFirst 数据时，分析结果不包含 etfirst_analysis。"""
        fund_data = {
            "code": "510300",
            "name": "沪深300ETF",
            "timestamp": "2026-09-27T00:00:00",
            "holdings": [{"stock_name": "A", "hold_ratio": 5}],
            "risk": {},
            "returns": {"year": 10},
            "data": {},
        }
        result = analyze_etf(fund_data)
        self.assertNotIn("etfirst_analysis", result)


class TestFormatTerminal(unittest.TestCase):
    def test_format(self):
        analysis = {
            "fund_code": "510300",
            "fund_name": "沪深300ETF",
            "timestamp": "2026-09-27T00:00:00",
            "holdings_analysis": {
                "concentration": {"top1_pct": 5, "top5_pct": 20, "top10_pct": 30, "hhi": 100},
                "holdings_count": 10,
            },
        }
        output = format_terminal(analysis)
        self.assertIn("510300", output)
        self.assertIn("持仓穿透", output)


class TestFetchFundAnalyticsConcurrency(unittest.TestCase):
    def test_concurrent_enrichment_with_htbr_and_graceful_degradation(self):
        from unittest.mock import patch
        import cmd_fund

        fake_snap = {"code": "510300", "name": "沪深300ETF", "data": {}, "holdings": []}
        with patch.object(cmd_fund, "fetch_fund_with_fallback", return_value=fake_snap), \
             patch.object(cmd_fund, "_fetch_kline_rows", return_value=[]), \
             patch.object(cmd_fund, "_fetch_index_hub_bundle", side_effect=RuntimeError("boom")), \
             patch.object(cmd_fund, "_fetch_etfirst_detail", return_value=None), \
             patch.object(cmd_fund, "_fetch_htbr_facts", return_value={"fund_code": "510300", "scale": "1000亿"}):
            res = cmd_fund.fetch_fund_analytics("510300")
        self.assertEqual(res["fund_code"], "510300")
        self.assertEqual(res["htbr_facts"]["scale"], "1000亿")


if __name__ == "__main__":
    unittest.main()
