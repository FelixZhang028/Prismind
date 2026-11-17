<script setup>
// 今天符合条件的股票：用表单里的选股条件和排序，在本地最新一个交易日筛一遍。
// 和回测用的是同一套计算；只描述数据，条件是用户自己设的，不是推荐。
import { ref, watch } from 'vue'
import { screenPackage } from '../../api.js'
import { openResearch } from '../researchNavigation.js'
import { definitionFromForm } from '../ruleForm.js'
import { changeText, conditionValues, formatIndicator, screenSummary } from '../screenPresentation.js'
import ScreenBrief from './ScreenBrief.vue'
import SectionCard from './SectionCard.vue'

const props = defineProps({
  form: { type: Object, required: true },
  disabled: { type: Boolean, default: false },   // 规则还有问题时不能筛
  notify: { type: Function, default: () => {} },
})
const emit = defineEmits(['result'])

const scope = ref('pool')
const excludeSt = ref(true)
const running = ref(false)
const result = ref(null)
const stale = ref(false)
const error = ref('')
const lastRequest = ref(null)     // 这次结果用的条件和范围：AI 解读要用同一组

watch([() => props.form, scope, excludeSt], () => { if (result.value) stale.value = true }, { deep: true })

async function run(offset = 0) {
  running.value = true
  error.value = ''
  try {
    const definition = definitionFromForm(props.form)
    if (!definition.name) definition.name = '未命名策略'
    const request = offset && lastRequest.value ? lastRequest.value : { definition, scope: scope.value, exclude_st: excludeSt.value }
    result.value = await screenPackage({ ...request, limit: 100, offset })
    lastRequest.value = request
    stale.value = false
    emit('result', result.value)
  } catch (e) {
    error.value = e.message || '筛选失败'
  } finally {
    running.value = false
  }
}

const pill = (active) => active ? 'border-indigo-400/50 bg-indigo-500/15 text-white' : 'border-white/10 bg-white/5 text-slate-300 hover:border-white/25'
const tone = (change) => (change > 0 ? 'text-rose-300' : change < 0 ? 'text-emerald-300' : 'text-slate-300')
</script>

