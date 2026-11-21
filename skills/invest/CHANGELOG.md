# Changelog

> 版本号唯一权威：根 `taxue-invest/SKILL.md` frontmatter 的 `version` 字段；
> 本文件跟随记录。公开仓 README 的 Version History 由发布脚本
> `scripts/publish-public.sh` 同步时带上，不再单独维护。
> （2026-10-25 起生效；此前三处各记各的，v2.9/v3.0/v3.1 三个数并存。）

## v3.2.2（2026-11-21 · 公开合版发布：金融口径收口 + sfg/htbr 接入 + 单源治理 + 验收自动化）

面向公开仓 `v3.1 → v3.2.2` 的对外合版发布（汇总内部迭代 v3.2–v3.8.2 全部已落地已验证改动）。**相对 v3.1 改进与新增：**

- **金融口径与跨资产路由收口**：美股默认链改为 `yfinance > fmp > tencent > tiingo`（`bitget` USDT 代币价移出默认股票快照链）；港股链优化为 `eastmoney > tencent > yfinance`；`intent macro` 按中美地区分流（避免美联储失败兜底中国统计局）；`intent deep bond` 补齐 `wind → mxds` 降级链；`intent deep fund` 定型为 `盈米诊断 → route 结构化快照 → 妙想兜底`。
- **新增数据源与能力发现**：接入见基行事（seefundgo）公募基金 MCP（`invest-cli sfg` / `intent sfg`，积分制，专攻多因子选基、经理画像、归因与异步组合体检 420s 轮询，纯关键词搜基金直走盈米省积分）与华泰柏瑞 ETF（`invest-cli htbr`）；`capabilities` 发现层覆盖 `yingmi`/`ttskill`/`westock`/`sfg`/`htbr`；新增 `research etf-rank` 指数基金横评与 `invest-recap-card` 复盘卡片。
- **工程治理与安全底座**：SSRF 四层安全闸收口至 `sources/_http.py` 并加 AST 守卫；信封与健康状态词收口至 `sources/envelope.py`；命令与 DSH 插件元数据收口至 `command_registry.py` 单源；新增 `INVEST_CLI_DISABLE_SOURCES` 停用集与 DSH 面板开关墙；新增 `invest-cli doctor` 六面体检与运行时 `usage_log` 账本；依赖收口至 `pyproject.toml` + `uv.lock`；`etf_analytics.py` 拆分渲染层 `_etf_render.py`。
- **验证基线**：`check.py` 全绿（pytest 770 passed + ruff F821/F401 + compileall + 版本记账 + 派生校验 + DSH 插件 30/30 passed）。

## v3.8.2（2026-11-21 · v3.8.1 细节缺陷收口：条件解析反转 / 超时假成功 / 积分保护）

修复 v3.8.1 审查暴露的 4 处实现缺陷。**相对上一版改进：**

- **修复 `_parse_conditions` 三处金融条件解析缺陷**：比较词与 `%` 改为紧邻各自指标词解析，修复「年化收益大于 15% 且回撤低于 20%」收益方向被反判为 `yieldMax`、「收益大于 3% / 回撤低于 5%」漏除 100、「管理费低于 1.5%」按 150% 传入的问题；清理未使用的 `_NUM_RE`。
- **修复 `sfg.poll_portfolio` 超时假成功**：超时返回显式置 `"ok": False`，避免沿用 `running` 态响应的 `ok=True` 导致 `invest-cli sfg --poll` 返回退出码 0。
- **积分保护**：`intent screen fund` 仅在解析出多因子 `conditions` 时调用积分制 `sfg_screen_funds`，纯名称关键词直接走无积分墙的盈米 `SearchFunds`。
- **结构化快照优先**：`intent deep fund` 降级链调为 `盈米诊断 → route.fetch("fund") → 妙想兜底`，确保无盈米 Key 时先走确定性结构化快照（`hithink > ttskill > eastmoney`）。

## v3.8.1（2026-11-21 · sfg 定位回正：积分制源不做通用主路 + 三处实测缺陷修复）

v3.8 把 sfg 提为三条路由的**主路**，但当日实测暴露前提不成立：**sfg 是积分制**，余额 0 时所有工具被拒（含 `sfg_help`），报错「积分余额不足…请签到或联系管理员充值」。用会断供的源当主轴，等于把通用取数押在配额上。**相对上一版改进：**

- **定位回正：通用取数走妙想，基金垂直深取走 sfg**。`sfg` 只做妙想没有的能力——经理画像、绩效归因、风格漂移、选基排行榜、组合体检；通用基金查询回到无配额墙的通道。
  - `intent deep fund` 降级链改为 `盈米诊断 → 妙想基金事实 → route.fetch("fund")`，中段从 sfg 换成 mxds（实测两条路径 0.45s，且不再受积分影响）。
  - `intent portfolio` 保留 sfg 首选（组合体检是唯一通道），但单只/空 codes 直接走盈米，并为 sfg 不可用补 `fallback_from/fallback_error`，排障能看到首选源缺席原因。
  - `data-sources.yaml` 与 SKILL.md 写明积分制与配额依赖，`capabilities sfg` 输出提示「通用取数请走妙想」。
- **修复 `intent screen fund` 条件未传给上游**：`sfg_screen_funds` 的 props 只有 `conditions/logic/limit/fund_type/only_main`，旧代码传 `{"query": t}` 恒回「请传 conditions」（实测）。现按上游口径构造 `conditions` 数组（year 必填、收益/回撤用小数、回撤负数口径）；数字改为**贴着指标词**取——旧写法全文 findall 会把「近3年收益大于20%」读成收益 3%、「2024年夏普大于1」读成夏普 2024。判据词去掉裸「前」，避免「白酒基金前十」被误判成阈值筛选。
- **修复 `--poll` 在真实耗时下拿不到结果**：上游组合体检 succeeded 实测 298.9s / 340.2s，而 `poll_portfolio` 默认上限 180s，会在结果落盘前返回 `running`（等于白提交一次）。上限抬到 420s，CLI `TIMEOUTS["sfg"]` 同步抬到 420s；超时输出带 `job_id` 与已等待时长可续查；轮询间隔改按上游 `retry_after_seconds` 退避。
- **发现层补齐**：`capabilities sfg` 列出 11 个未建别名但可直传的工具，其中投顾账户域（`sfg_client_*`/`sfg_advisor_*`）显式标🔒边界外；`mx-data` 删掉不可达的 `fund_deep` 场景（`--type` choices 与 `detect_scenario` 都到不了，属死路）。
- 新增 8 条离线回归锚（轮询上限覆盖实测耗时、超时可续查、conditions 解析、排名意图不误判、未映射工具可见、deep fund 不走 sfg）；测试 763→768，`check.py` 全绿。

## v3.8（2026-11-21 · 方案 B：金融口径收口 + sfg 接入规范化 + 能力分层重组）

按零基原则、奥卡姆剃刀、第一性原理与 MECE 原则对数据源搭配与路由层做系统性收口。**相对上一版改进：**

- **金融口径修正（美股/港股/宏观/债券）**：
  - 美股默认快照链改为 `yfinance(40) > fmp(38) > tencent(37) > tiingo(36)`，`bitget`（USDT 合成代币价，无基本面）移出默认股票快照链（`route_kinds: []`），消除代币价压过基本面源的口径倒挂。
  - 港股链局部优先级微调（`MARKET_PRIORITY_OVERRIDE`）：`eastmoney > tencent > yfinance`，`eastmoney` 失败时优先走 189ms 零鉴权腾讯行情，避免在境内网络为 Yahoo 支付 2s 探测延迟。
  - 宏观链 `intent macro` 按地区分流：中国宏观走 `ttskill(cn) → argo(nbs_stats)`，美国/美联储流动性走 `FRED → ttskill(us) → argo(macro)`，消除「美联储失败兜底到中国统计局」的口径错配。
  - 债券深取 `intent deep bond` 补齐 `wind → mxds` 兜底链，无 Wind Key 时不再单点硬死。
