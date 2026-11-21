# 数据源能力差距矩阵（盈米 69 工具 × ttskill 37 包 × invest-cli 现状）

> 更新：2026-09-03。本文档是 invest-cli 对两大外部数据源的"能力面核对表"，也是本次补齐改造的设计真源。
> 用法：接数据需求前先对照此表——同一能力若有 invest-cli 高层入口（fund/stock/intent）优先走高层；
> 无高层入口的，走 `invest-cli yingmi <tool>` / `invest-cli ttskill <skill_id>` 透传；
> 透传参数以官方 schema 为准，拿不准先跑 `invest-cli capabilities yingmi|ttskill` 看能力清单。

## 一、第一性原理：能力按"动作"而非"来源"归类

数据调用 = `标的类型 × 动作 × 源`。动作只有四类，官方 106 个能力点都落在这四类里：

| 动作 | 用户要什么 | 官方能力点 | invest-cli 高层入口 |
|---|---|---|---|
| **找**（discover） | 名字→代码、市场里筛出标的、近期谁火 | 盈米 SearchFunds/GuessFundCode/GetPopularFund/SearchHotTopic；ttskill CONDITION_SELECT/INDEX_FUND_SELECTION/THEME_SELECT/SEARCH | `intent screen fund`、`yingmi <tool>` 透传 |
| **查**（snapshot） | 单标的结构化快照/历史 | 盈米 BatchGetFundsDetail/BatchGetFundNavHistory；ttskill 三合一(BASE+HOLDING+SEARCH)+NAV_INFO | `fund <code>`（快照链）、`stock <code>`、`us <sym>` |
| **诊**（diagnose） | 风险/归因/经理/持仓深挖 | 盈米 GetFundDiagnosis/Brinson/行业族；ttskill MANAGER_INFO/VALUATION_MAP | `intent deep fund`（盈米诊断→快照回退） |
| **配**（allocate） | 组合诊断/配置方案/规划 | 盈米 DiagnoseFundPortfolio/GetAssetAllocationPlan/蒙特卡洛族 | `intent portfolio`、`intent plan` |

判断规则（第一性）：**凡四类动作已有高层入口的，不需要再为单工具造特判命令**（避免平行封装）；
凡高层入口缺失的，先看是否值得收敛，否则至少保证**透传可达 + 清单可见**。

## 二、盈米 69 工具差距（MECE 按动作×标的）

| 能力族 | 代表工具（参数要点） | invest-cli 现状 | 差距 | 处置 |
|---|---|---|---|---|
| 名称→代码 | GuessFundCode(fundNameOrCode) | classify/_resolve_fund_code 已用 | — | 已收敛 |
| 基金搜索排序 | SearchFunds(keyword/排序参数) | `intent screen fund` 已用 | — | 已收敛 |
| **热门基金** | GetPopularFund(window 必填 1-30/size≤20) | 数组适配已修（09-03 直连版 `_wrap` 支持 list；实测 window=7 返回 items） | 已消除 | — |
| 基金诊断 | GetFundDiagnosis(fundCode) | `intent deep fund` 已用 | — | 已收敛 |
| 批量详情/业绩/净值 | BatchGetFundsDetail / GetBatchFundPerformance(≤20只) / BatchGetFundNavHistory | 无高层入口；**数组返回→全被 bug 挡** | P0 | 修适配器后透传可用 |
| 持仓穿透分析 | GetFundAssetClassAnalysis / 行业族(getFundIndustryAllocation/Concentration/Preference/Returns) / getStockAllocationAndMetricsByFundCode / QDII地区 / Brinson/Campisi / 换手率 / 择时 / 债券族 | 无高层入口 | P1 | 透传可用，随用随收 |
| 风险/回撤分析 | AnalyzeFundRisk / fund-recovery-ability / fund-equity-position / fund-sector-preference | 无高层入口 | P1 | 透传可用 |
| 组合诊断 | DiagnoseFundPortfolio | `intent portfolio` 已用 | — | 已收敛 |
| 组合回测/相关性 | GetFundsBackTest / GetFundsCorrelation（只传基金列表，勿传 fundName） | 无高层入口 | P1 | 透传可用 |
| 资产配置方案 | GetAssetAllocationPlan(三性至少一) | `intent plan` 已用 | — | 已收敛 |
| 财富规划族 | AnalyzeAssetLiability/CashFlow/FamilyMembers/IncomeExpense/FinancialIndicators + MonteCarloSimulate | 无高层入口 | P2 | 透传可用（分析侧非主场景） |
| 投顾策略 | GetStrategyDetails/BatchGetStrategiesComposition/GetStrategyRiskInfo/GetFundRelatedStrategies | 无高层入口 | P2 | 透传可用 |
| 市场温度/收盘解读 | GetLatestQuotations | 无高层入口 | P1 | 透传可用 |
| 财经资讯/观点 | SearchFinancialNews / SearchManagerViewpoint / searchRealtimeAiAnalysis / searchInvestAdvisorContent / SearchHotTopic | 资讯走 argo（`info`，省配额） | P2 | argo 优先，盈米为候选 |
| 交易规则/限制 | BatchGetFundTradeLimit/Rules / GetTxnDayRange / 分红拆分 | 无高层入口 | P2 | 透传可用 |
| 工具 | GetCurrentTime / RenderEchart / RenderHtmlToPdf | 不用（本地渲染替代） | — | 有意排除 |

