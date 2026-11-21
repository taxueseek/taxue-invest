# invest-cli 数据源与能力矩阵

本文件是 invest 系列**数据层**的接入说明与能力矩阵。投资分析 skill 只负责「怎么想」，数据层（invest-cli）负责「怎么取」，二者分离。

- 数据源声明真源：`../data-sources.yaml`（新增/修改数据源只改它，不重写适配器）
- 可用性探测：`invest-cli datasources`（统一门闩，运行时才判定）
- 取数命令：`invest-cli <源> <标的/工具> ...`，统一输出 JSON

---

## 数据源总览

| 数据源 | 类型 | 覆盖场景 | 优先级 | 启用条件 |
| --- | --- | --- | --- | --- |
| Wind（万得，直连 MCP） | API | stock / fund / index / bond / news / macro / analytics | 80 | 有 `WIND_API_KEY`（`~/.wind-aifinmarket/config` 或环境变量） |
| 盈米（且慢，直连 OpenAPI） | API | fund / strategy / wealth / news | 70 | `~/.yingmi-skill-cli/config.json` 有 apiKey |
| 同花顺金融数据服务 | API | stock / fund（A 股与公募） | 60 | `HITHINK_FINANCE_API_KEY` 或用户级 `credentials.env` |
| 东方财富 | API | stock / fund / screen | 50 | 设置 `EASTMONEY_APIKEY` |
| Yahoo Finance（yfinance） | python | us | 40 | 安装 `yfinance` |
| SEC EDGAR（美股财报原文） | API | us 财报原文（10-K XBRL 指标 + 申报清单） | 45 | 免费无 key（可选 `SEC_EDGAR_USER_AGENT` 声明身份）；`invest-cli sec <代码>` 直取，不经快照链 |
| Financial Modeling Prep（fmp） | API | us_fundamentals / us_estimates / us_rating / dividends；us 链末位兜底 | 34 | `FMP_API_KEY` 或 `~/.config/invest-cli/fmp.env`；`invest-cli fmp <代码>` 深取；快照只在 yfinance/腾讯/Tiingo/Bitget 全败时使用（免费档 250 次/天，一次快照 5 请求） |
| Tiingo（美股 EOD） | API | us / eod_history | 36 | `TIINGO_API_KEY` 或 `~/.config/invest-cli/tiingo.env`；EOD 历史专项 `invest-cli us <代码> --history` |
| Bitget rToken | API | us（仅行情） | 35 | 始终可用（公开 API，无 key，stdlib） |
| 易方达指数直通车（index_hub） | API | fund / index 的 ETF 详情与规模 | 65 | `INDEX_HUB_API_KEY` 或 `~/.config/index-hub/api_key`；仅 `invest-cli fund --analytics` 增强项，失败静默跳过，不进快照链 |
| 首趋E指（etfirst） | CLI | ETF 详情 / 估值 / 行业分布 / Wind 排名 | 63 | 可选外部 CLI；未安装时自动跳过，只服务 `fund --analytics`，不影响任何主链 |
| 天天基金（直连 gateway，可选深取引擎） | API | fund（同类分位/机构占比/在管列表深取） | 55 | 官方凭据未过期（Keychain）+ 已装业务包；缺省自动跳过（主路=自带 hithink>eastmoney） |
| 华泰柏瑞ETF（htbr，透传 htbr-etf-skill） | API | fund / index / etf / fund_manager / industry_distribution / earning_forecast / capital_flow | 62 | `~/.htbr/credentials.json`（htbr 包内 config.py 读取，**不读** `HTBR_API_KEY` 环境变量）+ 内网/VPN 可达 htbr 服务端点（域名以内网为准，见 htbr 包内文档）；`invest-cli htbr` 直取，不进快照链 |
| 见基行事（sfg，透传 seefundgo MCP） | API | fund / etf / index / manager / screen / ranking / portfolio / market | 64 | `SFG_MCP_TOKEN` 或 `~/.config/invest-cli/sfg.env`；`invest-cli sfg <别名>` / `intent sfg` 直取，不进快照链。**积分制**：余额 0 时全工具被拒，只做妙想没有的垂直深取（经理画像/归因/风格漂移/选基排行榜/组合体检），通用取数走 mxds。上游要标准码（`005827.OF`/`510300.SH`），裸码先搜索解析；组合诊断走异步 submit + 轮询（实测 300-340s） |