- **公募基金数据源 MECE 定编与路由统一**：
  - 接入见基行事（seefundgo）公募基金 MCP（`invest-cli sfg` / `intent sfg`），收口到 `sources/envelope.py` 单源信封、`resolve_fund_code` 24h 磁盘缓存、`resolve_tool` 严格拦截未知别名，并在 `command_registry.py` 补齐 `sfg` 180s 超时与 60k 输出预算。
  - `intent screen fund` 与 `intent portfolio` 升级为 `sfg` 主路、`yingmi` 兜底（显式盈米 JSON 保持直达兼容）；`intent deep fund` 补齐 `yingmi → sfg → route.fetch("fund")` 三级降级；`mx-data` 的 `fund_deep` 统一指向 `intent deep fund`，消除双脑裂。
  - `capabilities` 发现层纳入 `sfg` 与 `htbr` 语义别名清单。
- **模块瘦身**：`etf_analytics.py` 终端渲染逻辑拆入 `_etf_render.py`（主模块 1211→1052 行），对外签名不变。

## v3.7（2026-11-09 · 隐式状态机显式化：场景单源 + 阶段编号收口）

把散在多处、各自漂移的隐式状态机收敛为可读的单一真源，全部**只改结构与判据、不加功能**。**相对上一版改进：**

- **P1 场景状态机单源**：`mx-data/scripts/query_router.py` 的 `SCENARIO_COMMANDS` 此前只承载展示名与命令文本，而 argv 分支在 `get_data._scenario_cmd()`、取数映射在 `get_data._FETCHERS`——同一场景的状态散在三处，加一个场景要改三处，漏一处就是「文档说走 A、实际走 B」。现每个场景在一个表项里同时定义 `name` / `argv`（含 `<code>` `<query>` 占位）/ `route_kind`（走 `route.fetch` 的 kind 与 market，`None` 表示不经快照链），`_scenario_cmd()` 与 `_FETCHERS` 全部删除并改为派生；`test_mx_data_router.py` 新增 3 条用例钉住「表 = argv = 取数路由」三者一致。
- **P2 阶段编号收口**：`invest-macro` 的维度编号是 A/B/D/C（D 插在 B 与 C 之间），`invest-risk` 的小节顺序是 1/2/5/3/4——两处都是「内容对、编号错」，读者按编号推导执行顺序会走偏。现按文档顺序重排为 A/B/C/D 与 1/2/3/4/5，正文内容未改。
- **P3 失效文档链接清理**：`invest-cli/docs/INDEX.md` 的 15 条历史报告链接指向 2026-11-09 已归档到 `docs-local/archive/` 的文件，链接全部失效。改为指向归档目录的清单 README（归档位置与内容会变，链接留在原处只会积累失效链接）；`docs/` 只留 3 份现行文档。
- **P4 文档表与代码表对齐**：`mx-data/SKILL.md` 场景表删掉代码里不存在的 htbr 行（场景表只写 `SCENARIO_COMMANDS` 内的 9 个场景，由 `test_doc_source_truth` 钉住）；`test_doc_source_truth` 的对应断言改为按 `argv` 首词校验（`--json` 是输出旗标，文档不写）。
- 测试 726→729；`check.py` 全绿。

## v3.6（2026-11-09 · argo v2.13.0 思路迁移：SSRF 收口 + 状态真源 + 运行时可观测）

按 argo v2.13.0 的优化思路做五处收口，全部**只改结构与判据、不加功能**。**相对上一版改进：**

- **P0 SSRF 旁路收口**：eastmoney 的 `requests.post`（screen 与 cmd_stock/cmd_fund 的东财查询）与 mxds 的裸 `http.client` 此前**完全不过**共享安全闸，DNS 公网校验与禁重定向对它们形同虚设。现新增 `sources/_http.guarded_request`（POST 形态，过同一套四层闸），两条路径并入；新增 `test_http_gate.py` 用 AST 扫描钉死「生产代码不得出现 requests/http.client/裸 urlopen」，新增适配器再开旁路即红。
- **P1 信封与状态词单点真源**：新增 `sources/envelope.py`，收口 5 份重复的 `_envelope`（hithink/fmp/tiingo/tencent/bitget）与 fund_classifier、sec_edgar 的变体；doctor 的 27 处 `pass/warn/fail/skip` 字面量收口为 `HEALTH_*` 常量，`is_blocking()` 统一退出码判据。新增 `test_envelope_truth.py` 钉住「适配器必须走真源、doctor 不得有手抄状态词」。
- **P2 账本交付条数**：`route.fetch` 的成功记录新增 `count`（列表取长度、dict 取 1）与 `empty` 标记；`_usage_bucket` 按源聚合 `delivered`/`empty`，doctor 与 datasources 展示「交付：hithink 1 条、mxds 1 条」——此前只有耗时，读不出「慢源是拖尾还是唯一出货」（argo 的 `engine_results` 同构）。
- **P3 空结果基线破位**：`usage_stats` 新增 `suspected_stale` 判据（历史曾非空 + 近期连续 ≥3 次空 + 跨 ≥2 查询），doctor 报「疑似失效」并 WARN。**零新增请求**——只读已有账本。判据常量收在 `envelope.py` 的 `STALE_*`。
- **P4 文档分层**：14 份过程报告（第一~十轮治理报告、审查/复核/hithink 回归等）从 `invest-cli/docs/` 归档到 `taxue-invest/docs-local/archive/`（新增索引 README，gitignore 排除出公开仓）；`docs/INDEX.md` 只留现行文档并指向归档。
- **P5 依赖收口到 uv**：新增 `pyproject.toml`（真源）+ `uv.lock`（62 包钉版）+ `.python-version`（3.15）；`requirements.txt` 与 `requirements-dev.txt` 降级为 `sync_requirements.py` 的派生清单，`check.py` 挂 `--check` 门禁；新增 `test_dependency_source_gate.py` 机械对账「清单依赖在真源里、真源依赖在 lock 里」。
- 测试 706→726；`check.py` 全绿；实测 `quote`/`stock`/`intent mxds`/`screen` 四条路径取数正常，账本已记 `count` 字段。

## v3.5（2026-11-08 · 数据源选择能力三段式 + 第十轮补记）

用户实测投诉「DSH 插件是死面板、不能像 Argo 插件那样选择」的诊断与修复：面板不是坏了，是**面板下面没有可操作的能力层**——Argo 的选择 = 引擎层 env 原语 → 插件 config → 面板控件三层配合，invest-cli 缺第一层。**相对上一版改进：**

- **引擎侧原语**：`route.disabled_sources()` 读 `INVEST_CLI_DISABLE_SOURCES`（逗号/分号/空白分隔，大小写不敏感），candidates/pick/chains 一处过滤三层生效；语义是「不要自动选它」，具名直调（`invest-cli wind / htbr`）不受影响；`datasources` 文本与 JSON 都报停用态。conftest 对该 env autouse 隔离（防本机环境让链序断言随环境腐烂）。
- **插件 config 桥接**：`disabledSources` 进 command_registry.DEFAULTS 单源（sync_registry 重新生成两侧产物）、index.js Config Schema 与 cordis.patch.yml；resolveEntry 组装 spawn env（空值不注入，解析口径与 route 侧逐条对齐）。invest-cli 每次调用都是新进程，面板改完即时生效。
- **面板开关墙**：「数据源拓扑」页从只读表升级为 17 源 checkbox 开关（写 config.disabledSources；行内元数据 priority/coverage/凭据需求取自注册表生成物），删掉硬编码的五条快照链——mxds 移出 stock 链后面板链序早已失真，链序是运行时事实，归 `invest-cli datasources` 自报，面板不再复述。
- **注册表启动校验**：注册表声明了命令但没有 cmd_ 实现时启动即给可读报错（原先是裸 KeyError）。
- **第十轮补记**：91234b9（命令单一注册表 + 直取账本 + FMP 链尾兜底）当时无轮次报告，补记见 `docs/性能与缺陷治理报告_2026-11-08_第十轮.md`；测试 695→699。

