/*
 * @taxueseek/invest-cli-dsh — 浏览器端可视化设置页（无需构建步骤）
 *
 * 由 DSH ModuleLoader 以 lazy-CJS 方式加载：工厂函数里只 require('react')，
 * 其余能力（slots / configForms / remote.credentials / locale）全部由宿主
 * 通过 cordis 服务注入。设置值走 configForms（settings namespace = 'invest-cli'），
 * 密钥走 credentials 域——两者都不经过插件配置文件，密钥绝不回显明文。
 *
 * 参照 Argo 体系设计：
 *   settings.section —— 设置弹窗左侧一级菜单（主入口）
 *   plugins.item     —— 设置 > 插件 页里的卡片（摘要 + 同一面板）
 */
window.__ModuleLoader__.load({
  id: '@taxueseek/invest-cli-dsh',
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;

    const react = require('react');
    const h = react.createElement;
    const useState = react.useState;
    const useEffect = react.useEffect;
    const useRef = react.useRef;

    const NS = 'invest-cli';
    const SECTION_ID = 'invest';

    const DICT = {
      zh: {
        title: 'Invest 投资分析配置',
        intro: '全市场数据接入、子命令执行预算、数据源拓扑与 API 凭据托管。保存后即时生效。',
        loading: '配置加载中…',
        unavailable: '本插件的配置服务不可用（未挂载或只读）。',
        readonly: '当前配置只读。',
        saved: '已保存',
        refused: '宿主拒绝写入（可能只读或字段不可热更新）',
        save: '保存',
        saving: '保存中…',
        on: '开',
        off: '关',
        showMore: '显示更多',
        showLess: '收起',
        tabDashboard: '看板',
        tabAccess: '接入与执行',
        tabCommands: '命令与预算',
        tabSources: '数据源拓扑',
        tabKeys: 'API 凭据',
        tabAdvanced: '高级调优',
        dashboardTitle: '运行监控与数据源全景看板',
        dashboardHint: '实时监控数据源拓扑矩阵、执行预算与工作流预设，提供一键预设与状态排查。',
        presetTitle: '工作流快速预设',
        presetHint: '一键对齐常用投研场景的超时与输出字符预算，免去逐项手动调整。',
        presetFast: '极速日常',
        presetFastDesc: '免鉴权高频源优先（腾讯行情/Bitget/SEC），紧凑字符上限，极速低延迟',
        presetStandard: '平衡投研（推荐）',
        presetStandardDesc: '主流源全覆盖（同花顺/东财/天天基金/妙想），开启公告与研报，标准超时与预算',
        presetDeep: '机构深研',
        presetDeepDesc: '激活万得 Wind、盈米、易方达、经理任职复盘与多年度历史，80K 大字符预算',
        presetApplied: '已应用预设：',
        matrixTitle: '核心数据源拓扑与可用全景',
        matrixHint: '当前数据源的分工、优先级与凭据状态。带免密标识的数据源无需密钥即可直接使用。',
        matrixConfigured: '密钥已就绪',
        matrixKeyless: '免密层可用',
        matrixPending: '待配密钥',
        searchFilterPlaceholder: '输入关键词筛选数据源（如 基金、美股、wind、东财）...',
        summary: 'Invest · {count} 个子命令 · 单次超时 {timeout}s · 字符上限 {chars}k · JSON模式 {json}',
        accessTitle: '接入与通用配置',
        entryTitle: 'CLI 运行时入口',
        entryHint: '默认留空自动探测：优先 ~/.local/bin/invest-cli，其次 skill 自带 .venv/bin/python，最后系统 python3。',
        cliPath: '自定义 CLI 路径',
        cliPathPlaceholder: '留空自动探测（如 /path/to/invest-cli）',
        skillRoot: '自定义 Skill 根目录',
        skillRootPlaceholder: '留空自动探测（如 ~/.agents/taxue-invest/skills/invest-cli）',
        timeoutMs: '默认命令超时 (ms)',
        maxOutputChars: '单次输出字符预算上限',
        jsonMode: '默认结构化 JSON 格式',
        jsonModeHint: '开启后向 LLM 返回结构化 JSON 数据；关闭后返回终端表格（人读形态）。',
        maxArgs: '单次调用参数个数上限',
        commandsTitle: '{count} 个子命令矩阵与业务分类',
        commandsHint: 'invest 工具为单入口收敛架构，避免每轮请求膨胀 4K+ token 常驻开销；以下子命令皆可经由 `invest` 工具调用。',
        commandsSlowNoticeTitle: '长耗时命令保护机制 (COMMAND_TIMEOUTS)',
        commandsSlowNotice: '复盘 (tenure) 串查在管全量净值分段需 180s；主题排行 (research) 最多扫 200 只需分批取，给 180s；研报 PDF (report) 下载需 120s；SEC 原文 (sec) 下载需 90s。插件已内置分档宽限，不被默认 60s 误杀。',
        commandsLimitNoticeTitle: '大结果安全截断保护 (safeClip + COMMAND_OUTPUT_LIMITS)',
        commandsLimitNotice: '美股历史 (us --history) 与 SEC 原文 (sec) 享有 80K 专用输出预算。若结果依然超出上限，插件返回合法的截断信封与 --brief 恢复提示，绝不向模型投喂残缺断裂的坏 JSON。',
        sourcesTitle: '数据源开关与自动路由',
        sourcesHint: '开关控制「自动路由选不选它」（写进插件配置并注入 INVEST_CLI_DISABLE_SOURCES，invest-cli 每次调用都是新进程，保存即时生效）；具名直调（invest-cli wind / htbr）不受影响。同一问题不混源、失败整单回退的纪律不变；实时链序与可用性以 `invest-cli datasources` 自报为准。',
        sourcesNeedsKey: '需凭据',
        sourcesKeyless: '免配置',
        sourcesDisabled: '已停用',
        keysTitle: 'API 凭据安全托管',
        keysHint: '凭据统一保存在 DSH 凭证库中（与 Models 模型页同级），绝不写入代码仓或插件普通配置文件，面板不回显明文。',
        commonKeys: '常用商业与官方数据源',
        moreKeys: '机构与专业数据源',
        configured: '已配置',
        notConfigured: '未配置',
        keyPlaceholderSet: '输入新密钥（留空保持当前配置不变）',
        keyPlaceholderEmpty: '粘贴对应平台的 API Key / 凭据',
        saveKey: '保存',
        clearKey: '清除',
        keySaved: '凭据已安全保存，下次调用即时生效。',
        keyCleared: '凭据已清除。',
        keyUnavailable: 'DSH 凭证服务不可用。',
        advancedTitle: '高级调优与结构说明',
        safeClipTitle: 'safeClip 防坏 JSON 原理',
        safeClipDesc: '普通截断直接截断字符会导致 JSON 后半截缺失，模型 JSON.parse 崩溃并反复报错。safeClip 会在检测到合法 JSON 超出预算时，就地封装为带 truncated: true 与 preview 的合法信封，并告知模型换用更精准的查询。',
        structuralTitle: '结构性配置说明',
        structuralHint: '若需在 profile 中永久挂载或调整插件行，请编辑 profile 的 cordis.patch.yml。',
      },
      en: {
        title: 'Invest Financial Analytics Settings',
        intro: 'Cross-market financial data access, execution budgets, datasource topology and credential vault. Saves apply immediately.',
        loading: 'Loading configuration…',
        unavailable: 'Configuration service unavailable (not mounted or read-only).',
        readonly: 'Configuration is read-only.',
        saved: 'Saved',
        refused: 'Host refused the write (read-only or not live-editable)',
        save: 'Save',
        saving: 'Saving…',
        on: 'on',
        off: 'off',
        showMore: 'Show more',
        showLess: 'Show less',
        tabDashboard: 'Dashboard',
        tabAccess: 'Access & Runtime',
        tabCommands: 'Commands & Limits',
        tabSources: 'Sources & Routing',
        tabKeys: 'API Keys',
        tabAdvanced: 'Advanced',
        dashboardTitle: 'Runtime Telemetry & Datasource Matrix',
        dashboardHint: 'Real-time overview of datasource topologies, execution budgets, and workflow presets.',
        presetTitle: 'Workflow Presets',
        presetHint: 'One-click presets tailored for common financial research scenarios.',
        presetFast: 'Fast Quotes',
        presetFastDesc: 'Keyless high-frequency sources first (Tencent/Bitget/SEC), compact char cap, lowest latency',
        presetStandard: 'Balanced (Recommended)',
        presetStandardDesc: 'Full mainstream coverage (Hithink/Eastmoney/TTFund/MX), notices & reports, standard timeout & budget',
        presetDeep: 'Institutional Deep',
        presetDeepDesc: 'Wind, YingMi, E Fund, manager tenure review and multi-year history, 80K large char budget',
        presetApplied: 'Preset applied:',
        matrixTitle: 'Core Datasource Topology & Coverage',
        matrixHint: 'Roles, priorities, and credential statuses of available sources. Keyless sources work out-of-the-box.',
        matrixConfigured: 'Key Ready',
        matrixKeyless: 'Keyless Ready',
        matrixPending: 'Key Required',
        searchFilterPlaceholder: 'Filter by keyword or source (e.g. fund, us, wind, eastmoney)...',
        summary: 'Invest · {count} subcommands · timeout {timeout}s · char cap {chars}k · JSON {json}',
        accessTitle: 'Access & General Settings',
        entryTitle: 'CLI Runtime Entry',
        entryHint: 'Default auto-detect: ~/.local/bin/invest-cli -> skill .venv/bin/python -> system python3.',
        cliPath: 'Custom CLI Path',
        cliPathPlaceholder: 'Leave empty for auto-detect',
        skillRoot: 'Custom Skill Root',
        skillRootPlaceholder: 'Leave empty for auto-detect',
        timeoutMs: 'Default Command Timeout (ms)',
        maxOutputChars: 'Max Output Character Budget',
        jsonMode: 'Default Structured JSON Mode',
        jsonModeHint: 'When enabled, returns structured JSON to LLM; when disabled, returns human-readable terminal tables.',
        maxArgs: 'Max Arguments per Call',
        commandsTitle: '{count} Subcommands Matrix & Categories',
        commandsHint: 'The invest tool uses a single-entry architecture to avoid token overhead; all {count} subcommands are callable through it.',
        commandsSlowNoticeTitle: 'Slow Command Grace System (COMMAND_TIMEOUTS)',
        commandsSlowNotice: 'Manager tenure review takes up to 180s; research theme ranking scans up to 200 funds and gets 180s; report PDF downloads take 120s; SEC filings take 90s. Built-in grace budgets prevent false timeouts.',
        commandsLimitNoticeTitle: 'Safe Truncation Protection (safeClip + COMMAND_OUTPUT_LIMITS)',
        commandsLimitNotice: 'US stock history and SEC filings have dedicated 80K output budgets. Over-budget outputs are wrapped in parseable JSON envelopes.',
        sourcesTitle: 'Source Toggles & Auto-Routing',
        sourcesHint: 'Toggles control whether a source participates in auto-routing (persisted to plugin config and injected as INVEST_CLI_DISABLE_SOURCES; the CLI runs a fresh process per call, so changes apply immediately). Named direct calls (invest-cli wind / htbr) are unaffected. Single-source consistency and whole-chain fallbacks are unchanged; live chain order and availability come from `invest-cli datasources`.',
        sourcesNeedsKey: 'Needs key',
        sourcesKeyless: 'Keyless',
        sourcesDisabled: 'Disabled',
        keysTitle: 'API Credential Vault',
        keysHint: 'Credentials are encrypted in the DSH credential vault, never saved in plugin configs, and never echoed as plaintext.',
        commonKeys: 'Common Commercial & Official Sources',
        moreKeys: 'Institutional & Specialized Sources',
        configured: 'Configured',
        notConfigured: 'Not configured',
        keyPlaceholderSet: 'Enter a new key (leave empty to keep current)',
        keyPlaceholderEmpty: 'Paste API Key / Credentials',
        saveKey: 'Save',
        clearKey: 'Clear',
        keySaved: 'Credential securely saved and effective immediately.',
        keyCleared: 'Credential cleared.',
        keyUnavailable: 'Credential service unavailable.',
        advancedTitle: 'Advanced Tuning & Architecture',
        safeClipTitle: 'safeClip Broken-JSON Prevention',
        safeClipDesc: 'Truncating text blindly breaks JSON syntax and crashes model parsing. safeClip wraps oversized responses into valid envelope JSON with recovery hints.',
        structuralTitle: 'Structural Configuration',
        structuralHint: 'To permanently mount or alter plugin rows, edit your profile cordis.patch.yml.',
      },
    };

    // >>> generated: registry (scripts/sync_registry.py) — do not edit by hand
    const REGISTRY = {"categories":[{"id":"quotes","nameZh":"行情与快照","nameEn":"Quotes & Snapshots","commands":[{"id":"stock","zh":"A股/港股快照","en":"A/HK Stock Snapshot","desc":"13项基本面+实时行情"},{"id":"fund","zh":"公募基金快照","en":"Mutual Fund Snapshot","desc":"净值/重仓/收益率+评级"},{"id":"us","zh":"美股行情与历史","en":"US Stock & History","desc":"全量快照/EOD历史"},{"id":"quote","zh":"极速免鉴权行情","en":"Fast Quotes (Keyless)","desc":"跨市场毫秒级批量行情"},{"id":"kline","zh":"K线行情","en":"K-Line Bars","desc":"日/周/月K线时序"}]},{"id":"fundamentals","nameZh":"财报与基本面","nameEn":"Fundamentals & Filings","commands":[{"id":"sec","zh":"SEC EDGAR 财报原文","en":"SEC EDGAR Filings","desc":"10-K/10-Q/8-K XBRL 原文及全文检索"},{"id":"fmp","zh":"美股三表深取","en":"FMP Fundamentals","desc":"三表财务/TTM比率/评级/预测"},{"id":"cn","zh":"A股市场结构","en":"CN Market Structure","desc":"公告检索/一致预期/股东/研报"}]},{"id":"governance","nameZh":"选股与治理","nameEn":"Screening & Governance","commands":[{"id":"screen","zh":"自然语言选股","en":"NL Stock Screener","desc":"多因子自然语言选股"},{"id":"fund-class","zh":"基金三层分类","en":"Fund Classification","desc":"大类/风格/细分三层定性"},{"id":"tenure","zh":"经理任职期复盘","en":"Manager Tenure Review","desc":"分年度超额收益与回撤归因"},{"id":"research","zh":"长程研究管线","en":"Research Pipeline","desc":"主题基金排名 / 指数基金横评"}]},{"id":"institutional","nameZh":"机构与透传","nameEn":"Institutional & Pass-through","commands":[{"id":"report","zh":"基金定期报告 PDF","en":"Fund Report PDF","desc":"季报/年报原文下载"},{"id":"westock","zh":"微证券透传","en":"WeStock Pass-through","desc":"筹码/龙虎榜/资金流/产业链"},{"id":"wind","zh":"万得透传","en":"Wind Pass-through","desc":"Wind 金融终端/MCP 原生能力"},{"id":"yingmi","zh":"盈米透传","en":"YingMi Pass-through","desc":"且慢投顾组合与策略"},{"id":"ttskill","zh":"天天基金透传","en":"TTFund Pass-through","desc":"37个官方业务包直连"},{"id":"htbr","zh":"华泰柏瑞ETF事实查询","en":"HTBR ETF Facts","desc":"72 接口：经理观点/行业穿透/盈利预测"},{"id":"sfg","zh":"见基行事基金MCP","en":"SeefundGo Fund MCP","desc":"45 工具：档案/持仓/经理/选基/组合体检"}]},{"id":"auxiliary","nameZh":"宏观与辅助","nameEn":"Macro & Utility","commands":[{"id":"info","zh":"财经资讯检索","en":"Financial News","desc":"argo 财经垂直引擎检索"},{"id":"watchlist","zh":"自选股管理","en":"Watchlist","desc":"自选池增删改查"},{"id":"capabilities","zh":"能力清单","en":"Capabilities Matrix","desc":"各数据源支持能力"},{"id":"datasources","zh":"数据源状态","en":"Data Sources Status","desc":"源可用性与快照链优先级"},{"id":"intent","zh":"意图路由","en":"Intent Router","desc":"资产类型自动识别与分流"},{"id":"doctor","zh":"运行面自检","en":"Runtime Health Check","desc":"源/账本/缓存/解释器/软链/副本六面体检"}]}],"commands":["stock","fund","us","quote","kline","sec","fmp","cn","screen","fund-class","tenure","research","report","westock","wind","yingmi","ttskill","htbr","sfg","info","watchlist","capabilities","datasources","intent","doctor"],"timeouts":{"tenure":180000,"research":180000,"sfg":420000,"report":120000,"sec":90000,"screen":60000,"cn":60000,"fmp":60000},"outputLimits":{"sec":80000,"tenure":80000,"research":60000,"sfg":60000},"defaults":{"timeoutMs":60000,"maxOutputChars":24000,"json":true,"maxArgs":32,"maxArgChars":512,"cliPath":"","skillRoot":"","disabledSources":""},"sources":[{"id":"wind","nameZh":"万得 Wind","nameEn":"Wind AI FinMarket","priority":80,"coverage":"stock, fund, index, bond, news, macro, analytics","kind":"cli","ref":"WIND_API_KEY","keyless":false},{"id":"yingmi","nameZh":"盈米且慢","nameEn":"YingMi Qieman","priority":70,"coverage":"fund, strategy, wealth, news","kind":"api","ref":"YINGMI_API_KEY","keyless":false},{"id":"index_hub","nameZh":"易方达指数直通车","nameEn":"E Fund Index Hub","priority":65,"coverage":"fund, index","kind":"api","ref":"INDEX_HUB_API_KEY","keyless":false},{"id":"sfg","nameZh":"见基行事(seefundgo) 公募基金 MCP","nameEn":"SeefundGo Fund MCP","priority":64,"coverage":"fund, etf, index, manager, screen, ranking, portfolio, market","kind":"api","ref":"SFG_MCP_TOKEN","keyless":false},{"id":"etfirst","nameZh":"首趋E指","nameEn":"etfirst","priority":63,"coverage":"fund, index, etf_detail, valuation, industry_distribution, wind_rank","kind":"cli","ref":"","keyless":true},{"id":"htbr","nameZh":"华泰柏瑞ETF（聚源底座，事实查询面）","nameEn":"HTBR ETF Facts","priority":62,"coverage":"fund, index, etf, fund_manager, industry_distribution, earning_forecast, capital_flow","kind":"api","ref":"~/.htbr/credentials.json","keyless":false},{"id":"hithink","nameZh":"同花顺金融数据服务","nameEn":"Hithink Finance","priority":60,"coverage":"stock, fund","kind":"api","ref":"HITHINK_FINANCE_API_KEY","keyless":false},{"id":"mxds","nameZh":"妙想(MX) MCP","nameEn":"Miaoxiang MCP","priority":55,"coverage":"screen, bond, index, macro, news, notice","kind":"api","ref":"EM_API_KEY","keyless":false},{"id":"ttskill","nameZh":"天天基金（直连 gateway）","nameEn":"TTFund Direct Gateway","priority":55,"coverage":"fund","kind":"api","ref":"TTSKILL_STATUS","keyless":true},{"id":"eastmoney","nameZh":"东方财富","nameEn":"Eastmoney","priority":50,"coverage":"stock, fund, screen","kind":"api","ref":"EASTMONEY_APIKEY","keyless":false},{"id":"sec_edgar","nameZh":"SEC EDGAR 美股财报（10-K XBRL 原文 + 申报清单）","nameEn":"SEC EDGAR Filings","priority":45,"coverage":"us_fundamentals, filings","kind":"api","ref":"","keyless":true},{"id":"yfinance","nameZh":"Yahoo Finance","nameEn":"Yahoo Finance","priority":40,"coverage":"us, stock","kind":"python","ref":"","keyless":true},{"id":"fmp","nameZh":"Financial Modeling Prep（美股深取：三表 JSON/TTM 比率/结构化评级/年度预测）","nameEn":"Financial Modeling Prep","priority":38,"coverage":"us, us_fundamentals, us_estimates, us_rating, dividends","kind":"api","ref":"FMP_API_KEY","keyless":false},{"id":"tencent","nameZh":"腾讯行情（零鉴权原生内核）","nameEn":"Tencent Quotes","priority":37,"coverage":"stock, us, quote","kind":"api","ref":"TENCENT_REACHABLE","keyless":true},{"id":"tiingo","nameZh":"Tiingo 美股 EOD（官方收盘价/复权历史/估值序列）","nameEn":"Tiingo EOD History","priority":36,"coverage":"us, eod_history","kind":"api","ref":"TIINGO_API_KEY","keyless":false},{"id":"bitget","nameZh":"Bitget rToken","nameEn":"Bitget rToken","priority":34,"coverage":"us","kind":"api","ref":"","keyless":true},{"id":"westock","nameZh":"腾讯微证券 CLI（长尾能力透传）","nameEn":"WeStock CLI","priority":30,"coverage":"chip, moneyflow, rank, consensus, sector, industry_chain, bond_detail","kind":"cli","ref":"WESTOCK_BIN","keyless":true},{"id":"fred","nameZh":"FRED 宏观时序（净流动性三序列：WALCL/TGA/ON RRP）","nameEn":"FRED Macro Series","priority":25,"coverage":"macro","kind":"api","ref":"FRED_API_KEY","keyless":true},{"id":"argo","nameZh":"argo 财经检索（资讯/舆情/宏观引擎池）","nameEn":"Argo Financial Search","priority":20,"coverage":"news, macro","kind":"cli","ref":"","keyless":true}],"sourceKeys":[{"ref":"HITHINK_FINANCE_API_KEY","nameZh":"同花顺金融数据","nameEn":"Hithink Finance","hintZh":"同花顺金融 OpenAPI 凭据 (stock, fund)","hintEn":"Hithink Finance credentials","common":true},{"ref":"EASTMONEY_APIKEY","nameZh":"东方财富","nameEn":"Eastmoney","hintZh":"东方财富数据开放平台 Key (stock, fund, screen)","hintEn":"Eastmoney API Key","common":true},{"ref":"EM_API_KEY","nameZh":"妙想(MX) MCP","nameEn":"Miaoxiang MCP","hintZh":"东财妙想自然语言取数 Key (全品类覆盖)","hintEn":"Eastmoney Miaoxiang API Key","common":true},{"ref":"WIND_API_KEY","nameZh":"万得 Wind","nameEn":"Wind AI FinMarket","hintZh":"万得 Wind 金融终端/MCP 密钥 (机构主力)","hintEn":"Wind AI FinMarket Key","common":true},{"ref":"YINGMI_API_KEY","nameZh":"盈米且慢","nameEn":"YingMi Qieman","hintZh":"盈米基金投顾 OpenAPI Key","hintEn":"YingMi OpenAPI Key","common":false},{"ref":"FMP_API_KEY","nameZh":"Financial Modeling Prep","nameEn":"Financial Modeling Prep","hintZh":"美股三表/TTM 比率/评级 Key (每日250次免费)","hintEn":"US fundamental & ratios Key","common":true},{"ref":"TIINGO_API_KEY","nameZh":"Tiingo","nameEn":"Tiingo","hintZh":"Tiingo 美股复权日线与估值序列 Key","hintEn":"Tiingo EOD & valuation Key","common":false},{"ref":"FRED_API_KEY","nameZh":"美联储 FRED","nameEn":"Federal Reserve FRED","hintZh":"FRED 宏观流动性 API Key (无 key 自动免密回退)","hintEn":"FRED API Key (keyless fallback supported)","common":false},{"ref":"INDEX_HUB_API_KEY","nameZh":"易方达指数直通车","nameEn":"E Fund Index Hub","hintZh":"易方达指数投资服务平台 Key","hintEn":"E Fund Index Hub Key","common":false},{"ref":"SFG_MCP_TOKEN","nameZh":"见基行事(seefundgo)","nameEn":"SeefundGo Fund MCP","hintZh":"见基行事公募基金 MCP Token (档案/持仓/经理/选基/组合体检)","hintEn":"SeefundGo fund MCP Token","common":false}]};
    const COMMAND_CATEGORIES = REGISTRY.categories;
    const COMMANDS = REGISTRY.commands;
    const DATA_SOURCES = REGISTRY.sources;
    const DATA_SOURCE_KEYS = REGISTRY.sourceKeys;
    const DEFAULTS = REGISTRY.defaults;
    // <<< generated: registry

    const S = {
      wrap: {
        display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 820,
        color: 'var(--dsw-alias-label-primary, #1f2328)',
      },
      title: { margin: 0, fontSize: 18, fontWeight: 600, lineHeight: '26px' },
      hint: { margin: 0, fontSize: 12, lineHeight: '18px', color: 'var(--dsw-alias-label-tertiary, #7b818b)' },
      notice: { margin: 0, fontSize: 12, lineHeight: '18px', color: 'var(--dsw-alias-state-business-primary, #3b6ef6)' },
      error: { margin: 0, fontSize: 12, lineHeight: '18px', color: 'var(--dsw-alias-state-error-primary, #d1242f)' },
      tabs: {
        display: 'flex', gap: 2, flexWrap: 'wrap',
        borderBottom: '.5px solid var(--dsw-alias-border-l2, #e5e7eb)',
      },
      tab: (active) => ({
        padding: '7px 12px 9px', border: 0, background: 'transparent', cursor: 'pointer',
        font: 'inherit', fontSize: 13, lineHeight: '20px', color: active
          ? 'var(--dsw-alias-label-primary, #1f2328)'
          : 'var(--dsw-alias-label-tertiary, #7b818b)',
        borderBottom: active ? '2px solid var(--dsw-alias-state-business-primary, #3b6ef6)' : '2px solid transparent',
        marginBottom: -1,
      }),
      card: {
        display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 16px',
        borderRadius: 12, border: '.5px solid var(--dsw-alias-border-l3, #e5e7eb)',
        background: 'var(--dsw-alias-settings-card-fill, #fff)',
      },
      cardTitle: { margin: 0, fontSize: 14, fontWeight: 600, lineHeight: '20px' },
      row: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
      field: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 },
      label: { fontSize: 13, fontWeight: 500, lineHeight: '18px' },
      sub: { fontSize: 12, lineHeight: '18px', color: 'var(--dsw-alias-label-tertiary, #7b818b)' },
      input: {
        width: '100%', boxSizing: 'border-box', font: 'inherit', fontSize: 13, lineHeight: '20px',
        padding: '7px 9px', borderRadius: 8,
        border: '.5px solid var(--dsw-alias-border-l4, #d0d7de)',
        background: 'var(--dsw-alias-bg-layer-1, #fff)', color: 'inherit',
      },
      mono: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 },
      textarea: { minHeight: 64, resize: 'vertical' },
      grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 },
      matrixGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 },
      check: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' },
      switchWrap: { display: 'flex', alignItems: 'center', gap: 8 },
      btn: {
        padding: '6px 12px', borderRadius: 8, border: '.5px solid var(--dsw-alias-border-l4, #d0d7de)',
        background: 'var(--dsw-alias-bg-layer-1, #fff)', color: 'inherit', font: 'inherit',
        fontSize: 12, lineHeight: '18px', cursor: 'pointer',
      },
      btnPrimary: {
        padding: '6px 14px', borderRadius: 8, border: '.5px solid var(--dsw-alias-state-business-primary, #3b6ef6)',
        background: 'var(--dsw-alias-state-business-primary, #3b6ef6)', color: '#fff', font: 'inherit',
        fontSize: 12, lineHeight: '18px', cursor: 'pointer',
      },
      chip: (on) => ({
        display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 9px',
        borderRadius: 999, fontSize: 11, lineHeight: '16px',
        border: '.5px solid ' + (on ? 'var(--dsw-alias-state-business-primary, #3b6ef6)' : 'var(--dsw-alias-border-l3, #e5e7eb)'),
        color: on ? 'var(--dsw-alias-state-business-primary, #3b6ef6)' : 'var(--dsw-alias-label-tertiary, #7b818b)',
        background: 'transparent',
      }),
      badge: (type) => ({
        display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: 6,
        fontSize: 11, fontWeight: 500, lineHeight: '16px',
        background: type === 'ready' ? 'rgba(46, 160, 67, 0.12)' : (type === 'keyless' ? 'rgba(59, 110, 246, 0.12)' : 'rgba(235, 87, 87, 0.12)'),
        color: type === 'ready' ? '#1a7f37' : (type === 'keyless' ? '#1f6feb' : '#cf222e'),
      }),
      status: { margin: 0, fontSize: 12, minHeight: 18, lineHeight: '18px' },
      keyRow: {
        display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 12px', borderRadius: 8,
        border: '.5px solid var(--dsw-alias-border-l3, #e5e7eb)',
        background: 'var(--dsw-alias-bg-layer-1, #fafbfc)',
      },
      actions: { display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginTop: 4 },
      divider: { height: 1, background: 'var(--dsw-alias-border-l2, #e5e7eb)', margin: '4px 0' },
    };

    function Card(props) {
      return h('div', { style: S.card }, [
        h('div', { key: 'h', style: S.row }, [
          h('h3', { key: 't', style: S.cardTitle }, props.title),
          props.extra || null,
        ]),
        props.children,
      ]);
    }

    function Field(props) {
      return h('div', { style: S.field }, [
        h('label', { key: 'l', style: S.label }, props.label),
        props.children,
        props.hint ? h('span', { key: 'h', style: S.sub }, props.hint) : null,
      ]);
    }

    function PrimaryButton(props) {
      return h('button', {
        type: 'button',
        disabled: Boolean(props.disabled),
        style: props.primary ? S.btnPrimary : S.btn,
        onClick: props.onClick,
      }, props.children);
    }

    function ToggleSwitch(props) {
      return h('label', { style: S.check }, [
        h('input', {
          type: 'checkbox',
          checked: Boolean(props.checked),
          disabled: Boolean(props.disabled),
          onChange: (e) => props.onChange(e.target.checked),
        }),
        h('span', { style: S.label }, props.label),
      ]);
    }

    function asString(value, fallback = '') {
      return typeof value === 'string' ? value : fallback;
    }

    function asNumber(value, fallback = 0) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function InvestPanel(props) {
      const form = props.hooks ? props.hooks.investForm : undefined;
      const state = form ? form.state : undefined;
      const disabled = !form || (state && state.status !== 'ready');

      const lang = props.locale && String(props.locale).startsWith('en') ? 'en' : 'zh';
      const t = (key) => (DICT[lang] && DICT[lang][key]) || (DICT.zh && DICT.zh[key]) || key;
      // 命令数不在文案里写死：COMMANDS 从分类派生，文案只需 {count} 占位。
      const tc = (key) => t(key).split('{count}').join(String(COMMANDS.length));

      const [tab, setTab] = useState('dashboard');
      const [busy, setBusy] = useState('');
      const [message, setMessage] = useState('');
      const [isError, setError] = useState(false);
      const [filterText, setFilterText] = useState('');

      const [keyBusy, setKeyBusy] = useState('');
      const [keyDraft, setKeyDraft] = useState({});
      const [credentials, setCredentials] = useState({});
      const credSeq = useRef(0);

      const liveValue = () => (state && state.value) || {};

      const [draft, setDraft] = useState(() => ({
        timeoutMs: String(DEFAULTS.timeoutMs),
        maxOutputChars: String(DEFAULTS.maxOutputChars),
        json: DEFAULTS.json,
        maxArgs: String(DEFAULTS.maxArgs),
        cliPath: '',
        skillRoot: '',
      }));

      const dirty = useRef(new Set());

      useEffect(() => {
        const val = liveValue();
        setDraft((prev) => {
          const next = { ...prev };
          if (!dirty.current.has('timeoutMs')) next.timeoutMs = String(val.timeoutMs ?? DEFAULTS.timeoutMs);
          if (!dirty.current.has('maxOutputChars')) next.maxOutputChars = String(val.maxOutputChars ?? DEFAULTS.maxOutputChars);
          if (!dirty.current.has('json')) next.json = val.json ?? DEFAULTS.json;
          if (!dirty.current.has('maxArgs')) next.maxArgs = String(val.maxArgs ?? DEFAULTS.maxArgs);
          if (!dirty.current.has('cliPath')) next.cliPath = asString(val.cliPath, '');
          if (!dirty.current.has('skillRoot')) next.skillRoot = asString(val.skillRoot, '');
          return next;
        });
      }, [state]);

      const refreshCredentials = async () => {
        if (!props.credentials || typeof props.credentials.describe !== 'function') return;
        const seq = ++credSeq.current;
        try {
          const response = await props.credentials.describe(DATA_SOURCE_KEYS.map((entry) => entry.ref));
          if (seq !== credSeq.current) return;
          if (response && response.ok) setCredentials(response.value || {});
        } catch {
          // Credential service temporarily unavailable: keep last state
        }
      };

      useEffect(() => {
        if (props.view === 'summary') return undefined;
        void refreshCredentials();
        const offs = [];
        if (props.remote && typeof props.remote.$on === 'function') {
          const offCreds = props.remote.$on('credentials/reference-updated', () => { void refreshCredentials(); });
          if (typeof offCreds === 'function') offs.push(offCreds);
        }
        return () => { for (const off of offs) off(); };
      }, [state]);

      const report = (ok, textMsg) => {
        setError(!ok);
        setMessage(textMsg);
      };

      const write = async (ops) => {
        if (disabled) return false;
        setBusy('save');
        try {
          const ok = await props.mutate(ops);
          report(ok, ok ? t('saved') : t('refused'));
          return ok;
        } catch (cause) {
          report(false, cause && cause.message ? cause.message : String(cause));
          return false;
        } finally {
          setBusy('');
        }
      };

      const edit = (key, textVal) => {
        dirty.current.add(key);
        setDraft((prev) => ({ ...prev, [key]: textVal }));
      };

      const saveAccess = async () => {
        const ok = await write([
          { op: 'set', path: ['timeoutMs'], value: Math.max(1000, asNumber(draft.timeoutMs, DEFAULTS.timeoutMs)) },
          { op: 'set', path: ['maxOutputChars'], value: Math.max(500, asNumber(draft.maxOutputChars, DEFAULTS.maxOutputChars)) },
          { op: 'set', path: ['json'], value: Boolean(draft.json) },
          { op: 'set', path: ['maxArgs'], value: Math.max(4, asNumber(draft.maxArgs, DEFAULTS.maxArgs)) },
          { op: 'set', path: ['cliPath'], value: draft.cliPath.trim() },
          { op: 'set', path: ['skillRoot'], value: draft.skillRoot.trim() },
        ]);
        if (ok) {
          dirty.current.delete('timeoutMs');
          dirty.current.delete('maxOutputChars');
          dirty.current.delete('json');
          dirty.current.delete('maxArgs');
          dirty.current.delete('cliPath');
          dirty.current.delete('skillRoot');
        }
      };

      // 数据源开关（写 config.disabledSources → spawn 注入 INVEST_CLI_DISABLE_SOURCES）。
      // 与 route.disabled_sources() 同一解析口径：逗号/分号/空白分隔，大小写不敏感。
      const parseDisabledSources = (raw) => {
        const text = String(raw ?? '').trim();
        if (!text) return new Set();
        return new Set(text.split(/[,;\s]+/).map((s) => s.trim().toLowerCase()).filter(Boolean));
      };

      const toggleSource = async (sid, enable) => {
        if (disabled) return;
        const next = parseDisabledSources(liveValue().disabledSources);
        if (enable) next.delete(sid);
        else next.add(sid);
        setBusy('sources');
        try {
          await write([{ op: 'set', path: ['disabledSources'], value: [...next].join(',') }]);
        } finally {
          setBusy('');
        }
      };

      const applyPreset = async (presetType) => {
        if (disabled) return;
        setBusy('preset');
        try {
          let timeoutMs = DEFAULTS.timeoutMs;
          let maxOutputChars = DEFAULTS.maxOutputChars;
          let json = true;

          if (presetType === 'fast') {
            timeoutMs = 30000;
            maxOutputChars = 16000;
            json = true;
          } else if (presetType === 'standard') {
            timeoutMs = 60000;
            maxOutputChars = 24000;
            json = true;
          } else if (presetType === 'deep') {
            timeoutMs = 120000;
            maxOutputChars = 80000;
            json = true;
          }

          const ok = await write([
            { op: 'set', path: ['timeoutMs'], value: timeoutMs },
            { op: 'set', path: ['maxOutputChars'], value: maxOutputChars },
            { op: 'set', path: ['json'], value: json },
          ]);

          if (ok) {
            dirty.current.clear();
            setDraft((prev) => ({
              ...prev,
              timeoutMs: String(timeoutMs),
              maxOutputChars: String(maxOutputChars),
              json,
            }));
            const label = presetType === 'fast' ? t('presetFast') : (presetType === 'standard' ? t('presetStandard') : t('presetDeep'));
            report(true, `${t('presetApplied')} ${label}`);
          }
        } finally {
          setBusy('');
        }
      };

      const saveKey = async (ref) => {
        const val = asString(keyDraft[ref]).trim();
        if (!val || !props.credentials) return;
        setKeyBusy(ref);
        try {
          const resp = await props.credentials.set(ref, val);
          if (!resp || !resp.ok) {
            throw new Error((resp && resp.error && resp.error.message) || t('keyUnavailable'));
          }
          setKeyDraft((prev) => ({ ...prev, [ref]: '' }));
          report(true, t('keySaved'));
          await refreshCredentials();
        } catch (cause) {
          report(false, cause && cause.message ? cause.message : String(cause));
        } finally {
          setKeyBusy('');
        }
      };

      const clearKey = async (ref) => {
        if (!props.credentials) return;
        setKeyBusy(ref);
        try {
          const resp = await props.credentials.unset(ref);
          if (!resp || !resp.ok) {
            throw new Error((resp && resp.error && resp.error.message) || t('keyUnavailable'));
          }
          report(true, t('keyCleared'));
          await refreshCredentials();
        } catch (cause) {
          report(false, cause && cause.message ? cause.message : String(cause));
        } finally {
          setKeyBusy('');
        }
      };

      // Summary view for Settings > Plugins card
      if (props.view === 'summary') {
        const timeoutS = Math.round(asNumber(draft.timeoutMs, DEFAULTS.timeoutMs) / 1000);
        const charsK = Math.round(asNumber(draft.maxOutputChars, DEFAULTS.maxOutputChars) / 1000);
        return h('span', { style: S.sub },
          tc('summary')
            .replace('{timeout}', String(timeoutS))
            .replace('{chars}', String(charsK))
            .replace('{json}', draft.json ? t('on') : t('off'))
        );
      }

      const tabButton = (id, textLabel) =>
        h('button', {
          key: id,
          type: 'button',
          style: S.tab(tab === id),
          onClick: () => { setTab(id); setMessage(''); },
        }, textLabel);

      const statusLine = message
        ? h('p', { key: 'status', style: isError ? S.error : S.notice }, message)
        : null;

      const panel = [];

      // ── Tab 1: 看板 (Dashboard) ──
      if (tab === 'dashboard') {
        const currentTimeout = asNumber(draft.timeoutMs, DEFAULTS.timeoutMs);
        const currentChars = asNumber(draft.maxOutputChars, DEFAULTS.maxOutputChars);

        // 快速预设卡片
        panel.push(h(Card, { key: 'presets', title: t('presetTitle') }, [
          h('p', { key: 'p_hint', style: S.hint }, t('presetHint')),
          h('div', { key: 'p_grid', style: S.grid }, [
            h('div', {
              key: 'fast',
              style: {
                ...S.keyRow,
                cursor: 'pointer',
                borderColor: currentTimeout <= 30000 && currentChars <= 16000 ? 'var(--dsw-alias-state-business-primary, #3b6ef6)' : undefined,
              },
              onClick: () => { void applyPreset('fast'); },
            }, [
              h('div', { key: 'h', style: S.row }, [
                h('span', { key: 't', style: { fontWeight: 600, fontSize: 13 } }, t('presetFast')),
                h('span', { key: 'b', style: S.badge('keyless') }, '30s / 16K'),
              ]),
              h('span', { key: 'd', style: S.sub }, t('presetFastDesc')),
            ]),
            h('div', {
              key: 'std',
              style: {
                ...S.keyRow,
                cursor: 'pointer',
                borderColor: currentTimeout === 60000 && currentChars === 24000 ? 'var(--dsw-alias-state-business-primary, #3b6ef6)' : undefined,
              },
              onClick: () => { void applyPreset('standard'); },
            }, [
              h('div', { key: 'h', style: S.row }, [
                h('span', { key: 't', style: { fontWeight: 600, fontSize: 13 } }, t('presetStandard')),
                h('span', { key: 'b', style: S.badge('ready') }, '60s / 24K'),
              ]),
              h('span', { key: 'd', style: S.sub }, t('presetStandardDesc')),
            ]),
            h('div', {
              key: 'deep',
              style: {
                ...S.keyRow,
                cursor: 'pointer',
                borderColor: currentTimeout >= 120000 && currentChars >= 80000 ? 'var(--dsw-alias-state-business-primary, #3b6ef6)' : undefined,
              },
              onClick: () => { void applyPreset('deep'); },
            }, [
              h('div', { key: 'h', style: S.row }, [
                h('span', { key: 't', style: { fontWeight: 600, fontSize: 13 } }, t('presetDeep')),
                h('span', { key: 'b', style: S.badge('keyless') }, '120s / 80K'),
              ]),
              h('span', { key: 'd', style: S.sub }, t('presetDeepDesc')),
            ]),
          ]),
        ]));

        // 核心数据源全景与拓扑矩阵
        const filterLower = filterText.trim().toLowerCase();
        const filteredSources = DATA_SOURCES.filter((s) => {
          if (!filterLower) return true;
          return s.id.toLowerCase().includes(filterLower) ||
            s.nameZh.toLowerCase().includes(filterLower) ||
            s.nameEn.toLowerCase().includes(filterLower) ||
            s.coverage.toLowerCase().includes(filterLower);
        });

        panel.push(h(Card, {
          key: 'matrix',
          title: t('matrixTitle'),
          extra: h('input', {
            type: 'text',
            placeholder: t('searchFilterPlaceholder'),
            style: { ...S.input, width: 220, fontSize: 12, padding: '4px 8px' },
            value: filterText,
            onChange: (e) => setFilterText(e.target.value),
          }),
        }, [
          h('p', { key: 'm_hint', style: S.hint }, t('matrixHint')),
          h('div', { key: 'm_grid', style: S.matrixGrid }, filteredSources.map((src) => {
            const hasKeyRef = Boolean(src.ref);
            const isConfigured = hasKeyRef && credentials[src.ref] && credentials[src.ref].configured;
            const badgeType = src.keyless ? 'keyless' : (isConfigured ? 'ready' : 'pending');
            const badgeLabel = src.keyless ? t('matrixKeyless') : (isConfigured ? t('matrixConfigured') : t('matrixPending'));

            return h('div', { key: src.id, style: S.keyRow }, [
              h('div', { key: 'h', style: S.row }, [
                h('span', { key: 'name', style: { fontWeight: 600, fontSize: 13 } }, lang === 'en' ? src.nameEn : src.nameZh),
                h('span', { key: 'b', style: S.badge(badgeType) }, badgeLabel),
              ]),
              h('div', { key: 'sub', style: { display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--dsw-alias-label-tertiary, #7b818b)' } }, [
                h('span', { key: 'p' }, `P${src.priority} · ${src.kind.toUpperCase()}`),
                h('span', { key: 'cov' }, src.coverage.split(',')[0]),
              ]),
            ]);
          })),
        ]));
      }

      // ── Tab 2: 接入与执行 (Access & Runtime) ──
      if (tab === 'access') {
        panel.push(h(Card, { key: 'access', title: t('accessTitle') }, [
          h(Field, { key: 'cli', label: t('cliPath'), hint: t('entryHint') }, h('input', {
            type: 'text',
            style: { ...S.input, ...S.mono },
            placeholder: t('cliPathPlaceholder'),
            value: draft.cliPath,
            disabled,
            onChange: (e) => edit('cliPath', e.target.value),
          })),
          h(Field, { key: 'root', label: t('skillRoot') }, h('input', {
            type: 'text',
            style: { ...S.input, ...S.mono },
            placeholder: t('skillRootPlaceholder'),
            value: draft.skillRoot,
            disabled,
            onChange: (e) => edit('skillRoot', e.target.value),
          })),
          h('div', { key: 'nums', style: S.grid }, [
            h(Field, { key: 'timeout', label: t('timeoutMs'), hint: '默认 60000ms' }, h('input', {
              type: 'number',
              style: S.input,
              value: draft.timeoutMs,
              disabled,
              onChange: (e) => edit('timeoutMs', e.target.value),
            })),
            h(Field, { key: 'chars', label: t('maxOutputChars'), hint: '默认 24000 字符' }, h('input', {
              type: 'number',
              style: S.input,
              value: draft.maxOutputChars,
              disabled,
              onChange: (e) => edit('maxOutputChars', e.target.value),
            })),
            h(Field, { key: 'args', label: t('maxArgs'), hint: '单次调用参数上限（默认 32）' }, h('input', {
              type: 'number',
              style: S.input,
              value: draft.maxArgs,
              disabled,
              onChange: (e) => edit('maxArgs', e.target.value),
            })),
          ]),
          h('div', { key: 'json_row', style: { marginTop: 6 } }, [
            h(ToggleSwitch, {
              key: 'json',
              checked: draft.json,
              disabled,
              label: t('jsonMode'),
              onChange: (checked) => edit('json', checked),
            }),
            h('p', { key: 'json_h', style: { ...S.hint, marginTop: 4, marginLeft: 24 } }, t('jsonModeHint')),
          ]),
          h('div', { key: 'actions', style: S.actions }, [
            h(PrimaryButton, {
              primary: true,
              disabled: disabled || busy === 'save',
              onClick: () => { void saveAccess(); },
            }, busy === 'save' ? t('saving') : t('save')),
          ]),
        ]));
      }

      // ── Tab 3: 命令与预算 (Commands & Limits) ──
      if (tab === 'commands') {
        panel.push(h(Card, { key: 'cmd_notices', title: t('commandsSlowNoticeTitle') }, [
          h('p', { key: 'n1', style: S.hint }, t('commandsSlowNotice')),
          h('p', { key: 'n2', style: { ...S.hint, marginTop: 4 } }, t('commandsLimitNotice')),
        ]));

        panel.push(h(Card, { key: 'cats', title: tc('commandsTitle') }, [
          h('p', { key: 'c_hint', style: S.hint }, tc('commandsHint')),
          ...COMMAND_CATEGORIES.map((cat) => h('div', { key: cat.id, style: { display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 } }, [
            h('span', { key: 'name', style: { fontWeight: 600, fontSize: 13, color: 'var(--dsw-alias-state-business-primary, #3b6ef6)' } }, lang === 'en' ? cat.nameEn : cat.nameZh),
            h('div', { key: 'items', style: S.matrixGrid }, cat.commands.map((cmd) => h('div', { key: cmd.id, style: S.keyRow }, [
              h('div', { key: 'h', style: S.row }, [
                h('span', { key: 'id', style: { fontWeight: 600, fontFamily: 'monospace', fontSize: 12 } }, cmd.id),
                h('span', { key: 'title', style: S.sub }, lang === 'en' ? cmd.en : cmd.zh),
              ]),
              h('span', { key: 'd', style: { fontSize: 11, color: 'var(--dsw-alias-label-tertiary, #7b818b)' } }, cmd.desc),
            ]))),
          ])),
        ]));
      }

      // ── Tab 4: 数据源开关与自动路由 (Sources & Routing) ──
      // 链序是运行时事实（route.candidates：yaml × 适配器能力 × 停用集 − 探测），
      // 面板不硬编码它——上一版手写的五条链在 mxds 移出 stock 链后全部失真。
      // 这里只给「选择」（写 disabledSources）与注册表里的静态元数据，
      // 实时链序与可用性指给 invest-cli datasources / doctor。
      if (tab === 'sources') {
        const disabledSet = parseDisabledSources(liveValue().disabledSources);
        panel.push(h(Card, { key: 'routing', title: t('sourcesTitle') }, [
          h('p', { key: 'r_hint', style: S.hint }, t('sourcesHint')),
          ...DATA_SOURCES.map((entry) => renderSourceRow(entry, disabledSet)),
        ]));
      }

      // ── Tab 5: API 凭据 (API Keys) ──
      if (tab === 'keys') {
        panel.push(h(Card, { key: 'keys_card', title: t('keysTitle') }, [
          h('p', { key: 'k_hint', style: S.hint }, t('keysHint')),
          h('span', { key: 'comm_title', style: { fontWeight: 600, fontSize: 13, marginTop: 4 } }, t('commonKeys')),
          ...DATA_SOURCE_KEYS.filter((k) => k.common).map((entry) => renderKeyRow(entry)),
          h('div', { key: 'div', style: S.divider }),
          h('span', { key: 'more_title', style: { fontWeight: 600, fontSize: 13, marginTop: 4 } }, t('moreKeys')),
          ...DATA_SOURCE_KEYS.filter((k) => !k.common).map((entry) => renderKeyRow(entry)),
        ]));
      }

      function renderKeyRow(entry) {
        const cred = credentials[entry.ref] || {};
        const isSet = Boolean(cred.configured);
        const currentDraft = keyDraft[entry.ref] || '';
        const isBusyNow = keyBusy === entry.ref;

        return h('div', { key: entry.ref, style: S.keyRow }, [
          h('div', { key: 'head', style: S.row }, [
            h('div', { key: 'meta', style: { display: 'flex', flexDirection: 'column' } }, [
              h('span', { key: 'name', style: { fontWeight: 600, fontSize: 13 } }, lang === 'en' ? entry.nameEn : entry.nameZh),
              h('span', { key: 'ref', style: { ...S.sub, fontFamily: 'monospace', fontSize: 11 } }, `${entry.ref} · ${lang === 'en' ? entry.hintEn : entry.hintZh}`),
            ]),
            h('span', { key: 'st', style: S.badge(isSet ? 'ready' : 'pending') }, isSet ? t('configured') : t('notConfigured')),
          ]),
          h('div', { key: 'inputs', style: { display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 } }, [
            h('input', {
              key: 'inp',
              type: 'password',
              autoComplete: 'off',
              spellCheck: false,
              style: { ...S.input, ...S.mono, flex: 1 },
              placeholder: isSet ? t('keyPlaceholderSet') : t('keyPlaceholderEmpty'),
              value: currentDraft,
              disabled: isBusyNow,
              onChange: (e) => setKeyDraft({ ...keyDraft, [entry.ref]: e.target.value }),
            }),
            h(PrimaryButton, {
              key: 'btn_s',
              primary: true,
              disabled: isBusyNow || !currentDraft.trim(),
              onClick: () => { void saveKey(entry.ref); },
            }, isBusyNow ? t('saving') : t('saveKey')),
            isSet ? h(PrimaryButton, {
              key: 'btn_c',
              primary: false,
              disabled: isBusyNow,
              onClick: () => { void clearKey(entry.ref); },
            }, t('clearKey')) : null,
          ]),
        ]);
      }

      function renderSourceRow(entry, disabledSet) {
        const enabled = !disabledSet.has(entry.id);
        const busyNow = busy === 'sources';
        const metaBits = [
          `prio ${entry.priority}`,
          entry.coverage || '-',
          entry.keyless ? t('sourcesKeyless') : t('sourcesNeedsKey'),
        ];
        return h('div', { key: entry.id, style: S.keyRow }, [
          h('div', { key: 'head', style: S.row }, [
            h('label', { key: 'tog', style: { ...S.switchWrap, cursor: busyNow ? 'wait' : 'pointer' } }, [
              h('input', {
                key: 'cb',
                type: 'checkbox',
                checked: enabled,
                disabled: busyNow,
                onChange: (e) => { void toggleSource(entry.id, e.target.checked); },
              }),
              h('span', { key: 'id', style: { fontWeight: 600, fontFamily: 'monospace', fontSize: 12 } }, entry.id),
            ]),
            h('span', { key: 'n', style: S.sub }, lang === 'en' ? (entry.nameEn || entry.id) : (entry.nameZh || entry.nameEn || entry.id)),
            enabled ? null : h('span', { key: 'st', style: S.badge('pending') }, t('sourcesDisabled')),
          ]),
          h('span', { key: 'm', style: { fontSize: 11, color: 'var(--dsw-alias-label-tertiary, #7b818b)' } }, metaBits.join(' · ')),
        ]);
      }

      // ── Tab 6: 高级调优 (Advanced) ──
      if (tab === 'advanced') {
        panel.push(h(Card, { key: 'adv', title: t('advancedTitle') }, [
          h('span', { key: 's_title', style: { fontWeight: 600, fontSize: 13 } }, t('safeClipTitle')),
          h('p', { key: 's_desc', style: S.hint }, t('safeClipDesc')),
          h('div', { key: 'div', style: S.divider }),
          h('span', { key: 'st_title', style: { fontWeight: 600, fontSize: 13 } }, t('structuralTitle')),
          h('p', { key: 'st_hint', style: S.hint }, t('structuralHint')),
        ]));
      }

      return h('div', { style: S.wrap }, [
        h('div', { key: 'head', style: { display: 'flex', flexDirection: 'column', gap: 4 } }, [
          h('h2', { key: 't', style: S.title }, t('title')),
          h('p', { key: 'i', style: S.hint }, t('intro')),
        ]),
        h('div', { key: 'tabs', style: S.tabs }, [
          tabButton('dashboard', t('tabDashboard')),
          tabButton('access', t('tabAccess')),
          tabButton('commands', t('tabCommands')),
          tabButton('sources', t('tabSources')),
          tabButton('keys', t('tabKeys')),
          tabButton('advanced', t('tabAdvanced')),
        ]),
        statusLine,
        ...panel,
      ]);
    }

    const inject = ['slots', 'locale', 'configForms', 'remote', 'remote.credentials'];

    function apply(ctx) {
      const form = ctx.configForms.get(NS);
      const locale = ctx.locale ?? (typeof ctx.get === 'function' ? ctx.get('locale') : undefined);
      const credentials = ctx.remote ? ctx.remote.credentials : undefined;
      const label = () => 'Invest 投资分析';

      const injected = () => ({
        hooks: { investForm: form },
        set: (field, next) => form.set(field, next),
        mutate: (ops) => form.mutate(ops),
        credentials,
        remote: ctx.remote,
        locale,
      });

      ctx.effect(() => ctx.configForms.whileServed([NS], () => {
        const offs = [
          ctx.slots.inject('settings.section', () => ctx.slots.register({
            name: 'settings.section',
            id: SECTION_ID,
            order: 28,
            label,
            inject: injected,
          }, InvestPanel)),
          ctx.slots.inject('plugins.item', () => ctx.slots.register({
            name: 'plugins.item',
            id: SECTION_ID,
            order: 52,
            label,
            inject: injected,
          }, InvestPanel)),
        ];
        return () => {
          for (const off of offs) if (typeof off === 'function') off();
        };
      }), 'invest-cli-dsh: settings page');
    }

    exports.apply = apply;
    exports.inject = inject;
    exports.InvestPanel = InvestPanel;
    exports.COMMANDS = COMMANDS;
    exports.COMMAND_CATEGORIES = COMMAND_CATEGORIES;
    exports.DATA_SOURCES = DATA_SOURCES;
    exports.DATA_SOURCE_KEYS = DATA_SOURCE_KEYS;
    exports.DEFAULTS = DEFAULTS;

    return module.exports;
  },
});
