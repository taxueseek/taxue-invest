---
name: invest-cli
description: |
  投资分析 CLI — 数据获取 + 分析框架一体化，dual-mode 运行。

  触发：「/cli」「/投资cli」「invest cli」「终端分析」「命令行分析」
  或：「用cli分析」「终端查一下」「命令行看看」

  命令入口：`invest-cli stock 600519`（PATH 无 invest-cli 时兜底：`"$HOME/.local/bin/invest-cli" stock 600519`——wrapper 优先用 skill 自带 venv，含 yfinance）
---

# invest-cli — 投资分析 CLI

## 定位

invest 系列 skill 定义"怎么想"（分析框架），invest-cli 负责"怎么取"（数据获取）。两者不是替代关系：明确说「/cli」或要终端取数时走 invest-cli，否则走 invest 系列（路由见 `invest/SKILL.md`）。

**入口约定**：优先 `invest-cli` 命令（PATH，wrapper 在 `~/.local/bin/`）；PATH 无该命令时用 `"$HOME/.local/bin/invest-cli"` 兜底。不要绕过 wrapper 直接 `python3` 裸跑系统解释器——那样会丢掉 venv 里的 yfinance，美股路径从全量快照依次降级为腾讯行情 → Tiingo EOD → Bitget rToken。

## 路由逻辑

1. 识别标的类型（股票/基金/美股/选股）
2. 调用对应子命令，`--json` 获取结构化数据
3. 将 JSON 数据传给 invest 系列分析框架
4. 输出完整分析报告

不带 `--json` 直接跑同一条命令 = 终端模式，输出表格快照（样例见文末「终端直接运行示例」）。

## 输出契约（给 agent）

- **默认 `--json` 保持各命令原形状**（历史原因有 6+ 种：裸载荷 / `{ok,source,data,error}` / `{data}` / 源名字典）。
  要「一种形状解析」时加 **`--envelope`**（写在子命令前后都行），恒得
  `{ok, source, data, error, meta}`；失败原因取 stderr 尾部，而不是只剩退出码。
- **大结果用窄口**：`sec --brief`（去掉 5 年 series）、`us <代码> --history --brief`
  （去掉逐日 bars）、`screen --limit N`（默认 20，`--all` 全量）。
  这几个开关只影响载荷体积，不改变口径；终端表格仍按原样渲染。
- 为什么要窄口：agent 工具对单次输出有字符上限，`sec`（28.5k）与
  `us --history`（59.9k）默认会被截断——截断的 JSON 无法解析

## 子命令

### stock — A股/港股分析

```bash
invest-cli stock <代码/名称> [--json]
```

- 数据源：同花顺金融数据服务优先（A 股官方 REST）；失败或港股回退东方财富
- 获取：实时行情 + PE/PB/PS/PCF + 近 5 年年报 + ROE/毛利率/现金流（港股仍走东财）
- 分析框架：对标 invest-stock 三关审查（懂不懂 / 好不好 / 贵不贵）
- 内置名称映射：茅台→600519、五粮液→000858、宁德时代→300750 等

### fund — 基金分析

```bash
invest-cli fund <代码/名称> [--json]
```

- 数据源：同花顺金融数据服务优先；失败回退东方财富（intent deep fund 仍先盈米）
- 获取：净值/业绩/回撤/费率/经理/十大重仓
- 分析框架：对标 invest-fund 三问准入
- 内置名称映射：易方达蓝筹（精选）→005827、中欧医疗→003096 等；110011 现为「易方达优质精选(QDII)」，勿按旧文档把易方达蓝筹映射到 110011（纠偏记录见源码注释）

### us — 美股分析

```bash
invest-cli us <代码> [--json]
invest-cli us <代码> --history [--years N] [--brief]   # Tiingo EOD 历史专项（复权K线+分红/拆股/回撤摘要）
```

