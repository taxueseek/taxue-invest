# 数据管线：官方 ttskill 接入（口径速查）

> 取数统一走 `invest-cli fund <代码/名称>`，route 自动选源。本文件是字段口径、判定阈值与错误处理的单一真源；适配器实现在 `invest-cli/scripts/sources/ttskill.py`，两处同步维护。

## 源优先级与降级链

```
hithink（同花顺，自带主路，费用明细全）→ ttskill（官方可选深取，结构化最全：风险族/同类分位/经理解析；登录就绪才参与）→ eastmoney（东财）→ argo 网页搜索（末位，标注「未经结构化源验证」）
```

- 首个成功即用，整单回退，不混字段（route.fetch 保证）
- ttskill 登录态失效时 detect 探测不过，自动跳过；恢复：终端跑 `ttskill login`，用户扫码后重试
- ttskill 优势：风险族（夏普/波动/回撤+同类排名）、阶段涨幅同类分位、经理解析（代表作/在管列表）；短板：管理费/托管费不在返回中，费率分析需 f10 档案页补查并标注来源
- P2 取数顺序（防重复）：先 `invest-cli fund <代码>`（快照链内已并行 BASE+HOLDING），经理画像不够再补 `ttskill TTFUND_MANAGER_INFO`；不许快照与画像各查一遍全量

## 调用矩阵（适配器内部已封装；分析场景一律走 invest-cli，直连仅作口径参考）

> 生产路径：基金深取 `invest-cli fund <代码>`；经理/净值/估值等扩展包 `invest-cli ttskill <skill_id> --input '<json>'`（37 包透传，2026-09-03 起）。以下直连命令只用于核对字段契约。

| 目的 | 命令 |
|------|------|
| 名称→代码 | `ttskill invoke TTFUND_SEARCH --action query --body '{"query":"基金名","search_type":"fund","page_size":5}'` |
| 详情+风险+费率 | `ttskill invoke TTFUND_BASE_INFOS --action query --body '{"fcode":"163406","nav_range":"n"}'`（fcode 与 fund_name 至少传一） |
| 重仓+行业+资产配置 | `ttskill invoke TTFUND_HOLDING_INFO --action query --body '{"fund_id":"163406","holding_type":"stock","period_mode":"latest"}'` |
| 经理画像+在管列表 | `ttskill invoke TTFUND_MANAGER_INFO --action query --body '{"manager_name":"谢治宇"}'` |

扩展（按需，均走 `invest-cli ttskill` 透传）：`TTFUND_NAV_INFO`（历史净值）、`TTFUND_VALUATION_MAP`（指数/行业估值分位）、`TTFUND_STOCK_PRICE_QUERY`（实时行情）、`TTFUND_MACRO_DATA`（中美宏观）、`TTFUND_SIMILAR_FUND_SELECT`（同风格替代，仅主动权益）。全套 37 包清单与参数：`invest-cli capabilities ttskill`。

## 字段口径（以 163406 实测校准，2026-09-03）

**收益**：主表 `SYL_Y/3Y/6Y/1N/2N/3N/5N/JN/LN`（近1月/3月/6月/1-5年/今年/成立来，单位 %）。阶段涨幅 `expansion.comprehensive_info.period_increase[]`：`{title, syl 本基金, avg 同类平均, hs300, benchmark 基准, rank 同类排名, sc 同类样本数}` → **同类分位 = rank/sc**（越小越好），α = syl − benchmark。

**风险**（`expansion.comprehensive_info.unique_info[0]`，**注意是数组首元素**）：`SHARP1/3/5`、`STDDEV1/3/5`（年化波动%）、`MAXRETRA1/3/5`（区间最大回撤%）、`MAXRETRA_SE` 成立以来最大回撤（配 `MAXRETRA_SDATE_SE/EDATE_SE` 起止日期）、`JGBL` 机构占比%（与 `fund_holder_structure[].JGBL` 一致，看 `FSRQ`）。卡玛未直接给出，粗估 = 近1年收益 ÷ |近1年最大回撤|。

**收益**：`fund_profile_overview` 内；阶段涨幅 `expansion.comprehensive_info.period_increase[]`：`{title, syl 本基金, avg 同类平均, hs300, benchmark 基准, rank 同类排名, sc 同类样本数}` → **同类分位 = rank/sc**（越小越好），α = syl − benchmark。title 编码（110011 实测反推）：`Y=近1月, 3Y=近3月, 6Y=近6月, 1N=近1年, 2N=近2年, 3N=近3年, 5N=近5年, JN=今年来, LN=成立来`（Z=近1周不进报告）。

