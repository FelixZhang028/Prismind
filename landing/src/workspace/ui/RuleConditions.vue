<script setup>
// 选股条件和排序的表单：新建规则策略和条件选股共用。直接改传进来的 form（同一份表单）。
import { computed, ref } from 'vue'
import { blankRule, chooseIndicator, isQuantileOperator, quantileHint } from '../ruleForm.js'
import FormField from './FormField.vue'

const props = defineProps({
  form: { type: Object, required: true },
  options: { type: Object, required: true },   // studioOptions()：指标（含因子库/Alpha101）、判断方式、周期范围
})

const MAX_RULES = 10
const dirOptions = [{ value: 'descending', label: '从高到低' }, { value: 'ascending', label: '从低到高' }]
const logicOptions = [{ value: 'all', label: '全部满足' }, { value: 'any', label: '满足任意一条' }]
const compareOptions = [{ value: 'value', label: '一个数值' }, { value: 'indicator', label: '另一个指标' }]
const select = (mapping) => Object.entries(mapping || {}).map(([value, label]) => ({ value, label }))
const operatorOptions = computed(() => select(props.options.operators))
const windowLimits = (name) => props.options.indicator_windows?.[name]
const indicatorKeyword = ref('')

const baseGroups = computed(() => {
  if (Array.isArray(props.options.indicator_groups) && props.options.indicator_groups.length) {
    return props.options.indicator_groups
  }
  return [{ label: '可用指标', items: select(props.options.indicators) }]
})

function filteredGroupsFor(currentValue) {
  const kw = indicatorKeyword.value.trim().toLowerCase()
  if (!kw) return baseGroups.value
  return baseGroups.value
    .map((group) => ({
      label: group.label,
      items: (group.items || []).filter(
        (item) =>
          item.value === currentValue
          || String(item.label || '').toLowerCase().includes(kw)
          || String(item.value || '').toLowerCase().includes(kw)
      ),
    }))
    .filter((group) => group.items.length > 0)
}

const hasFactorIndicators = computed(() => (
  String(props.form.ranking?.name || '').startsWith('factor:')
  || props.form.rules.some(
    (rule) =>
      String(rule.left?.name || '').startsWith('factor:')
      || (!isQuantileOperator(rule.operator, props.options) && rule.compare === 'indicator' && String(rule.right?.name || '').startsWith('factor:'))
  )
))

const usesDividendYield = computed(() => (
  ['dividend_yield', 'factor:dividend_yield'].includes(props.form.ranking.name)
  || props.form.rules.some(
    (rule) =>
      ['dividend_yield', 'factor:dividend_yield'].includes(rule.left.name)
      || (rule.compare === 'indicator' && ['dividend_yield', 'factor:dividend_yield'].includes(rule.right.name))
  )
))

function chooseOperator(rule, op) {
  rule.operator = op
  if (isQuantileOperator(op, props.options)) {
    rule.compare = 'value'
    const num = Number(rule.value)
    if (!Number.isFinite(num) || num < 1 || num >= 100) {
      rule.value = 20
    }
  }
}

