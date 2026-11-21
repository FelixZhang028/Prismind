import assert from 'node:assert/strict'
import test from 'node:test'
import {
  blankForm, blankRule, chooseIndicator, definitionFromForm, formFromDefinition,
  packagePayload, sourceLabel, strategyProtectionSummary,
} from '../src/workspace/ruleForm.js'

const options = {
  indicators: { close: '收盘价', return_1d: '区间涨跌幅', sma: '移动平均线' },
  operators: { gt: '大于', lt: '小于' },
  indicator_windows: {
    close: null,
    return_1d: { default: 20, minimum: 1, maximum: 500 },
    sma: { default: 20, minimum: 2, maximum: 500 },
  },
}

// 「均线趋势」模板的写法：既有“指标比指标”，也有自定义周期。
const template = {
  name: '均线趋势',
  entry_logic: 'all',
  entry_rules: [
    { left: { name: 'close' }, operator: 'gt', right: { name: 'sma', window: 60 } },
    { left: { name: 'return_1d', window: 5 }, operator: 'lt', value: -0.03 },
  ],
  ranking: { indicator: { name: 'return_1d', window: 20 }, direction: 'descending' },
}

test('模板里的规则填进表单后再取出来，内容不变', () => {
  const form = formFromDefinition(template, { top_n: 7, rebalance: 'monthly' }, options)
  assert.equal(form.rules[0].compare, 'indicator')
  assert.deepEqual(form.rules[0].left, { name: 'close', window: null })
  assert.deepEqual(form.rules[0].right, { name: 'sma', window: 60 })
  assert.equal(form.rules[1].compare, 'value')
  assert.equal(form.rules[1].value, -0.03)
  assert.deepEqual([form.top_n, form.rebalance], [7, 'monthly'])
  assert.deepEqual(definitionFromForm(form), template)
})

test('空白表单是一条可以直接保存的条件，换指标时周期回到默认值', () => {
  const form = blankForm(options)
  assert.equal(form.rules.length, 1)
  assert.deepEqual(definitionFromForm({ ...form, name: ' 我的策略 ' }), {
    name: '我的策略', entry_logic: 'all',
    entry_rules: [{ left: { name: 'close' }, operator: 'gt', value: 0 }],
    ranking: { indicator: { name: 'close' }, direction: 'descending' },
  })
  const rule = blankRule(options)
  chooseIndicator(rule.left, 'sma', options)
  assert.deepEqual(rule.left, { name: 'sma', window: 20 })
  rule.left.window = 60
  chooseIndicator(rule.left, 'close', options)
  assert.deepEqual(rule.left, { name: 'close', window: null })
})

test('切换成“和数值比较”后不会把另一个指标一起提交', () => {
  const form = formFromDefinition(template, { top_n: 5, rebalance: 'weekly' }, options)
  form.rules[0].compare = 'value'
  form.rules[0].value = '12.5'
  const [first] = definitionFromForm(form).entry_rules
  assert.deepEqual(first, { left: { name: 'close' }, operator: 'gt', value: 12.5 })
})

test('请求体如实记录表单是从哪里开始的', () => {
  const form = formFromDefinition(template, { top_n: 5, rebalance: 'weekly' }, options)
  assert.equal(packagePayload(form, null).source, 'visual_builder')
  assert.equal(packagePayload(form, { kind: 'describe' }).source, 'nl_builder')
  const fromTemplate = packagePayload(form, { kind: 'template', template_id: 'ma_trend', style: 'aggressive' })
  assert.deepEqual([fromTemplate.source, fromTemplate.style, fromTemplate.top_n], ['template:ma_trend', 'aggressive', 5])
})

test('来源标签区分原样的模板和改过的模板', () => {
  assert.equal(sourceLabel('template:momentum:balanced'), '模板')
  assert.equal(sourceLabel('template_modified:momentum:balanced'), '基于模板修改')
  assert.equal(sourceLabel('copy:abc'), '副本')
  assert.equal(sourceLabel('nl_builder'), '一句话生成')
  assert.equal(sourceLabel('visual_builder'), '自己填写')
  assert.equal(sourceLabel(undefined), '规则策略')
})

test('防换手缓冲与大盘均线择时在表单和接口定义之间无损往返，并兼容下拉框字符串值', () => {
  const form = formFromDefinition(template, { top_n: 5, rebalance: 'weekly' }, options)
  assert.equal(form.hold_buffer, 0)
  assert.deepEqual(form.market_timing, { enabled: false, benchmark: '000300.SH', ma_window: 60, off_weight: 0 })

  // 模拟 HTML <select> 回传字符串
  form.hold_buffer = '10'
  form.market_timing = { enabled: true, benchmark: '000905.SH', ma_window: '120', off_weight: '0.3' }
  const def = definitionFromForm(form)
  assert.equal(def.hold_buffer, 10)
  assert.deepEqual(def.market_timing, { benchmark: '000905.SH', ma_window: 120, off_weight: 0.3 })

  const restored = formFromDefinition(def, { top_n: 5, rebalance: 'weekly' }, options)
  assert.equal(restored.hold_buffer, 10)
  assert.deepEqual(restored.market_timing, { enabled: true, benchmark: '000905.SH', ma_window: 120, off_weight: 0.3 })

  // 关掉后不再携带这两个字段
  restored.hold_buffer = '0'
  restored.market_timing.enabled = false
  assert.deepEqual(definitionFromForm(restored), template)
})

test('策略保护摘要按配置拼接防换手与大盘择时说明', () => {
  assert.equal(strategyProtectionSummary({}), '')
  assert.equal(
    strategyProtectionSummary({ hold_buffer: 10 }),
    '防换手缓冲：已持股跌出前 N+10 名再卖',
  )
  assert.equal(
    strategyProtectionSummary({
      hold_buffer: 5,
      market_timing: { benchmark: '000300.SH', ma_window: 60, off_weight: 0 },
      market_timing_triggers: 8,
    }),
    '防换手缓冲：已持股跌出前 N+5 名再卖 · 大盘择时：沪深 300低于 60 日均线空仓等待（共触发 8 个调仓日）',
  )
  assert.equal(
    strategyProtectionSummary({
      market_timing: { benchmark: '399006.SZ', ma_window: 20, off_weight: 0.3 },
      market_timing_triggers: 3,
    }),
    '大盘择时：创业板指低于 20 日均线降至 30%（共触发 3 个调仓日）',
  )
})