**费率**（`expansion.trade_info.fee_rates`）：`purchase[]` 的 `source` 原价 / `rate` 优惠价（如 1.20%→0.12%，两个口径都报）；`redeem[]` 持有期梯度；`service[]` 销售服务费（C 类）。**管理费/托管费不在返回中**：f10 档案页补查，查不到标「以招募说明书为准」。换手率接口未提供，缺失时剔除该项并注明。

**持仓**（HOLDING_INFO 响应有 `data.` 包装：`data.top_holdings` / `data.periods[]`）：个股 `top_holdings.stocks[].{GPJC, GPDM, JZBL 占净值比%, PCTNVCHGTYPE 新增/增持/减持/不变, HOLDCOUNT 连续重仓季数}`；行业 `industry_allocation[].{HYMC, ZJZBL}`；报告期与滞后提示 `data.holding_overview.{report_date, data_lag_notice}`。**QDII 等产品顶层 stocks 可能为空 → 从 `data.periods[-1].top_holdings.stocks` 取**。**口径**：`asset_allocation.GP`（股票资产总占比）与前十 `JZBL` 求和（重仓明细合计）不同。持仓滞后一季度属正常，报告必须标 `report_date`。

**规模**：`ENDNAV` 单位是元（6777001473.91 = 67.77 亿），一律 ÷1e8。

**经理**：BASE 的 `fund_profile_overview.JJJL`（可含多人，逗号分隔，取首位为主经理）；深查用 `TTFUND_MANAGER_INFO`（响应 `body.data`）：`manager_profile.{representative_fund_code/name 代表作, years_of_experience_days, total_aum(元), current_fund_count}`；在管列表 `managed_funds[].{FCODE, SHORTNAME, FTYPE, FEMPDATE 任职起始, TOTALDAYS 管理天数, ENDNAV, SYL_1N, RANKY}`。

## 外部基准映射（用户点名指数时用）

| 用户说法 | --benchmark 取值 | 备注 |
|---|---|---|
| 偏股混合基金指数 / 万得偏股混合 | 885001.WI | 实测直连 Wind 可取，基期对齐 tenure 口径 |
| 沪深300 | 000300.SH |  |
| 中证500 | 000905.SH |  |
| 中证800 | 000906.SH |  |

例：`invest-cli tenure 001437 --manager 武阳 --benchmark 885001.WI`
基期对齐 tenure 口径（任职日前一交易日；成立即任职取成立日）。
校验：`wind.index_series("<代码>", begin, end)` 同基期复算，偏差 >0.05pct 必须暴露。

## 判定阈值速查（服务三关，绝对阈值 × 同类分位交叉验证）

| 指标 | 优 | 中 | 需关注 |
|------|----|----|--------|
| 夏普 SHARP1 | >1 | 0.5-1 | <0.5（>1 但同类后 50% = 行情红利非能力） |
| 最大回撤 MAXRETRA1 | <20% | 20-30% | >30% |
| 年化波动 STDDEV1 | <15% | 15-25% | >25% |
| 卡玛（粗估） | >2 | 1-2 | <1 |
| 前十集中度（JZBL 求和） | 40-60% 适中 | <40% 分散 | >60% 集中；单一股票 >10% 额外提示 |
| 行业偏离 ZJZBL | — | — | 单一行业 >30% = 行业主题特征 |
| 单只规模 | 5-50 亿灵活 | 50-100 亿 | >100 亿调仓难 / <5 亿清盘风险 |
| 经理年限 | >5 年 | 3-5 年 | <3 年；在管 >5 只精力分散 |
| A/C 选择 | 持有超 1 年选 A | — | 短持有 C（对照 redeem 梯度） |

## 错误处理

| 情形 | 动作 |
|------|------|
| `cli_login_required` / token 失效 | `ttskill login` 扫码后重试；不便扫码则让 route 落到 hithink/eastmoney |
| 名称解析多候选（disambiguation_candidates） | 列候选（代码+名称+类型）请用户确认，不自动猜 |
| 基金不存在 / `invalid_fund_codes` | 提示核对代码或名称 |
| 主表字段空（如 MGRNAME） | 换备用路径（`fund_profile_overview.JJJL`、`manager_information`），再缺标「未披露」 |
| 货币基金 DWJZ | 万份收益口径，勿当净值解读 |

