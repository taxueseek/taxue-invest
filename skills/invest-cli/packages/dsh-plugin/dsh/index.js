/*
 * @taxueseek/invest-cli-dsh — 把 invest-cli 收敛成单个 invest 工具，并提供可视化配置与诊断。
 *
 * 形态选择：单入口 + CLI 单发（不是每个子命令一个具名工具，也不挂 MCP）。
 *   · 工具定义（名称+描述+schema）每轮请求都注入上下文且压缩清不掉；
 *     逐个具名工具 ≈4.5K token/轮 的常驻开销，而本 CLI 的调用面是平摊的
 *     （会话日志实测 top5 是 stock/sec/us/cn/tenure，各占 6–9%），没有哪条
 *     够格做「专属工具」；
 *   · 单入口把常驻开销压到 ≈0.5K/轮，能力面一个不少（全部子命令可达）。
 *   与 Argo 的取舍同源（那边是 2 个原生工具 + MCP 默认关）。
 *
 * 参照 Argo 体系设计：
 *   · 统一配置规范与 Schemastery schema（可选依赖，运行时优雅降级）
 *   · 原生可视化设置页（运行看板 / 接入与执行 / 命令与预算 / 数据源拓扑 / API 凭据 / 高级调优）
 *   · safeClip 守卫：超预算返回合法信封与恢复提示，绝不向模型投喂残缺损坏的坏 JSON
 *   · 多级超时分档与大结果专用预算（tenure/report/sec 等慢命令保护）
 *
 * 真源不变：CLI 脚本仍是唯一实现，本插件负责「参数校验 + 动态预算 + 安全截断 + 可视化治理」。
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { REGISTRY } from './registry.generated.js'

/** Cordis 插件名 —— 必须与 cordis.patch.yml 里的行 id 一致。 */
export const name = 'invest-cli'

/** 依赖 tools；systemPrompt 为可选增强，缺席时跳过（headless 环境亦可加载）。 */
export const inject = ['tools']

const text = (value) => [{ type: 'text', text: value }]

/** 命令面与插件元数据：唯一真源是 scripts/command_registry.py，本文件只消费生成物。 */
export const COMMAND_CATEGORIES = Object.freeze(REGISTRY.categories)

export const COMMANDS = Object.freeze(REGISTRY.commands)

/** 数据源面板：id/优先级/覆盖/凭据来自 data-sources.yaml，英文名与免密标记来自注册表。 */
export const DATA_SOURCES = Object.freeze(REGISTRY.sources)

export const DATA_SOURCE_KEYS = Object.freeze(REGISTRY.sourceKeys)

/** 慢命令预算、大结果预算与默认值；改值去 scripts/command_registry.py。 */
export const COMMAND_TIMEOUTS = Object.freeze(REGISTRY.timeouts)

export const DEFAULTS = Object.freeze(REGISTRY.defaults)

export const COMMAND_OUTPUT_LIMITS = Object.freeze(REGISTRY.outputLimits)

/**
 * Schemastery 可选加载：若宿主提供则导出 Schema 供 DSH 设置表单自动校验，
 * 缺席时优雅降级为 undefined（离线测试与 headless 环境不受影响）。
 */
let Schema
try {
  const schemastery = await import('@deepseek-ai/schemastery')
  Schema = schemastery.default ?? schemastery.Schema ?? schemastery
} catch {
  // 无 schemastery 依赖时保持 undefined
}

export const Config = Schema === undefined ? undefined : Schema.object({
  timeoutMs: Schema.number().default(DEFAULTS.timeoutMs)
    .description('单次命令默认超时（毫秒）')
    .volatile(),
  maxOutputChars: Schema.number().default(DEFAULTS.maxOutputChars)
    .description('单次命令返回字符上限（字符）')
    .volatile(),
  json: Schema.boolean().default(DEFAULTS.json)
    .description('默认返回结构化 JSON（false 为终端表格）')
    .volatile(),
  maxArgs: Schema.number().default(DEFAULTS.maxArgs)
    .description('单次调用的参数个数上限')
    .volatile(),
  cliPath: Schema.string().default('')
    .description('自定义 invest-cli 二进制或入口路径（留空自动探测）')
    .volatile(),
  skillRoot: Schema.string().default('')
    .description('自定义 invest-cli skill 根目录（留空自动探测）')
    .volatile(),
  disabledSources: Schema.string().default(DEFAULTS.disabledSources)
    .description('停用的数据源（逗号分隔）；停用后不参与自动路由，具名直调不受影响')
    .volatile(),
})