- 数据源：yfinance（估值/财务/评级，装了才在）；缺失或失败时回退**腾讯行情**（实时美股行情，含 PE/PB/市值/52周/股息率/ROE，实测 ~189ms 全字段），再退 **Tiingo**（官方交易所收盘价 + 市值/PE/PB/52周/股息率/最大回撤，`quote_basis=eod` 诚实标注收盘口径），最后 Bitget rToken 报价（USDT，非官方价，只有成交价与 24h 区间）
- 获取：全量快照（yfinance）或行情口径快照（tencent）或 EOD 口径快照（tiingo）或行情-only（bitget，`quote_type=rtoken`）
- 妙想（mxds）已于 2026-10-11 移出美股快照链：它是「自然语言→表格」服务（单次 1.2s+，快照查询只回收盘价简表，对比 tencent 全字段 189ms），不适合确定性快照；美股的自然语言查询走 `intent mxds "AAPL 股价"`（裸 ticker 已适配包装，结果缓存 300s）
- `--history` 走 Tiingo 独占能力：可靠复权历史（adjClose + divCash + splitFactor），快照链其余源都不提供；免费档无三表，财报问题走 `invest-cli sec`
- `--history --brief` 只留摘要（区间/回撤/分红/拆股），去掉逐日 bars：默认载荷约 60KB，会在 agent 工具侧被截断
- 分析框架：对标 invest-stock 美股四维度（ROE持续性/负债安全/FCF质量/经济护城河）；Bitget 回退仅有报价，无财务

### quote — 免鉴权多标的实时行情（跨市场）

```bash
invest-cli quote <代码[,...]> [--json]
```

- 用途：**只要行情**的问题（「现在多少钱」「涨跌多少」「这几只对比一下」）
- 数据源：腾讯行情（零鉴权），一次 HTTP 请求可带任意多个标的，跨 A股/港股/美股/ETF/可转债
- 实测：单标的 ~130ms，6 标的混合 ~132ms；缓存 10s（比快照链的 60s 更严，行情语境下可忽略）
- 与 `stock`/`fund`/`us` 的分工：那三条是**深度快照**（含基本面，冷取数 0.5s 起，美股 4s 量级），
  `quote` 是**纯行情**。问基本面却用 quote 会缺 ROE/净利润；问行情却用 stock 会多付几倍等待

### sec — SEC EDGAR 美股数据（免费官方源，五个动作）

```bash
invest-cli sec <代码> [--forms 10-K,10-Q,8-K] [--filings 5] [--years 5] [--quarterly] [--brief] [--json]
invest-cli sec <代码> --search "关键词" [--forms 10-K] [--from 2025-01] [--to 2025-12] [--limit 10]
invest-cli sec <代码> --insiders [--days 180] [--limit 20]
invest-cli sec <代码> --events [--days 365] [--limit 20]
invest-cli sec <投资人> --holdings [--limit 40]     # 机构名 / CIK / 上市代码（如 BRK）
```

- 数据源：SEC EDGAR 官方 API（companyfacts + submissions + full-text search + Archives），免费无 key
- 身份声明：SEC 要求 UA 含邮箱（www.sec.gov 强制，否则 403）；默认用占位邮箱通过校验，建议设置 `SEC_EDGAR_USER_AGENT="你的名字 你的邮箱"` 声明真实联系方式
- `--brief`（仅快照）：省略 5 年年度序列 `series`，保留最新指标与申报清单；默认快照 28.5KB，窄口后几 KB
- 快照（默认动作）：24 项年报指标（营收/毛利/营业利润/净利/EPS/研发/销售管理费/所得税/经营现金流/资本开支/自由现金流/回购/分红/资产/负债/权益/现金/长期债务/存货/应收/流通股数；FCF 为派生并标注）+ 近 5 年年度序列（三关趋势表直接可用）+ 最近申报清单；`--quarterly` 附近 8 季（Q4 为推导值，标 derived）
- 全文检索：EDGAR full-text search（2001 年起），命中到申报 + 原文段落（前 5 条拉原文抽取，抽不到留空、不编造）；多词自动按短语检索
- 内部人交易：Form 4 逐笔（谁/职位/交易代码/股数/价格/金额/交易后持股），含期权行权与代扣税行
- 事件：8-K 逐事项（业绩发布/高管变动/协议/减值/退市通知…按 SEC item 编码映射）+ 13D/13G 权益变动
- 13F 持仓：机构最新一期（按发行人聚合，带占比）；金额单位随申报期标注（2023 年起为美元）
- 口径：标签漂移按优先级回退（如 Apple 的 Revenues 停在 2018，自动改用 RevenueFromContractWithCustomerExcludingAssessedTax）；时长型事实限 300~400 天，季度值不进年度结果；**一次只做一件事**（四个动作旗标互斥，同时给会报错）
- 定位：与 Wind / yfinance 的结构化数字交叉验证的「原文级」依据；原始 JSON 磁盘缓存（companyfacts 24h / 申报原文 7 天）
- 不做：外国私人发行人（20-F）、投资公司（N-CSR）不在覆盖内，会明确报错；13F 只含美国多头与期权（不含空头）