## 三、ttskill 37 包差距（MECE 按用途）

| 能力族 | 业务包 | invest-cli 现状 | 差距 | 处置 |
|---|---|---|---|---|
| 基金快照深取 | SEARCH + BASE_INFOS + HOLDING_INFO（三合一） | `fund <code>` 快照链内嵌（hithink→ttskill→eastmoney） | — | 已收敛 |
| 黄金 | GOLD_INFO | `intent deep commodity` 特判 | — | 已收敛 |
| **经理画像/在管列表** | MANAGER_INFO(manager_name) | 仅 data-pipeline.md 记载，无命令可达 | **P0** | 加 ttskill 透传（本次） |
| **历史净值** | NAV_INFO(fund_id, range) | 无命令可达 | **P0** | 加 ttskill 透传（本次） |
| **实时行情** | STOCK_PRICE_QUERY(query=名称/代码) 等 | 无命令可达；A股实时已由同花顺 stock 覆盖 | P1 | 加 ttskill 透传；同花顺优先不换链 |
| 估值地图 | VALUATION_MAP(group=全部) | 无命令可达 | P1 | 加 ttskill 透传 |
| 条件选基/指数选基/主题选基 | CONDITION_SELECT / INDEX_FUND_SELECTION(top_n,period_codes,index_codes) / THEME_SELECT(theme_name) | 指数选基已收敛为 `research etf-rank`（2026-11-08）；条件/主题选基仍透传 | P1（条件/主题） | 透传可用，按消费频率再收敛 |
| 机会扫描 | MARKET_OPPORTUNITY_SCANNER | 无命令可达 | P1 | 加 ttskill 透传 |
| 宏观 | MACRO_DATA(region=cn/us, categories) | `intent macro`→argo；Wind 可选 | P1 | 透传可用，与 argo 双通道 |
| 指数/行业行情 | INDEX_INFO / CHIP_INDEX_QUOTE / NONFERROUS_INDEX_QUOTE | 无命令可达 | P2 | 透传可用 |
| 研报 | RESEARCH_SEARCH / RESEARCH_VIEW | 研报走 wind/argo | P2 | 透传可用 |
| 账户/交易/定投 | ACCOUNT_HOLDING/PROFIT、TRADE_QUERY、CONDITION_ORDER、SIM_TRADE、SUBACCOUNT、RATION_PLAN | **有意不封装** | — | 边界纪律：invest-cli 定位"数据与分析"，交易执行类不做高层入口，仅透传可读 |
| 主题/策略/创新药/债市/分红温度/事件 | THEME_INFO、STRATEGY_INFO、PORTFOLIO_ANALYSIS、INNOVATIVE_PHARMA、BOND_MARKET、DIVIDEND_TEMPERATURE、EVENT_SELECT、GROUP_BACKTEST、HUOQIBAO_LIST、FAVOR_ZX、PREMIUM_FINANCE、SIMILAR_FUND_SELECT | 无命令可达 | P2 | 透传可用，随用随收 |

## 四、westock 收敛（2026-09-24）

westock（腾讯微证券）此前整体以「长尾透传」接入（`invest-cli westock <子命令>`）。
2026-09-24 收敛**高频五个**到 `cn` 高层入口，判据是「分析链路会反复消费」而不是「顺手封装」：

| westock 子命令 | cn 入口 | 收敛后新增的价值 |
|---|---|---|
| `notice list/detail` | `cn notice`（+`--search` 走 argo/cninfo） | 公告列表结构化 + 全市场公告检索（此前 CN 侧无公告检索能力） |
| `consensus` | `cn consensus` | 一致预期（目标价 + 年度 EPS/PE 预测）结构化 |
| `shareholder` | `cn holders` | 十大股东与变动结构化（治理/质押核查） |
| `disclosure` | `cn disclosure` | 财报披露日历（预约披露日） |
| `report list` | `cn report` | 研报列表（可翻页） |

