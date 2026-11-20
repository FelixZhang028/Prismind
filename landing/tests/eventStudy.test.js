import test from 'node:test'
import assert from 'node:assert/strict'
import {
  bigNumbers, compareRows, decodePreset, defaultCondition, diffText, encodePreset, entryLabel,
  hasLimitUpCloseWarning, histogramBars, pathChart, reading, sentenceParts, significanceBadge,
  statesFromFacts, strategyHandoffFromEvent, tone, yearChart,
} from '../src/workspace/eventStudy.js'

const kinds = [
  { type: 'ret', days: [5, 20, 60], directions: [], compare: true, example: -20 },
  { type: 'ma_cross', days: [20, 60], directions: [{ value: 'up' }, { value: 'down' }], compare: false },
  { type: 'pe', days: [], directions: [], compare: true, example: 15 },
]

test('新加条件的默认值；条件写进链接再读出来', () => {
  assert.deepEqual(defaultCondition(kinds[0]), { type: 'ret', days: 20, op: '<=', value: -20 })
  assert.deepEqual(defaultCondition(kinds[1]), { type: 'ma_cross', days: 20, direction: 'up' })
  assert.deepEqual(defaultCondition(kinds[2]), { type: 'pe', op: '>=', value: 15 })
  const conditions = [{ type: 'ret', days: 20, op: '<=', value: -15 }, { type: 'ma_cross', days: 60, direction: 'up' }]
  const text = encodePreset(conditions)
  assert.equal(text, 'ret:20::<=:-15|ma_cross:60:up::')
  assert.deepEqual(decodePreset(text, kinds), conditions)
  assert.deepEqual(decodePreset('nope:1:::|pe:::<=:30', kinds), [{ type: 'pe', op: '<=', value: 30 }])   // 不认识的去掉
  assert.deepEqual(decodePreset('', kinds), [])
})

const horizon = { events: { count: 120, mean: 0.05, median: 0.03, up_share: 0.62, p25: -0.03, p75: 0.12 },
  all: { count: 9000, mean: 0.01, median: -0.005, up_share: 0.47, p25: -0.07, p75: 0.06 }, excess: { mean: -0.002, up_share: 0.45 } }
const result = { start: '2016-02-29', end: '2026-10-19', scope: '全市场', events: 3311, stocks: 1401, main_horizon: 20, horizons: { 20: horizon } }

test('满足条件和平时的对照表、三个大数字', () => {
  const rows = compareRows(horizon)
  assert.deepEqual(rows.map((r) => r.label), ['平均涨跌', '中位数', '上涨的比例', '中间一半落在'])
  assert.equal(rows[0].event, '+5.00%')
  assert.equal(diffText(rows[0]), '+4.00%')
  assert.equal(diffText(rows[2]), '+15.0 个百分点')
  assert.equal(diffText(rows[3]), '')
  assert.deepEqual(compareRows({ events: { count: 0 } }), [])
  assert.deepEqual(bigNumbers('20', horizon).map((n) => [n.label, n.value, n.note]), [
    ['之后 20 个交易日平均涨跌', '+5.0%', '平时 +1.0%'], ['上涨的比例', '62%', '平时 47%'], ['和同一天的全部股票比', '-0.2%', '跑赢的占 45%']])
  assert.deepEqual(bigNumbers('20', { events: { count: 0 } }), [])
  assert.equal(tone(0.01), 'text-rose-300')
  assert.equal(tone(-0.01), 'text-emerald-300')
})

test('结果的读法：和平时比、是不是因为大盘、每年是不是都这样', () => {
  // 比平时高很多，但扣掉同一天的全部股票以后差不多：是大盘在涨
  assert.equal(reading(result, '20'), '历史上出现过 3,311 次。之后 20 个交易日平均比平时高 4.0 个百分点，但主要是因为那段时间大部分股票也在涨；和同一天的全部股票比，差不多。')
  const stronger = { ...horizon, excess: { mean: 0.03, up_share: 0.58 } }
  const years = [2018, 2019, 2020, 2021].map((year, i) => ({ year, events: i === 3 ? 5 : 50, mean: i === 1 ? -0.01 : 0.04, all_mean: 0 }))
  assert.equal(reading({ ...result, horizons: { 20: stronger }, by_year: years }, '20'),
    '历史上出现过 3,311 次。之后 20 个交易日平均比平时高 4.0 个百分点；和同一天的全部股票比，平均高 3.0 个百分点，跑赢的占 58%。次数够多的 3 年里，2 年比平时高，1 年比平时低。')
  const close = [2018, 2019, 2020].map((year, i) => ({ year, events: 50, mean: [0.012, 0.011, 0.03][i], all_mean: 0.01 }))
  assert.match(reading({ ...result, horizons: { 20: stronger }, by_year: close }, '20'), /3 年里，1 年比平时高，2 年和平时差不多。$/)
  const same = { events: { count: 10, mean: 0.011 }, all: { mean: 0.01 }, excess: { mean: 0.001 } }
  assert.equal(reading({ ...result, events: 10, horizons: { 5: same } }, '5'), '历史上出现过 10 次。之后 5 个交易日的平均涨跌和平时差不多；和同一天的全部股票比，也差不多。次数太少，结果很不稳定，看看就好。')
  assert.equal(reading({ ...result, events: 0 }, '20'), '这段时间里没有满足条件的情况。')
})