### fund-class — 基金三层分类器（评价友好分类）

```bash
invest-cli fund-class <6位代码> [--json]
```

- 定位：只输出**稳定的分类事实**——L1 大类资产 / L2 产品形态 / L3 投资策略 + 辅助标签（运作方式/固收+/指数型/QDII/FOF/养老/REITs/申赎状态/风险等级/目标ETF），含依据与口径原文；**不做评价结论**——筛选/三关审查/同类对比/watchlist 各自消费，分类器与消费方解耦
- 数据底座：ttskill TTFUND_BASE_INFOS expansion（**单请求**：FTYPE + SHORTNAME + traits 布尔组 + 申赎状态）；其余源没有类型字段（实测快照只有场内外标记），SHORTNAME 的类型后缀当交叉复核列，冲突并列不裁决、只对境内大类生效
- 规则真源：`fund-classification.yaml`（FTYPE 全文映射 + 前缀兜底 + 资产段优先 + L3 关键词 + 固收+ 判定）——改规则不改代码，golden 用例锁行为
- 未定语义：字段缺失/未登记 → None + unresolved 原因，**绝不静默猜**；L1 按「主要投什么资产」判（资产优先：QDII-商品 → 另类(商品) 而非跨境）
- 与基金链分工：`invest-cli fund` 给净值/费率/重仓快照；本命令给分类事实

### fmp — Financial Modeling Prep 美股深取（免费档，us 链末位兜底）

```bash
invest-cli fmp <代码> [--json]                       # 深取快照：行情 + TTM 比率 + 结构化评级 + 公司概况
invest-cli fmp <代码> --estimates [--json]           # 年度分析师预测（EPS/营收 低/均/高）
invest-cli fmp <代码> --statements [--period annual] [--limit 2]
invest-cli fmp <代码> --dividends [--json]
```

- 数据源：FMP `/stable` API；免费档 250 次/天 + 30 天 500MB 带宽，**深取专项，us 链末位兜底**（前四源全败才用，别拿本源做日常快照）
- 与 `sec` 分工：sec = 10-K XBRL **原文级**（官方免费、申报清单/内部人/事件/13F）；fmp = **加工好**的 TTM 比率（毛利率/利润率/负债/股息）、结构化评级（字母 + DCF/ROE/ROA/负债/PE/PB 六维分项分）、年度分析师预测
- 免费档边界（2026-09-30 实测）：三表 annual 通、quarterly 付费；`ratios-ttm` 的 **ROE/ROA=null**（要 ROE 走三表自算或 yfinance）；estimates 仅 annual；ETF 持仓明确付费墙；**查无此票与付费墙同码 402**（按文案分流）
- 分析框架：评级分项与 TTM 比率喂给 invest-stock 的「好不好/贵不贵」，数字与 sec_edgar/yfinance 交叉验证

### cn — A股/港股市场结构（公告/一致预期/股东/披露日历/研报）

```bash
invest-cli cn notice <代码[,代码...]> [--type N] [--limit N] [--offset N]
invest-cli cn notice --search "关键词" [--limit N]      # 巨潮 cninfo 关键词检索（走 argo）
invest-cli cn consensus <代码[,代码...]>                # 一致预期（目标价 + 年度预测）
invest-cli cn holders <代码[,代码...]>                  # 股东研究（十大股东 + 变动）
invest-cli cn disclosure <代码[,代码...]>               # 财报披露日历（预约披露日）
invest-cli cn report <代码[,代码...]> [--limit N] [--offset N]   # 研报列表
```

- 数据源：westock（腾讯微证券）五个高频子命令的收敛入口；`--search` 走 argo 的 cninfo 引擎
- `--json` 把 markdown 表格解析成结构化行（`tables[].rows` 按字段取值），原文始终保留在 `raw`
- 公告列表在 westock 通道故障时自动降级到 argo/cninfo 检索（标明来源与局限）
- 代码归一：`600519,000858` → `sh600519,sz000858`，中文名也可直接用
- 与 `westock` 透传的关系：透传仍是长尾出口（chip/lhb/events/industry-chain 等 40+ 子命令）；`invest-cli capabilities westock` 看已收敛清单

### screen — 选股（**股票**筛选）