function addRule() {
  if (props.form.rules.length < MAX_RULES) props.form.rules.push(blankRule(props.options))
}
function removeRule(index) {
  if (props.form.rules.length > 1) props.form.rules.splice(index, 1)
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-white">选股条件</h3>
        <p class="mt-1 text-xs text-slate-400">支持 13 项基础指标、全部内置因子、Alpha101 与自定义因子；分位过滤（如「剔除最差 20%」）直接填百分比数字 1~99。其余涨跌幅/波动率/股息率/ROE 用小数填写（0.05 表示 5%）。</p>
      </div>
      <div class="flex flex-wrap items-end gap-3">
        <label class="block w-52">
          <span class="mb-1 block text-xs text-slate-400">快速筛选指标 / 因子</span>
          <input
            v-model="indicatorKeyword"
            type="search"
            placeholder="搜 roe、股息率、alpha101…"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-white outline-none focus:border-indigo-400/40"
          />
        </label>
        <div class="w-40"><FormField label="多条条件之间" type="select" v-model="form.entry_logic" :options="logicOptions" /></div>
      </div>
    </div>
    <ol class="mt-3 space-y-3" aria-label="选股条件">
      <li v-for="(rule, index) in form.rules" :key="index" :data-guide="index === 0 ? 'rule-first-condition' : undefined" class="rounded-xl border border-white/10 bg-white/5 p-4">
        <div class="flex items-center justify-between">
          <span class="text-xs text-slate-400">条件 {{ index + 1 }}</span>
          <button type="button" class="text-xs text-rose-300 hover:underline disabled:opacity-40" :disabled="form.rules.length <= 1" @click="removeRule(index)">删除</button>
        </div>
        <!-- 只排出用得到的格子：没有周期的指标不留“周期”那一格，分位过滤直接填百分比 -->
        <div class="mt-3 flex flex-wrap gap-4">
          <label class="block min-w-[13rem] flex-[2]">
            <span class="mb-1 block text-xs text-slate-400">指标 / 因子</span>
            <select
              :value="rule.left.name"
              class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/40"
              @change="chooseIndicator(rule.left, $event.target.value, options)"
            >
              <optgroup v-for="group in filteredGroupsFor(rule.left.name)" :key="group.label" :label="group.label" class="bg-ink text-slate-300">
                <option v-for="item in group.items" :key="item.value" :value="item.value" class="bg-ink text-white">{{ item.label }}</option>
              </optgroup>
            </select>
          </label>
          <FormField v-if="rule.left.window != null && windowLimits(rule.left.name)" class="w-28 shrink-0" label="周期（日）" type="number" v-model="rule.left.window" :min="windowLimits(rule.left.name).minimum" :max="windowLimits(rule.left.name).maximum" :step="1" />
          <FormField class="min-w-[10rem] flex-[1.3]" label="判断" type="select" :model-value="rule.operator" :options="operatorOptions" @update:model-value="chooseOperator(rule, $event)" />

          <template v-if="isQuantileOperator(rule.operator, options)">
            <div class="min-w-[12rem] flex-[1.6]">
              <FormField label="分位比例（%）" type="number" v-model="rule.value" :min="1" :max="99" :step="1" />
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                <button
                  v-for="pct in [10, 20, 30, 50]"
                  :key="pct"
                  type="button"
                  class="rounded-full border px-2 py-0.5 transition"
                  :class="Number(rule.value) === pct ? 'border-indigo-400/40 bg-indigo-500/20 text-indigo-200' : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'"
                  @click="rule.value = pct"
                >
                  {{ pct }}%
                </button>
              </div>
              <p class="mt-1 text-xs text-indigo-200/80">{{ quantileHint(rule.operator, rule.value) }}</p>
            </div>
          </template>
          <template v-else>
            <FormField class="min-w-[9rem] flex-1" label="和什么比较" type="select" v-model="rule.compare" :options="compareOptions" />
            <template v-if="rule.compare === 'indicator'">
              <label class="block min-w-[13rem] flex-[2]">
                <span class="mb-1 block text-xs text-slate-400">另一个指标 / 因子</span>
                <select
                  :value="rule.right.name"
                  class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/40"
                  @change="chooseIndicator(rule.right, $event.target.value, options)"
                >
                  <optgroup v-for="group in filteredGroupsFor(rule.right.name)" :key="group.label" :label="group.label" class="bg-ink text-slate-300">
                    <option v-for="item in group.items" :key="item.value" :value="item.value" class="bg-ink text-white">{{ item.label }}</option>
                  </optgroup>
                </select>
              </label>
              <FormField v-if="rule.right.window != null && windowLimits(rule.right.name)" class="w-28 shrink-0" label="周期（日）" type="number" v-model="rule.right.window" :min="windowLimits(rule.right.name).minimum" :max="windowLimits(rule.right.name).maximum" :step="1" />
            </template>
            <FormField v-else class="min-w-[9rem] flex-[1.5]" label="数值" type="number" v-model="rule.value" step="any" />
          </template>
        </div>
      </li>
    </ol>
    <button type="button" class="mt-3 text-sm text-indigo-300 hover:underline disabled:opacity-40" :disabled="form.rules.length >= MAX_RULES" @click="addRule">+ 添加条件</button>

    <h3 class="mt-6 text-sm font-semibold text-white">排序</h3>
    <div class="mt-3 flex flex-wrap gap-4">
      <label class="block min-w-[13rem] flex-[2]">
        <span class="mb-1 block text-xs text-slate-400">排序指标 / 因子</span>
        <select
          :value="form.ranking.name"
          class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/40"
          @change="chooseIndicator(form.ranking, $event.target.value, options)"
        >
          <optgroup v-for="group in filteredGroupsFor(form.ranking.name)" :key="group.label" :label="group.label" class="bg-ink text-slate-300">
            <option v-for="item in group.items" :key="item.value" :value="item.value" class="bg-ink text-white">{{ item.label }}</option>
          </optgroup>
        </select>
      </label>
      <FormField v-if="form.ranking.window != null && windowLimits(form.ranking.name)" class="w-28 shrink-0" label="周期（日）" type="number" v-model="form.ranking.window" :min="windowLimits(form.ranking.name).minimum" :max="windowLimits(form.ranking.name).maximum" :step="1" />
      <FormField class="min-w-[9rem] flex-1" label="排序方向" type="select" v-model="form.ranking.direction" :options="dirOptions" />
    </div>
    <p v-if="hasFactorIndicators" class="mt-2 text-xs text-slate-400">已引用因子库或 Alpha101 因子：每个调仓日均在当日有效股票池截面上无前视偏差计算；部分估值/财务/行业类因子依赖对应历史数据。</p>
    <p v-if="usesDividendYield" class="mt-2 text-xs text-slate-400">股息率按近 365 天已有的现金分红记录和当日未复权收盘价估算。没有现金分红记录时，该值按缺失处理。</p>
  </div>
</template>