test('条件写成一句话：每种条件后面跟哪几段', () => {
  const parts = (kind) => sentenceParts(kind).map((p) => p.text || p.part)
  assert.deepEqual(parts({ type: 'ret', unit: '%' }), ['近', 'days', '个交易日', 'op', 'value', '%'])
  assert.deepEqual(parts({ type: 'ma_cross' }), ['收盘价当天', 'direction', 'days', '日均线'])
  assert.deepEqual(parts({ type: 'limit' }), ['当天', 'direction'])
  assert.deepEqual(parts({ type: 'pb', unit: '' }), ['op', 'value'])
  assert.deepEqual(sentenceParts(undefined), [])
})

test('走势图：三条线、纵轴刻度包括 0、缺的点断开', () => {
  const path = { days: [0, 5, 20, 60], events: [0, 0.01, 0.04, null], market: [0, 0.005, 0.03, 0.05], all: [0, 0.002, 0.008, 0.02] }
  const c = pathChart(path, { width: 600, height: 200 })
  assert.ok(c.ticks.some((t) => t.zero && t.label === '0%'))
  assert.equal(c.lines.events.split('L').length, 3)                // 第 60 天没有数据，事件的线只画到第 20 天
  assert.ok(c.lines.market.startsWith('M48.0 '))
  assert.equal(c.point('events', 60), null)
  assert.equal(c.point('market', 60).x, 600 - 12)
  assert.ok(c.point('events', 20).y < c.point('all', 20).y)        // 涨得多的在上面
  assert.equal(pathChart(null), null)
})

test('每一年的柱子：正的往上、负的往下，次数少的年份标出来', () => {
  const chart = yearChart([{ year: 2020, events: 50, mean: 0.04, all_mean: 0.01 }, { year: 2021, events: 3, mean: -0.02, all_mean: 0 }], { width: 200, height: 100 })
  const [up, down] = chart.bars
  assert.ok(up.up && up.y + up.h === chart.zero && !up.few)
  assert.ok(!down.up && down.y === chart.zero && down.few)
  assert.ok(up.allY < chart.zero && up.allY > up.y)
  assert.equal(yearChart([]), null)
})

test('分布图柱子的高度', () => {
  const bars = histogramBars({ labels: ['跌', '平', '涨'], events: [0.2, 0.4, 0.4], all: [0.1, 0.8, 0.1] })
  assert.deepEqual(bars.map((b) => [b.eventHeight, b.allHeight]), [[25, 13], [50, 100], [50, 13]])
})

test('从 AI研究员的数据表推出这只股票现在的状态，每个都带着事件研究的条件', () => {
  const facts = [{ key: 'ret_20d', value: -0.23 }, { key: 'from_high_250d', value: -0.37 }, { key: 'ma60_gap', value: -0.05 },
    { key: 'amount_ratio', value: 2.6 }, { key: 'pe_ttm', value: 12.3 }, { key: 'profit_growth', value: 0.8 }]
  const states = statesFromFacts(facts)
  assert.deepEqual(states.map((s) => s.text), ['近 20 个交易日跌了 23%', '距近一年最高价 -37%', '收盘价在 60 日均线下方', '当日成交额是近 20 日平均的 2.6 倍', '市盈率 12.3'])
  assert.deepEqual(states[1].conditions, [{ type: 'from_high', op: '<=', value: -30 }])
  assert.deepEqual(states[4].conditions, [{ type: 'pe', op: '<=', value: 15 }])
  assert.deepEqual(statesFromFacts([{ key: 'ret_20d', value: 0.02 }]), [])
  assert.equal(statesFromFacts([{ key: 'pe_ttm', value: 80 }])[0].conditions[0].op, '>=')
})

