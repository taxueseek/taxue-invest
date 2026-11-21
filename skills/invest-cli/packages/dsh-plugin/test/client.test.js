import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  COMMANDS,
  COMMAND_CATEGORIES,
  DATA_SOURCES,
  DATA_SOURCE_KEYS,
  DEFAULTS,
} from '../dsh/index.js'
import { REGISTRY } from '../dsh/registry.generated.js'

const here = dirname(fileURLToPath(import.meta.url))
const clientCode = readFileSync(join(here, '..', 'dsh', 'client.js'), 'utf8')

// 模拟 ModuleLoader 载入 client.js
function loadClientModule() {
  let loaded = null
  const original = globalThis.window
  globalThis.window = {
    __ModuleLoader__: {
      load: (entry) => {
        const fakeRequire = (name) => {
          if (name === 'react') {
            return {
              createElement: (type, props, ...children) => ({ type, props, children }),
              useState: (init) => [init, () => {}],
              useEffect: () => {},
              useRef: (init) => ({ current: init }),
            }
          }
          throw new Error(`Unexpected require: ${name}`)
        }
        loaded = entry.factory(fakeRequire)
      },
    },
  }

  try {
    const fn = new Function(clientCode)
    fn()
  } finally {
    globalThis.window = original
  }
  return loaded
}

test('client module loads and exposes required symbols', () => {
  const mod = loadClientModule()
  assert.ok(mod, 'client module should export an object')
  assert.equal(typeof mod.apply, 'function')
  assert.ok(Array.isArray(mod.inject))
  assert.ok(mod.inject.includes('configForms'))
  assert.ok(mod.inject.includes('slots'))
  assert.equal(typeof mod.InvestPanel, 'function')
})

test('drift gate: COMMANDS set is identical between index.js and client.js', () => {
  const mod = loadClientModule()
  assert.deepEqual([...mod.COMMANDS].sort(), [...COMMANDS].sort())
})

test('client generated block equals the registry artifact', () => {
  const mod = loadClientModule()
  assert.deepEqual(mod.COMMAND_CATEGORIES, REGISTRY.categories)
  assert.deepEqual(mod.COMMANDS, REGISTRY.commands)
  assert.deepEqual(mod.DATA_SOURCES, REGISTRY.sources)
  assert.deepEqual(mod.DATA_SOURCE_KEYS, REGISTRY.sourceKeys)
  assert.deepEqual(mod.DEFAULTS, REGISTRY.defaults)
})

test('drift gate: DATA_SOURCES list is aligned between index.js and client.js', () => {
  const mod = loadClientModule()
  assert.equal(mod.DATA_SOURCES.length, DATA_SOURCES.length)
  for (let i = 0; i < DATA_SOURCES.length; i++) {
    assert.equal(mod.DATA_SOURCES[i].id, DATA_SOURCES[i].id)
    assert.equal(mod.DATA_SOURCES[i].priority, DATA_SOURCES[i].priority)
    assert.equal(mod.DATA_SOURCES[i].ref, DATA_SOURCES[i].ref)
  }
})

test('drift gate: DATA_SOURCE_KEYS refs are identical between index.js and client.js', () => {
  const mod = loadClientModule()
  assert.deepEqual(
    mod.DATA_SOURCE_KEYS.map((k) => k.ref),
    DATA_SOURCE_KEYS.map((k) => k.ref),
  )
})

test('drift gate: DEFAULTS values match between index.js and client.js', () => {
  const mod = loadClientModule()
  assert.equal(mod.DEFAULTS.timeoutMs, DEFAULTS.timeoutMs)
  assert.equal(mod.DEFAULTS.maxOutputChars, DEFAULTS.maxOutputChars)
  assert.equal(mod.DEFAULTS.json, DEFAULTS.json)
  assert.equal(mod.DEFAULTS.maxArgs, DEFAULTS.maxArgs)
})

test('client.apply registers settings.section and plugins.item slots', () => {
  const mod = loadClientModule()
  const injectedSlots = []
  const registeredSlots = []

  const ctx = {
    locale: 'zh-CN',
    configForms: {
      get: () => ({ state: { status: 'ready', value: {} } }),
      whileServed: (_namespaces, cb) => {
        cb()
        return () => {}
      },
    },
    slots: {
      inject: (name, cb) => {
        injectedSlots.push(name)
        cb()
        return () => {}
      },
      register: (descriptor, component) => {
        registeredSlots.push({ descriptor, component })
        return () => {}
      },
    },
    effect: (cb) => {
      cb()
      return () => {}
    },
    remote: { credentials: {} },
  }

  mod.apply(ctx)
  assert.ok(injectedSlots.includes('settings.section'))
  assert.ok(injectedSlots.includes('plugins.item'))
  assert.equal(registeredSlots.length, 2)
  assert.equal(registeredSlots[0].descriptor.id, 'invest')
  assert.equal(registeredSlots[1].descriptor.id, 'invest')
})