/** 单次调用的输出预算：显式配置 > 命令专项 > history 变体 > 默认。 */
export function outputBudget(command, args = [], config = {}) {
  const per = config.maxOutputCharsByCommand ?? {}
  if (Number.isFinite(per[command]) && per[command] > 0) return per[command]
  if (Number.isFinite(COMMAND_OUTPUT_LIMITS[command])) return COMMAND_OUTPUT_LIMITS[command]
  const argv = (args || []).map(String)
  if (command === 'us' && argv.includes('--history')) return 80_000
  const base = config.maxOutputChars ?? DEFAULTS.maxOutputChars
  return Number.isFinite(base) && base > 0 ? base : DEFAULTS.maxOutputChars
}

/**
 * 截断但**不制造坏 JSON**：超预算的 JSON 给一个合法信封 + 可执行的下一步，
 * 而不是切在任意字符上。纯文本（终端表格）仍按字符截断，因为那不参与解析。
 */
export function safeClip(body, max) {
  if (body.length <= max) return body
  const head = body.replace(/^\s+/, '')[0]
  if (head === '{' || head === '[') {
    try {
      JSON.parse(body)
      return JSON.stringify({
        ok: false,
        truncated: true,
        original_chars: body.length,
        limit: max,
        hint: '结果超过单次输出上限：改用 --brief / --limit，或拆成更小的查询',
        preview: body.slice(0, Math.min(1200, max)),
      })
    } catch {
      // 非法 JSON 按文本处理（不是本函数能修复的）
    }
  }
  // 纯文本保持旧口径（恰好 max 字符、以省略号收尾）：不参与解析，越短越好。
  return body.slice(0, Math.max(0, max - 1)) + '…'
}

export function expandHome(p) {
  if (!p) return ''
  if (p === '~') return homedir()
  return p.startsWith('~/') ? join(homedir(), p.slice(2)) : p
}

/** 本包所在位置 → invest-cli skill 根目录（packages/dsh-plugin/dsh/ → ../../..）。 */
export function skillRootFrom(moduleUrl) {
  const here = dirname(fileURLToPath(moduleUrl))
  return resolve(here, '..', '..', '..')
}

/**
 * 入口解析：优先 wrapper（它自己会选 venv，且认得 INVEST_CLI_ROOT），
 * 其次 skill 自带 venv 直跑脚本，最后系统 python3。
 */
export function resolveEntry(config = {}, deps = {}) {
  let skillRoot = expandHome(config.skillRoot ?? deps.skillRoot ?? '')
  const exists = deps.exists ?? existsSync
  if (skillRoot && !exists(join(skillRoot, 'scripts', 'invest_cli.py')) && exists(join(skillRoot, 'skills', 'invest-cli'))) {
    skillRoot = join(skillRoot, 'skills', 'invest-cli')
  }
  let entry
  if (config.cliPath) {
    entry = { command: expandHome(config.cliPath), args: [] }
  } else {
    const wrapper = join(homedir(), '.local', 'bin', 'invest-cli')
    if (exists(wrapper)) {
      entry = { command: wrapper, args: [] }
    } else {
      const script = join(skillRoot, 'scripts', 'invest_cli.py')
      const venvPython = join(skillRoot, '.venv', 'bin', 'python')
      entry = { command: exists(venvPython) ? venvPython : 'python3', args: [script] }
    }
  }
  return { ...entry, env: { ...rootEnv(skillRoot), ...sourceToggleEnv(config.disabledSources) } }
}

function rootEnv(skillRoot) {
  return skillRoot ? { INVEST_CLI_ROOT: skillRoot } : {}
}