```bash
invest-cli screen <条件> [--limit N|--all] [--json]
```

- 数据源：妙想 mx_stocks_screener（自然语言选股，priority 55）优先，东方财富**选股** API（stock-screen）兜底——按定义只筛股票；两者结果体形状不同，解析层已兼容
- 支持自然语言条件："市盈率低于10的银行股"、"ROE大于20%的消费股"
- `--limit`（默认 20）/`--all`：行数裁剪，JSON 顶层带 `screen_meta{total,returned,truncated}`，不静默丢
- 筛**基金**不要用本命令（基金条件会被服务端当成股票的主营业务关键词，结果不是基金）：
  走 `invest-cli intent screen <条件>`，带「基金/ETF/债基」等词时自动路由到盈米基金搜索

### watchlist — 本地自选股

```bash
invest-cli watchlist add <代码> [--name N] [--type fund|stock]
invest-cli watchlist remove <代码>
invest-cli watchlist list [--with-quote]
```

- 本地存储 `<state_root>/watchlist.json`（默认 `~/.config/invest-cli/`，可用 `INVEST_CLI_STATE_DIR` 覆盖；用户数据不放缓存目录），不依赖任何外部账户登录态
- 行情预览走 route.fetch（A 股/基金快照链），按 `--type` 选 stock 或 fund

### tenure — 基金经理任职期复盘（分年度业绩/回撤 + 任职以来 vs 业绩基准指数）

```bash
invest-cli tenure <基金代码|名称> [--manager 姓名] [--since YYYY-MM-DD]
                  [--benchmark auto|指数代码] [--source auto|wind|ttskill]
                  [--years 5] [--excel out.xlsx] [--csv DIR] [--json]
invest-cli tenure --manager 姓名 [--company 公司] [--excel out.xlsx] [--json]
```

- 一次调用产出：档案（成立日/经理/任职日/基准）+ 分年度收益率与最大回撤（近 5 年含 YTD）
  + 任职以来逐日收益（基金 vs 基准）+ 累计/年化/超额 + 官方字段校验行
- 产物三层：终端表（默认）、`--json`（结构化信封，供 agent 消费）、`--excel`（概览/每只基金明细/数据来源；
  无 openpyxl 时自动落 `--csv` 同构文件，不丢数据）
- 数据源：Wind 为主（档案 get_fund_info / 复权净值 get_fund_performance 分段并行 / 基准 get_index_kline /
  官方年度字段），Wind 不可用时回退天天官方 gateway（NAV_INFO/BASE_INFOS/MANAGER_INFO）并在产物里标注
- 口径：任职以来基期 = 任职日前一交易日（与 Wind 区间收益率一致，任职当日收益计入）；
  年度回撤取年内峰值口径；基准指数 = 基金代码 + BI.WI，港股假期沿用前值
- `--manager` 不带基金时扫描该经理全部在管产品，按初始份额（A 类/唯一份额）过滤，一次产出组合级工作簿
- 成本提示：Wind 净值单次硬顶 100 行 → 分段抓取按次计费；结果落 6 小时磁盘缓存，
  同轮重跑命中缓存不再计费（实测 6 只基金全量重取 ≈75s → 命中 <0.1s）

### datasources — 数据源探测（统一门闩）

```bash
invest-cli datasources [--json]
```

- 列出所有已登记数据源（配置真源 `data-sources.yaml`）及运行时可用性
- 同时打印默认快照链（yaml × 真方法 × 可用性）；`--json` 含 `_chains`
- 取数走 `stock/fund/us/intent`，由 `sources/route.py` 选源，禁止在分析 skill 里猜源

### wind — 万得 Wind（机构级，直连 MCP）

```bash
invest-cli wind <server_type> <tool> --input '<json>' [--json]
```

- **直连 Wind MCP**（JSON-RPC over HTTP），不依赖 wind-mcp-skill 的 node CLI
- server_type：stock_data/fund_data/index_data/bond_data/financial_docs/economic_data/analytics_data
- Key 顺序与官方一致：`~/.wind-aifinmarket/config` > skill config.json > 环境变量 `WIND_API_KEY`

### yingmi — 盈米且慢（直连 OpenAPI）

```bash
invest-cli yingmi <tool> --input '<json>' [--json]
```