## v3.4（2026-11-08 · 命令单一注册表 + 直取账本 + FMP 兜底）

第十轮：把「同一个命令事实存五处」的结构缺口收成一个注册表，并补上直取源的可观测性。**相对上一版改进：**

- **命令与插件元数据单源**：新增 `scripts/command_registry.py`，登记命令 id、分类、中英文名、超时、输出预算与直取源；`invest_cli.build_parser()` 与 dispatch 从它派生，插件 `index.js` 消费生成的 `dsh/registry.generated.js`，`client.js` 的注册表块由 `scripts/sync_registry.py` 生成。加命令只改注册表一处；`check.py` 增 `sync_registry.py --check`，生成物过期即红。插件注释与 `cordis.patch.yml` 删掉写死的命令数（21/24 都曾漂移）。
- **直取源进入运行时账本**：`wind/yingmi/ttskill/htbr/westock/sec/fmp` 绕开 `route.fetch`，过去账本只记快照链。现由 CLI 入口写 `scope:"direct"` 记录，`usage_stats` 单列 `direct` 桶；`doctor` 与 `datasources` 报告直取失败与尾部连续失败。
- **FMP 补齐 `us()` 适配**：把深取结果收敛为 `cmd_us` 的统一快照形状，priority 34 排在 bitget 之后，只在前四源全败时消耗免费额度；`route_kinds: [us]` 与 `coverage` 同步，链序测试钉住「fmp 必须末位」。
- **去重**：`invest-cli fund --analytics` 与 `cmd_fund.py --analytics` 的整段装配逻辑合并为 `fetch_fund_analytics()`，删掉约 55 行逐字重复。
- **默认值分场景**：`research --limit` 不再全局写死 200；`fund-rank` 仍 200，`etf-rank` 默认 50，避免单行含成分股的 JSON 越过插件 60k 输出预算。
- **文档**：`docs/data-sources.md` 补 index_hub / etfirst 的定位与启用条件，并说明 `route_kinds` 为空只表示直取、priority 不参与快照链。

## v3.3（2026-11-08 · 运行时证据层 + htbr 接入 + 真值单源收口）

一天内四轮改进的收口（四代理架构审计 → 方案二真值单源化 → htbr 接入与充分运用 → 运行时账本 → 收敛轮），8 笔提交：

- **判据收口到运行时证据**：新增 usage 账本（route.fetch 唯一写入点，缓存命中与输入层拒绝不记，诊断命令不自记），doctor 与 datasources 共读同一份 24h 汇总（usage_stats 唯一聚合点）；KIND_FNS 9→4——bond/index/macro/news/notice 恒空链的假承诺摘除，test 钉住「元组 == yaml route_kinds 并集」。
- **SSRF 四层闸并口**：tiingo/fmp 各自内联的 _NoRedirect/_OPENER/_assert_public_host 全删，唯一真身收口 sources/_http.guarded_open；适配器只保留信封语义。
- **htbr 华泰柏瑞ETF 接入**：透传官方 htbr-etf-skill（72 接口事实查询面，route_kinds 留空不进快照链），detect 以 ~/.htbr/credentials.json 为判据（1.0.8 起不读环境变量）；导航别名 56/72（经理 20 + 指数 13 全量 + 分辨率入口），暂停接口不进导航；空结果 empty 标记不落缓存；错误话术映射结构化 error_kind（quota 当日勿重试/scope 勿绕过）。
- **真值单源收口**：invest 门闩表与 mx-data 场景表删源名列（源名只归 yaml 与运行时输出，test_doc_source_truth 钉住场景→命令、命令存在性与源名黑名单）；SKILLS 路径相对定位；venv 版本行退出文档改 doctor 自报；插件拓扑表 htbr keyless 纠正（需官网 Key）。
- **体积门禁固定红线**：MAX_LINES=1400 锁死，删「当前最大值上方约 8%」的合法化机制。
- **发布链修复**：publish-public.sh 的 --exclude scripts 加根锚定（此前把 skills/invest-cli/scripts 剔出公开仓，公开仓 invest_cli.py 冻结在 10-19 的根因）；发布前挂 check.py 与插件 Node 单测两道门禁；根级 packages/dsh-plugin 以相对软链入真源（GitHub 安装路径不再被 --delete 删除）；check_public_sync 对账门禁进 pre-commit（公开仓不得领先真源）。
- **记账机制化**：check.py 新增版本记账门禁（SKILL.md version 与 CHANGELOG 顶条目一致），「改版本忘记账」从惯例问题变成门禁拦截。
- **README 增设 Feedback 入口**；capability-gap 台账迁 invest-cli/docs 并落地 research etf-rank 关闭指数基金横评缺口；测试 614→682。

## v3.2（2026-10-25 · 结构治理 + 验收自动化 + 运行时统一 venv）

一次体检驱动的治理轮：代码基本面全绿（614 tests / 17 源可用），问题集中在
仓库结构、验收时机与运行时一致性三处。**相对上一版改进：**

- **发布链路固化**：新增 `scripts/publish-public.sh`（clone 公开仓 → 真源 rsync
  镜像 → 内置脱敏门 → 演练/--commit/--push 三档）；GPT 工作区大仓上误配的
  origin（直接指向公开仓，一条手滑 push 会把整个个人工作区推上去）已摘除。
- **分支归位**：`~/.agents` 仓 main 从 6 月 13 日快进合并 174 个提交（此前的
  事实主干挂在名不副实的 `feat/mxds-mcp-integration` 上），删两个旧分支。
- **产物出仓**：`report` 默认输出从 CWD/`fund_reports/` 改 state 目录
  `reports/<代码>/`（1.7M PDF 不再堆进 skill 目录）；`skills-backup/` 200M
  移 `.trash/`；第三方技能 mx-mcp-install 收编进真源并按家族约定挂软链。
- **提交门禁**：pre-commit hook——staged 含 `taxue-invest/` 时自动跑
  `check.py`（pytest + F821 + F401 + compileall），F821 类回归「活两天没人
  发现」的窗口关闭。
- **live 用例隔离**：7 条真实联网用例加 `live` marker 默认排除
  （`pytest -m live` 显式跑），「跑一次全绿」在任何机器上是同一句话。
- **运行时统一 venv**：mx-data 被任意解释器启动时自动 exec 进 venv 3.14
  （原仅美股场景缺 yfinance 才升级）。系统 3.9 已 EOL（2025-10）且 LibreSSL
  打 NotOpenSSLWarning 假故障——统一后退出热路径、生产与主测解释器一致。
  公开仓 Python 3.9+ 兼容下限不变（venv 缺失时任意 3.9+ 是合法兜底）。
- **环境修复实锤**：10-23 Python 清理把系统 3.9 的 pyyaml/requests 一并清掉，
  mx-data 快路径静默退化成 subprocess 慢路无人报警——已装回，且新增
  `invest-cli doctor` 子命令（数据源/缓存/解释器/软链/DSH 副本漂移五项自检，
  11 条单测）把这个盲区变成一条命令；首跑即抓到 DSH 副本 license 漂移与
  PATH python3 缺包两真问题。
- **DSH 同步链**：新增 `packages/dsh-plugin/scripts/sync-local.sh`
  （--check 漂移检测 / 同步 / 复检闭环），license 漂移（源 Prosperity-3.0 vs
  副本 MIT）已修复。
- **文档单一真源**：invest-cli SKILL.md 数据源表删除（11 源的表永远追不上
  17 源的 yaml，运行时真值就是 `datasources`）；补 kline/westock/report/
  info/doctor 子命令速览；mx-data stderr 加 urllib3 告警过滤（挂两轮的一行
  修复，现为 venv 化后的二线防线）。
- **测试数字**：3.14 venv 633 collected（625 passed + 1 skipped + 7 live
  deselected，10.1s）；3.9 全量 633 collected（609 passed + 17 skipped + 7
  deselected，4.9s，此前「停在 35% 无 summary」的 execv 悬案已破）。链头断言
  按解释器能力钉：缺 yfinance 环境钉 tencent 降级真值而非误报。

