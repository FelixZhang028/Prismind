import test from 'node:test'
import assert from 'node:assert/strict'
import {
  BACKTEST_SETTINGS_KEY,
  clearBacktestSettings,
  loadBacktestSettings,
  sanitizeBacktestSettings,
  saveBacktestSettings,
  settingsFromEffectiveConfig,
} from '../src/workspace/backtestSettings.js'

function memoryStorage() {
  const map = new Map()
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)) },
    removeItem: (k) => { map.delete(k) },
  }
}

test('保存并读取回测常用参数（股票范围、日期、持仓、频率、换手缓冲、成本与过滤）', () => {
  const storage = memoryStorage()
  const ok = saveBacktestSettings({
    market: '000906.SH',
    from_date: '2020-01-01',
    to_date: '2025-12-31',
    initial_capital: 2000000,
    max_positions: 20,
    rebalance: 'quarterly',
    hold_buffer: 20,
    exec: { commission_wan: 2.5, minimum_commission: 5, historical_fees: true, stamp_tax_wan: 5, slippage_bps: 10 },
    filter: { exclude_st: true, exclude_suspended: true, minimum_listing_days: 250, minimum_history_days: 120, minimum_average_amount: 5000000 },
  }, storage)
  assert.equal(ok, true)
  const loaded = loadBacktestSettings(storage)
  assert.equal(loaded.market, '000906.SH')
  assert.equal(loaded.from_date, '2020-01-01')
  assert.equal(loaded.max_positions, 20)
  assert.equal(loaded.rebalance, 'quarterly')
  assert.equal(loaded.hold_buffer, 20)
  assert.equal(loaded.exec.slippage_bps, 10)
  assert.equal(loaded.filter.minimum_listing_days, 250)
})

test('非法或损坏的本地缓存会被过滤掉而不影响页面加载', () => {
  const storage = memoryStorage()
  storage.setItem(BACKTEST_SETTINGS_KEY, '{not-json')
  assert.equal(loadBacktestSettings(storage), null)

  const cleaned = sanitizeBacktestSettings({
    from_date: 'bad-date',
    max_positions: 9999,
    rebalance: 'yearly',
    hold_buffer: -5,
    exec: { slippage_bps: 15, commission_wan: -2 },
    filter: { minimum_listing_days: 250, exclude_st: 'yes' },
  })
  assert.deepEqual(cleaned, {
    exec: { slippage_bps: 15 },
    filter: { minimum_listing_days: 250 },
  })
})

test('从后端 effective_config 还原最近一次回测的表单口径设置', () => {
  const converted = settingsFromEffectiveConfig({
    market: '000906.SH',
    from_date: '2020-01-01',
    to_date: '2025-12-31',
    initial_capital: 2000000,
    max_positions: 20,
    rebalance: 'quarterly',
    hold_buffer: 20,
    execution: {
      commission_rate: 0.00025,
      minimum_commission: 5,
      historical_fees: true,
      stamp_tax_rate: 0.0005,
      slippage_rate: 0.001,
    },
    filters: {
      exclude_st: true,
      exclude_suspended: true,
      minimum_listing_days: 250,
      minimum_history_days: 120,
      minimum_average_amount: 0,
    },
  })
  assert.equal(converted.market, '000906.SH')
  assert.equal(converted.from_date, '2020-01-01')
  assert.equal(converted.max_positions, 20)
  assert.equal(converted.rebalance, 'quarterly')
  assert.equal(converted.hold_buffer, 20)
  assert.equal(converted.exec.commission_wan, 2.5)
  assert.equal(converted.exec.slippage_bps, 10)
  assert.equal(converted.filter.minimum_listing_days, 250)
})

test('恢复默认配置时可清空本地保存的回测参数', () => {
  const storage = memoryStorage()
  saveBacktestSettings({ market: '000300.SH', rebalance: 'monthly', max_positions: 15 }, storage)
  assert.equal(loadBacktestSettings(storage)?.rebalance, 'monthly')
  assert.equal(clearBacktestSettings(storage), true)
  assert.equal(loadBacktestSettings(storage), null)
})