- **直连盈米 OpenAPI**，不依赖 `yingmi-skill-cli`；操作清单取官方 docs.json（缓存 6h）
- 凭据：`~/.yingmi-skill-cli/config.json` 的 apiKey（`Authorization: Bearer`）
- 已收敛高层入口（优先走，勿重复透传）：GuessFundCode/GetFundDiagnosis/SearchFunds/DiagnoseFundPortfolio/GetAssetAllocationPlan
- 批量/列表类工具（GetPopularFund/Batch*）返回 JSON 数组，适配器已支持

### ttskill — 天天基金业务包（透传，37 包可达，直连 gateway）

```bash
invest-cli ttskill <skill_id> --input '<json>' [--json]
```

- **直连官方 gateway**（POST /openapi/skill/invoke），不依赖 ttskill CLI；
  沿用官方凭据存储（macOS Keychain `com.ttfund.ttskill.base`）与 ed25519 签名（官方同一套认证）
- 常用：`TTFUND_MANAGER_INFO`（经理画像/在管）、`TTFUND_NAV_INFO`（历史净值）、`TTFUND_STOCK_PRICE_QUERY`（实时行情）、`TTFUND_MACRO_DATA`（中美宏观）、`TTFUND_VALUATION_MAP`（指数/行业估值分位）
- 参数以官方包 `examples/*.example.json` 为准；返回为原始结构（各包层级不一，透传不解释）
- fund 深取层内嵌 SEARCH/BASE_INFOS/HOLDING_INFO（走 `fund <code>`，勿手动透传）；黄金走 `intent deep commodity`
- 账户/交易类包（ACCOUNT_*/TRADE_QUERY/CONDITION_ORDER/SIM_TRADE/RATION_PLAN/SUBACCOUNT）为边界外：invest-cli 数据链路不消费，不建高层入口
- 全套 37 包用途与收敛标注：`invest-cli capabilities ttskill`
- 口径真源 = `invest-fund/references/data-pipeline.md` + `sources/ttskill.py`；差距与收敛进度见 `docs/capability-gap.md`。老 ttfund CLI 已于 2026-09-03 退役，能力由官方业务包取代；分析 skill 不要绕过 invest-cli 直接调官方包。
### htbr — 华泰柏瑞ETF事实查询（透传，72 接口，聚源底座）

```bash
invest-cli htbr <api_id> --input '<json>' [--json]
invest-cli htbr --list                 # 语义别名 → api_id
```

- **透传 htbr-etf-skill**（`scripts/api_client.py invoke`），不重写其鉴权、取数与校验逻辑
- 覆盖：基金档案/费率/规模、基金经理（含季报观点原文）、净值业绩、收益风险、
  持仓与申万一级穿透、ETF 申赎资金流、指数成分与盈利预测等 72 个接口
- **不进快照链**（route_kinds 为空）：由本命令直取
- 凭据：`~/.htbr/credentials.json`（htbr 包内 `config.py` 唯一读取，**不读** `HTBR_API_KEY`）；需内网/VPN
- 接口可用性：51 个放行、21 个 404 未开放（明细见 `invest-cli htbr --list`）；未开放如实报 404，不拼凑替代
- 参数口径以 htbr 包内 `references/apis/<api_id>.md` 为唯一真源（三套代码口径极易串用，调用前必查）
- 别名见 `invest-cli htbr --list`；常用：`basic`、`viewpoint`、`industry-dist`、`earning-forecast`


### sfg — 见基行事(seefundgo) 公募基金 MCP（透传，45 工具）

```bash
invest-cli sfg <工具|别名> --input '<json>' [--json]
invest-cli sfg --list                     # 语义别名 → 工具名
invest-cli sfg portfolio-submit --input '{"codes":["005827.OF"]}'
invest-cli sfg --poll <job_id>            # 轮询组合诊断结果
```

- **透传见基行事 MCP**（Streamable HTTP 会话式），不重写上游口径；`--list` 看别名
- 覆盖：全市场 14000+ 公募基金/ETF/指数、6900+ 经理——档案/净值/业绩/风险/
  持仓穿透/经理画像/选基/排行榜/ETF 资金流/组合体检
- **不进快照链**（route_kinds 为空）：由本命令直取；自然语言入口 `intent sfg`
- **积分制**（余额 0 时全工具被拒）：只做妙想没有的**垂直深取**（经理画像/归因/
  风格漂移/选基排行榜/组合体检）；通用基金查询走 `intent deep fund`
