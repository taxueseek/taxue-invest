# Invest 系列：投资分析指南

买基金像请管家，买股票像合伙做生意。不懂的人、不靠谱的人、要价太高的人，都不能托付。

这个工具帮你三件事：**看清投的是什么，判断值不值得投，确定价格合不合适**。

**支持一组可插拔数据源（API）与 11 个分析方法论**：
- **数据源**：免 Key 源（腾讯行情 / SEC EDGAR / FRED / yfinance）+ 配置启用源（同花顺 / 东方财富 / 妙想 / FMP / Tiingo / Wind / 盈米 / 见基行事 MCP / 天天基金官方 ttskill / 易方达指数直通车）+ 长尾能力（腾讯微证券 40+ 子命令 / 华泰柏瑞 ETF）
- **方法论**：覆盖个股、基金、选基、单一资产（债/转债/商品/REITs）、资产配置、风险管理、企业深度、宏观环境、机构级产出、多视角会诊

---

## 快速安装，输入下列指令即可开始使用

```bash
npx skills add taxueseek/taxue-invest
```

安装后直接问 Claude：
- "这只基金怎么样？"
- "分析一下茅台"
- "黄金能买吗？"
- "让大师们看看这只股"

系统会自动识别你要分析什么，进入对应的分析流程。

> **注意**：这个工具只是帮你理清思路，不是投资建议，也不保证赚钱。用它分析后，买不买都是你自己的决定。

---

## 支持的数据源（API）

装上就能用**判断框架**。不配任何 API 也能分析（公开检索 + 你提供的材料 + 免 Key 取数通道）。数据源清单以 `data-sources.yaml` 为唯一真源（下表为常用源；全量与实时可用性跑 `invest-cli datasources`），按启用方式分三档；取数与下判断分离：

### 免 Key（装上即用）

| 数据源 | 启用能力 |
|:-------|:---------|
| **腾讯行情**（零鉴权） | `invest-cli quote` 多标的实时行情、`kline` K 线；A股/港股/美股/ETF/可转债 |
| **SEC EDGAR** | `invest-cli sec` 美股财报原文（10-K XBRL + 申报清单） |
| **FRED** | `invest-cli intent macro` 净流动性三序列（免 Key 走 CSV 通道） |
| **yfinance**（Python 包） | `invest-cli us` 美股快照（行情 + 财务 + 评级） |

### 配置后启用