test('入场口径文案、涨停收盘提醒与按事件日显著性徽标', () => {
  assert.equal(entryLabel('close'), '事件当天收盘')
  assert.equal(entryLabel('next_open'), '次日开盘入场')
  assert.equal(hasLimitUpCloseWarning([{ type: 'limit', direction: 'up' }], 'close'), true)
  assert.equal(hasLimitUpCloseWarning([{ type: 'limit', direction: 'up' }], 'next_open'), false)
  assert.equal(hasLimitUpCloseWarning([{ type: 'limit', direction: 'down' }], 'close'), false)

  const sigPos = significanceBadge({ significance: { event_days: 186, daily_mean: 0.0124, t_stat: 2.41, p_value: 0.017, significant: true } })
  assert.equal(sigPos.tone, 'indigo')
  assert.match(sigPos.text, /统计较稳定/)
  assert.match(sigPos.detail, /独立事件日 186 天.*t = 2\.41.*p = 0\.017/)

  const sigNeg = significanceBadge({ significance: { event_days: 60, daily_mean: -0.015, t_stat: -2.9, p_value: 0.005, significant: true } })
  assert.equal(sigNeg.tone, 'slate')
  assert.match(sigNeg.text, /弱于同期市场/)

  const sigNone = significanceBadge({ significance: { event_days: 40, daily_mean: 0.008, t_stat: 1.1, p_value: 0.28, significant: false } })
  assert.equal(sigNone.tone, 'amber')
  assert.match(sigNone.text, /统计不显著/)

  const sigFew = significanceBadge({ significance: { event_days: 3, significant: false, label: '独立事件日不足 5 天' } })
  assert.equal(sigFew.tone, 'slate')
  assert.match(sigFew.text, /独立事件日太少/)

  const enriched = {
    ...horizon,
    excess: { mean: 0.025, up_share: 0.56 },
    untradable_entry: 19,
    significance: { event_days: 120, daily_mean: 0.02, t_stat: 1.2, p_value: 0.23, significant: false },
  }
  assert.equal(bigNumbers('20', enriched)[2].note, '跑赢的占 56% · 覆盖 120 天')
  const text = reading({ ...result, entry: 'next_open', horizons: { 20: enriched } }, '20')
  assert.match(text, /暂未达显著水平/)
  assert.match(text, /另有 19 次因次日一字涨停或停牌无法买入/)
})

test('事件研究条件转规则策略：全支持、部分支持、单日盘面触发降级一句话描述', async () => {
  const full = strategyHandoffFromEvent(
    [
      { type: 'ret', days: 20, op: '<=', value: -20 },
      { type: 'pe', op: '<=', value: 15 },
      { type: 'ma_gap', days: 60, op: '>=', value: 0 },
    ],
    ['近 20 个交易日涨跌幅 ≤ -20%', '市盈率 ≤ 15', '收盘价相对 60 日均线 ≥ 0%'],
  )
  assert.equal(full.mode, 'rules')
  assert.deepEqual(full.skippedLabels, [])
  assert.equal(full.definition.entry_rules.length, 4) // pe <= 15 自动带 pe_ttm > 0 仅算盈利公司
  assert.deepEqual(full.definition.entry_rules[0], { left: { name: 'return', window: 20 }, operator: 'less_or_equal', value: -0.2 })
  assert.deepEqual(full.definition.entry_rules[1], { left: { name: 'pe_ttm' }, operator: 'greater_than', value: 0 })
  assert.deepEqual(full.definition.entry_rules[3], { left: { name: 'close' }, operator: 'greater_or_equal', right: { name: 'moving_average', window: 60 } })

  const partial = strategyHandoffFromEvent(
    [{ type: 'from_high', op: '<=', value: -30 }, { type: 'amount_ratio', op: '>=', value: 3 }],
    ['距近一年最高价 ≤ -30%', '当日成交额 / 近 20 日平均 ≥ 3倍'],
  )
  assert.equal(partial.mode, 'rules')
  assert.deepEqual(partial.convertedLabels, ['距近一年最高价 ≤ -30%'])
  assert.deepEqual(partial.skippedLabels, ['当日成交额 / 近 20 日平均 ≥ 3倍'])
  assert.deepEqual(partial.definition.entry_rules, [{ left: { name: 'drawdown', window: 250 }, operator: 'less_or_equal', value: -0.3 }])
  assert.match(partial.note, /暂不支持/)

  const describeOnly = strategyHandoffFromEvent([{ type: 'limit', direction: 'up' }], ['当天涨停'])
  assert.equal(describeOnly.mode, 'describe')
  assert.equal(describeOnly.definition, null)
  assert.match(describeOnly.nlPrompt, /当天涨停/)

  const store = new Map()
  globalThis.sessionStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }
  const { handOffStrategyDraft, takeStrategyDraft } = await import('../src/workspace/ruleHandoff.js')
  handOffStrategyDraft({ mode: 'describe', prompt: describeOnly.nlPrompt })
  assert.deepEqual(takeStrategyDraft(), { mode: 'describe', prompt: describeOnly.nlPrompt })
  assert.equal(takeStrategyDraft(), null)
  delete globalThis.sessionStorage
})
