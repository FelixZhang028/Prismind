import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ALPHA101_NOTE, annualIcRows, directionText, directionTone, factorNote, factorSummary,
  historyText, longShortSignMismatchNote, significanceSummary, styleCorrelationSummary,
} from '../src/workspace/factorPresentation.js'

const alpha = {
  name: 'alpha101_001', display_name: '收益为负时的波动与价格的高点位置', source: 'Alpha101', direction: 1, min_history: 25,
  description: '收益为负时的波动与价格的高点位置。按原公式计算，正向输出；A股有效性需独立评估。',
  formula: 'rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5',
}

test('方向写正向 / 反向，正向绿色、反向红色；历史长度带单位', () => {
  assert.equal(directionText(1), '正向')
  assert.equal(directionText(-1), '反向')
  assert.equal(directionText(0), '—')
  assert.equal(directionTone(1), 'text-emerald-300')
  assert.equal(directionTone(-1), 'text-rose-300')
  assert.equal(directionTone(0), 'text-slate-400')
  assert.equal(historyText(25), '25 天')
  assert.equal(historyText(null), '—')
})

test('Alpha101 不再每行重复同一句话，说明和名字一样时显示公式', () => {
  assert.deepEqual(factorSummary(alpha), { text: alpha.formula, formula: true })
  const builtin = { name: 'mom_20', display_name: '20 日动量', description: '过去 20 个交易日的涨跌幅', formula: 'close / close.shift(20) - 1' }
  assert.deepEqual(factorSummary(builtin), { text: '过去 20 个交易日的涨跌幅', formula: false })
  assert.deepEqual(factorSummary({ name: 'x', display_name: 'x' }), { text: '—', formula: false })
})

test('详情：专门写的说明优先，Alpha101 和自定义因子各有通用说明', () => {
  assert.deepEqual(factorNote(alpha, {}), { meaning: '收益为负时的波动与价格的高点位置。', usage: ALPHA101_NOTE })
  const special = { meaning: '专门的说明', usage: '专门的用法' }
  assert.equal(factorNote(alpha, { alpha101_001: special }), special)
  assert.match(factorNote({ name: 'my', category: '自定义', description: '' }).usage, /自定义因子/)
  assert.doesNotMatch(factorNote({ name: 'mom_20', category: '动量', description: '动量' }).usage, /自定义因子/)
  assert.equal(factorNote(null), null)
})

test('HAC 显著性、多空反号提示、分年份 IC 与风格相关性速查的展示规则', () => {
  const sig = significanceSummary({ observations: 120, hac_t: 2.85, hac_p: 0.0044, positive_ratio: 0.583 })
  assert.equal(sig.value, '2.85')
  assert.equal(sig.badge, '高度显著')
  assert.match(sig.sub, /p = 0.004/)
  assert.match(sig.sub, /58\.3%/)

  const weak = significanceSummary({ observations: 10, hac_t: null, hac_p: null })
  assert.equal(weak.value, '—')
  assert.equal(weak.badge, '样本不足')

  assert.match(longShortSignMismatchNote({ rank_ic_mean: 0.03, long_short_mean: -0.004 }), /符号相反/)
  assert.equal(longShortSignMismatchNote({ rank_ic_mean: 0.03, long_short_mean: 0.005 }), '')

  const annual = annualIcRows([
    { year: 2024, observations: 240, rank_ic: 0.0312, rank_ic_ir: 0.452, positive_ratio: 0.575, hac_t: 3.12, hac_p: 0.0002 },
  ])
  assert.deepEqual(annual[0], {
    year: '2024', observations: 240, rankIc: '0.031', ir: '0.452', positiveRatio: '57.5%', hacT: '3.12', hacP: '< 0.001',
  })

  const styles = styleCorrelationSummary([
    { style: 'ln_market_cap', label: '规模（对数总市值）', correlation: -0.62, tilt: '偏小盘', observations: 100, high_overlap: true },
    { style: 'momentum_20', label: '动量（20日涨跌幅）', correlation: 0.08, tilt: '关联较弱', observations: 100, high_overlap: false },
  ])
  assert.equal(styles.rows[0].corrText, '-0.620')
  assert.equal(styles.rows[1].corrText, '+0.080')
  assert.deepEqual(styles.highOverlapLabels, ['规模（对数总市值）'])
  assert.match(styles.warning, /规模（对数总市值）/)
})