## v3.1（2026-10-19 · 数据源适配器迭代 + 测试扩充 + 美股支持）

eastmoney/hithink/tencent/tiingo/wind/mxds/ttskill/etfirst 八源适配器迭代，
路由逻辑增强；新增 8 个测试文件（含 test_doc_source_truth / test_envelope /
test_module_size_gate / test_py39_compat / test_static_imports 等守卫层）；
invest-stock 与 mx-data 美股用法增强，路由表补「季报/财报/研报」关键词；
docs/INDEX.md、check.py、requirements-dev.txt 落地。细节见公开仓 README
v3.1 增量段与 `invest-cli/docs/性能与缺陷治理报告_2026-10-19_第六轮.md`。

## v3.0（2026-10-13 · 三层架构 + 推理档位）

invest 系列从并列技能改为分层架构：方法论（invest-* 10 技能）/ 数据
（mx-data，invest-cli 统一封装）/ 呈现（mx-templates）。推理分低/中/高三档、
公开默认低档；新增 invest-pool / invest-risk / invest-enterprise / invest-discuss /
invest-analyst；invest-cli 新增 tenure / report / research fund-rank 命令，
MIT 改 Prosperity Public License 3.0。

## v2.9（2026-09-27 · 第六轮：代码归一歧义仲裁 + 热路径白付 + 探测判据回归）

前五轮都在做「热路径去白付 + 回退链收敛」。这一轮换了起点：**先按真实使用权重
量一遍，再决定动哪里**。结论是——热路径已经不是瓶颈，**答错数据**才是。

### 一、真实基线（先量，再优化）

从 216 个真实会话的调用权重 + 本机实测：

| 路径 | 修复前 | 修复后 | 说明 |
|---|---|---|---|
| `stock`（缓存命中，最常用） | 50ms | **30ms** | 去掉一个只为 2 行正则的适配器 import |
| `fund` / `us`（命中） | 51-52ms | 40ms | 去掉重复 yaml 解析 |
| `us`（冷） | 2.36s | 2.35s | **无变化，诚实结论**：这 2.0s 是 yfinance 不可达探测（`HTTP_PROBE_TIMEOUT`），一次探测 120s 负缓存，不是回归 |
| 启动 / `--help` | 37ms | 37ms | 本来就快，不动 |

**为什么 `us` 冷路径不改**：那 2 秒是「Yahoo 端点不可达」的一次性探测成本，
负缓存 120s 内复用。改它要么缩短探测（更早放弃可用性判定，治标不治本），
要么加长负缓存（把瞬时抖动放大成持续不可用）。前四轮已就同一问题做过取舍，
本轮维持。

### 二、修 10 个缺陷，其中 4 个是「一处修复消灭一类」

**① 美股代码被当成市场前缀吃掉（最严重，两份实现）**

`us SHEL`（壳牌）→ 答成**雅诗兰黛**；`us SHW`→Wayfair；`us USB`→巴里克矿业。
整条链 rc=0，把用户问的标的答成**另一家公司**。

根因是**同一个前缀在两个市场都合法**时没有做歧义仲裁。修第一处（`route.canonical_arg`）
之后 `USO`/`USB` 仍错——因为 `sources/tencent.normalize_code` 里还有**第二份**
独立实现。两处都改成可判定的规则：

- `sh/sz/bj/hk` 后面跟**数字**才当前缀（A 股/港股/北交所代码全是数字），
  跟字母则整串是真代码；
- `us` 后面跟字母时按**大小写**仲裁：小写 `us` + 大写代码（`usAAPL`）才是前缀
  写法，真实 ticker 整串大写（`USMOO`）原样保留。

> 教训：「同一件事的第二份实现」是漂移与误用的源头。旧代码里
> `sources/hithink.py:155` 的 `looks_like_hk` 也是同类——本轮一并下沉到 `_common`。

**② 净值缓存被窄窗口投毒**（`sources/ttskill.py`）

`nav_series(code, begin)` 按 `ttnav|{code}` 落盘**切片后**的结果，于是
先查 2022+ 再查 2019+ 时，第二次**零网络请求**拿到 2022+ 的子集，
`ok=True`、`coverage.first` 显示 2022-06——不报错的错数字，且短序列会让
累计收益率与最大回撤**偏小**。改为缓存**过滤前**的全量序列、切片每次现做，
键与语义重新对齐。

**③ 已装的数据源被判死**（`registry.detect` 缺 `command` 分支）

`data-sources.yaml` 里 etfirst 声明 `type: command`，而该分支在 v2.6
「外部 CLI 依赖清理」时随 command/dir 探测一起删了 → `datasources` 恒报
「未知探测方式 'command'」，尽管 `/opt/homebrew/bin/etfirst` 就在那儿。
恢复该分支（适配器 `detect()` 优先，回退 `<bin> --help`），并给 etfirst 补上
`detect()`。**声明与判据漂移的代价是静默的**：链路少一个源，没有任何报错。

**④ index_hub 假可用**（同一个类，漏了它）

yaml 声明 `INDEX_HUB_API_KEY` + key 文件，而适配器**从未读过这两个**
（grep 零命中），真正开关是硬编码的 `api_client.py` 路径。本机两条路径
恰好都在，结论对了但理由是错的；换台机器就会「报可用而取不到数」。
补 `detect()`，判据与实际前置条件对齐，并**第一次真的去读**声明的那个凭据。

**其余 6 个**：`fund --analytics` 在东财回落路径上解析 `"9.99%"` 持仓权重
直接 `TypeError` 崩给用户（`_safe_float` 收口百分号/千位分隔符/哨兵）；
`etfirst` 回列表形状时 `AttributeError`；`bitget` 空壳记录 `ok=True`
（rc=0 假成功，v2.4 给 yfinance 修过的类）；`watchlist` 非原子写 + 损坏文件
当空列表 → **用户自选股静默永久丢失**（无上游可重取，改为 tmp+replace+fsync，
损坏文件留档为 `.corrupt`）；`westock` 的 `--json` 被 `REMAINDER` 转发给子 CLI
导致 unknown flag；`eastmoney`/`fred` 凭据解析不剥引号（带引号的 key 鉴权失败
而 detect 报「已配置」）→ 收敛到 `env.read_credential_file` 一份实现。

### 三、热路径：两处白付，合计 −20ms（占命中路径约 40%）

- **`stock` 命令为一个 2 行正则 import 整个同花顺适配器**：`cmd_stock._looks_like_hk`
  在 `route.fetch` 判缓存**之前**就 `from sources.hithink import looks_like_hk`，
  而后者 import 期拉进 `urllib.request → ssl` + `concurrent.futures`。
  实测 **17.4ms / 50ms**。判据下沉到 `_common`（与 `kind_from_code` 同处一室），
  命中路径现在**不再 import 任何适配器**。
- **`load_registry()` 一次冷取数解析 3+N 次 yaml**（3.8ms/次）：`candidates` 一次、
  `fetch` 一次、`_invoke` **每个候选源再一次**。配置是只读静态的，进程内缓存 +
  把已加载的 registry 传下去。

### 四、对抗验证后补修（自己的修复也要被审）

修完没停——另起一个「以证伪为目标」的独立复核，逐条攻击本轮 10 处改动。
它找出 4 个**我自己引入或没修干净**的问题，全部已修：

1. **`us` 前缀判据过度收紧**（我引入的回归）。第一版用「整串全大写 ⇒ 真实
   ticker」仲裁，把合法的 `USAAPL`/`UsAAPL`/`USaapl` 判成 ticker，
   `invest-cli us USAAPL` 直接查不到。改用**剩余长度**判据（去掉 `us` 后
   ≥4 位字母才算前缀），并给 `route` 与 `tencent` 两处加了**一致性守卫**——
   两份实现曾各写一份、各自漂移过一次，必须钉住同一判据。