- 凭据：`SFG_MCP_TOKEN` 或 `~/.config/invest-cli/sfg.env`
- **代码口径**：上游要标准码（`005827.OF` / `510300.SH`），裸 6 位码直接 404；
  同一代码可能场内外并存，**不猜后缀**，先经 `sfg_search_funds` 解析再取数
- **组合诊断走异步**：同步接口有 30s 硬顶，用 `portfolio-submit` + `--poll`
  （实测 succeeded 需 300-340s，轮询上限 420s）
- 出处标注：产出必须保留「数据来源：见基行事MCP（fundfof.com）」
- 常用别名：`profile`、`holdings`、`manager`、`screen`、`rankings`、`etf`、`index`、`market`


### capabilities — 能力发现层

```bash
invest-cli capabilities [yingmi|ttskill] [--json]
```

- 取数前先查：官方（盈米 69 工具 / 天天 37 包）有什么、invest-cli 收敛到哪、怎么调——一处可见，根治"不知道有 X 能力"的重复低效
- 空参=数据源总览 + 高层入口速查；`--json` 给 skill 层做路由决策
- 只列清单不取业务数据；拿不准参数先看 `capabilities` 输出里的工具描述

### intent — 意图层（默认取数入口，收敛接口面）

```bash
invest-cli intent <deep/screen/portfolio/plan/macro/present/mxds/sfg> <参数> [--json]
```

- 把盈米 69 工具 + Wind 7 类 + 见基行事收敛为语义入口，内部按场景 + 标的类型路由到权威源
- `intent mxds "<自然语言>"` — 妙想自然语言查询（A股/港股/美股/基金/债券/指数/宏观/新闻/公告自动路由，结果按查询文本缓存 300s）
- `intent sfg "<查询>"` — 见基行事：单只基金→档案，多只代码/名称→组合诊断（异步轮询）
- 接口面小、能力面全；`--json` 输出统一信封（source/ok/data/error）
- 推荐作为分析 skill 的首选取数方式；wind/yingmi/sfg 透传仅作高级/调试

### research — 长程研究管线（编排既取数入口，不自建数据路径）

```bash
# 主题主动基金：池构建 → 批量快照 → 排名 → 重仓×股息率交叉
invest-cli research fund-rank <主题> [--top N] [--order r3y|r1y|ytd] [--limit N] [--dy auto|on|off] [--enrich] [--out DIR] [--json]

# 指数基金横评：同一指数下的 ETF / 联接基金 → 规模/费率/跟踪误差/得分
invest-cli research etf-rank <指数代码或名称> [--top N] [--period 1m|3m|6m|1y|3y|5y] [--components N] [--limit N] [--out DIR] [--json]
```

- fund-rank 一条命令完成「池构建(TTFUND_SEARCH 分页) → 批量快照(复用 `fund` 同路径同缓存) → 多期业绩排名 → 重仓×股息率交叉(公司名合并, A/H 同司一司) → 双源互证」
- 快照并发默认 3（`INVEST_CLI_RESEARCH_CONCURRENCY` 可调；同花顺合同配额未知，调高前先小池试）
- 池规则：主动型（剔指数/货币/理财/债券/QDII）、份额类去重（留 A 类）、「改革红利/混改红利」剔除、离岸互认剔除；红利/股息主题并入「股息」别名并开启股息率交叉（妙想 ≥4%），港股通默认剔除
- **双源互证**：hithink returns vs ttskill 深取逐期对照（容差 0.05pp），不一致显式标注 ✗——业绩冠军可能不持高股息股
- `--out` 落 Markdown 报告 + result.json；`--enrich` 给 Top-N 附 argo 资讯（默认关）
- 定位：2026-10-11 十轮手工调用收敛为一条命令，97 只池排名与手工一致
- **etf-rank** 走 `TTFUND_INDEX_FUND_SELECTION`：一次取回候选指数、基金横评、前 N 大成分与指数估值。`--components` 是成分股条数（非基金条数）；按接口 `score` 排序，`score_note`/`risk_note` 原样透出；规模<2 亿单独汇总。实测沪深300 357 只（2026-11-08）

### 其余子命令速览