## ETF 深度分析模块（etf_analytics.py）

> 入口：`invest-cli fund <代码> --analytics`。纯标准库实现，零第三方依赖。

### 数据源

| 源 | 获取方式 | 提供字段 | 失败行为 |
|---|---------|---------|---------|
| invest-cli fund | `fetch_fund_with_fallback()` | 净值、业绩、持仓、费率、经理 | 主源，必须成功 |
| invest-cli kline | `cmd_kline.run()` | 收盘价序列（回撤分析） | 跳过回撤分析 |
| ttskill 深取 | `_ttskill_deep()` | 夏普、波动、同类分位 | 跳过缺失字段 |
| Index Hub API | `sources/index_hub.py` | 估值(PE/PB/PS)、资金流、跟踪误差、换手率 | 跳过估值/资金流分析 |

### 字段映射

| 分析模块 | 输入字段（fund JSON） | 输出字段 |
|---------|----------------------|---------|
| 持仓穿透 | `holdings[].hold_ratio` / `holdings[].占净值比例` | `concentration.top1/5/10_pct`, `hhi` |
| 风险增强 | `risk.sharpe_1y` / `data.夏普比率` / kline 回撤 | `sharpe`, `sortino_ratio`, `downside_deviation`, `calmar_ratio` |
| 回撤深度 | kline 的 `close`/`收` 序列 | `max_drawdown_pct`, `recovery_days`, `current_drawdown_pct` |
| 相关性 | 多标的 kline 收盘价 | `correlation_matrix`, `avg_correlation` |
| 估值分析 | Index Hub `PETtm`/`PETtm5Y`/`PBLf`/`PBLf5Y` | `pe_ttm`, `pe_percentile_5y`, `valuation_signal` |
| 资金流分析 | Index Hub `etf/etf-scale` 的 `netInflow` 序列 | `total_net_inflow`, `flow_trend`, `recent_1w/1m_inflow` |
| ETFirst 估值 | ETFirst `getMarketIndicatorData` 的 `pe`/`pePercent`/`pb`/`pbPercent` | `valuation.pe`, `valuation.pe_percent` |
| ETFirst 风险收益 | ETFirst `getRiskReturnCharacter` 的 `sharpeRatio`/`standardDeviation`/`maximumBack` | `risk_return.sharpe`, `risk_return.volatility` |
| ETFirst 行业分布 | ETFirst `getIndustryDistribution` 的 `firstWeightList` | `industry_distribution[].industry`, `industry_distribution[].weight_pct` |
| 排名动态 | `data.近1年同类分位` / `data.近3年同类分位` | `current_percentile`, `trend`, `best/worst_percentile` |

### 判定阈值

| 指标 | 优 | 中 | 需关注 |
|------|----|----|--------|
| Top1 集中度 | <10% | 10-20% | >20% |
| Top5 集中度 | <30% | 30-50% | >50% |
| Top10 集中度 | <50% | 50-70% | >70% |
| HHI | <1000 | 1000-1800 | >1800 |
| 信息比率 | >0.5 | 0-0.5 | <0 |
| 索提诺比率 | >2 | 1-2 | <1 |
| 下行波动率 | <15% | 15-25% | >25% |
| 最大回撤 | <20% | 20-30% | >30% |
| 恢复天数 | <90 天 | 90-180 天 | >180 天 |
| 同类分位 | 前 25% | 25-50% | 后 50% |
| 平均相关系数 | <0.3 | 0.3-0.6 | >0.8 |

### 数据缺失处理

- hithink 源的 `risk` 数据可能全为 null → 风险增强模块返回"数据不足"，属正常行为
- ttskill 深取会补充风险字段（夏普/波动/回撤），有数据时自动计算
- K 线获取失败时回撤分析跳过，不影响其他模块

## 同步义务

本文件口径表与 `invest-cli/scripts/sources/ttskill.py` 的映射逻辑互为镜像：改字段映射必须同步改本文件，反之亦然。ttskill 官方技能包升级后（`ttskill status` 看版本），抽查 163406 验证口径无漂移。