<template>
  <SectionCard title="今天符合条件的股票" hint="用上面的选股条件和排序，在本地最新一个交易日筛一遍；和回测用的是同一套计算">
    <div class="flex flex-wrap items-center gap-3">
      <div class="flex gap-2" role="group" aria-label="筛选范围">
        <button type="button" class="rounded-full border px-4 py-1.5 text-sm transition" :class="pill(scope === 'pool')" :aria-pressed="scope === 'pool'" @click="scope = 'pool'">我的股票池</button>
        <button type="button" class="rounded-full border px-4 py-1.5 text-sm transition" :class="pill(scope === 'market')" :aria-pressed="scope === 'market'" @click="scope = 'market'">全市场</button>
      </div>
      <label class="flex items-center gap-2 text-sm text-slate-300">
        <input v-model="excludeSt" type="checkbox" class="h-4 w-4 rounded border-white/20 bg-white/5 accent-indigo-500" />排除 ST
      </label>
      <button type="button" :disabled="running || disabled" class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/40 transition hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0" @click="run(0)">
        {{ running ? (scope === 'market' ? '筛选全市场中…（几秒钟）' : '筛选中…') : '开始筛选' }}
      </button>
    </div>
    <p v-if="excludeSt" class="mt-2 text-xs text-slate-400">开启「排除 ST」时，仅纳入当天 ST 状态明确为正常的股票。</p>
    <p class="mt-2 text-xs text-slate-500">停牌的股票当天没有行情，不参与筛选。结果只是按你设置的条件从数据里筛出来的，不是推荐，也不代表以后的走势。</p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">{{ error }}</p>

    <div v-if="result" class="mt-4" aria-live="polite">
      <div class="mb-3 flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <span>共匹配 {{ result.matched }} 只，本页显示 {{ result.items.length ? (result.offset || 0) + 1 : 0 }}–{{ (result.offset || 0) + result.items.length }} 只；分页不改变股票池。</span>
        <button :disabled="running || stale || !result.offset" class="text-indigo-300 disabled:opacity-40" @click="run(Math.max(0, result.offset - 100))">上一页</button>
        <button :disabled="running || stale || (result.offset || 0) + result.items.length >= result.matched" class="text-indigo-300 disabled:opacity-40" @click="run((result.offset || 0) + 100)">下一页</button>
      </div>
      <p class="text-sm text-slate-200">{{ screenSummary(result) }}</p>
      <p v-if="stale" class="mt-1 text-xs text-amber-300">筛选设置已变更。点击「开始筛选」更新结果。</p>
      <p class="mt-1 text-xs text-slate-500">条件：{{ result.conditions.join(result.logic === 'all' ? '，并且' : '，或者') }}；{{ result.ranking }}</p>

      <div v-if="result.items.length" class="mt-3 overflow-x-auto">
        <table class="w-full min-w-[640px] text-left text-sm [&_td]:whitespace-nowrap [&_td]:px-3 [&_th]:whitespace-nowrap [&_th]:px-3 [&_td:first-child]:pl-0 [&_th:first-child]:pl-0">
          <thead>
            <tr class="text-xs text-slate-500">
              <th class="pb-2 font-medium">#</th>
              <th class="pb-2 font-medium">股票</th>
              <th class="pb-2 text-right font-medium">收盘价</th>
              <th class="pb-2 text-right font-medium">当日涨跌</th>
              <th class="pb-2 text-right font-medium">{{ result.ranking_label }}</th>
              <th v-for="(text, index) in result.conditions" :key="index" class="pb-2 text-right font-medium" :title="text">条件 {{ index + 1 }}</th>
              <th class="pb-2 text-right font-medium"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-white/5">
            <tr v-for="(item, rank) in result.items" :key="item.symbol" class="text-slate-300">
              <td class="py-2 text-xs text-slate-500">{{ rank + 1 }}</td>
              <td class="py-2">
                <button type="button" class="text-left hover:text-indigo-200" @click="openResearch('market-lookup', { symbol: item.symbol })">
                  <span class="text-white">{{ item.name || item.symbol }}</span> <span class="text-xs text-slate-500">{{ item.symbol }}</span>
                </button>
              </td>
              <td class="py-2 text-right tabular-nums">{{ item.close?.toFixed(2) ?? '—' }}</td>
              <td class="py-2 text-right tabular-nums" :class="tone(item.change)">{{ changeText(item.change) }}</td>
              <td class="py-2 text-right tabular-nums text-white">{{ formatIndicator(result.ranking_indicator, item.ranking) }}</td>
              <td v-for="(text, index) in result.conditions" :key="index" class="py-2 text-right text-xs tabular-nums text-slate-400" :title="text">
                {{ conditionValues(result, item, index).left }} / {{ conditionValues(result, item, index).right }}
              </td>
              <td class="py-2 text-right">
                <button type="button" class="rounded-full border border-white/10 px-2.5 py-0.5 text-xs text-indigo-200 hover:border-indigo-400/40" @click="openResearch('agent-lab', { symbol: item.symbol })">AI 分析</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="mt-2 text-xs text-slate-500">“条件 N”一列是这条条件左边和右边的数值，鼠标移上去看是哪条条件。点股票名字在股票查询里打开；“AI 分析”在 AI 个股分析里打开这只股票，点“开始分析”才会分析。</p>
      </div>
      <p v-else class="mt-3 text-sm text-slate-400">今天没有股票同时满足这些条件，可以放宽条件或者换成全市场再试。</p>
      <ScreenBrief v-if="result.items.length && lastRequest" :request="lastRequest" :result="result" :stale="stale" />
    </div>
  </SectionCard>
</template>