优先级的含义：同一**问题**有多个数据源可用时，按优先级从高到低选取；高优先级源失败才整单降级。yaml 的 coverage 只是声明；适配器必须暴露 `stock()` / `fund()` / `us()` / `screen()` 才会进入默认快照链。Wind 声明覆盖 stock 但只有 `call()`，因此**不会**出现在 `invest-cli stock` 里。`route_kinds` 为空（wind/yingmi/htbr/sfg/index_hub/etfirst 等）表示只经具名命令直取，priority 仅用于展示排序，不参与快照链。

运行时链由 `scripts/sources/route.py` 计算，`invest-cli datasources` 打印。不要在各 cmd_* 里再写一套 if/else。

---

## 能力矩阵（数据源 × 场景）

| 场景 | Wind | 盈米 | 同花顺 | 东财 | 天天官方 ttskill | yfinance | Bitget |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 个股行情/估值（A股） | 强 | — | 强（官方 REST） | 强 | — | — | — |
| 个股行情/估值（港股） | 强 | — | — | 强 | — | — | — |
| 个股财务（近 5 年年报） | 强 | — | 强 | 中（最新一期） | — | — | — |
| 选股（多条件筛选） | 强 | — | — | 强（自然语言） | — | — | — |
| 美股行情 | 强 | — | — | — | 强 | 中（rToken/USDT，非官方价） | — |
| 美股财务 | 强 | — | — | — | 强 | — | — |
| 基金净值/业绩/风险 | 强（复权净值，单次 100 行硬顶需分段） | 强 | 强 | 强 | 强（成立来全量 1 次调用；成立后前 6 周为周频、日增长率 2 位小数） | — | 中 |
| 基金重仓/持仓穿透 | 强 | 中 | 强 | 强 | — | — | 中 |
| 基金经理画像/产品对比 | 强 | 中 | 中（经理列表） | 中 | 强（MANAGER_INFO：在管清单含任职日/规模/任职回报） | — | — |
| 策略/组合筛选 | 中 | 强（策略、持仓） | — | — | — | — | — |
| 财富规划/资产配置 | 中 | 强（wealth-* 场景） | — | — | — | — | — |
| 宏观/行业/汇率指标 | 强（economic_data） | 中 | — | — | — | — | — |
| 财经资讯/舆情/经理观点 | 强（financial_docs） | 强（content/*） | — | 中 | — | — | — |
| 债券/转债 | 强（bond_data） | 中 | — | — | — | — | — |

同一格内越靠前越推荐；`—` 表示该源基本不覆盖该场景。

---

## 取数与降级约定

1. **取数走命令，探测走内部**：`stock/fund/us/screen/intent` 内部由 `route.pick` 做准入（coverage × 真方法 × detect）。`datasources` 是诊断命令，不要当作每次取数的前置——它会额外探测 Wind/盈米等 CLI，把一次茅台查询拖成十几秒。
2. **单源优先，整单回退**：一个场景优先用最高优先级源一次性取全；失败才降级到下一可用源，禁止跨源合并字段。
3. **逐项探针**：同一源需要批量标的时，先发第一个作探针，成功才继续其余；探针返回错误中止该批。
4. **口径标注**：数据来自哪个源必须在输出里标注，冲突字段并列，禁止口径未对齐合并。
5. **Wind 接口错误**：`AUTH_ERROR`、`RATE_LIMIT_ERROR`、`backend_error` 等必须原样报告，不得用其它源掩盖，也不得切换到 `analytics_data` 伪装支持。

---

## 数据源成本与降级链

数据源按「精确度 × 成本」分两类，取数优先结构化权威源，配额不足降级到检索源：

| 类别 | 数据源 | 特点 | 用在哪 |
| --- | --- | --- | --- |
| 结构化权威 | 盈米 / Wind / 同花顺 / 东财 / yfinance / SEC EDGAR / FMP / Tiingo / Bitget(rToken 行情) | 精确但限额、部分需 key（SEC 免费无 key） | 净值 / 行情 / 财务 / 财报原文 / EOD 历史 / 筛选 / 配置 |
| 检索资讯 | argo（eastmoney/zhihu/cninfo/财经垂直源） | 广覆盖、低成本、需核验 | 资讯 / 舆情 / 宏观背景 / 观点；结构化源兜底 |

**降级链**：结构化源 → 同域其他结构化源 → `invest-cli info <词>`（argo 检索，结果需核验）。
**省配额**：资讯 / 舆情 / 宏观背景优先用 `invest-cli info <词>`，把盈米 / Wind 的配额留给结构化数值取数。
**取代关系**：`invest-cli intent` 是主取数入口（分析层不再直接依赖盈米/Wind skill，二者降为后端数据源）；argo 仅作检索资讯与兜底。

### argo 财经垂直源池

`invest-cli info <词> --engine <源>` 可从 argo 的垂直源取数，把盈米/Wind 配额留给结构化取数。

**引擎清单不在 invest-cli 维护**：argo 自带 250+ 引擎且随版本演进，任何本地白名单都会
漂移（曾出现白名单里的 `cn-web-search` 已不存在 → 用户拿到「0 结果 + ok=true」的静默空答复；
合法引擎如 anysearch 被静默换成 eastmoney）。现在引擎名原样透传，传错会明确报错：

```bash
python3 <argo>/scripts/search.py --list-engines          # 全部引擎
python3 <argo>/scripts/search.py --list-engines --detail # 含 key/熔断/可路由状态
```

投资场景常用的几个：

| 引擎 | 领域 | 备注 |
| --- | --- | --- |
| eastmoney / cninfo / cn_ai_news | 东财资讯 / 上市公司披露 / AI 资讯 | 免 key，`info` 默认 eastmoney |
| jin10 / cls_telegraph / em_flow / em_global_news / em_miaoxiang | 财经快讯 / 资金流 / 全球资讯 | 免 key |
| finviz / fx_rate / gdelt / coingecko | 美股可视化 / 汇率 / 全球事件 / 加密 | 免 key |
| nbs_stats | 国家统计局（GDP/CPI/工业等） | 免 key，`intent macro` 的 argo 兜底引擎 |
| zhihu / anysearch | 中文观点 / 通用中文检索 | 免 key |
| fred / eurostat / eu_opendata / worldbank / fr_opendata | 欧美官方统计 | 需各自 key；未配置时 argo 会给出原因 |

`intent macro` 取数顺序：**FRED 结构化净流动性优先**（`sources/fred.py`，有 key 走官方 API、
无 key 走 fredgraph.csv），失败或取不到净流动性时才降级为 `info --engine nbs_stats` 检索兜底。

---

## 配置方法

### 同花顺金融数据服务（A 股 / 公募优先）

统一凭据（不要写进仓库或对话）：

```bash
export HITHINK_FINANCE_API_KEY=你的_key
# 或用户级文件（macOS）：
# ~/Library/Application Support/hithink-finance/credentials.env
```

启用能力：`invest-cli stock`（A 股）、`invest-cli fund`。港股、自然语言选股、美股不走此源。
A 股个股降级链：Wind（透传）→ 同花顺 → 东财。基金 intent：盈米 → 同花顺 → 东财。
名称消歧走官方 search，禁止猜测 `.SH` / `.SZ` / `.OF`。null 不补零。跨源禁止混字段。

### 东方财富（A股/港股/基金快照、选股）

```bash
export EASTMONEY_APIKEY=你的_key
```

启用能力：`invest-cli stock/fund/screen`。

### 美股

```bash
uv pip install yfinance
```

启用能力：`invest-cli us`（yfinance 全量快照：估值/财务/评级）。

**Bitget rToken 报价兜底**（无需配置）：公开行情 API，stdlib 即可。未装 yfinance 或取数失败时，`invest-cli us` / `intent deep us` 自动回退，输出为 USDT 代币价（`quote_type=rtoken`），**不是**美股交易所官方报价。美股行情降级链：**yfinance → 腾讯行情 → Tiingo → bitget**（Wind 只走 `invest-cli wind` 透传，不在快照链上，运行时链以 `invest-cli datasources` 的 `_chains` 为准）。

### Tiingo（美股 EOD：官方收盘价/复权历史/估值序列，免费档）

```bash
export TIINGO_API_KEY=...   # 或用户级文件 ~/.config/invest-cli/tiingo.env（TIINGO_API_KEY=...）
```

- **免费档实测边界（2026-09-29）**：EOD 日线（OHLCV + adjClose + divCash + splitFactor）、
  标的元数据、日频估值序列（市值/PE/PB/PEG，约 3 年）、IEX 桥收盘报价（tngoLast）可用；
  **新闻与三表在付费墙内**——美股财报走 SEC EDGAR，别在 Tiingo 上找
- **链上位次（36，tencent 37 与 bitget 35 之间）**：收盘口径压不过腾讯实时（盘中查快照
  腾讯价更新），但官方交易所数据严格优于 rToken 代币价
- **专项入口**：`invest-cli us <代码> --history [--years N]`——EOD 历史 + 分红/拆股/回撤
  摘要。快照链其余源都不给可靠复权历史，这是 Tiingo 在本仓的**独有贡献**

### 腾讯行情（零鉴权，多市场实时行情）

无需任何配置。`qt.gtimg.cn` 公开行情接口，一次请求可带多个标的（逗号分隔），
覆盖 A股/港股/美股/ETF/可转债/指数。

- **优先场景**：`invest-cli quote <代码...>`（纯行情，实测 6 标的混合 132ms）
- **兜底场景**：`us` 链的兜底位（yfinance 不可达时 130ms 给出真实美股行情，
  而 bitget 只有代币成交价、无 PE/PB/ROE/市值）；A股/港股链的末位
- **能力边界**：**没有基本面**（净利润/ROE/EPS/资产负债率一项都没有），
  因此不占主位——`stock`/`us` 的主位必须留给带基本面的富源，否则是能力降级
- **不含基金**：`fund` 链不走腾讯。场外基金号码与沪市可转债共用号段
  （110011 既是易方达中小盘也是歌华转债），行情接口只覆盖后者，
  直接查会**返回另一个标的**；适配器对这类输入直接拒绝并指向 `invest-cli fund`
- **口径注意**：qt 返回的字段下标**按市场不同**（市净率 A股在 [46]、美股在 [51]；
  换手率 A股在 [38]、港股在 [59]；成交额 A股是万元而港美股是元）。
  适配器按市场分表并只登记已用独立源核对过的下标，见 `scripts/sources/tencent.py`

### SEC EDGAR（美股原文级数据，免费官方源）

无需任何配置（SEC 官方公开 API）。建议设置真实联系方式（SEC 要求 UA 含邮箱，www.sec.gov 域不带邮箱会 403；默认用占位邮箱通过校验）：

```bash
export SEC_EDGAR_USER_AGENT="your-name your@email"
invest-cli sec AAPL                       # 快照：24 项指标 + 近 5 年序列 + 申报清单
invest-cli sec AAPL --json                # 结构化（给分析层）
invest-cli sec AAPL --quarterly --years 8 # 附季度序列（Q4 为推导值，标 derived）
invest-cli sec AAPL --search "supply chain" --forms 10-K --limit 5   # 全文检索 + 原文段落
invest-cli sec AAPL --insiders --days 90  # Form 4 内部人交易逐笔
invest-cli sec AAPL --events --days 365   # 8-K 逐事项 + 13D/13G 权益变动
invest-cli sec BRK --holdings             # 13F 机构持仓（机构名/CIK/代码均可）
```

- 快照：24 项年报指标（含负债/现金/资本开支/回购分红/研发/流通股数；自由现金流为派生，只在同期间两值都在时产出）+ 近 N 年年度序列（三关趋势表直接可用）+ 申报清单
- 全文检索：EDGAR full-text search（`efts.sec.gov`，2001 年起全部申报）；多词自动按短语检索；前 5 条命中拉原文抽段落（抽不到留空，不编造上下文）
- 内部人：Form 4 XML 逐笔解析（交易代码 → 中文标签、买/卖方向、交易后持股），含期权行权与代扣税行
- 事件：8-K 的 `items` 字段逐事项展开（业绩发布 2.02 / 高管变动 5.02 / 协议 1.01 / 减值 2.06 / 退市 3.01…）+ 13D/13G 权益变动
- 13F：按 (CUSIP, put/call) 聚合（同一 CUSIP 多子管理人分行申报会合并），带占比；金额单位随申报期标注（SEC 2023-01 起改美元，此前为千美元）
- 口径：只取 `form=10-K` + `fp=FY`；时长型事实限 300~400 天（季度值不进年度结果）；标签漂移按优先级回退；四个动作旗标**互斥**（一次只做一件事）
- 缓存：`~/Library/Caches/invest-cli/sec/`（ticker 映射 7 天、companyfacts 24h、submissions 6h、申报原文 7 天、全文检索 1h）
- 边界：仅美股发行人；20-F（外国私人发行人）与基金 N-CSR 不在覆盖内，会明确报错；13F 只含美国多头与期权（不含空头）
- 定位：与 Wind / yfinance 数字交叉验证的原文级依据；**不经快照链**（`route.pick` 只认 stock/fund/us/screen 方法）

### FMP（美股深取：三表 JSON/TTM 比率/结构化评级/年度预测，免费档）

```bash
export FMP_API_KEY=...   # 或用户级文件 ~/.config/invest-cli/fmp.env（FMP_API_KEY=...）
```

- **免费档边界（2026-09-30 实测，/stable 版）**：quote（50/200 日均线）、profile
  （sector/industry/CEO/员工/CIK/ISIN/上市日）、三表 annual、key-metrics-ttm（EV 系）、
  ratios-ttm（利润率/流动性/杠杆/股息；**ROE/ROA=null**，免费档不给）、
  ratings-snapshot（字母评级 + DCF/ROE/ROA/负债/PE/PB 六维分项分）、
  analyst-estimates（**annual 通，quarterly 402**）、dividends 历史 + 市场级分红日历、
  historical-price-eod/full（约 5 年）。**锁**：etf-holdings 明确付费墙；
  peers/press-releases/insider-trading/sec-filings 在 stable 下 404
- **错误形态**：缺/坏 key → 401；付费端点 → 402 "Restricted Endpoint"；
  **查无此票 → 也是 402**（"Premium Query Parameter"），适配器按文案分流成「未找到标的」；
  超限 → 429 文案里带 250 次/天
- **定位**：深取专项（priority 46，sec_edgar 旁边），**不进快照链**——250 次/天
  扛不住日常兜底消耗，一次深取 3-5 个请求。与 sec_edgar 分工：sec 原文级（官方免费），
  fmp 加工好的比率/评级/预测；与 yfinance/Tiingo 数字交叉验证

### CN 市场结构（`cn` 子命令：westock 高频五个 + 巨潮检索）

```bash
invest-cli cn notice 600519 --limit 20       # 公告列表（可 --type 过滤、--offset 翻页）
invest-cli cn notice --search "会计政策变更"  # 巨潮（cninfo）关键词检索，走 argo
invest-cli cn consensus 600519,000858        # 一致预期（目标价 + 年度预测）
invest-cli cn holders 600519                 # 股东研究（十大股东 + 变动）
invest-cli cn disclosure 600519              # 财报披露日历（预约披露日）
invest-cli cn report 600519 --limit 20       # 研报列表
```

- 数据源：westock（腾讯微证券）对应子命令；`--search` 走 argo 的 `cninfo` 引擎（**不**自建巨潮抓取，先复用 argo；覆盖不足再考虑直连接口）
- 结构化：`--json` 把 westock 的 markdown 表格解析成 `tables[].rows`（按字段取值），**原文始终保留在 `raw`**（解析失败不丢数据）；终端仍按表格展示
- 降级：公告列表在 westock 通道故障时回退 argo/cninfo 检索，并在 `note` 里标明「检索非完整清单」
- 代码归一：逗号分隔多代码逐个归一（`600519,000858` → `sh600519,sz000858`），中文名可直用
- 收敛登记：`invest-cli capabilities westock` 列已收敛的五个；长尾 40+ 子命令仍走 `invest-cli westock <子命令>` 透传（chip/lhb/events/industry-chain…）

### FRED（宏观时序，可选 key）

```bash
invest-cli intent macro            # 净流动性三序列（WALCL/TGA/ON RRP）+ SOFR
```

- 有 `FRED_API_KEY`（环境变量或 `~/.config/invest-cli/fred.env`）：走官方 API
- 无 key：自动回退 `fredgraph.csv` 免 key 通道（同源同口径，内置 3 次重试）；输出 `transport` 字段标注走了哪条通道
- 长期使用建议免费注册 key（https://fred.stlouisfed.org/docs/api/api_key.html ，约 2 分钟）

### 万得 Wind（机构级，直连 MCP）

只需要一个 Key，**不需要安装 wind-mcp-skill 的 node CLI**。Key 顺序与官方一致：

```bash
export WIND_API_KEY=<你的Key>      # 或写入 ~/.wind-aifinmarket/config
```

启用能力：`invest-cli wind <server_type> <tool> --input '<json>'`。
server_type：stock_data / fund_data / index_data / bond_data / financial_docs / economic_data / analytics_data。

### 盈米且慢（基金/策略/财富/资讯，直连 OpenAPI）

只需要 apiKey，**不需要安装 `yingmi-skill-cli`**（仍沿用它的凭据位置）：

```json
// ~/.yingmi-skill-cli/config.json
{"apiKey": "<你的apiKey>"}
```

启用能力：`invest-cli yingmi <tool> --input '<json>'`。操作清单取官方 docs.json（磁盘缓存 6h），不在本地维护第二份。

### 天天基金（直连 gateway）

**不需要安装 ttskill CLI**：直接调官方 gateway（`POST /openapi/skill/invoke`），认证沿用官方凭据存储（macOS Keychain `com.ttfund.ttskill.base`）与 ed25519 签名（与官方基础包同一套逻辑）。只需完成一次官方登录（用官方基础包或任何写同一 Keychain 的工具）。

invest-cli 只暴露两处入口，Agent 不直接管理 37 个业务包：
- `invest-cli fund <代码/名称>`：三关快照（SEARCH/BASE_INFOS/HOLDING_INFO；链位 55，登录就绪才参与，主路仍是自带 hithink）
- `invest-cli intent deep commodity ...`：黄金 → `TTFUND_GOLD_INFO`
- 其他包透传：`invest-cli ttskill <skill_id> --input '<json>'`（清单 `invest-cli capabilities ttskill`）

字段口径真源：invest-fund `invest-fund/references/data-pipeline.md` + `sources/ttskill.py`。

---

### 见基行事（sfg，透传 seefundgo 公募基金 MCP）

```bash
export SFG_MCP_TOKEN=<你的Token>     # 或写入 ~/.config/invest-cli/sfg.env
```

启用能力：`invest-cli sfg <别名> --input '<json>'`（`--list` 看 37 个别名）与
`invest-cli intent sfg "<查询>"`（单只→档案，多只→组合诊断）。

- 协议是**会话式** Streamable HTTP：initialize 后必须回带 `mcp-session-id`，
  适配器已封装（过期自动重 Initialize 一次）
- 代码口径：上游要标准码（`005827.OF` / `510300.SH`），**裸 6 位码直接 404**；
  同一代码可能场内外并存（005827 只有 `.OF`、161725 只有 `.SZ`、510300 只有 `.SH`），
  本模块**不猜后缀**，先经 `sfg_search_funds` 解析；多候选（A/C 份额）不自动挑
- 组合诊断走异步：同步 `sfg_portfolio_check` 有 30s 服务端硬顶（两只基金即超时），
  用 `portfolio-submit` 拿 job_id 后 `invest-cli sfg --poll <job_id>` 轮询
- 出处标注：产出必须保留「数据来源：见基行事MCP（fundfof.com）」
- 字段口径真源：上游 `sfg_help` 与资源 `sfg://api-catalog`，本模块不解释字段

---

## 快速自检

```bash
invest-cli datasources              # 查看各数据源是否可用
invest-cli sec AAPL                 # SEC 财报原文（免费，无需配置）
invest-cli wind stock_data get_stock_price_indicators --input '{"windcode":"600519.SH"}'
invest-cli yingmi GetCurrentTime
invest-cli sfg --list               # 见基行事别名清单
```

数据来源于万得 Wind 金融数据服务 / 盈米且慢 / 同花顺金融数据服务 / 东方财富 / Yahoo Finance / SEC EDGAR / Bitget rToken。