/** 停用集 → 子进程 env。空串/未设置不注入（route 侧空值即全员参战）。 */
function sourceToggleEnv(raw) {
  const list = String(raw ?? '')
    .split(/[,;\s]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
  return list.length ? { INVEST_CLI_DISABLE_SOURCES: list.join(',') } : {}
}

/** 单次命令的超时（按命令分档，见 COMMAND_TIMEOUTS）。 */
export function pickTimeout(command, config = {}) {
  const perCommand = config.timeouts ?? {}
  const explicit = perCommand[command]
  if (Number.isFinite(explicit) && explicit > 0) return explicit
  const byClass = COMMAND_TIMEOUTS[command]
  if (Number.isFinite(byClass)) {
    const base = config.timeoutMs ?? DEFAULTS.timeoutMs
    return Math.max(base, byClass)
  }
  const base = config.timeoutMs ?? DEFAULTS.timeoutMs
  return Number.isFinite(base) && base > 0 ? base : DEFAULTS.timeoutMs
}

export function sanitizeArgs(raw = []) {
  if (!Array.isArray(raw)) throw new TypeError('invest args must be an array of strings')
  if (raw.length > DEFAULTS.maxArgs) {
    throw new Error(`too many args: ${raw.length} > ${DEFAULTS.maxArgs}`)
  }
  const cleaned = []
  for (const item of raw) {
    if (item === undefined || item === null) continue
    if (typeof item !== 'string') {
      throw new TypeError(`all args must be strings, got ${typeof item}`)
    }
    const trimmed = item.trim()
    if (!trimmed) continue
    if (trimmed.includes('\u0000')) {
      throw new Error('arg contains NUL character')
    }
    if (trimmed.length > DEFAULTS.maxArgChars) {
      throw new Error(`arg too long: ${trimmed.length} > ${DEFAULTS.maxArgChars}`)
    }
    cleaned.push(trimmed)
  }
  return cleaned
}

export function buildArgv(command, userArgs = [], wantJson = true) {
  const cleaned = sanitizeArgs(userArgs)
  const argv = [command, ...cleaned]
  if (wantJson && !argv.includes('--json')) argv.push('--json')
  return argv
}

export function failureText(argv, result) {
  const head = `invest-cli ${argv.join(' ')} failed (rc=${result.code})`
  const tail = (result.stderr || result.stdout || '').trim()
  return tail ? `${head}\n${tail}` : head
}

function spawnRun(entry, argv, timeoutMs) {
  return new Promise((resolveResult) => {
    const child = spawn(entry.command, [...entry.args, ...argv], {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, ...entry.env },
    })
    let stdout = ''
    let stderr = ''
    let killedByTimeout = false

    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })

    const timer = setTimeout(() => {
      killedByTimeout = true
      child.kill('SIGKILL')
    }, timeoutMs)

    child.on('close', (code) => {
      clearTimeout(timer)
      if (killedByTimeout) {
        resolveResult({
          code: -1,
          stdout,
          stderr: `invest-cli ${argv.join(' ')} timed out after ${timeoutMs}ms (SIGKILL)`,
        })
        return
      }
      resolveResult({ code: code ?? 0, stdout, stderr })
    })

    child.on('error', (err) => {
      clearTimeout(timer)
      resolveResult({
        code: -1,
        stdout,
        stderr: `cannot spawn invest-cli (${entry.command}): ${err.message}`,
      })
    })
  })
}

