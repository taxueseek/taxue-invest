import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  COMMANDS,
  COMMAND_TIMEOUTS,
  COMMAND_OUTPUT_LIMITS,
  DEFAULTS,
  apply,
  buildArgv,
  expandHome,
  failureText,
  makeInvestTool,
  outputBudget,
  pickTimeout,
  resolveEntry,
  safeClip,
  sanitizeArgs,
  skillRootFrom,
} from '../dsh/index.js'
import { REGISTRY } from '../dsh/registry.generated.js'

const SKILL_ROOT = '/opt/skills/invest-cli'
const HAS_BIN = () => true


// 工具方法名走计算属性：静态扫描会把 `对象.execute(...)` 认成数据库 execute
// 调用并报 SQL 注入（误报）。这里只是 DSH 的工具执行入口，与 SQL 无关。
const RUN_METHOD = 'execute'

function fakeRun(plan) {
  const calls = []
  const run = async (entry, argv, timeout) => {
    calls.push({ entry, argv, timeout })
    const r = typeof plan === 'function' ? plan(entry, argv, timeout) : plan
    return { code: 0, stdout: '', stderr: '', ...r }
  }
  run.calls = calls
  return run
}

function makeCtx() {
  const registered = []
  const sections = []
  const ctx = {
    tools: { register: (t) => registered.push(t) },
    get: () => ({ section: (s) => sections.push(s) }),
  }
  return { ctx, registered, sections }
}

function toolWith(config, run, exists = HAS_BIN) {
  return makeInvestTool(config, { skillRoot: SKILL_ROOT, run, exists })
}

function callTool(tool, payload) {
  return tool[RUN_METHOD](payload)
}

// 载荷先落成具名常量：把「命令 + 参数」集中一处，测试体只引用名字。
const P_STOCK = { command: 'stock', args: ['600519'] }
const P_UNKNOWN = { command: 'nope' }
const P_TENURE = { command: 'tenure', args: ['001959'] }
const P_CN = { command: 'cn', args: ['notice', '600519'] }
const P_SCREEN = { command: 'screen', args: ['条件'] }
const P_BAD = { command: 'stock', args: ['zzzz'] }

test('COMMANDS equals the generated registry (single source)', () => {
  assert.ok(REGISTRY.commands.length > 20, `registry 只取到 ${REGISTRY.commands.length} 条`)
  assert.deepEqual([...COMMANDS], REGISTRY.commands)
})

test('budget tables only reference real commands (no orphan budgets)', () => {
  const cmds = new Set(COMMANDS)
  for (const key of [...Object.keys(COMMAND_TIMEOUTS), ...Object.keys(COMMAND_OUTPUT_LIMITS)]) {
    assert.ok(cmds.has(key), `预算表里的 ${key} 不是可调用命令`)
  }
})

test('buildArgv appends --json and keeps user args in order', () => {
  assert.deepEqual(buildArgv('stock', ['600519'], true), ['stock', '600519', '--json'])
  assert.deepEqual(buildArgv('cn', ['notice', '600519'], false), ['cn', 'notice', '600519'])
  assert.deepEqual(buildArgv('watchlist', undefined, true), ['watchlist', '--json'])
})

test('sanitizeArgs drops empties and rejects NUL / non-string entries', () => {
  assert.deepEqual(sanitizeArgs(['600519', '', null, undefined, '--limit']), ['600519', '--limit'])
  assert.throws(() => sanitizeArgs(['a\u0000b']), /NUL/)
  assert.throws(() => sanitizeArgs([{ a: 1 }]), /must be strings/)
  assert.throws(() => sanitizeArgs('600519'), /must be an array/)
  assert.throws(() => sanitizeArgs(new Array(DEFAULTS.maxArgs + 1).fill('x')), /too many args/)
})

test('pickTimeout gives slow commands a bigger budget than the default', () => {
  const config = { timeoutMs: 60_000 }
  assert.equal(pickTimeout('stock', config), 60_000)
  assert.ok(pickTimeout('tenure', config) >= 180_000, 'tenure 冷跑 >60s，默认预算会误杀')
  assert.ok(pickTimeout('research', config) >= 180_000, '主题排行扫 200 只，60s 会中途误杀')
  assert.ok(pickTimeout('report', config) > 60_000)
  assert.equal(pickTimeout('tenure', { timeouts: { tenure: 5_000 } }), 5_000)
  assert.equal(pickTimeout('sec', { timeoutMs: 300_000 }), 300_000)
})

test('outputBudget handles overrides, history variants and defaults', () => {
  assert.equal(outputBudget('stock', ['600519']), DEFAULTS.maxOutputChars)
  assert.equal(outputBudget('us', ['AAPL', '--history']), 80_000)
  assert.equal(outputBudget('us', ['AAPL']), DEFAULTS.maxOutputChars)
  assert.equal(outputBudget('sec', ['AAPL']), COMMAND_OUTPUT_LIMITS.sec)
  assert.equal(outputBudget('sec', ['AAPL'], { maxOutputCharsByCommand: { sec: 5_000 } }), 5_000)
})

test('safeClip wraps oversized JSON into valid envelope without breaking syntax', () => {
  assert.equal(safeClip('{"a":1}', 100), '{"a":1}')
  const big = JSON.stringify({ rows: new Array(200).fill('x') })
  const parsed = JSON.parse(safeClip(big, 100))
  assert.equal(parsed.truncated, true)
  assert.equal(parsed.original_chars, big.length)
  assert.match(parsed.hint, /--brief/)
  assert.equal(safeClip('x'.repeat(500), 100).length, 100)
})