| 数据源 | 配置物 | 启用能力 |
|:-------|:-------|:---------|
| **同花顺金融数据服务** | `HITHINK_FINANCE_API_KEY` | `stock` / `fund` 的 A 股与公募主路（快、字段全） |
| **东方财富** | `EASTMONEY_APIKEY` | A 股/港股快照、基金快照、自然语言选股；港股必经此路 |
| **妙想**（东方财富） | `EM_API_KEY` | `screen` 自然语言选股、`intent deep bond` 债券场景 |
| **Financial Modeling Prep** | `FMP_API_KEY` | `invest-cli fmp` 美股基本面/一致预期/评级/分红（免费档 250 次/天） |
| **Tiingo** | `TIINGO_API_KEY` | `invest-cli us <代码> --history` 美股 EOD 历史 |
| **Wind**（万得） | `WIND_API_KEY` | 机构级数据，`invest-cli wind` 透传 |
| **盈米且慢** | `~/.yingmi-skill-cli/config.json` | 基金诊断/组合/配置方案（`intent deep fund` / `portfolio` / `plan`） |
| **见基行事（seefundgo）MCP** | `SFG_MCP_TOKEN` | 公募基金垂直深取（积分制）：多因子选基、经理画像、归因、异步组合体检（`invest-cli sfg` / `intent sfg`） |
| **天天基金官方 ttskill** | 官方登录 | `fund` 快照深取补充（同类分位/机构占比/经理在管）与 `research etf-rank` 指数横评 |
| [argo](https://github.com/taxueseek/argo) | 安装 argo | `invest-cli info` 资讯/舆情、宏观检索兜底（多数免 Key，省结构化源配额） |

### 长尾能力

| 数据源 | 配置物 | 启用能力 |
|:-------|:-------|:---------|
| **腾讯微证券 CLI** | 安装 westock 二进制 | `invest-cli westock` 40+ 子命令：筹码/龙虎榜/陆股通/北向/两融/一致预期/ESG/机构评级/产业链/板块估值/可转债条款 |

**取数与判断分离**：数据层只负责「把数取回来并标明来源」，判断由 `invest-*` 框架完成。
**零配置也能跑**：不配任何 Key，仍可用 `sec`（SEC EDGAR 官方）、`us`（yfinance）、`intent macro`（FRED）三条免 Key 通道。

**和 argo 的分工**：盈米 / Wind / 同花顺 / 东财管「精确数值」，argo 管「检索资讯」——资讯、舆情、宏观背景优先走 argo 省配额，结构化源失败时也由它兜底（结果需核验）。argo 是可选项，没装则自动跳过，不影响其他能力。

**引擎名不再由 invest-cli 维护白名单**：argo 自带 250+ 引擎且随版本演进，本地名单必然漂移（曾出现名单里的引擎已不存在 → 用户拿到「0 结果 + ok=true」的静默空答复）。现在引擎名原样透传，传错会明确报错并给出清单命令。

详细步骤与排错见 **[docs/data-sources.md](docs/data-sources.md)**。

密钥只放本机环境变量或官方安全存储，不要提交到 Git。本仓库不提供券商交易，也不捆绑第三方基金聚合站 skill。

---

## 这到底是什么

不是纯数据查询工具，是一套**判断框架**（可选取数后端）。

投资最大的坑，不是信息不够，是**不知道该看什么**。这个工具告诉你：看这三样就够了。

```
用户提问
    │
    ▼
┌─────────────┐
│  invest     │  ← 识别你要分析什么
│  主入口     │
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
   ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
   │ 股票  │  │ 基金  │  │可转债 │  │商品   │  │REITs  │  │资产   │
   │三关   │  │场景   │  │三关   │  │三关   │  │三关   │  │配置   │
   │+深度  │  │路由   │  │审查   │  │审查   │  │审查   │  │       │
   └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘
       │          │          │          │          │          │
       └──────────┴────┬─────┴──────────┴──────────┴──────────┘
                       ▼
               ┌───────────────┐
               │  三关审查     │
               │               │
               │ 1. 懂不懂？   │  ← 能力圈/策略理解
               │ 2. 好不好？   │  ← 护城河/持续性
               │ 3. 贵不贵？   │  ← 安全边际/估值
               └───────────────┘
```

---

## 覆盖的分析能力

11 个方法论技能，覆盖各类分析场景。v3.0 起方法论大幅补强，并按分析对象分层：

| 你要分析 | 路由到 | 核心问题 | 适用市场 |
|:--------|:-------|:---------|:---------|
| 某只股票 | invest-stock | 懂生意吗？有护城河吗？价格合适吗？ | A股、港股、美股 |
| 某只基金 | invest-fund | 懂策略吗？能跑赢吗？成本合理吗？ | 主动基金、ETF、QDII |
| 可转债/黄金原油/REITs/债券 | invest-asset | 债券：偿付+利差+位置；可转债：条款+债底+溢价；商品：逻辑+位置+波动；REITs：底层+运营+估值 | 债市/大宗/国内外REITs |
| 整体配置 | invest-allocation | 股债比例合理吗？再平衡了吗？ | 跨资产组合 |
| 选基/基金池 | invest-pool | 风格稳不稳？能力圈在哪？行业轮动值不值得配？ | 基金组合管理 |
| 风险管理/杠杆/仓位 | invest-risk | 本金安全吗？杠杆安全吗？系统不靠意志力能撑住吗？ | 风险与纪律 |
| 企业深度/信用 | invest-enterprise | 股东治理+行业+经营+财务+信用+司法 | 单一企业主体 |
| 市场温度/流动性 | invest-macro | 钱紧不紧？市场过热吗？ | 全球流动性、美股情绪、加密底部 |
| 出研报/纪要/日报 | invest-analyst | IC 研报、电话会纪要、一致预期、行业深度、市场日报 | 机构级内容产出 |
| 拿不准？ | invest-discuss | 让多种投资思维同时审视 | 任何标的 |
| `/cli` 分析 | invest-cli | 终端数据获取 + 分析框架 | A股/港股/美股/基金 |

**方法论补强要点**（v3.0）：
- **个股**：行业生命周期判断 + 波特五力竞争格局 + 管理层与治理（诚信/能力/激励/股权结构）+ 6 种估值方法交叉验证（PE/PB/DCF/EV-EBITDA/DDM/PS）
- **基金**：基金经理七维度评分（35 分制）+ 业绩持续性检验（滚动收益/排名稳定/超额持续）+ 费率结构（6 项费率 + 30 年复利影响）+ 行业轮动基金评估
- **选基（新增）**：风格分类矩阵（5 风格 × 5 类型）+ 选基七维度 + 组合配置原则（底仓/核心/卫星/观察）
- **风险（新增）**：风险四层递进诊断 + 风险管理四层框架 + 不依赖意志力的系统设计 + 现金管理三层安全垫
- **企业深度（新增）**：15 板块（股东治理/行业/经营/财务/信用/司法）
- **配置**：投稳/投变框架 + 全天候三核心 + 组合风险度量（波动率/最大回撤/VaR/CVaR/夏普/索提诺）+ 相关性矩阵（正常 vs 危机）
- **宏观**：中国经济核心指标（PMI/CPI/PPI/社融/M2）+ 经济周期四阶段定位 + 全球央行政策协调
- **分析师**：金融文档速读引擎（5 层 MECE）+ 估值方法论选择矩阵 + 产业链分析框架

---

## 三关审查是什么

投资分析最怕什么？**该看的没看，不该看的看了太多**。

这三关把复杂的投资决策，拆成三个必答题：

### 第一关：懂不懂

不懂的东西，涨跌你都拿不住。

- 股票：这家公司怎么赚钱？客户为什么选它？
- 基金：投的是什么？策略是什么？基准是什么？
- 可转债：条款看明白了吗？下修、回售、强赎什么意思？

**这一关掉链子，直接放弃。** 不懂的不碰。

### 第二关：好不好

好东西才能持续赚钱。

- 股票：有定价权吗？ROE能持续>12%吗？现金流好吗？
- 基金：长期跑赢基准吗？经理稳定吗？风险调整后收益如何？
- 商品/REITs：底层资产质量如何？分派/收益可持续吗？

**这一关掉链子，说明是平庸标的，不值得花时间。**

### 第三关：贵不贵

再好的东西，买贵了也难受。

- PE/PB在历史什么分位？
- 如果跌30%，能承受吗？
- 现在入场，安全边际够吗？

**这一关掉链子，不是不买，是等更好的时机。**

---

## v3.2.2 增量（本版）：金融口径收口 + 新源定编 + 单源治理 + 验收自动化

从 v3.1 到 v3.2.2 完成多轮架构与金融口径治理，全面收口数据源编排、安全底座与自动化门禁。

**相对 v3.1 改进与新增能力：**
- **金融口径与跨资产路由收口**：美股默认快照链改为 `yfinance > fmp > tencent > tiingo`（`bitget` USDT 代币价移出默认股票快照链）；港股链优化为 `eastmoney > tencent > yfinance`；`intent macro` 按中美地区分流；`intent deep bond` 补齐 `wind → mxds` 降级链；`intent deep fund` 定型为 `盈米诊断 → route 结构化快照 → 妙想兜底`
- **新增数据源与能力发现**：接入见基行事（seefundgo）公募基金 MCP（`invest-cli sfg` / `intent sfg`，积分制，专攻多因子选基与异步组合体检 420s 轮询，纯关键词搜基金直走盈米省积分）与华泰柏瑞 ETF（`invest-cli htbr`）；`capabilities` 覆盖 `yingmi`/`ttskill`/`westock`/`sfg`/`htbr`；新增 `research etf-rank` 指数基金横评与 `invest-recap-card` 复盘卡片
- **单源治理与安全底座**：SSRF 四层闸统一至 `sources/_http.py`（AST 门禁锁死）；信封与健康状态词收口至 `sources/envelope.py`；命令与 DSH 插件元数据收口至 `command_registry.py`；新增 `INVEST_CLI_DISABLE_SOURCES` 停用集与 DSH 面板开关墙；`mx-data` 场景状态机单源化；依赖收口至 `pyproject.toml` + `uv.lock`
- **验收自动化与可观测性**：新增 `invest-cli doctor` 六面自检、运行时 `usage_log` 账本与空结果基线预警、`check.py` 全量门禁（770 条 Python 单测 + 30 条 DSH 插件单测 + ruff F821/F401 + 版本记账与派生校验）

**默认关闭功能的打开方式：**
- live 联网用例：`pytest -m live`（个别另有 `INVEST_LIVE=1` 二道门）
- 停用指定数据源：`INVEST_CLI_DISABLE_SOURCES=src1,src2`（或在 DSH 插件面板勾选）
- 关闭运行时账本：`INVEST_CLI_USAGE_LOG=0`；关闭解释器自动升级：`MX_DATA_NO_REEXEC=1`

**相关依赖：**
- Python 3.9+（`uv sync` 或 `pip install -r skills/invest-cli/requirements.txt`，含 PyYAML / yfinance / cryptography）
- 可选：`openpyxl`（`tenure --excel` 导出，缺失时自动降级 CSV）、Node.js 18+（DSH 插件）

**v3.1（数据源适配器迭代 + 测试扩充 + 美股支持）与 v3.0（三层架构 + 推理档位）的完整增量说明见下方 Version History 与 CHANGELOG。**

### 新增三个方法论技能

- **invest-pool**：风格分类矩阵（5 风格 × 5 类型）+ 选基七维度评分（35 分制）+ 行业轮动基金评估 + 组合配置原则（15-25 只，底仓/核心/卫星/观察）
- **invest-risk**：风险四层递进诊断（杠杆→本金→认知→心态）+ 风险管理四层框架（仓位→分散→估值→行为约束）+ 不依赖意志力的系统设计 + 现金管理三层安全垫
- **invest-enterprise**：企业深度分析（15 板块，股东治理 + 行业 + 经营 + 财务 + 信用 + 司法）

### invest-cli 同步演进（v2.8 → v2.9 + 十月）

- **新增命令**：`tenure`（经理任职期复盘，把分年度业绩/回撤 + 逐日超额从手工 14 分钟变成一条命令）、`report`（基金定期报告 PDF，`--latest 4` 一条命令拿齐四季）、`research fund-rank`（主题基金池 → 批量快照 → 排名 + 重仓×股息率交叉，97 只基金冷缓存 **45.96s**，对照手工串行约 210s，**4.6×**）、`cn` / `fmp` / `fund-class`
- **新增数据源**：妙想（东方财富，自然语言选股）、fmp、tiingo、etfirst、index_hub；`fund-classification.yaml` 三层分类器
- **热路径再降**：`stock` 缓存命中 50→**30ms**（命中路径不再 import 任何适配器）、`fund`/`us` 51-52→**40ms**
- **正确性与守卫**：修「同一件事的第二份实现」类漂移（美股代码前缀吃掉真实 ticker → 答成另一家公司；净值缓存跨窗口投毒）、自选股非原子写致静默丢失、失败信封负缓存（重复失败查询 6285→50ms）；回归 **440 → 513** 测试全绿

## v2.7 增量：热路径去白付 + 腾讯源并入

### 先量化「日常怎么用」，再动手

从 216 个真实会话提取 `invest-cli` 取数调用，**80% 的相邻调用间隔 <60s**（落在快照缓存 TTL 内）。所以日常性能等于「缓存命中路径 + 每个标的第一次取数」，冷路径才是少数。这条数据直接否掉了两个原本准备做的优化（把美股快照 TTL 拉长只惠及 4-5 次调用；港股那条 3.5s 只占 0.3% 调用），判定不改。

### 性能：热路径不再白付

快照缓存命中前，旧实现会先把整条候选链算完（YAML 解析 + 一串适配器 import，含 ssl），而缓存键与候选链无关；另有一次纯废的 yfinance 补取。修完后（缓存命中，同机交替各 5 次）：

| 命令（缓存命中） | 修改前 | 修改后 | 幅度 |
|:---|---:|---:|---:|
| `fund 110011` | 0.09s | **0.03s** | 3.0x |
| `stock 600519` | 0.08s | **0.05s** | 1.7x |
| `us AAPL` | 0.05s | **0.03s** | 1.7x |
| `intent deep stock 600519` | 0.09s | **0.05s** | 1.8x |
| 冷路径（各源首次取数） | — | 无可测量变化 | 诚实结论：被上游抖动淹没 |

### 新增：免鉴权多标的行情快路径

腾讯行情（零鉴权）并入数据层，新增 `quote` 命令：一次请求可带任意多个标的，跨 A 股/港股/美股/ETF/可转债。三个市场 **186ms**，对照旧路径同问题串行实测 **7.7s（约 41x）**；6 个标的混合 **189ms**（多标的边际成本≈0）。同时新增 `kline`（K 线，年线按自然年聚合）与 `westock`（腾讯微证券 40+ 子命令透传，补筹码/龙虎榜/北向/两融/一致预期/ESG 等长尾能力）。

腾讯**不进 `stock` / `fund` 主位**：它只有行情、没有基本面（净利润/ROE/EPS/资产负债率一个都没有），进主位就是把 A 股快照从 13 项基本面退化成纯行情，属能力降级。链序是 `us = yfinance > 腾讯 > bitget`、`stock = 同花顺 > 东财 > yfinance > 腾讯`，`fund` / `screen` 不含腾讯。

### 正确性：第四轮修 19 项 + 第五轮移植时不继承 17 类

- **代码域不匹配返回冒牌数据**（最严重）：把别的市场/类别的数据当成目标标的返回。
- **输入层失败触发跨源猜测**：同一输入可能返回两只不同基金。
- **可用性判据与凭据加载器漂移**：同花顺 / Wind 被静默移出可用链。
- **号码重叠时静默返回另一个标的**：问基金 110011，回的是「歌华转债」。
- **帮助文本 / 限流通告当数据**（退出码还是 0）：`westock macro gdp` 回 35 行帮助。
- **同一数组下标在不同市场是不同量**：`[47]` A 股是涨停价、港股是股息率，港股换手率因此恒为 0.0。改为按市场分表。
- **当日 K 冒充年 K**：年线未聚合，改为按自然年合成。
- 其他：`screen` 把「上游没答」说成「未找到结果」、`us .L` 股息率低估 100 倍、非 UTF-8 环境抛 traceback、Python 3.9 无法导入、`watchlist` 空代码写盘等。

### 回归守卫

测试 **237 → 317**，三个解释器全绿（3.14 / 3.9 / Homebrew 无依赖环境）。

## v2.5 增量：性能与判据层修复

本版不增加功能，只做两件事：**把日常取数的固定开销降下来，把「判据落在错误的层」这类缺陷修掉**。

### 性能：路由改为惰性探测（最大一笔）

旧实现在建链时**一次性探测整条链**，于是每次查 A 股都要为末位兜底的 yfinance 付一次真实 HTTPS 探测，wind 目录探测也白付。现在只做便宜的能力判定，在**即将调用某个源之前**才探测可用性；主源命中就不再碰兜底源。

| 指标（同机、清空缓存后实测） | 修改前 | 修改后 | 幅度 |
|:---|---:|---:|---:|
| A 股路由探测段（隔离） | 0.53s | **0.012s** | 约 44x |
| `stock 600519` 冷路径 | 1.52s | **0.51–0.60s** | 约 2.6x |
| `fund 110011` 冷路径 | 2.30s | **1.24–1.45s** | 约 1.7x |
| 查 A 股触发的探测次数 | 4 | **1** | — |
| 热路径（缓存命中） | 0.11–0.13s | 0.11–0.13s | 不变（已是地板） |

另去掉一处重复请求：hithink 利润表曾为拿年报年份先发一次 `limit=1` 预览，而批里本来就有同端点的 `limit=5`；现在按年报披露规律直接定位财年，猜错再补一次。

### 正确性：四处「判据选错层」

- **中文名被判成美股代码**：Python 里汉字也是 `isalpha()`，`intent deep 茅台` 会去 Yahoo 找「茅台」（实测 3.2s 白付）。判据改为 ASCII 字母。
- **盈米模糊匹配把股票判成基金**：`GuessFundCode` 是子串式匹配，「中国平安」→「华银平安中国主题灵活配置混合」、「招商银行」→「银叶投资-招商银行-宁海工业园1号」。判据从「盈米返回了东西」改为「返回的基金名与查询确有对应」。
- **空标的打满整条链**：`stock ""` 实测 3.55s 后拼出三句多源错误；现在在入口拦下，0.05s 给一句中文。
- **上游 `data.data=null` 抛裸异常**：`screen ""` 曾直接抛 `TypeError` 并打出 traceback。

### 资源：缓存不再无界增长

TTL 只决定「读时是否命中」，不删文件；SEC 的 companyfacts 单文件约 3.7MB，按查过的公司数无界累积。新增 7 天上限与写时清理，本机实测缓存目录 24MB → 11MB。

### 回归守卫

测试从 156 条增至 **171 条**，新增的每条都对应一个真实发生过的行为（含反向对照，防止「修成一律拒绝」）。

## v2.4 增量

- **argo 协作纠偏**：删除本地引擎白名单，改为向 argo 要一次合法引擎清单再校验。旧白名单里有一个早已不存在的引擎，用户拿到的是「0 结果 + ok=true」的静默空答复；同时合法引擎会被静默换成 eastmoney、`--max-results` 未透传。修完净删代码，可用引擎从 20 个变成 argo 全部 250+ 个。
- **热路径性能**：`fund` 深取（ttskill 两次子进程）此前从不缓存，主快照命中缓存后仍每次重付，**0.985s → 0.104s（9.5x）**；FRED 四条序列由串行改并发并加缓存，`intent macro` **2.380s → 0.076s 热 / 0.889s 冷**。
- **美股三条失态**：未知代码的「非空但全 None 假成功」、yfinance 库内 TypeError 外泄、原始 HTTP 响应体污染 stderr，全部归一为明确中文错误；类别股 `BRK.B` 按**事实**回退到 `BRK-B`（不按字符串形状改写，避免打断 `VOD.L` 这类交易所后缀）。
- **缓存原子性**：临时文件名带 pid，消灭「多进程共用同一个 .tmp 互相截断」这一类；自选股从缓存目录迁到用户数据目录（缓存会被系统清理）。

## v2.3 增量

- **消融式维护**：注册链 9/9 对齐（清 3 条死链）、死路由清理、命令路径统一（禁止写死个人家目录）、`watchlist` 隐藏能力文档化。
- **判定原则**：只处理经实验证据证明有价值或损坏的项，删无可证明必要性的复杂度。

## v2.2 增量

- **薄单品种四合一**：invest-bond / invest-convertible / invest-commodity / invest-reit → invest-asset（同一「三关审查」骨架 × 四种资产参数；注册数 12→9）
- **资产细则下沉**：债券/可转债/商品（含黄金十维度）/REITs 的专属三关、指标表、一票否决、时间定位、输出模板，收敛到 `skills/invest-asset/references/asset-*.md` + `commodity-gold.md`
- **数据措辞统一**：残留 `ttfund bond` / `ttfund gold` 老 CLI 措辞改为 `intent deep bond` / `intent deep commodity`（官方 TTFUND_GOLD_INFO 已封装进 intent）
- **invest-cli 演进同步**：退役 cmd_ttfund.py / ttfund.py，接入 ttskill 官方源 + hithink/bitget/route 回退链与契约测试（本地 09-03 多笔修复：hithink 部分失败整单回退、探测缓存等一并入包）
- **引用面消毒**：invest 入口路由/图谱、README、CHANGELOG、macro/allocation/analyst 分工表全部改指 invest-asset；历史原文见本地 `~/.claude/skills-archive/2026-09-03_merged-invest-asset/`

## v2.0.5 增量

- **配置门闩**：东财 Key / yfinance / 可选 ttfund 探测通过后，才启用对应 CLI 取数
- **invest-cli 加固**：路径可移植、字段别名、JSON 契约、易方达蓝筹映射 **005827**、友好「如何启用」报错
- **数据源文档**：`docs/data-sources.md`（东财 + 美股 + 天天基金引导）
- **路由消毒**：公开包仅 9 件套框架 + invest-cli；死链 skill 清理

## v2.0 功能亮点

### 个股分析统一入口

原来 A股、港股、美股分别用不同 skill，现在统一为 `invest-stock`：

| 能力 | 说明 |
|:-----|:-----|
| 三关审查 | 默认模式，A股/港股通用 |
| 四维评分 | 美股自动切换，ROE/负债/FCF/护城河 → A-D评级 |
| 机构深度 | 说"深度分析"进入，DCF估值+同行比较+IC Memo |
| 港A增强 | A股/港股自动附加政策敏感度、AH溢价、南北资金流检查 |

### 基金分析场景路由

不再一套流程走到底，根据你的问题自动选路径：

| 场景 | 触发 | 核心判断轴 |
|:-----|:-----|:-----------|
| 同经理多选一 | "张坤的几只基金选哪个" | 选最像经理本人的那只（管理时间最长/规模适中/机构占比高） |
| 跨基金横向对比 | "A基金和B基金哪个好" | 多维度对比打分 |
| 行业主题 | "新能源基金怎么样" | 经理-行业匹配度 > 行业β |
| 次新基金 | "这只新基金能买吗" | 经理推断 + 公司基因 |
| ETF | "沪深300ETF" | 费率 + 跟踪误差 + 流动性 |
| 标准体检 | "这只基金怎么样" | 完整三关审查 |

### 大师会诊

四种投资思维同时审视一个标的，暴露单一视角的盲区：

| 视角 | 核心问题 |
|:-----|:---------|
| 生意视角 | 懂这门生意吗？有护城河吗？ |
| 趋势视角 | 价格反映了多少乐观？有催化剂吗？ |
| 配置视角 | 占多少仓位？能承受多大回撤？ |
| 反向视角 | 最可能亏钱的三个场景？ |

支持两档深度：快速扫描（默认）和深度质问（重仓前自检）。

### 投资分析 CLI

终端直接取数，输出快照或 JSON（统一入口 `invest-cli`；PATH 无该命令时用 `"$HOME/.local/bin/invest-cli"` 兜底）：

```bash
invest-cli stock 600519          # A股/港股：行情 + 估值 + 五年财务
invest-cli fund 110011           # 基金：净值/业绩/回撤/费率/经理/重仓
invest-cli us AAPL               # 美股：估值 + 财务 + 评级
invest-cli quote 600519,00700,AAPL   # 免鉴权多标的实时行情（跨 A股/港股/美股/ETF/可转债）
invest-cli kline 600519 --period day # K 线（腾讯原生快路径，年线按自然年聚合）
invest-cli westock chip 600519   # 腾讯微证券长尾能力透传（40+ 子命令）
invest-cli sec AAPL              # 美股财报原文（SEC EDGAR，免费无 Key）
invest-cli screen "市盈率低于10的银行股"   # 自然语言选股
invest-cli intent macro          # 宏观：净流动性三序列（免 Key 通道）
invest-cli info 茅台             # 资讯/舆情（走 argo）
invest-cli datasources           # 排查「为什么没数据」：各源可用性与默认快照链
```

加 `--json` 输出结构化数据给 Agent 解读；不加则输出终端表格。同一问题不混源，单个源失败整单回退到下一个，并在结果里标明来源。

---

## 跟普通分析有什么区别

| 普通做法 | 这个工具 |
|:---------|:---------|
| 给一堆数据，让你自己判断 | 告诉你该看什么，不该看什么 |
| 预测明天涨不涨 | 不预测，只评估"值不值得持有" |
| 复杂的评分体系 | 简单的通过/未通过/观望 |
| 手动更新年份数据 | 自动计算当前该看什么报告 |
| 只看收益率 | 看风险调整后收益（夏普、卡玛比率）|
| 单只产品分析 | 支持资产配置视角 |

---

## 设计理念

### 1. 大道至简

投资不需要复杂的模型。巴菲特看企业就看三点：懂不懂、好不好、便不便宜。这个工具把这个思路扩展到所有资产类型。

### 2. 不替决策

工具只提供分析框架，决策权完全交还给你。不告诉你"买"或"卖"，只告诉你"这一关过了吗"。

### 3. 动态时间

不用手动改年份。输入当前日期，自动算出该看N年报告还是N-1年报告，数据新鲜度是多少。

### 4. 大师视角

拿不准的时候，启动投资圆桌。让生意视角、趋势视角、配置视角、反向视角四种思维同时审视同一个标的，发现你自己看不到的盲区。

---

## 实际使用示例

### 分析一只股票

```
你：分析一下腾讯 00700

系统：分析腾讯(00700)，进入invest-stock。

三关审查结果：

| 关卡 | 结果 | 关键发现 |
|------|------|----------|
| 懂不懂 | 通过 | 游戏+广告+投资，三块业务清晰 |
| 好不好 | 通过 | 护城河深厚，ROE持续>15%，现金流充沛 |
| 贵不贵 | 观望 | PE在历史70%分位，安全边际不足 |

综合判断：等估值回落到PE<25再考虑。
```

### 分析一只基金

```
你：张坤的基金怎么样？

系统：分析张坤的基金，进入invest-fund。

关键发现：
- 代表作管理5年+，穿越牛熊周期
- 重仓股重合度>80%的几只基金，选费率最低的
- 当前规模>100亿，灵活性受限，超额收益可能下降

建议：如果是张坤的粉丝，选他管理时间最长的代表作。
```

### 资产配置检视

```
你：我的资产配置合理吗？

系统：进入invest-allocation。

战略配置建议（基于你能承受20%回撤、投资期限5年+）：
- 股票：60%
- 债券：30%
- 商品：10%

再平衡规则：
- 每季度检查一次
- 某类资产偏离目标±5%时触发再平衡

当前你的组合偏离：股票超配15%，建议减仓股票或增配债券。
```

### 投资圆桌

```
你：让大师们看看茅台

系统：启动大师会诊，四种视角并行扫描。

生意视角：茅台是理想生意，品牌护城河罕见，定价权极强...
趋势视角：当前价格包含太多乐观预期...
配置视角：如果仓位>10%，波动风险需关注...
反向视角：最可能亏钱的场景是...

共识：生意模式顶级，但当前价格安全边际不足。
```

---

## 使用之前，你要知道

这个工具像字典——帮你认字，但不替你写作文。具体来说：

**第一，盈亏自负。** 这个工具不会告诉你买哪只股、卖哪只基金，也不保证你能赚钱。用它分析后，买不买、买多少，都是你自己的决定，赚了亏了都自己承担。

**第二，信息有限。** 这个工具会尽量用最新的公开数据，但数据可能滞后、可能有错。它给你的只是参考，不是标准答案。

**第三，不能替代专业建议。** 如果你有大额投资需求，应该咨询持牌的投资顾问，而不是依赖一个AI工具。

**一句话：工具只是帮你理清思路，决策在你，风险自担。**

---

## 项目结构

```
docs/
└── data-sources.md            # 可选数据源：配置后启用
skills/
├── invest/                    # 主入口：自动识别标的类型
├── invest-stock/              # 个股分析（三关审查/四维评分/机构深度/港A增强）
├── invest-fund/               # 基金分析（场景路由）
├── invest-asset/              # 单品种资产：债券/可转债/商品（含黄金十维度）/REITs
├── invest-allocation/         # 资产配置
├── invest-macro/              # 宏观与市场环境（流动性/情绪/底部信号）
├── invest-discuss/            # 大师会诊（多视角验证）
├── invest-analyst/            # 机构级内容产出（IC 研报/纪要/一致预期/日报）
└── invest-cli/                # 数据层：CLI + 多源适配器 + 回归测试
    └── docs/                  # 数据源说明 + 性能与缺陷治理报告（实测数据与复现方式）
```

---

## 版本更新记录

| 版本 | 日期 | 变更内容 |
|:-----|:-----|:---------|
| v3.2.2 | 2026-11 | 公开合版发布（汇总 v3.2–v3.8.2）：金融口径收口（美股 `yfinance > fmp > tencent > tiingo`，移出 `bitget` 代币价；港股 `eastmoney > tencent > yfinance`；宏观中美分流；债券 `wind → mxds` 兜底）；接入见基行事（seefundgo）公募基金 MCP（积分制，多因子选基/组合体检 420s 轮询，纯关键词走盈米省积分）与 `htbr`；`capabilities` 纳入 `sfg`/`htbr`；新增 `doctor`、`usage_log`、SSRF AST 门禁、`command_registry` 单源、DSH 开关墙与 `uv.lock`；测试 770 passed + DSH 插件 30 passed |
| v3.7 | 2026-11 | 隐式状态机显式化（只改结构与判据、不加功能）：**P1 场景状态机单源**——`mx-data/scripts/query_router.py` 的 `SCENARIO_COMMANDS` 此前只承载展示名与命令文本，argv 分支在 `get_data._scenario_cmd()`、取数映射在 `get_data._FETCHERS`，同一场景散在三处；现每个场景在一个表项里定义 `name`/`argv`（含占位）/`route_kind`，两处派生逻辑删除，新增 3 条用例钉住「表 = argv = 取数路由」一致。**P2 阶段编号收口**——`invest-macro` 维度 A/B/D/C 与 `invest-risk` 小节 1/2/5/3/4 的编号乱序重排为 A/B/C/D 与 1/2/3/4/5，正文未改。**P3 失效文档链接清理**——`invest-cli/docs/INDEX.md` 的 15 条链接指向已归档报告，改为指向归档目录清单，`docs/` 只留 3 份现行文档。**P4 文档表对齐代码表**——`mx-data/SKILL.md` 场景表删掉代码里不存在的 htbr 行，`test_doc_source_truth` 断言改为按 `argv` 首词校验。测试 726→729 |
| v3.6 | 2026-11 | argo v2.13.0 思路迁移五处收口（只改结构与判据、不加功能）：**P0 SSRF 旁路收口**——eastmoney 的 `requests.post` 与 mxds 的裸 `http.client` 并入共享安全闸新增的 `guarded_request`（POST 形态），此前 DNS 公网校验与禁重定向对二者完全失效；`test_http_gate.py` 用 AST 扫描钉死「生产代码不得出现 requests/http.client/裸 urlopen」。**P1 状态真源**——新增 `sources/envelope.py` 收口 5 份重复 `_envelope` 与 doctor 的 27 处状态字面量（`HEALTH_*` 常量 + `is_blocking()`）。**P2 账本交付条数**——成功记录加 `count`/`empty`，doctor 展示「交付：hithink 1 条」，可区分「慢源拖尾」与「唯一出货」。**P3 空结果基线破位**——`usage_stats` 新增 `suspected_stale`（历史曾非空 + 连续 ≥3 次空 + 跨 ≥2 查询），零新增请求。**P4 文档分层**——14 份过程报告归档 `docs-local/archive/`，`docs/` 只留现行文档。**P5 依赖收口到 uv**——`pyproject.toml` + `uv.lock` + `.python-version`，requirements 降级为派生清单并挂 `check.py --check` 门禁。测试 706→726 |
| v3.5 | 2026-11 | 数据源选择能力三段式（Argo 同构）：引擎侧原语 `INVEST_CLI_DISABLE_SOURCES`（candidates/pick/chains 一处过滤三层生效，具名直调不受影响，`datasources` 报停用态）→ 插件 config `disabledSources`（registry 单源派生 + Schema + spawn 注入 env，invest-cli 每次调用新进程、改完即时生效）→ 面板「数据源拓扑」升级为 17 源 checkbox 开关墙（删除硬编码的失真链序，链序归 `datasources` 运行时自报）；命令注册表启动校验（声明无实现给可读报错，替代裸 KeyError）；第十轮补记报告 |
| v3.4 | 2026-11 | 命令单一注册表：`command_registry.py` 成为命令/分类/预算/直取源唯一真源，dispatch 从它派生、插件产物由 `sync_registry.py` 生成、`test_registry` 钉「注册表=parser=dispatch=插件产物」四方相等，`check.py` 增生成物过期门禁；直取命令（wind/yingmi/ttskill/htbr/westock/sec/fmp）写 `scope=direct` 账本，doctor/datasources 报直取连续失败；FMP 补 us() 适配（priority 34 链尾兜底，仅前四源全败才烧配额）；`fund --analytics` 装配合并 −55 行；research --limit 按场景分默认值 |
| v3.3 | 2026-11 | 运行时事实层：`route.fetch` 默认路径每次真实取数记一条 `usage_log`（成败/耗时/降级链/逐源原因），CLI 入口再记一条命令级事实（rc/耗时，诊断命令自身不记）；`doctor` 的 usage 检查分源级与命令级报告（24h 失败率、同一链尾部连续失败、降级次数），`datasources` 尾部展示同一份 24h 汇总；账本 1MiB 回缩、失败静默、`INVEST_CLI_USAGE_LOG=0` 可关。补上「静态测试看不见运行态」这一层；插件补齐 `htbr` / `research` / `doctor` 三个命令（21→24）与 htbr 拓扑、`research` 给 180s 分档预算，命令面改由 CLI dispatch 真源校验，预算表不再允许孤儿项；`KIND_FNS` 从 9 种收敛到配置里真实有链的 4 种；文档去掉写死的源数量与失真的链序，改由 `datasources` 运行时给；新增 `research etf-rank`（按真实回包接线：同指数基金横评、成分股、指数估值；评分口径与 `risk_note` 原样透出）。接入 htbr 华泰柏瑞ETF（透传官方 htbr-etf-skill，72 接口事实查询面：经理 20 + 指数 13 全量导航 + 分辨率入口，暂停接口不进导航）；SSRF 四层闸并口 `_http` 单出口；体积门禁固定红线 1400；门闩表/场景表删源名列（源名只归 yaml 与运行时输出）；发布链修复（`--exclude /scripts` 根锚定、发布前挂 check 与插件单测、根级 packages/dsh-plugin 软链、check_public_sync 对账门禁）；check.py 新增版本记账门禁；README 增设 Feedback 入口 |
| v3.2 | 2026-10 | 工程底座收口：新增 `invest-cli doctor` 一条命令查数据源/缓存/解释器/注册软链/DSH 副本漂移五面（首跑即抓到 license 漂移）；运行时统一 venv 3.14（EOL 的 3.9 退出热路径，公开仓兼容下限仍为 3.9+）；发布链固化为 `scripts/publish-public.sh`（镜像 + 内置脱敏门）；pre-commit 门禁自动跑 check.py；7 条联网用例默认排除（`pytest -m live`）；`report` 产物迁出仓库；DSH `sync-local.sh`；invest-cli SKILL.md 删掉追不上 17 源 yaml 的静态数据源表 |
| v3.1 | 2026-10 | 数据源适配器迭代（eastmoney/hithink/tencent/tiingo/wind/mxds/ttskill/etfirst）与路由加固；新增 8 个测试文件（doc-source-truth / envelope / module-size-gate / py39-compat / static-imports 等守卫）；美股用法文档；`docs/INDEX.md`、`check.py`、`requirements-dev.txt` |
| v3.0 | 2026-10 | 三层架构重构（方法论 `invest-*` / 数据 `mx-data` / 呈现 `mx-templates`），消除重复的 auth 与报告模板；新增推理档位（低/中/高，公开默认低档，报告按需）；新增 invest-pool / invest-risk / invest-enterprise 三个方法论技能；invest-cli 同步 v2.8→v2.9 及十月演进（`tenure` / `report` / `research fund-rank` 等新命令，妙想/fmp/tiingo 等新源，热路径再降，回归 440→513） |
| v2.7 | 2026-09 | 并入腾讯行情（零鉴权）与腾讯微证券 CLI：新增 `quote`（多标的实时行情，三市场 186ms，对照旧路径 7.7s，约 41x）/`kline`/`westock` 三命令；热路径去白付（缓存命中 `fund` 0.09→0.03s、`stock` 0.08→0.05s、`us` 0.05→0.03s）；修 19 项缺陷（代码域冒牌数据/跨源猜测/可用性判据漂移/号码重叠静默串号/限流通告当数据等）；移植时不继承 17 类缺陷；回归 237→317 |
| v2.6 | 2026-09 | 去外部 CLI 依赖：天天基金/盈米/Wind 三源由 `subprocess → CLI` 改为直连 API（认证沿用官方）；隔离实测 invoke 0.374→0.237s、yingmi 0.458→0.244s、wind 0.591→0.426s；修自然语言持仓/配置路径从未可用、凭据重复读取等；回归 171→192 |
| v2.5 | 2026-09 | 路由惰性探测（A 股探测段 0.53s→0.012s，`stock` 冷路径 1.52s→0.51s）；去重复利润表请求；修四处判据错层（中文名误判美股/盈米误配基金/空标的打满整链/`screen` 裸异常）；缓存 7 天上限自清（本机 24MB→11MB）；回归 156→171 |
| v2.4 | 2026-09 | argo 引擎清单不再本地维护（可用引擎 20→250+，修静默空答复）；`fund` 深取缓存（0.985s→0.104s）、FRED 并发+缓存（2.380s→0.076s 热）；美股未知代码/类别股/日志污染三类失态修复；缓存原子写（tmp 带 pid）；自选股迁出缓存目录 |
| v2.3 | 2026-09 | 消融式维护：注册链 9/9 对齐（清 3 条死链）、死路由清理、命令路径统一、`watchlist` 文档化 |
| v2.2 | 2026-09 | 薄单品种四合一：invest-bond/convertible/commodity/reit → invest-asset（同一三关骨架×四资产参数，注册数 12→9）；invest-cli 退役 `ttfund`、接入 ttskill 官方源与 hithink/bitget/route 回退链；引用面消毒 |
| v2.0.5 | 2026-08 | 统一多源数据层（invest-cli 接入 Wind/盈米/东财/yfinance/天天基金 + argo 财经垂直源；intent 意图层收敛接口面、datasources 探测）；新增 invest-bond/invest-macro；黄金十维度并入 invest-commodity；合并 invest-hk-a/us/institutional 进 invest-stock |
| v2.0.2 | 2026-07 | 配置门闩 + 数据源引导（东财/yfinance）；invest-cli 工程加固；公开路由消毒与死链清理 |
| v2.0 | 2026-06 | 统一框架升级：invest-stock 合并原 invest-hk-a/invest-us/invest-institutional，invest-fund 新增场景路由，新增 invest-discuss/invest-cli，移除 invest-report/invest-fund-manager 等 |
| v1.0 | 2026-04 | 全面重构，统一三关审查框架，覆盖股基债商+配置+圆桌 |

---

如果这个项目对你有帮助，欢迎点个 Star。

---

* * *

## English Version

# Invest Series: Investment Analysis Guide

Buy funds like hiring a steward, buy stocks like partnering in business. Don't trust people you don't understand, who are unreliable, or who charge too much.

This tool helps you with three things: **see what you're investing in, judge whether it's worth it, determine if the price is right**.

**Pluggable data sources (APIs) and 11 analysis methodologies**:
- **Data sources**: keyless (Tencent quotes / SEC EDGAR / FRED / yfinance) + config-enabled (Hithink / Eastmoney / Miaoxiang / FMP / Tiingo / Wind / YingMi / SeefundGo MCP / TTFund official ttskill / E Fund Index Hub) + long-tail (Tencent WeStock 40+ subcommands / HTBR ETF)
- **Methodologies**: stocks, funds, fund picking, single assets (bonds/convertibles/commodities/REITs), allocation, risk, company deep-dive, macro, institutional output, multi-perspective review

---

## Quick Start

```bash
npx skills add taxueseek/taxue-invest
```

After installation, just ask Claude:
- "How is this fund?"
- "Analyze Moutai"
- "Can I buy gold?"
- "Let the masters take a look at this stock"

The system automatically identifies what you want to analyze and routes to the corresponding analysis flow.

> **Note**: This tool only helps you think clearly. It's not investment advice and doesn't guarantee profits. After using it to analyze, buying or selling is entirely your own decision.

---

## Supported data sources (APIs)

The **judgment framework works immediately** without any API (public search + your own materials + keyless fetch paths). **The source list is defined by `data-sources.yaml`** (main ones below; run `invest-cli datasources` for runtime truth), grouped by how they unlock; fetch and judgment are separate:

### Keyless (install and go)

| Source | Unlocks |
|:-------|:--------|
| **Tencent quotes** (keyless) | `invest-cli quote` multi-symbol real-time, `kline`; A/HK/US/ETF/convertibles |
| **SEC EDGAR** | `invest-cli sec` US filing原文 (10-K XBRL + filings list) |
| **FRED** | `invest-cli intent macro` net-liquidity series (keyless CSV path) |
| **yfinance** (Python pkg) | `invest-cli us` US snapshot (quote + financials + analyst) |

### Config-enabled

| Source | Config | Unlocks |
|:-------|:-------|:--------|
| **Hithink** | `HITHINK_FINANCE_API_KEY` | Primary A-share / public-fund path for `stock` / `fund` |
| **Eastmoney** | `EASTMONEY_APIKEY` | A/HK snapshot, fund snapshot, natural-language screening; required for HK |
| **Miaoxiang** (Eastmoney) | `EM_API_KEY` | `screen` natural-language screening, `intent deep bond` |
| **Financial Modeling Prep** | `FMP_API_KEY` | `invest-cli fmp` US fundamentals / consensus / ratings / dividends (free tier 250/day) |
| **Tiingo** | `TIINGO_API_KEY` | `invest-cli us <code> --history` US EOD history |
| **Wind** | `WIND_API_KEY` | Institutional-grade data, `invest-cli wind` passthrough |
| **YingMi** | `~/.yingmi-skill-cli/config.json` | Fund/portfolio diagnosis and plans (`intent deep fund` / `portfolio` / `plan`) |
| **SeefundGo MCP** | `SFG_MCP_TOKEN` | Mutual-fund vertical deep-dive (credit-based): multi-factor screening, manager profile, attribution, async portfolio check (`invest-cli sfg` / `intent sfg`) |
| **TTFund official ttskill** | official login | Extra fund fields (peer percentile / institutional ratio / manager AUM) and `research etf-rank` |
| [argo](https://github.com/taxueseek/argo) | install argo | `invest-cli info` news/sentiment, macro retrieval fallback (mostly keyless) |

### Long-tail

| Source | Config | Unlocks |
|:-------|:-------|:--------|
| **Tencent WeStock CLI** | install westock binary | `invest-cli westock` 40+ subcommands: chips / dragon-tiger list / Stock Connect / margin / consensus / ESG / analyst ratings / industry chain / sector valuation / convertible-bond terms |

**Zero-config still works**: without any key you can still use `sec` (SEC EDGAR), `us` (yfinance) and `intent macro` (FRED).

**Division of labor with argo**: YingMi / Wind / Hithink / Eastmoney handle precise numbers, argo handles retrieval. Engine names are passed through verbatim — invest-cli keeps no local allow-list (it always drifts), so a wrong engine errors out with the command to list valid ones instead of silently returning an empty result.

---

## What This Is

Not only a data tool — a **judgment framework** (optional data backends).

The biggest pitfall in investing isn't lack of information, it's **not knowing what to look at**. This tool tells you: these three things are all you need to check.

```
User Question
    │
    ▼
┌─────────────┐
│  invest     │  ← Identifies what you want to analyze
│  Entry      │
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼
   ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
   │ Stocks│  │ Funds │  │Convert│  │Commod │  │ REITs │  │Asset  │
   │3-Gate │  │Scene  │  │3-Gate │  │3-Gate │  │3-Gate │  │Alloc  │
   │+Deep  │  │Route  │  │Review │  │Review │  │Review │  │       │
   └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘  └───┬───┘
       │          │          │          │          │          │
       └──────────┴────┬─────┴──────────┴──────────┴──────────┘
                       ▼
               ┌───────────────┐
               │  3-Gate Review│
               │               │
               │ 1. Understand?│  ← Capability circle / Strategy
               │ 2. Good?      │  ← Moat / Sustainability
               │ 3. Cheap?     │  ← Margin of safety / Valuation
               └───────────────┘
```

---

## Analysis coverage

11 methodology skills covering every analysis scenario. Since v3.0 the methodologies are substantially deepened and layered by target:

| You want to analyze | Routes to | Core Question | Applicable Markets |
|:--------------------|:----------|:--------------|:-------------------|
| A specific stock | invest-stock | Understand the business? Moat? Right price? | A-shares, HK stocks, US stocks |
| A specific fund | invest-fund | Understand the strategy? Can beat benchmark? Cost reasonable? | Active funds, ETFs, QDII |
| Convertible bonds / Gold & Oil / REITs / Bonds | invest-asset | Bonds: solvency+spread+position; Convertibles: terms+floor+premium; Commodities: logic+position+volatility; REITs: assets+operations+valuation | Bond market / Commodities / REITs |
| Overall allocation | invest-allocation | Stock-bond ratio reasonable? Rebalanced? | Cross-asset portfolio |
| Fund picking / fund pool | invest-pool | Style stable? Where's the circle of competence? Is sector rotation worth it? | Fund portfolio management |
| Risk / leverage / position | invest-risk | Is principal safe? Is leverage safe? Does the system hold without willpower? | Risk & discipline |
| Company deep-dive / credit | invest-enterprise | Governance + industry + operations + financials + credit + legal | A single corporate entity |
| Market temperature / liquidity | invest-macro | Is money tight? Is the market overheated? | Global liquidity, US sentiment, crypto bottom signals |
| Research note / minutes / daily | invest-analyst | IC memo, earnings-call minutes, consensus, industry deep-dive, daily report | Institutional-grade output |
| Not sure? | invest-discuss | Let multiple investment minds examine together | Any target |
| `/cli` analysis | invest-cli | Terminal data fetch + analysis framework | A/HK/US stocks, funds |

**Methodology highlights (v3.0)**:
- **Stocks**: industry life-cycle + Porter's Five Forces + management & governance + 6-method valuation cross-check (PE/PB/DCF/EV-EBITDA/DDM/PS)
- **Funds**: 7-dimension manager score (out of 35) + performance-persistence tests + fee structure (6 fee items + 30-year compounding) + sector-rotation fund assessment
- **Fund picking (new)**: style matrix (5 styles × 5 types) + 7-dimension pick + portfolio construction (core/satellite/watch)
- **Risk (new)**: four-layer risk diagnosis + four-layer risk management + willpower-free system design + three-tier cash cushion
- **Company deep-dive (new)**: 15 sections (governance / industry / operations / financials / credit / legal)
- **Allocation**: hold-firm/hold-change framework + all-weather three questions + risk metrics (vol / max drawdown / VaR / CVaR / Sharpe / Sortino) + correlation matrix (normal vs crisis)
- **Macro**: China core indicators (PMI/CPI/PPI/Tsf/M2) + four-phase cycle positioning + global central-bank coordination
- **Analyst**: financial-document speed-reading engine (5-layer MECE) + valuation-method selection matrix + industry-chain framework

---

## What is the 3-Gate Review

What's the biggest fear in investing? **Looking at what you shouldn't, missing what you should**.

These three gates break complex investment decisions into three must-answer questions:

### Gate 1: Do You Understand?

If you don't understand it, you can't hold it through ups and downs.

- Stocks: How does this company make money? Why do customers choose it?
- Funds: What does it invest in? What's the strategy? What's the benchmark?
- Convertible bonds: Do you understand the terms? Put, call, reset — what do they mean?

**Fail this gate: abandon directly.** Don't touch what you don't understand.

### Gate 2: Is It Good?

Only good things can sustain returns.

- Stocks: Pricing power? ROE consistently >12%? Good cash flow?
- Funds: Beats benchmark long-term? Manager stable? Risk-adjusted returns good?
- Commodities/REITs: Underlying asset quality? Distribution/earnings sustainable?

**Fail this gate: it's a mediocre target, not worth your time.**

### Gate 3: Is It Cheap?

Even good things hurt if you buy expensive.

- PE/PB at what historical percentile?
- If it drops 30%, can you handle it?
- Is there margin of safety entering now?

**Fail this gate: not don't buy — wait for a better time.**

---

## v2.0 Feature Highlights

### Unified Stock Entry

Previously A-shares, HK stocks, and US stocks used separate skills. Now unified into `invest-stock`:

| Capability | Description |
|:-----------|:------------|
| 3-Gate Review | Default mode, A-shares/HK stocks |
| 4-Dimension Score | Auto-switches for US stocks, ROE/Debt/FCF/Moat → A-D rating |
| Institutional Deep | Say "deep analysis" to enter, DCF + comparable company + IC Memo |
| HK-A Enhancement | Auto-adds policy sensitivity, AH premium, north/south flow for A/HK stocks |

### Fund Scene Routing

No longer one-size-fits-all. Auto-selects path based on your question:

| Scene | Trigger | Core Judgment Axis |
|:------|:--------|:-------------------|
| Same manager, multiple funds | "Which of Zhang Kun's funds to pick" | Pick the one most like the manager |
| Cross-fund comparison | "Which is better, Fund A or B" | Multi-dimensional comparison scoring |
| Industry theme | "New energy fund" | Manager-industry fit > industry beta |
| New fund | "Is this new fund worth buying" | Manager inference + company DNA |
| ETF | "CSI 300 ETF" | Expense ratio + tracking error + liquidity |
| Standard checkup | "How is this fund" | Full 3-gate review |

### Masters Discussion

Four investment minds examine the same target simultaneously:

| Perspective | Core Question |
|:------------|:--------------|
| Business | Understand this business? Has a moat? |
| Trend | How much optimism is priced in? Any catalyst? |
| Allocation | What position size? Can handle how much drawdown? |
| Contrarian | Three most likely scenarios to lose money? |

### Investment Analysis CLI

Terminal fetch, table or JSON (`invest-cli` entry point; fall back to `"$HOME/.local/bin/invest-cli"` if not on PATH):

```bash
invest-cli stock 600519          # A/HK: quote + valuation + 5y financials
invest-cli fund 110011           # Fund: NAV / returns / drawdown / fees / manager / holdings
invest-cli us AAPL               # US: valuation + financials + analyst rating
invest-cli quote 600519,00700,AAPL   # Keyless multi-symbol quotes (A/HK/US/ETF/convertibles)
invest-cli kline 600519 --period day # K-line (Tencent native fast path, yearly bars aggregated)
invest-cli westock chip 600519   # Tencent WeStock long-tail passthrough (40+ subcommands)
invest-cli sec AAPL              # US filings, original source (SEC EDGAR, no key)
invest-cli screen "Bank stocks with PE below 10"
invest-cli intent macro          # Macro: net-liquidity series (keyless path)
invest-cli info 茅台             # News / sentiment (via argo)
invest-cli datasources           # Diagnose "why no data": per-source availability and chains
```

Add `--json` for structured output an agent can parse; omit it for a terminal table. One question never mixes sources: a failing source falls back as a whole, and the result always labels its origin.

---

## Recent Improvements & Performance

### v3.0: three-layer architecture + inference tiers

This version turns the invest series from "a pile of parallel skills" into a **layered architecture**, and makes "produce a report" **on-demand** instead of the default.

**Three layers — methodology / data / presentation separated**

| Layer | Responsibility | Components |
|:------|:---------------|:-----------|
| **Methodology** | Analysis frameworks, decision logic | `invest` / `invest-stock` / `invest-fund` / `invest-asset` / `invest-analyst` / `invest-enterprise` / `invest-allocation` / `invest-pool` / `invest-risk` / `invest-discuss` / `invest-macro` |
| **Data** | Fetch, clean, structure | `mx-data` (a thin wrapper over `invest-cli`; no duplicate auth / routing / fallback) |
| **Presentation** | Report structure and templates | `mx-templates` (10 report templates, `{{var}}` placeholders, source-agnostic) |

**Inference tiers: low / medium / high, default low**

Not every question needs a report. "Recommend a short-duration bond fund" and "write an IC report" should not take the same path:

| Tier | Fetches | Output | Trigger |
|:-----|:--------|:-------|:--------|
| **low** (default) | ≤ 2 | Terminal conclusion (1-5 lines of key metrics + verdict) | Simple query, recommendation, screening |
| **medium** | ≤ 4 | Bullet summary + brief analysis | User says "detailed" / "in depth" |
| **high** | unlimited | Full report (`mx-templates`) | User says "report" / "IC" / "deep analysis" |

The public default is **low** (fast, cheap, sufficient); locally you can override to high via `invest/references/mode.local.yaml` without affecting the public default.

**Three new methodology skills**

- **invest-pool**: style matrix (5 styles × 5 types) + 7-dimension fund-picking score (out of 35) + sector-rotation fund assessment + portfolio construction (15-25 funds; core/satellite/watch)
- **invest-risk**: four-layer risk diagnosis (leverage → principal → cognition → mindset) + four-layer risk management + a system that doesn't rely on willpower + a three-tier cash safety cushion
- **invest-enterprise**: company deep-dive (15 sections: governance + industry + operations + financials + credit + legal)

**invest-cli evolution in step (v2.8 → v2.9 + October)**

- **New commands**: `tenure` (manager-tenure review — turns per-year return/drawdown + daily excess from a 14-minute manual job into one command), `report` (fund periodic-report PDFs, `--latest 4` grabs four quarters in one command), `research fund-rank` (theme fund pool → batch snapshot → ranking + holdings × dividend-yield cross; 97 funds cold-cache in **45.96s** vs ~210s manual, **4.6x**), plus `cn` / `fmp` / `fund-class`
- **New sources**: Miaoxiang (Eastmoney, natural-language screening), fmp, tiingo, etfirst, index_hub; a three-layer fund classifier (`fund-classification.yaml`)
- **Hot path faster again**: `stock` cache hit 50→**30ms** (no adapter import on the hit path), `fund`/`us` 51-52→**40ms**
- **Correctness & guards**: fixed "second implementation of the same thing" drift (a US ticker prefix swallowed a real symbol and returned a different company; NAV cache cross-window poisoning), non-atomic watchlist writes silently losing user data, and added a failure-envelope negative cache (repeated failing query 6285→50ms); regression **440 → 513**, all green

### v2.7: hot-path waste removed + Tencent sources merged

**Measure real usage first.** From 216 real sessions, **80% of consecutive `invest-cli` calls are <60s apart** (inside the 60s snapshot cache TTL). So daily performance = the cache-hit path plus the first fetch per symbol; cold paths are the minority. That killed two planned optimizations (raising the US snapshot TTL would help only 4-5 calls; the 3.5s HK path is 0.3% of calls).

**Hot path no longer pays for nothing.** Before a cache hit, the old code still computed the whole candidate chain (YAML parse + adapter import chain, incl. ssl), even though the cache key does not depend on it; one wasted yfinance fetch was also removed. Cache-hit readings (5 alternating runs):

| Command (cache hit) | Before | After |
|:---|---:|---:|
| `fund 110011` | 0.09s | **0.03s** (3.0x) |
| `stock 600519` | 0.08s | **0.05s** |
| `us AAPL` | 0.05s | **0.03s** |
| `intent deep stock 600519` | 0.09s | **0.05s** |

Cold paths: no measurable change (honest result — drowned by upstream jitter).

**New: keyless multi-symbol quote fast path.** Tencent quotes (keyless) merged into the data layer, with a new `quote` command: one request, any number of symbols, across A/HK/US/ETF/convertibles. Three markets in **186ms** vs **7.7s** serial on the old path (**~41x**); 6 mixed symbols in **189ms**. Also new: `kline` (yearly bars aggregated by calendar year) and `westock` (Tencent WeStock 40+ subcommands passthrough).

Tencent does **not** enter the primary `stock`/`fund` slot: it has quotes but no fundamentals (no net income / ROE / EPS / debt ratio), so promoting it would degrade an A-share snapshot from 13 fundamental fields to pure quotes. Chains: `us = yfinance > Tencent > bitget`; `stock = Hithink > Eastmoney > yfinance > Tencent`; `fund`/`screen` exclude Tencent.

**Correctness.** 19 defects fixed (round 4) and 17 classes deliberately not inherited when porting Tencent (round 5): wrong-domain fake data, cross-source guessing on input failure, availability-criteria drift silently dropping Hithink/Wind, number-overlap silently returning a different symbol, help text / rate-limit notices returned as data (exit code 0), one array index meaning different quantities per market (HK turnover stuck at 0.0), daily bars masquerading as yearly bars, and more.

**Guards.** Tests **237 → 317**, green on three interpreters.

### v2.5: lazy source probing

No new features in v2.5 — just lower fixed cost per call, and fixes for defects where the judgment was made at the wrong layer.

### Performance: lazy source probing (the big one)

The old router probed **every source in the chain up front**, so every A-share query paid a real HTTPS probe for the last-resort yfinance fallback. Now it only does a cheap capability check up front and probes availability right before calling a source; if the primary succeeds, fallbacks are never touched.

| Metric (same machine, cleared cache) | Before | After |
|:---|---:|---:|
| A-share routing probe segment (isolated) | 0.53s | **0.012s** (~44x) |
| `stock 600519` cold path | 1.52s | **0.51–0.60s** (~2.6x) |
| `fund 110011` cold path | 2.30s | **1.24–1.45s** (~1.7x) |
| Probes triggered by one A-share query | 4 | **1** |
| Hot path (cache hit) | 0.11–0.13s | unchanged (already the floor) |

One duplicate request was also removed: the income statement was fetched twice (a `limit=1` preview plus the `limit=5` batch) to learn the latest fiscal year; it is now derived from the annual-report disclosure rule, with a fallback when the guess is wrong.

### Correctness: four cases of "judged at the wrong layer"

- **Chinese names treated as US tickers**: CJK characters are also `isalpha()` in Python, so `intent deep 茅台` went to Yahoo for "茅台" (3.2s wasted). The test is now ASCII-only.
- **YingMi fuzzy match turning stocks into funds**: `GuessFundCode` is substring-based; "中国平安" matched an unrelated fund. The test changed from "YingMi returned something" to "the returned fund name actually corresponds to the query".
- **Empty target exhausting the whole chain**: `stock ""` took 3.55s and returned three concatenated source errors; now rejected at the entry in 0.05s with one clear message.
- **Upstream `data.data=null` raising a bare exception**: `screen ""` used to print a Python traceback.

### Resources: cache no longer grows unbounded

TTL decides read hits, it does not delete files; a single SEC companyfacts file is ~3.7MB and accumulated per company queried. Added a 7-day cap with cleanup on write — measured 24MB → 11MB locally.

### Regression guards

Tests went from 156 to **171**, each new one tied to a behavior that actually happened (including counter-cases so a fix cannot degrade into "reject everything").

---

## Design Philosophy

1. **Simplicity** — Buffett's three questions extended to all asset types
2. **No Decision-Making for You** — Framework only, decisions are yours
3. **Dynamic Time** — Auto-calculates which report to look at
4. **Master Perspective** — Multi-perspective discussion to expose blind spots

---

## Before You Use This

**First, you bear your own gains and losses.** This tool won't tell you which stock to buy or which fund to sell.

**Second, information is limited.** Data may be delayed or incorrect. It gives you reference, not definitive answers.

**Third, it cannot replace professional advice.** Consult a licensed investment advisor for large investment needs.

**One sentence: The tool only helps you think clearly. The decision is yours. The risk is yours.**

---

## Project Structure

```
docs/
└── data-sources.md            # Optional data sources (unlock after config)
skills/
├── invest/                    # Entry: auto-identifies target type
├── invest-stock/              # Stock analysis (3-Gate/4-Dimension/Institutional Deep/HK-A)
├── invest-fund/               # Fund analysis (scene routing)
├── invest-asset/              # Single-asset: Bonds/Convertibles/Commodities (incl. gold 10D)/REITs
├── invest-allocation/         # Asset allocation
├── invest-pool/               # Fund picking & fund pool (style matrix / 7-dim score / rotation)
├── invest-risk/               # Risk & discipline (4-layer diagnosis / system design / cash cushion)
├── invest-enterprise/         # Company deep-dive (15 sections: governance/industry/ops/financials/credit/legal)
├── invest-macro/              # Macro & market environment (liquidity/sentiment/bottom signals)
├── invest-discuss/            # Masters discussion (multi-perspective validation)
├── invest-analyst/            # Institutional-grade output (IC memo/minutes/consensus/daily)
├── mx-data/                   # Data layer: thin wrapper over invest-cli (scene → command)
├── mx-templates/              # Presentation layer: 10 report templates ({{var}} placeholders)
└── invest-cli/                # Data layer: CLI + multi-source adapters + regression tests
    └── docs/                  # Data-source notes + performance & defect reports (with repro steps)
```

---

## Feedback

Issues are the fastest channel and are actively watched: <https://github.com/taxueseek/taxue-invest/issues>.

- **Bug report**: the command you ran, expected vs actual, and the JSON output if any.
- **Data-source failure**: run `invest-cli doctor` first and attach its output — it reports per-source availability, cache, interpreter and DSH-copy drift in one pass.
- **Feature requests & methodology feedback** are equally welcome; for larger changes, open an issue before the PR.

---

## Version History

| Version | Date | Changes |
|:--------|:-----|:--------|
| v3.2.2 | 2026-11 | Public release rollup (v3.2–v3.8.2): financial-caliber hardening (US chain `yfinance > fmp > tencent > tiingo`, `bitget` synthetic rToken removed from default equity chain; HK `eastmoney > tencent > yfinance`; US/CN macro split; bond `wind → mxds` fallback); added SeefundGo Fund MCP (credit-based, multi-factor screening & 420s async portfolio check, plain keywords route to YingMi to save credits) and HTBR ETF; `capabilities` expanded to `sfg`/`htbr`; added `doctor`, `usage_log`, SSRF AST gate, single-source `command_registry`, DSH toggle wall, and `uv.lock`; 770 Python tests + 30 DSH plugin tests passing |
| v3.7 | 2026-11 | Implicit state machines made explicit (structure and criteria only, no new features): **P1 scenario state machine single-source** — `mx-data/scripts/query_router.py`'s `SCENARIO_COMMANDS` previously held only display names and command text, while argv branching lived in `get_data._scenario_cmd()` and fetch mapping in `get_data._FETCHERS`, so one scenario's state was scattered across three places; each scenario now defines `name`/`argv` (with placeholders)/`route_kind` in a single table entry, both derivation bodies are deleted, and 3 new tests pin "table = argv = fetch route". **P2 stage-number cleanup** — `invest-macro`'s A/B/D/C dimension order and `invest-risk`'s 1/2/5/3/4 section order are renumbered to A/B/C/D and 1/2/3/4/5; body text unchanged. **P3 stale doc links removed** — 15 links in `invest-cli/docs/INDEX.md` pointed at archived reports; they now point at the archive index, leaving 3 live docs in `docs/`. **P4 doc table aligned to code table** — the htbr row (absent from code) is dropped from `mx-data/SKILL.md`'s scenario table, and `test_doc_source_truth` now checks the `argv` head word. Tests 726→729 |
| v3.6 | 2026-11 | Five Argo-v2.13.0-aligned structural fixes (no new features): **P0 SSRF bypass closed** — eastmoney's `requests.post` and mxds's raw `http.client` now go through the shared gate's new `guarded_request` (POST form); previously DNS public-address checks and redirect blocking did not apply to either; `test_http_gate.py` AST-scans to pin "no requests/http.client/raw urlopen in production code". **P1 state single-source** — new `sources/envelope.py` collapses 5 duplicate `_envelope` implementations and doctor's 27 status literals (`HEALTH_*` constants + `is_blocking()`). **P2 ledger delivery counts** — success records gain `count`/`empty`; doctor shows "delivered: hithink 1", distinguishing "slow tail" from "sole supplier". **P3 empty-result baseline break** — `usage_stats` gains `suspected_stale` (ever non-empty + ≥3 consecutive empties + ≥2 distinct queries), zero extra requests. **P4 doc layering** — 14 process reports archived to `docs-local/archive/`, `docs/` keeps only live docs. **P5 dependency uv lock** — `pyproject.toml` + `uv.lock` + `.python-version`; requirements demoted to derived manifests with a `check.py --check` gate. Tests 706→726 |
| v3.5 | 2026-11 | Per-source selection, built as three Argo-aligned layers: engine primitive `INVEST_CLI_DISABLE_SOURCES` (filtered once in candidates, effective across pick/chains; named direct calls unaffected; `datasources` reports disabled state) → plugin config `disabledSources` (registry-derived defaults + Schema + spawn env injection; the CLI runs a fresh process per call, so changes apply immediately) → panel "Sources" tab upgraded from a read-only table to a 17-source checkbox wall (stale hard-coded chains removed; live chain order belongs to `datasources`); command-registry startup validation (readable error instead of raw KeyError); round-10 retrospective report |
| v3.4 | 2026-11 | Single command registry: `command_registry.py` as the sole source for commands/categories/timeouts/output budgets/direct sources; dispatch derived from it, plugin artifacts generated by `sync_registry.py`, `test_registry` pins the four-way equality, `check.py` gains a generated-artifact staleness gate; direct-call commands (wind/yingmi/ttskill/htbr/westock/sec/fmp) logged as `scope=direct` ledger records with per-source failure reporting; FMP added as us() tail fallback (priority 34, quota spent only after all four earlier sources fail); `fund --analytics` assembly merged (−55 lines); research --limit scene-specific defaults |
| v3.3 | 2026-11 | Runtime evidence layer: every real fetch logs one `usage_log` record on the `route.fetch` default path (success/elapsed/fallback chain/per-source reasons; cache hits and input-layer rejections excluded), plus one command-level record at the CLI entry; `doctor` and `datasources` read the same 24h summary; `KIND_FNS` 9→4 (empty-chain fake promises removed, pinned to the yaml union). HTBR ETF facts source integrated (passthrough of the official htbr-etf-skill: 72 interfaces, manager ×20 + index ×13 navigation, resolution entry, paused endpoints excluded); SSRF gate merged into `_http` single exit; module-size gate fixed at 1400; mapping tables drop source columns (sources live only in data-sources.yaml and runtime output); publish chain fixed (rooted `--exclude /scripts`, pre-publish gates, root packages/dsh-plugin symlink, check_public_sync reconciliation gate); version-accounting gate in check.py; README Feedback section; `research etf-rank` (same-index fund comparison wired from real responses) |
| v3.2 | 2026-10 | Engineering hardening: new `invest-cli doctor` one-command health check (sources/cache/interpreters/symlinks/DSH-copy drift, caught a real license drift on first run); runtime unified on venv 3.14 via auto re-exec (EOL 3.9 out of the hot path, LibreSSL warning gone; public Python 3.9+ floor unchanged); publish pipeline fixed into `scripts/publish-public.sh` (mirror + privacy gate, no more ad-hoc subtree pushes); pre-commit hook runs check.py on invest-path commits; 7 live network tests excluded by default (`pytest -m live`); `report` output moved to state dir; DSH sync-local.sh; stale source table dropped from SKILL.md (runtime truth = `datasources`) |
| v3.1 | 2026-10 | Data-source adapter iteration (eastmoney/hithink/tencent/tiingo/wind/mxds/ttskill/etfirst) with routing hardening; 8 new test files (doc-source-truth / envelope / module-size-gate / py39-compat / static-imports guards); US-stock usage docs; docs/INDEX.md, check.py, requirements-dev.txt |
| v3.0 | 2026-10 | Three-layer refactor (methodology `invest-*` / data `mx-data` / presentation `mx-templates`), removing duplicated auth and report templates; inference tiers (low/medium/high, public default low, report on demand); three new methodology skills invest-pool / invest-risk / invest-enterprise; invest-cli synced through v2.8→v2.9 and October work (new `tenure` / `report` / `research fund-rank` commands; Miaoxiang/fmp/tiingo sources; hot path faster again; guards 440→513) |
| v2.7 | 2026-09 | Tencent quotes (keyless) and Tencent WeStock CLI merged: new `quote` (multi-symbol real-time, three markets in 186ms vs 7.7s on the old path, ~41x) / `kline` / `westock` commands; hot-path waste removed (cache hit: `fund` 0.09→0.03s, `stock` 0.08→0.05s, `us` 0.05→0.03s); 19 defects fixed (wrong-domain fake data / cross-source guessing / availability-criteria drift / silent symbol overlap / rate-limit notice as data); 17 classes not inherited when porting; guards 237→317 |
| v2.6 | 2026-09 | External-CLI dependency removed: TTFund / YingMi / Wind moved from `subprocess → CLI` to direct API calls (same official auth); isolated timings invoke 0.374→0.237s, yingmi 0.458→0.244s, wind 0.591→0.426s; fixed the natural-language portfolio/plan path that never worked; guards 171→192 |
| v2.5 | 2026-09 | Lazy source probing (A-share probe segment 0.53s→0.012s; `stock` cold 1.52s→0.51s); removed a duplicate income-statement request; four wrong-layer fixes (CJK as US ticker / YingMi fund false positive / empty target exhausting the chain / `screen` bare exception); 7-day cache cap with cleanup (24MB→11MB locally); guards 156→171 |
| v2.4 | 2026-09 | argo engine list no longer maintained locally (20→250+ usable engines, silent-empty answer fixed); `fund` deep-fetch cache (0.985s→0.104s) and FRED concurrency+cache (2.380s→0.076s hot); three US failure modes fixed (unknown ticker / share classes / log pollution); atomic cache writes (pid in tmp name); watchlist moved out of the cache dir |
| v2.3 | 2026-09 | Ablation-style maintenance: registration chains 9/9 aligned (3 dead links removed), dead routes cleaned, command paths unified, `watchlist` documented |
| v2.2 | 2026-09 | Thin single-asset 4-in-1: invest-bond/convertible/commodity/reit → invest-asset (same 3-gate skeleton × 4 asset params; registry 12→9); invest-cli retired `ttfund`, adopted ttskill official source + hithink/bitget/route fallback chain |
| v2.0.5 | 2026-08 | Unified multi-source data layer (Wind/YingMi/Eastmoney/yfinance + argo finance verticals; intent-layer convergence; datasources probe); new invest-bond/invest-macro; gold 10-dimension merged into invest-commodity |
| v2.0.2 | 2026-07 | Config gates + data-source guide; invest-cli hardening; public route sanitization |
| v2.0 | 2026-06 | Unified framework: invest-stock merged HK/US/Institutional, invest-fund scene routing, new invest-discuss/invest-cli |
| v1.0 | 2026-04 | Initial release, unified 3-gate review framework |

---

If this project is helpful to you, feel free to give it a Star.

---

Prosperity Public License 3.0.0 © 2026 — 个人非商业使用免费，商业使用需 30 天试用后获取授权