| 命令 | 一句话 |
|---|---|
| `invest-cli kline <代码>` | K线（分钟级自动转 westock CLI，日线原生快路径） |
| `invest-cli westock <子命令>` | 腾讯微证券透传（筹码/龙虎榜/资金流/ESG/产业链 40+ 子命令），收敛入口见 `invest-cli cn` |
| `invest-cli report <基金代码> --latest 4` | 基金定期报告 PDF 下载（季报/半年报/年报，东财源）；默认落 state 目录 `reports/<代码>/`，不进仓库 |
| `invest-cli info <查询词>` | 财经检索/资讯/舆情（走 argo，省配额） |
| `invest-cli doctor` | 运行面健康自检：数据源/运行时账本/缓存/解释器/注册软链/DSH 插件副本漂移，一条命令六个面。账本在 `~/.config/invest-cli/usage_log/calls.jsonl`：源级记每次真实取数（成败/耗时/降级链/逐源原因），命令级记每次 CLI 调用（rc/耗时，doctor 等诊断命令自身不记）；1MiB 回缩，`INVEST_CLI_USAGE_LOG=0` 可整体关闭。`invest-cli datasources` 尾部同源展示最近 24h 汇总 |

完整参数以 `invest-cli --help` 与各子命令 `--help` 为准。命令清单不在本文档手写：`test_command_surface.py` 从 `invest_cli.py` 的 `add_parser` 与 `dispatch` 用 AST 取真值并断言两者双射，新增命令时不必回来改数字。

## 数据源接入（统一门闩）

数据源声明真源为 `data-sources.yaml`（源清单与数量以该文件为准，不在文档里写死），可用性与覆盖范围由 `invest-cli datasources` 运行时探测——表格不在此复述（曾经列过 11 源的表，永远追不上 yaml，2026-10-25 删除）。启用条件（各源所需 env / 凭据路径）见下节「环境要求」；能力矩阵与字段口径见 `docs/data-sources.md`。取数与降级：单一场景优先最高优先级源，整单失败才降级，禁止跨源合并字段。

三条行为约定（表格时代就在、仍然成立）：

- **探测负缓存**：http 型（如 yfinance 的端点可达性）探测失败的源 120s 内不重探（`INVEST_CLI_PROBE_TTL_FAIL` 可覆盖）；adapter 型（同花顺/Wind/盈米/天天等凭据型）失败**也落盘**，但用短 TTL（默认 60s，`INVEST_CLI_PROBE_TTL_FAIL` 可覆盖；排障设 0 立即失效）——补凭据是秒级恢复，窗口必须短到下一分钟就能看到新结论。
- **argo 透传**：引擎名原样传给 argo（250+ 个，传错即报错、不静默换源）；清单见 argo `search.py --list-engines`。
- **免 Key 源开箱即用**：腾讯行情 / SEC EDGAR / FRED / yfinance / Bitget 无需任何配置。

## 环境要求

- `HITHINK_FINANCE_API_KEY` 或 `~/Library/Application Support/hithink-finance/credentials.env`：同花顺官方源（A 股/公募优先）
- `EASTMONEY_APIKEY`：东方财富 API Key（港股、自然语言选股、以及同花顺失败时的回退）
- `yfinance`：Python 包（us 全量快照推荐；缺省可回退 Bitget）
- `TIINGO_API_KEY` 或 `~/.config/invest-cli/tiingo.env`：Tiingo 美股 EOD（us 链兜底位 + `us --history` 专项；免费注册 https://www.tiingo.com）
- `FMP_API_KEY` 或 `~/.config/invest-cli/fmp.env`：FMP 美股深取（`invest-cli fmp`；免费注册 https://site.financialmodelingprep.com）
- `~/.htbr/credentials.json`：华泰柏瑞 ETF 事实查询（`invest-cli htbr`；Key 在 etf-skill 官网自助获取后 `config.py save-key` 保存，**不读** `HTBR_API_KEY` 环境变量；需内网/VPN 可达 htbr 服务端点）
- `SFG_MCP_TOKEN` 或 `~/.config/invest-cli/sfg.env`：见基行事基金 MCP（`invest-cli sfg`）
- Python 3.9+（兼容下限，公开仓承诺）。本机运行时统一 skill 自带 venv（版本由
  `invest-cli doctor` 自报）：
  mx-data 被任意解释器启动时会自动 exec 进 venv（`MX_DATA_NO_REEXEC=1` 可关），
  系统 3.9 已 EOL（2025-10）不再进热路径。改动仍不得引入 3.10+ 语法
  （如 `zip(strict=True)`、`match`）——venv 缺失时任意 3.9+ 解释器都是合法兜底，
  两套门禁（`test_py39_compat` / `test_static_imports`）钉住这一点。