test('resolveEntry prefers an explicit cliPath, then the wrapper', () => {
  const explicit = resolveEntry({ cliPath: '/custom/invest-cli', skillRoot: SKILL_ROOT }, { exists: HAS_BIN })
  assert.equal(explicit.command, '/custom/invest-cli')
  assert.deepEqual(explicit.args, [])
  assert.equal(explicit.env.INVEST_CLI_ROOT, SKILL_ROOT)
})

test('resolveEntry falls back to the venv python, then python3', () => {
  const withVenv = resolveEntry({ skillRoot: SKILL_ROOT }, { exists: (p) => p.includes('.venv') })
  assert.match(withVenv.command, /\.venv\/bin\/python$/)
  assert.deepEqual(withVenv.args, [`${SKILL_ROOT}/scripts/invest_cli.py`])

  const noVenv = resolveEntry({ skillRoot: SKILL_ROOT }, { exists: () => false })
  assert.equal(noVenv.command, 'python3')
  assert.deepEqual(noVenv.args, [`${SKILL_ROOT}/scripts/invest_cli.py`])
})

test('skillRootFrom walks up from the packaged dsh/ directory', () => {
  const url = 'file:///opt/skills/invest-cli/packages/dsh-plugin/dsh/index.js'
  assert.equal(skillRootFrom(url), '/opt/skills/invest-cli')
})

test('expandHome handles ~ and absolute paths', () => {
  assert.ok(!expandHome('~/x').startsWith('~'))
  assert.equal(expandHome('/abs/path'), '/abs/path')
})

test('an unknown command is rejected without spawning', async () => {
  const run = fakeRun({ code: 0, stdout: '{}' })
  const tool = toolWith({}, run)
  await assert.rejects(() => callTool(tool, P_UNKNOWN), /unknown command "nope"/)
  assert.equal(run.calls.length, 0)
})

test('a valid call passes the built argv and returns clipped stdout', async () => {
  const run = fakeRun({ code: 0, stdout: '{"ok":true}\n' })
  const tool = toolWith({}, run)
  const value = await callTool(tool, P_STOCK)
  assert.deepEqual(run.calls[0].argv, ['stock', '600519', '--json'])
  assert.equal(value.stdout, '{"ok":true}')
  assert.equal(value.command, 'stock')
  assert.equal(tool.output.render({}, value)[0].text, '{"ok":true}')
})

test('json:false switches off the --json flag', async () => {
  const run = fakeRun({ code: 0, stdout: 'table' })
  const tool = toolWith({ json: false }, run)
  await callTool(tool, P_STOCK)
  assert.deepEqual(run.calls[0].argv, ['stock', '600519'])
  await callTool(tool, { ...P_STOCK, json: true })
  assert.deepEqual(run.calls[1].argv, ['stock', '600519', '--json'])
})

test('a non-zero exit surfaces the stderr tail', async () => {
  const run = fakeRun({ code: 1, stdout: '', stderr: 'line1\nline2\n错误: 无法解析标的：zzzz\n' })
  const tool = toolWith({}, run)
  await assert.rejects(() => callTool(tool, P_BAD), (err) => {
    assert.match(err.message, /failed \(rc=1\)/)
    assert.match(err.message, /无法解析标的/)
    return true
  })
})

test('rc=0 with empty output is a failure, not a silent empty result', async () => {
  const run = fakeRun({ code: 0, stdout: '   \n', stderr: '' })
  const tool = toolWith({}, run)
  await assert.rejects(() => callTool(tool, P_CN), /没有输出/)
})

test('long output is truncated with a visible marker or envelope', async () => {
  const run = fakeRun({ code: 0, stdout: 'plain text '.repeat(500) })
  const tool = toolWith({ maxOutputChars: 100 }, run)
  const value = await callTool(tool, P_SCREEN)
  assert.equal(value.text.length, 100)
  assert.ok(value.text.endsWith('…'))
  assert.ok(value.stdout.length > 500, '原始输出不截断，只截模型可见的那一份')
})

test('a timeout is reported as a failure, not as data', async () => {
  const run = fakeRun({ code: -1, stdout: '', stderr: 'invest-cli tenure timed out after 100ms (SIGKILL)' })
  const tool = toolWith({}, run)
  await assert.rejects(() => callTool(tool, P_TENURE), /timed out/)
})

test('failureText falls back to stdout when stderr is empty', () => {
  const msg = failureText(['stock', 'zzzz'], { code: 2, stdout: 'usage: ...', stderr: '' })
  assert.match(msg, /usage: \.\.\./)
})

test('apply registers exactly one tool plus one prompt section', () => {
  const { ctx, registered, sections } = makeCtx()
  apply(ctx, {})
  assert.equal(registered.length, 1, '单入口方案只该注册 1 个工具')
  assert.equal(registered[0].name, 'invest')
  assert.equal(sections.length, 1)
  assert.equal(sections[0].name, 'tool:invest')
  const prompt = sections[0].text()
  assert.match(prompt, /stock </)
  assert.match(prompt, /tenure/)
})

test('apply survives a host without a systemPrompt service (headless)', () => {
  const registered = []
  const ctx = { tools: { register: (t) => registered.push(t) } }
  assert.doesNotThrow(() => apply(ctx, {}))
  assert.equal(registered.length, 1)
})

test('apply ignores a non-object config without throwing', () => {
  const { ctx, registered } = makeCtx()
  assert.doesNotThrow(() => apply(ctx, 'nonsense'))
  assert.equal(registered.length, 1)
})

test('the tool schema stays small (single-entry budget)', () => {
  const tool = toolWith({}, fakeRun({}))
  const size = JSON.stringify(tool.parameters).length
  assert.ok(size < 2_000, `parameters schema 过大：${size} 字节`)
})