2. **持仓权重只修了一半**。集中度三行换了 `_hold_ratio`，同函数里的
   行业分布（`industries[ind] = ... + w`）与加权估值仍用裸值，同一次调用
   里照样 `int + str`。两处一并收口。
3. **`.corrupt` 留档会被下一次损坏顶掉**。固定文件名在第二次损坏时覆盖
   上一份备份——而上一份可能正是唯一含用户原始标的的那份。改为带序号留档。
4. **留档不等于止损**：只留档、不拦写入，用户感知仍是「自选股没了」
   （损坏 → add → 写回一条 → 原数据被覆盖）。补写入闸门：留档未处理时
   `add`/`remove` **拒绝执行并说明恢复方式**，`list` 也必须报损坏而不是
   打印「自选列表为空」。

> 教训：修一个 bug 只补了它**当前触发的那一行**，同函数里的兄弟行照样崩；
> 「留了备份」不等于「用户不会丢数据」。两者都要按**后果**验，不是按代码验。

### 五、文档与守卫

- 修 3 处**悬空命令引用**（`invest bond`/`invest commodity`/`invest macro` 都不是
  `invest-cli` 子命令；`eastmoney 子命令` 连技能都已删）。因整表带「归档」标记，
  原指针守卫会跳过这一段——悬空引用永久豁免，现由新守卫单独钉住。
- 补「通用开场白」规则：「分析一下/看看这个/值得买吗/这只怎么样」4 句
  只说明「要分析」不说明「分析什么」，会唤起技能却无处路由；规则是先从标的
  判定类型再回表，**不因缺关键词就反问**。
- 新增 `test_round6_regressions.py`：**27 个守卫**。其中 10 个**逐一验证过
  red-green**（在回退全部修复的副本上确认为红），其余是能力保持反向用例与
  对抗验证补上的 4 个新守卫。
- 修一个**只在特定机器上失败**的既有测试：eastmoney 那个用例只
  `delenv`，而 `read_env` 还会读 `launchctl` 与 `~/.zshrc`——本机 launchctl 里
  真有 key，于是它读到**开发机的真 key**（无凭据的机器上恒绿）。已隔离。

### 六、测试

**440 通过 / 1 跳过**（本轮前 415 通过 / 1 跳过 + 1 失败；那个失败是上述环境
耦合用例，已修）。功能矩阵 23 条真实命令全绿，含跨市场、港股、美股（含
`USAAPL` 等前缀变体与 `SHEL`/`USO`/`USB` 等真实代码）、基金、宏观、SEC、
公告、选股、westock `--json`（此前报 unknown flag）与全部边界/负例。

## v2.8（2026-09-23 · tenure：把「经理任职期复盘」从手工作业变成一条命令）

起因是一次真实任务：查华商余懿在管的 6 只初始份额产品 —— 分年度业绩/回撤 + 任职以来逐日收益
vs 业绩基准指数（基金代码+BI.WI）+ Excel 留档。人工串起来 **14 分 30 秒**（会话 21:05:09 →
交付 21:19:39），光 Wind 净值就打了 53 次分段调用。这些步骤没有一步需要人的判断，全是确定性
取数与算术 —— 该固化成命令。

### 新增 `invest-cli tenure`

- 两种入口：单基金（`tenure 001959 --manager 余懿`）/ 经理全在管产品（`tenure --manager 余懿
  --company 华商基金`，自动按初始份额过滤）；一次产出终端表 + `--json` + `--excel`
  （概览/每只基金明细/数据来源；无 openpyxl 时自动落同构 CSV，不丢数据）
- 口径写成代码并配回归测试：基期 = 任职日前一交易日（与 Wind 区间收益率同口径，任职当日收益
  计入）、年度最大回撤取年内峰值（不跨年回溯，两种口径实测差 1.4pct）、基准缺口（港股假期）
  前值沿用、年化按 365 自然日
- 数据源编排：Wind 精确路径（复权净值分段并行 / 官方年度字段 / BI.WI 基准）→ ttskill 快路径
  降级；产物标注实际用的源与缺口，不静默降级

### 顺带修的两处取数成本

- **Wind 复权净值单次硬顶 100 行**（实测问「全部」也只回 100 行）→ 分段逻辑收敛进适配器
  （`NAV_CHUNK_DAYS`）；新增进程内熔断：积分/鉴权类硬失败不再重复打网络（实测积分耗尽时
  6 只基金 × 4 次调用 = 24 次无谓往返）
- **天天官方 `TTFUND_NAV_INFO` 一次回成立来全量**（001959 十年 2582 行 0.7s，对比 Wind 分段
  12 次调用 17.2s，≈24.7x）→ 做成快路径；三个坑逐个量化并处理（成立后前 6 周上游只给周频、
  日增长率 2 位小数、部分交易日缺日增长率）。缺增长率用「累计净值差分 / 前日单位净值」复原后，
  任职以来累计与 Wind 官方值的偏差从 ≤6.60pct 收到 ≤0.20pct

### 附：把两条历史提示词合成「基金调研元提示词（带取数）」

调研时真正难的不是「问什么」，是「口径怎么定、数字从哪来」——这部分不该由模型临场决定。
把 2026-02-14《基金深度研究分析提示词（通用版）》（六维）与 2026-03-07《基金经理分析提示词
（优化版）》（五维 + 结论四选一）合并，补上 invest-cli 取数清单与口径红线，落在
`invest-fund/references/fund-research-prompt.md`；素材库只留一行指针（原文保留不维护）。

### 测试

新增 33 个用例（纯口径 / 真实数据基线 / 降级链 / Wind 主路径守卫），全仓 350 通过、1 跳过。
基线 `tenure_samples.json` 用真实快照钉住已校验的交付值（001959 任职以来 +95.6399%、
基准 +16.5450%、2024 年内回撤 -28.907%）。

## v2.7（2026-09-22 · 第四/五轮：热路径去白付 + 腾讯源并入 + 判据层再收紧）

两轮合起来一个方向：**先用真实使用权重定位代价，再动手；能换更快的路就不做微优化**。
完整报告见 `invest-cli/docs/性能与缺陷治理报告_2026-09-22_第四轮.md` 与
`性能与缺陷治理报告_2026-09-22_第五轮_腾讯源整合.md`。

### 一、先量化「日常怎么用」（第四轮）

从 216 个真实会话提取 `invest-cli` 取数调用：**80% 的相邻调用间隔 <60s**（落在 60s
快照 TTL 内）。所以「日常性能」= 缓存命中路径耗时 + 每个标的的第一次取数，冷路径才是少数。
这条数据直接否掉了两个原本准备做的优化（`us` 快照 TTL 60→300s 只惠及 4-5 次；港股那条
3.5s 只占 0.3% 调用），**判定不改**。

- **热路径去掉每次白付的重库开销**（`sources/route.py`）：快照缓存判定此前要先把
  `candidates()` 跑完（`yaml.safe_load` + 整条适配器 import 链，含 `urllib → http.client
  → ssl`），而缓存键只由 `kind/market/arg` 决定，与候选链无关。改为命中即返回。
- **跳过 yfinance `trailingPegRatio` 补取**：该字段不在任何评分口径里，却每次冷取多付一次请求。
- 读数（缓存命中，同机交替各 5 次、无重叠）：`us AAPL` 0.05→0.03s、
  `stock 600519` 0.08→0.05s、`fund 110011` 0.09→0.03s（**3.0x**）、
  `intent deep stock 600519` 0.09→0.05s。**冷路径无可测量变化**（诚实结论：上游抖动淹没）。

### 二、修 19 项缺陷，重点几类（第四轮）