export function makeInvestTool(config = {}, deps = {}) {
  const skillRoot = deps.skillRoot ?? skillRootFrom(import.meta.url)
  const run = deps.run ?? spawnRun
  const wantJsonDefault = config.json ?? DEFAULTS.json

  return {
    name: 'invest',
    description:
      '查询中国与美股市场数据（行情/财报/基金/美股/SEC 原文/A股结构/经理任职复盘），'
      + '直接返回结构化 JSON。用于任何需要真实金融数据的场景：'
      + '「茅台现在多少钱」「分析 005827」「AAPL 的 ROE」「这只基金是谁在管、任职以来赚了多少」'
      + '「600519 最近公告」。一次只做一件事；command 见 systemPrompt 里的清单。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        command: {
          type: 'string',
          enum: [...COMMANDS],
          description: '子命令，决定取哪类数据（清单与参数见 systemPrompt 的 invest 一节）。',
        },
        args: {
          type: 'array',
          items: { type: 'string' },
          description:
            '子命令的参数，原样传给 CLI（标的代码/名称、子动作、旗标）。'
            + '例：["600519"]、["notice","600519"]、["--manager","余懿"]。'
            + '不要传 --json（由本工具的 json 参数控制）。',
        },
        json: {
          type: 'boolean',
          description: `是否要结构化 JSON 输出（默认 ${wantJsonDefault}）。置 false 得到终端表格，适合直接展示给人看。`,
        },
      },
      required: ['command'],
    },
    isConcurrencySafe: () => true,
    output: {
      schema: { type: 'object' },
      render: (_args, value) => text(value?.text ?? ''),
    },
    async execute(args) {
      const command = typeof args?.command === 'string' ? args.command.trim() : ''
      if (!COMMANDS.includes(command)) {
        throw new Error(
          `invest: unknown command "${command}". Known: ${COMMANDS.join(', ')}`,
        )
      }
      const wantJson = args?.json === undefined ? wantJsonDefault : args.json === true
      const argv = buildArgv(command, args?.args, wantJson)
      const entry = resolveEntry(config, { skillRoot })
      const result = await run(entry, argv, pickTimeout(command, config), deps)
      if (result.code !== 0) throw new Error(failureText(argv, result))
      const body = result.stdout.trim()
      if (body === '') {
        // 与 CLI 自身纪律一致：rc=0 但没有输出 = 假成功，不能当空结果传下去。
        throw new Error(`invest-cli ${argv.join(' ')} 退出码为 0 但没有输出（非空结果才可信）`)
      }
      const budget = outputBudget(command, args?.args, config)
      return { stdout: body, text: safeClip(body, budget), command, budget }
    },
  }
}

export function apply(ctx, providedConfig = {}) {
  const config = { ...DEFAULTS, ...(isObject(providedConfig) ? providedConfig : {}) }
  ctx.tools.register(makeInvestTool(config))

  // 命令目录：注入 systemPrompt，保持紧凑（≈150 token/轮）
  // 使用 ctx.get('systemPrompt') 安全探测可选服务，避免直接访问未声明属性触发 Cordis 代理拦截
  const prompt = typeof ctx.get === 'function' ? ctx.get('systemPrompt') : undefined
  if (prompt && typeof prompt.section === 'function') {
    prompt.section({
      name: 'tool:invest',
      order: 116.4,
      text: () => [
        'Use the `invest` tool for real market data instead of guessing or searching the web.',
        'Commands (pass as `command`, extra flags as `args`):',
        'stock <代码|名称> · fund <代码|名称> [--analytics] · us <代码> [--history --years N] — A股/港股、公募基金、美股快照',
        'quote <代码[,代码...]> · kline <代码> [--period day|week|month] — 免鉴权行情/K线（最快）',
        'sec <美股代码> [--search 词|--insiders|--events|--holdings] — SEC EDGAR 原文级（免费官方源）',
        'fmp <美股代码> [--statements|--estimates|--dividends] — 美股 TTM 比率/评级/预测',
        'cn <notice|consensus|holders|disclosure|report> <代码> — A股公告/一致预期/股东/披露日历/研报',
        'screen <自然语言条件> — 选股（股票）；fund-class <基金代码> — 基金三层分类',
        'tenure <基金代码|名称> [--manager 姓名] [--excel 路径] — 基金经理任职期复盘（慢，>60s）',
        'report <基金代码> [--latest N] — 基金定期报告 PDF；info <关键词> — 财经资讯检索',
        'watchlist [add|remove|list] · capabilities · datasources — 自选股 / 能力清单 / 数据源状态',
        'westock <子命令> <代码> · wind · yingmi · ttskill · intent — 长尾透传（筹码/龙虎榜/资金流/Wind/盈米/天天基金）',
        '任何命令都可加 --envelope 得 {ok,source,data,error,meta}；大结果用 --brief（sec/us --history）或 --limit（screen）。',
        'Ask for `capabilities` when unsure what a long-tail command accepts.',
      ].join('\n'),
    })
  }
}

function isObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