**为什么收敛这五个**：invest-stock 三关（治理核查）与 invest-analyst（一致预期/研报）会反复消费；
其余 40+ 子命令（chip/lhb/events/industry-chain/bond/macro…）保持透传——用到再收敛，
避免「预支复杂度」（与 ttskill 一节同一纪律）。

**收敛同时修掉的两个缺陷**：
1. 多代码不归一：`notice list 600519,000858` 这类逗号串过不了形状守卫，服务端按「代码错误」拒绝
   → 新增 `westock.normalize_codes()` 逐段归一；
2. `notice list` 的代码位不在 `_CODE_AT` 表里（裸代码不归一）→ 补 `("notice","list"): 2`。

**守护**：`test_cn_cmd.py`（信封契约 + 解析 fail-open + argo 降级路径）、
`cmd_capabilities.py` 的 `WESTOCK_CONVERGED` 登记（`invest-cli capabilities westock` 可见）。

## 五、三个系统性根因（为什么"没高效利用现有工具"会重复犯）

1. **ttskill 无透传子命令**：invest-cli 命令面只有 wind/yingmi 两个透传，ttskill 37 包里除基金三合一与黄金外全部"声明不可达"→ Agent 只能现场翻官方包学 CLI 调用（低效、易错）。本次补 `invest-cli ttskill <skill_id>`。
2. **盈米适配器只认 `{` 开头**：批量/列表/搜索类工具（GetPopularFund、Batch*、Search*）返回 JSON 数组 → 一律被误判"未返回结构化数据"。本次修复。
3. **无能力发现层**：106 个官方能力点无一处集中登记"有什么、参数怎么传、invest-cli 收敛到哪"→ 靠记忆必然遗忘。本次补 `invest-cli capabilities`（动态列官方清单 + 标注收敛状态）。

## 六、消融/回归纪律（改完逐项验证，删不掉价值就不加）

- 每个"高层入口收敛"都要有对应测试：验证路由参数、失败回退（整单不混字段）、来源标注。
- 透传命令是"面"的补齐（37/69 能力可达），不是逐个封装；某个工具用得多再收敛成高层入口并登记到本表。
- 交易执行类（下单/调仓/账户资金）永远不进 invest-cli 高层入口——那是券商/基金账户职责，CLI 只做只读数据与分析。

## 七、2026-10-11 更新：基金排行/长程研究缺口已关闭

此前登记的能力缺口「按主题筛主动基金并按多期业绩排名」无原生入口（盈米 SearchFunds
无业绩字段且当时静默空结果、天天 37 包无排行业务、SearchFunds 分页参数不被
intent 层透传），Agent 只能手工十轮编排（搜索候选 → 逐只快照 → 排名 → 交叉）。

本次由 `invest-cli research fund-rank <主题>` 关闭：池构建（TTFUND_SEARCH 分页，
名称子串搜索须先提炼关键词）→ 批量快照（复用 fund 同路径同缓存）→ 排名 →
重仓×股息率交叉 → 双源互证。实测 97 只池 46s（手工串行 ~210s）。
遗留缺口：--enrich 的资讯相关性受限于基金名非热词。

## 八、2026-11-08 更新：指数基金横评缺口已关闭

原遗留的「指数/ETF 维度横向对比未进管线」由 `invest-cli research etf-rank <指数代码或名称>`
关闭。数据走 ttskill `TTFUND_INDEX_FUND_SELECTION` 一次调用，取回候选指数、
`fund_items` 横评（规模/管理费/托管费/跟踪误差/超额收益/得分/risk_note）、
前 N 大成分股与指数估值。

本次以真实回包接线（2026-11-08 实测沪深300：357 只跟踪基金，前五 510310 /
510300 / 510330 / 159919 / 000051），字段路径 `selection_result.data` 与文档写的
`raw_result.body` 两种形状都兼容；结构缺失、`fund_items` 为空、上游失败一律 rc=1，
不返回空表。评分口径 `score_note`、风险提示 `risk_note` 原样透出，不在本地重算；
规模<2 亿的基金单独汇总提示清盘风险。

剩余：条件选基（CONDITION_SELECT）与主题选基（THEME_SELECT）仍只有透传，
按「被分析链路反复消费才收敛」的纪律暂不封装。守护见
`scripts/test_research_etf.py`。