- **代码域不匹配返回冒牌数据**（最严重）：把别的市场/别的类别的数据当成目标标的返回。
- **输入层失败触发跨源猜测**：同一输入可能返回两只不同基金。
- **可用性判据与凭据加载器漂移**：同花顺 / Wind 被静默移出可用链。
- **东财假可用信号**；**`screen` 把「上游没答」说成「未找到结果」**。
- `watchlist` 空代码写盘、`--json` 退出码与信封相悖；非 UTF-8 输出环境抛 traceback；
  `cmd_fund` 在 Python 3.9 上无法导入；`us .L` 股息率低估 100 倍；代码内部空格未清洗；
  基金回撤「全 0」被当有效值。
- 分析层：常驻 description 里的悬空技能名、`cli-runtime.md` 三处口径病、裸文件名引用。

### 三、并入腾讯：三条通道，前两条成为一等数据源（第五轮）

把平行实现 `tencent-invest` 收进 invest-cli：

| 通道 | 是什么 | 处理 |
|---|---|---|
| 腾讯行情原生内核（`qt.gtimg.cn` 等四个零鉴权接口） | 实时/批量/历史行情、K 线、分时、标的搜索 | 收为 `sources/tencent.py` |
| westock CLI（40+ 子命令） | 筹码/龙虎榜/陆股通/北向/两融/一致预期/ESG/机构评级/研报/产业链/板块估值/转债条款/停复牌/风险事件 | 收为 `sources/westock.py` 透传 |
| NeoData 云 API | 自然语言金融查询 | **不吸收**（token 依赖客户端刷新） |

- **链位置 `priority: 37`**（有意卡在 yfinance 40 与 bitget 35 之间）：
  `us = yfinance > tencent > bitget`；`stock = hithink > eastmoney > yfinance > tencent`；
  `fund` / `screen` **不含腾讯**（腾讯无基本面、不接基金）。不进主位是有意的：
  腾讯没有净利润/ROE/EPS/资产负债率，进主位就是把 A 股快照从 13 项基本面退化成纯行情，
  属能力降级——宁可慢 0.4s 也不掉字段。
- **新命令 `quote`（免鉴权多标的实时行情）**：三个市场一次请求 **186ms**，
  对照旧路径同问题串行实测 **7.7s（约 41x）**；6 标的跨市场混合 189ms（多标的边际成本≈0）。
- **新命令 `kline`**（原生快路径 + CLI 兜底）、**新命令 `westock`**（长尾能力透传）。
- **日常热路径零回归**（缓存命中 54/41/42/58ms，与旧版逐项相同）。

### 四、移植时不继承的 17 类缺陷（第五轮，逐条实测）

其中四条属「一处修复消灭一类」：

- **同一数组下标在不同市场是不同量**：`[47]` A 股=涨停价、港股=股息率 TTM；`[57]`
  A 股=成交额、港股=市盈率、美股=ROE。原实现只有一张字段表。→ 按市场分表，逐字段反查。
- **港股换手率恒为 0.0**（真值 0.78%，在另一个下标）。→ 分市场表 + 回归锁。
- **号码重叠时静默返回另一个标的**：`quote(["sz110011"])` 回的是 `sh110011 歌华转债`
  （问的是基金 110011）。→ `stock()` 对基金代码直接拒绝并指向 `fund`；`quote()` 对
  11xxxx 重叠段带冲突说明；`_alt_market` 收窄到同号换市场。
- **帮助文本 / 限流通告当数据返回（rc=0）**：`westock macro gdp` 回 35 行帮助、退出码 0。
  → 在 spawn 边界按形状判定，帮助页与单行短通告一律报错。

其余重点：年线未聚合（当日 K 冒充年 K，改为按自然年合成）、代码位置表不全
（`disclosure 600519` 把「代码没写错」伪装成「该标的没有数据」，补 `bond/disclosure/risk/
score/esg`，并锁定唯一反例 `rating`）、失败吞成空串、未知周期静默降级成日线、
`kline(limit=N)` 恒多回一根、名称解析在 `quote`/`kline` 上给出不同标的、
搜索缓存键不含 `limit`、`None`/NUL 入参抛异常穿透调用方。

### 五、顺手做实（第五轮）

- **同号重叠的告知**：`quote 000001` 会说明「同时也是沪市指数 sh000001」，判据由接口回答。
- **目标价货币符号跟随载荷**：`stock hk00700` 由写死的 `$663.85` 改为 `HK$663.85`，
  认不出的币种只报代码不猜符号。

### 六、回归守卫

测试 **237 → 317**，三个解释器全绿（3.14.7 / 3.9.6 各 317 passed，
Homebrew 无依赖环境 305 passed + 12 skipped）。

## v2.6（2026-09-21 · 去外部 CLI 依赖：三个数据源直连 API）

方向：数据源不应依赖外部 CLI。旧实现里天天基金/盈米/Wind 三个源都是
`subprocess → CLI → API`，每次调用多付一次进程冷启动与一次 JSON 往返。
本轮全部改为**直连 API，认证沿用官方**（不新造登录体系）。

- **天天基金直连 gateway**（`sources/ttskill.py`）：`POST /openapi/skill/invoke`，
  凭据读官方 Keychain（`com.ttfund.ttskill.base`，兼容 `auth/*.json` 回退），
  ed25519 签 `X-Signature` 等五个头（与官方基础包同一套逻辑）；
  版本从本机 `skills/index.json` 取，409 时用服务端 latest 重试一次。
  不再依赖 `ttskill` 二进制。
- **盈米直连 OpenAPI**（`sources/yingmi.py`）：操作清单取官方 `docs.json`（缓存 6h），
  按 operationId 定位后直接 HTTP，`Authorization: Bearer <apiKey>`；
  入参拆分（path/query/header/body）与官方 `splitInput` 同规则。不再依赖 `yingmi-skill-cli`。
- **Wind 直连 MCP**（`sources/wind.py`）：JSON-RPC over HTTP，`tools/call` 直接可用，
  **跳过 initialize**（实测省一次往返，约 0.1s）；上游若以后要求握手，
  失败后自动补一次 `initialize` 重试。Key 顺序与官方一致。不再依赖 node CLI。
- **隔离实测（best-of-3）**：ttskill invoke 0.374s → **0.237s**；
  yingmi call 0.458s → **0.244s**；wind call 0.591s → **0.426s**；
  `capabilities ttskill` 0.743s → **0.087s**（探针从子进程改读本机索引）；
  `capabilities yingmi` 0.756s → **0.08s 热**（doc 落盘）；
  `yingmi <不存在的工具>` 0.47s → **0.06s**（工具名本地校验，不打网络）。
- **低级 bug 修复**：
  - `intent portfolio` / `intent plan` 的**自然语言路径从未能用**：旧实现把整串当
    `{"input": ...}` 发出去，服务端固定回 400（基金列表为空 / 缺投资三性参数）。
    现在：持仓简写（`110011:50,005827:50` / `110011 005827`）→ `fundList`；
    「能承受20%回撤 5年 年化8%」→ 三个查询参数（百分比换小数）。JSON 仍原样透传。
  - 持仓简写的金额必须带显式分隔符（`:`/`=`）：否则「110011 005827」会被
    正则贪心成 `code=110011, amount=5827`（已加守卫）。
  - 凭据每次 `_invoke` 都重跑 `security find-generic-password`（fund 深取一次调用会
    跑 6 次）；改为进程内缓存一次。
- **删掉子进程探测这一整类**：`data-sources.yaml` 已无 `type: command` / `type: dir`，
  对应的 `_probe_command` / `_probe_dir` / `DETECT_TIMEOUT` 与 detect 分支全部删除
  （净删代码）；wind 的 `locate_skill_dir` 也一并删掉。
- **新增依赖**：`cryptography>=41.0`（ed25519 签名，官方同一套）。
- **回归守卫 171 → 192 passed**：新增盈米直连契约（拆分/信封/错误/无 key）、
  ttskill 认证层（凭据形状/签名头/过期判据/索引两种形状）、Wind 直连（端点表/
  SSE 解析/握手回退），以及「适配器不得再起子进程」三条守护。

## v2.5（2026-09-21 · 第二轮：判据层修复 + 路由惰性探测 + 缓存自清）

本轮接着 v2.4 的实测方法重跑一遍，找到的都是「v2.4 之后才暴露或上轮没看到」的项。
完整报告见 `docs/审查报告_2026-09-21_第二轮.md`。

- **最大性能收益：路由探测改为惰性（`sources/route.py`）**。v2.4 之前的 `fetch`
  先 `pick()` 一次性探测整条链，于是每次查 A 股都要为末位兜底的 yfinance
  付一次真实 HTTPS 探测（实测 0.5s），wind 目录探测也白付。现在 `candidates()`
  只做便宜的能力判定（coverage + 真有方法），`fetch` 在**即将调用某个源之前**
  才 `detect()`，主源命中就不再碰兜底源。隔离实测：A 股路由探测段
  **0.515s → 0.007s（73x）**；`stock 600519` 冷路径 **1.52s → 0.51s**。
  `pick()` 保留给 `datasources` / `chains()` 这类「一次看清全链可用性」的场景。
- **hithink 利润表不再请求两次（`sources/hithink.py`）**。v2.4 为拿年报年份先发一次
  `income-statements limit=1` 预览，而批里又有 `limit=5` 的同一端点。现在按年报
  披露规律直接猜财年（5 月起 year-1，1-4 月 year-2）并把 indicators 放进同一批；
  猜错时用批里拿到的真实年份补一次（新增守卫）。A 股冷路径再省一段 RTT。
- **一处修复消灭一类：中文名被判成美股代码（`cmd_intent.classify`）**。
  Python 里汉字也是 `isalpha()`，旧判据 `t.isalpha() and 1<=len(t)<=5` 对
  「茅台」「腾讯」为真，`intent deep 茅台` 会去 Yahoo 找「茅台」（实测 3.2s 白付）。
  判据改为 `t.isascii()`。
- **一处修复消灭一类：盈米名称模糊匹配把股票判成基金（`_is_fund_by_yingmi`）**。
  GuessFundCode 是子串式匹配，实测「中国平安」→「华银平安中国主题灵活配置混合」、
  「招商银行」→「银叶投资-招商银行-宁海工业园1号」。判据从「盈米返回了东西」
  改为「返回的基金名与查询确有对应」（前缀，或查询占基金名 60% 以上）；
  另对 ≤2 字短名不做模糊匹配。19 个常见股票/基金名分类全部正确。
- **一处修复消灭一类：空标的打满整条链（`sources/route.py`）**。
  `stock ""` / `fund ""` / `us ""` / `screen ""` 现在在取数前就被拦下并给一句
  明确中文（原来要 0.1–3.5s、拼三句多源错误）。
- **一处修复消灭一类：上游 data.data 为 null 时抛裸异常（`cmd_screen.py`）**。
  `screen ""` 曾直接抛 `TypeError: 'NoneType' object is not subscriptable`（用户看到
  traceback）。现在逐层容错，`securityCount` 缺失/为 null 按 0 算。
- **缓存自清，磁盘不再无界增长（`_common.py`）**。TTL 只决定读时是否命中，
  不删文件；`sec` 的 companyfacts 单文件约 3.7MB，按查过的公司数无限累积。
  新增 `CACHE_MAX_AGE`（7 天）与写时清理（含残留 `.tmp`），进程内每命名空间一次。
  另清理 7 个 v2.4 重构前的 SEC 旧命名孤儿文件（实测释放 13MB，本机 24M → 11M）。
- **argo 非零退出的原因不再只有 traceback 表头（`sources/argo.py`）**。
  stderr 取最后一行非空内容，用户看到的是真实异常行。
- **`intent deep <type>` 缺标的给出明确报错**，`commodity`/`gold` 是固定场景不受影响
  （反向对照守卫）。
- **回归守卫 156 → 171 passed**，新增 15 条：CJK 分类、盈米误配、短名不模糊匹配、
  缺标的报错、空标的拦截、惰性探测与反向对照、整链不可用措辞不变、缓存清理与阈值有限、
  选股 null 回包与缺失计数、利润表单次请求、财年猜测边界、猜错财年的 fallback、
  argo 取最后一行原因。

## v2.4（2026-09-21 · argo 协作纠偏 + 热路径性能）

本轮从第一性原理重测 invest-cli 的日常耗时与错误形态，全部结论以实机测量为依据。
完整报告见 `invest-cli/docs/性能与缺陷治理报告_2026-09-21.md`。

- **argo 协作三处纠偏（正确性 + 能力解锁）**：`sources/argo.py` 的本地引擎白名单已删除。
  - `cn-web-search` 早已不在 argo 的引擎表里，旧实现把它当合法引擎，用户拿到
    「0 结果 + ok=true」的**静默空答复**；现在以 argo 自己的 `--list-engines`
    清单（磁盘缓存 1h）为准，在发起检索之前就拦下并给出可执行的清单命令。
    注：第一版判据是读 argo stderr 的 `未知引擎`，**第二次同 query 就会失效**
    （argo 命中自身缓存后不再解析引擎，stderr 变空），故改为清单校验，stderr 仅作兜底。
  - 白名单外的合法引擎（如 `anysearch`）会被**静默替换**成 eastmoney；现在引擎名原样透传。
  - `--max-results` 未透传，`limit>5` 被 argo 默认值静默截断；现已透传。
  - 无结果时的原因改为引用 argo 信封里的 `errors`（不再本地猜「缺 key」）。
  - 净删常量与分支，可用引擎从 20 个变成 argo 全部 250+ 个。
- **热路径性能**：
  - `fund` 深取（ttskill 两次子进程，实测 1.0–1.3s）此前**从不缓存**，主快照命中缓存后仍每次重付；
    现按 1h 落盘缓存，只缓存成功结果。热路径 **0.985s → 0.104s（9.5x）**。
  - FRED 四条序列此前串行取数（实测网络段 1.958s）；现并发 + 30min 缓存。
    `intent macro` **2.380s → 0.076s 热 / 0.889s 冷**。
- **低级 bug 修复**：
  - `us <未知代码>`：yfinance 返回非空但无内容的 `info`（`{'trailingPegRatio': None}`）
    会造成全 None 的静默假成功，`history` 还会抛库内 TypeError；现由实体守卫转成明确中文错误。
    守卫**刻意不含 `symbol`/`currency`**，因为它们是请求侧原样回显的。
  - yfinance 把原始 HTTP 响应体经 root logger 打进 stderr；现压到 CRITICAL。
  - `us BRK.B`（类别股点号写法）此前返回空壳快照；现按**事实**回退到 `BRK-B` 取真实数据。
    注意**不做**字符串形状改写：点号也可能是交易所后缀（`VOD.L` 伦敦、`VOW3.F` 法兰克福），
    按形状改会打断它们（中间版本实测打断过 `us VOD.L`，已纠正）。
  - `screen` 的「还有 N 条结果」按固定 15 算，17 条结果时说「还有 2 条」（实际少 7 条）；
    现按实际打印行数算。
  - 缓存临时文件共用 `<name>.tmp`，跨进程写同一键时会互相截断并丢缓存；现按 pid 分名（两处）。
  - 自选股从 `~/.cache/invest-cli/` 迁到 `state_root()`（默认 `~/.config/invest-cli/`，
    可用 `INVEST_CLI_STATE_DIR` 覆盖）：用户数据不该放会被系统清理的缓存目录。旧文件自动迁移。
  - FRED 宏观缓存此前「部分失败也写」，会把缺一条序列的半成品固定 30 分钟；现只在四条全成时写。
  - `fred.liquidity(use_cache=False)` 此前只绕过读、仍然写，测试 mock 会污染生产缓存
    （实测发生过）；现改为不读也不写，`test_fred.py` 另加缓存目录隔离。
- **文档纠偏 3 处**：`--engine` 的引擎示例、`intent macro` 的取数顺序（FRED 优先，nbs_stats 兜底）、
  `screen` 的作用域（只筛股票，基金条件走 `intent screen`）。
- **回归守卫**：全仓测试 129 → 156 passed。测试按不变式拆成三个模块
  （`test_perf_guards.py` 427 行 / `test_source_guards.py` 700 行 / `test_cli_guards.py` 126 行）：
  原单文件 1235 行已越过 1000 行，且混装了探测判据、数据源契约、CLI 输出三类关注点。
  缓存/状态目录隔离与探测缓存清空提到 `conftest.py`，**对所有测试文件生效**
  （不再依赖每个新测试文件作者记得加夹具）。新增 26 条守卫中 15 条经红绿验证，
  5 条为反向对照，6 条为新增能力（对应场景均在修复前用活数据复现过）。
- **严格可维护性复查**：删掉仪式性代码而非美化它（argo 从 stderr 解析引擎名、
  其值与入参恒等）；把无捕获的闭包 `_deep_fetch`、内联的并发取数、内联的读时迁移、
  内联的类别股回退分别提成具名步骤（`_ttskill_deep` / `_collect_series` /
  `_migrate_legacy` / `_resolve_snapshot`），主函数回到单一职责。
  另把内联在入口 `invest_cli.py` 里的 72 行选股排版挪回 `cmd_screen.py`——
  兄弟命令都各自成模块，入口只该做 argparse + 分发（330 → 263 行）。
- 本轮改动经独立审查者对抗复核，其找到的 1 个 P0、2 个 P1 全部成立并已修
  （详见报告第八节），另修正两处测试卫生问题。

## v2.3（2026-09-03 · 消融式维护）

本次按「第一性原理 + MECE + 消融实验」梳理系列，只处理经实验证据证明有价值或损坏的项，删无可证明必要性的复杂性。

- **注册链对齐**：`.codex` 注册链残留 3 个死链（invest-commodity/convertible/reit，指向已删源目录）已删，补齐缺失 6 技能（invest/asset/cli/discuss/macro/stock + fund）。四套链（`.agents` 真源 / `.claude` / `.zcode` / `.codex`）现全部 9/9 对齐。消融证据：`find -xtype l` 死链接扫描为零。
- **死路由清理（消融确认的真实断链）**：
  - invest-discuss 下游路由 `invest-us`（已归档）、`invest-hk-a`（已并入 stock）改指 `invest-stock` / `invest-asset`
  - invest-analyst 下游 `eastmoney`（已删，功能并入 invest-cli）、`market-analysis-radar`（已并入 macro）、能力确认列表同步改指 `invest-macro`/`invest-cli`
  - invest-fund 「言行一致」引用 `references/manager-patterns.md`（相对本目录断裂）统一为跨目录 `../invest-stock/references/manager-patterns.md`，与同文件 403 行一致
- **跨技能引用补前缀**：invest-cli SKILL/docs 中指向 invest-fund 口径真源的 `references/data-pipeline.md` 补全为 `invest-fund/references/data-pipeline.md`，消除 agent 按字面路径解析失败的风险。
- **过期文档对齐退役现状**：
  - 重写 `invest/references/cli-runtime.md`：删 ttfund/fundfof/fundscreen 全篇活性引用（2026-09-03 已退役），改为只声明「登录态源 + 搜索技能」两类外部依赖，并记录运行时数据源可用性矩阵
  - `invest/_shared/invest-asset-merge-design.md`（v2.2 已完成）归档 `.trash/`
- **命令路径统一**：invest-macro / invest-asset(asset-bond) 内硬编码家目录 `python ~/.agents/...` 改统一 `invest-cli` 命令（PATH 优先 + $HOME 兜底），符合 cli-runtime「禁止写死个人家目录」约定
- **隐藏能力文档化**：invest-cli `watchlist` 子命令（本地自选股，复用 route.fetch）此前有实现无文档，SKILL 补齐命令说明（不依赖外部登录态）
- **消融实验放行/不放行的判定**（不删项）：
  - 8 个数据源适配器各有测试覆盖（11 个 test 文件 67 测全绿），无孤儿组件，全部保留
  - 入口 table 所有路由目标技能齐全；9 技能 frontmatter 完整可触发——路由正确性消融通过
  - 端到端冒烟：`stock 600519`(茅台，hithink)、`fund 110011`(易方达优质精选，hithink)、`intent macro`(argo) 真实取数全部成功
  - 6 个分析 SKILL 头部「数据获取」段保留：每段含本技能特有命令（asset 用 `intent deep bond/commodity`、macro 用 `intent macro`），删整段会破坏自包含，非纯冗余

## v2.2（2026-09-03）

- **薄单品种四合一**：invest-bond / invest-convertible / invest-commodity / invest-reit 合并为 invest-asset（同一「三关审查」骨架 × 四种资产参数），资产细则下沉到 `invest-asset/references/asset-{bond,convertible,commodity,reit}.md` + `commodity-gold.md`
- **注册数收敛**：12 → 9（四个旧技能目录从 `.agents`/`.claude`/`.zcode` 三条注册链删除，原文归档 `~/.claude/skills-archive/2026-09-03_merged-invest-asset/`）
- **触发词归一**：四技能 description 触发词全集并入 invest-asset description（A1 验证 100% 覆盖），入口路由表/示例/图谱/归档记录同步改指
- **数据措辞统一**：asset-*.md 内残留 `ttfund bond` / `ttfund gold` 措辞改为 `intent deep bond` / `intent deep commodity`（官方 TTFUND_GOLD_INFO 已封装进 intent，不再裸透传老 CLI）
- **引用同步**：invest-macro / invest-allocation 分工表中四个旧技能名改指 invest-asset

## v2.1（2026-08-30）

- **回归修复**：v2.0 声称的 invest-analyst 路由行、「结论信号 → 下一步」导航表、维护段落此前被误删，本次补回；版本号从 v1.3 对齐到 v2.1
- **数据层口径统一**：cli-runtime.md 声明取数口径以入口「场景 → invest-cli 取数映射」表为真源；「诊断一下 XXXX」统一为 `intent deep fund`（盈米）优先、fundfof 降级备选；invest-cli 各源启用条件写全（同花顺免 key / 东财需 `EASTMONEY_APIKEY` 且港股必经 / 美股 yfinance 未装回退 bitget）
- **死引用清理**：invest-fund 分工表删除已归档的 invest-report / invest-fund-manager 两行，补 invest-allocation / invest-discuss；invest-cli 文案中 invest-us 改为 invest-stock 美股
- **断链清理**：invest-institutional 及 4 个已归档技能的断链入口（invest-fund-read / invest-hk-a / invest-us / fund-investor）移入 `.trash/`；补齐 invest-bond / invest-macro 缺失的 `.claude`、`.zcode` 注册链
- **references 收敛落地**：invest-stock 6 个重复 references 副本改为指向 `invest/_shared/references/` 的相对 symlink，原件归档 `.trash/2026-08-30_invest-stock-references-dup/`
- **入口可用性**：invest-cli SKILL.md 13 处硬编码家目录路径改为 `invest-cli` 命令 + `$HOME` 兜底说明；新增 `~/.local/bin/invest-cli` wrapper
- **测试修复**：route.fetch 新增 `order` / `invoke` 注入参数，回退逻辑测试不再依赖本机数据源配置；新增「整单失败返回 tried 信封」「单源异常续回退」两测
- **frontmatter 清理**：invest-discuss 删除冗余 aliases、description 去 markdown 星号

## v2.0（2026-08-03）

- **真源归并**：invest-stock 与 invest-institutional 的 6 个重复 references（1526 行）收敛到 `_shared/references/`，两成员改为引用共享路径
- **接入 invest-analyst**：路由表 + 图谱新增「IC报告/电话会/一致预期/主题策略 → invest-analyst」
- **任务后导航**：新增「结论信号 → 下一步」导航表（仿 dbs 的闭环设计）
- **维护机制**：新增维护段落（版本/共享方法论/归档记录）
- **清理过期引用**：invest-us 删除对不存在的 invest-report 的引用

## v1.1

- 纯路由入口，覆盖股基债商+配置+圆桌+机构深度分析
