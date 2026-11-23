<script setup>
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { getBacktestBenchmark, getBacktestCatalog, getBacktest, getPreferences, getRunAudit, listPackages, submitBacktest } from '../../api.js'
import { REBALANCE_OPTIONS, backtestDefaults } from '../preferences.js'
import { openResearch } from '../researchNavigation.js'
import { setFocus } from '../chatFocus.js'
import { backtestId, countText, executionSummaryText, filterSummaryText, poolLabel, runTime, strategyName, validityLabel } from '../runRecords.js'
import BacktestAiReview from '../ui/BacktestAiReview.vue'
import BacktestHealthCard from '../ui/BacktestHealthCard.vue'
import BacktestTasks from '../ui/BacktestTasks.vue'
import FactorCompositeEditor from '../ui/FactorCompositeEditor.vue'
import UsefulPrompt from '../ui/UsefulPrompt.vue'
import RiskSettings from '../ui/RiskSettings.vue'
import MetricCard from '../ui/MetricCard.vue'
import SectionCard from '../ui/SectionCard.vue'
import LineChart from '../ui/LineChart.vue'
import EmptyState from '../ui/EmptyState.vue'
import FormField from '../ui/FormField.vue'
import DataTable from '../ui/DataTable.vue'
import StatusPill from '../ui/StatusPill.vue'
import { pendingAuditRun } from '../auditLink.js'
import { benchmarkCards, benchmarkChoices, benchmarkCoverageNote, benchmarkNote, benchmarkSeries } from '../benchmarkPresentation.js'
import { CURRENT_POOL, marketChoices, marketLabel, marketNote, suggestedHistoricalMarket, usableMarket } from '../marketPresentation.js'
import { paperPrefill, parseFactorRows, returnTone } from '../paperPresentation.js'
import { strategyProtectionSummary, tradeReasonClass } from '../ruleForm.js'
import { takeFactorBacktestDraft } from '../factorBacktestDraft.js'

const props = defineProps({
  routeContext: { type: Object, default: () => ({}) },
  user: { type: Object, default: null },
  notify: { type: Function, default: () => {} },
})

// ---------- 新建回测表单 ----------
// 股票范围：自己的股票池，或某个指数当时的成分股（来自回测目录接口）。
const markets = ref([])
const marketOptions = computed(() => marketChoices(markets.value))
const marketHint = computed(() => marketNote(form.market, markets.value))
const strategyOptions = ref([])
const catalogLoading = ref(false)
const catalogErrors = ref([])
const strategyParameters = reactive({})
const selectedStrategy = computed(() => strategyOptions.value.find((s) => s.value === form.strategy))
const factorComposition = computed(() => (form.strategy === 'factor_composite' ? parseFactorRows(strategyParameters.factors_json) : []))
const poolPreset = ref(null)
const suggestedHistorical = computed(() => (
  form.market === CURRENT_POOL ? suggestedHistoricalMarket(poolPreset.value, markets.value) : null
))
const benchmarkCoverage = ref(null)
const riskEditor = ref(null)
const riskOpen = ref(false)
const execFilterOpen = ref(false)
const executionDefaults = ref(null)
const filterDefaults = ref(null)
let execFilterInitialized = false
const execForm = reactive({
  commission_wan: 3, // 万分之几，3 = 0.0003（万三）
  minimum_commission: 5,
  historical_fees: true,
  stamp_tax_wan: 5, // 固定印花税模式下的万分比，5 = 0.0005（万五）
  slippage_bps: 5, // 基点，5 = 0.0005（0.05%）
})
const filterForm = reactive({
  exclude_st: true,
  exclude_suspended: true,
  minimum_listing_days: 60,
  minimum_history_days: 120,
  minimum_average_amount: 0,
})
function syncExecFilterFromDefaults(execSrc, filterSrc) {
  if (execSrc) {
    execForm.commission_wan = Number(((execSrc.commission_rate ?? 0.0003) * 10000).toFixed(2))
    execForm.minimum_commission = Number(execSrc.minimum_commission ?? 5)
    execForm.historical_fees = execSrc.historical_fees !== false
    execForm.stamp_tax_wan = Number(((execSrc.stamp_tax_rate ?? 0.0005) * 10000).toFixed(2))
    execForm.slippage_bps = Number(((execSrc.slippage_rate ?? 0.0005) * 10000).toFixed(2))
  }
  if (filterSrc) {
    filterForm.exclude_st = Boolean(filterSrc.exclude_st ?? true)
    filterForm.exclude_suspended = Boolean(filterSrc.exclude_suspended ?? true)
    filterForm.minimum_listing_days = Number(filterSrc.minimum_listing_days ?? 60)
    filterForm.minimum_history_days = Number(filterSrc.minimum_history_days ?? 120)
    filterForm.minimum_average_amount = Number(filterSrc.minimum_average_amount ?? 0)
  }
}
function resetExecFilterDefaults() {
  syncExecFilterFromDefaults(executionDefaults.value, filterDefaults.value)
}
const currentExecOverrides = computed(() => ({
  commission_rate: Math.max(0, Number(execForm.commission_wan) || 0) / 10000,
  minimum_commission: Math.max(0, Number(execForm.minimum_commission) || 0),
  historical_fees: Boolean(execForm.historical_fees),
  stamp_tax_rate: Math.max(0, Number(execForm.stamp_tax_wan) || 0) / 10000,
  slippage_rate: Math.max(0, Number(execForm.slippage_bps) || 0) / 10000,
}))
const currentFilterOverrides = computed(() => ({
  exclude_st: Boolean(filterForm.exclude_st),
  exclude_suspended: Boolean(filterForm.exclude_suspended),
  minimum_listing_days: Math.max(0, Math.round(Number(filterForm.minimum_listing_days) || 0)),
  minimum_history_days: Math.max(0, Math.round(Number(filterForm.minimum_history_days) || 0)),
  minimum_average_amount: Math.max(0, Number(filterForm.minimum_average_amount) || 0),
}))
const formExecSummary = computed(() => executionSummaryText(currentExecOverrides.value))
const formFilterSummary = computed(() => filterSummaryText(currentFilterOverrides.value))
const resultExecutionSummary = computed(() => executionSummaryText(result.value?.effective_config?.execution))
const resultFilterSummary = computed(() => filterSummaryText(result.value?.effective_config?.filters))
const costRatioPct = computed(() => {
  const cap = num(result.value?.effective_config?.initial_capital)
  const cost = num(totalCost.value)
  if (!cap || cap <= 0 || cost === null) return ''
  return `占初始资金 ${((cost / cap) * 100).toFixed(2)}%`
})
function chooseStrategy() {
  const strategy = selectedStrategy.value
  for (const key of Object.keys(strategyParameters)) delete strategyParameters[key]
  Object.assign(strategyParameters, strategy?.defaults || {})
  if (strategy?.top_n) form.max_positions = strategy.top_n
  if (strategy?.rebalance) form.rebalance = strategy.rebalance
}
const rebalances = REBALANCE_OPTIONS

const form = reactive({
  strategy: '',
  market: CURRENT_POOL,
  from_date: '2025-01-01',
  to_date: '2025-12-31',
  initial_capital: 1000000,
  max_positions: 10,
  rebalance: 'weekly',
})

const presetNote = computed(() => {
  const pool = poolPreset.value
  if (form.market !== CURRENT_POOL || !pool) return ''
  const earlier = form.from_date && form.from_date < pool.snapshot_date
  return poolLabel(pool) + (earlier ? '。回测起点早于名单快照，可能存在前视偏差。' : '。回测期间使用这份固定名单。')
})
const coverageNote = computed(() => benchmarkCoverageNote(benchmarkCoverage.value, form.from_date, form.to_date))
const running = ref(false)
const tasksRefresh = ref(0)
function taskCompleted(job) {
  props.notify('回测已完成')
  if (job.id === props.routeContext.job) openResearch('backtest-review', { run: job.result_id })
}
const runError = ref('')

// ---------- 回测结果 ----------
// 这里只显示一次回测：刚运行的，或从研究记录打开的。以前的回测都在研究记录里。
const selectedId = ref(null)
const current = ref(null)
const detailLoading = ref(false)

const result = computed(() => current.value?.result || {})
const protectionSummary = computed(() => strategyProtectionSummary(result.value))
const shownStrategy = computed(() => {
  const config = result.value.effective_config || {}
  return strategyName(strategyOptions.value, config.strategy_reference || config.strategy_plugin, current.value?.strategy)
})

// ---------- 可信度审计（结果的属性，随详情一起加载） ----------
const audit = ref(null)
// 评级视觉语言与审计页一致：A 绿 / B 蓝 / C 黄 / D 红
const GRADE_TONE = { A: 'text-emerald-300', B: 'text-sky-300', C: 'text-amber-300', D: 'text-rose-300' }
const gradeTone = computed(() => GRADE_TONE[audit.value?.grade] || 'text-slate-300')
const gradeValue = computed(() => audit.value?.grade || '待检查')
const gradeSub = computed(() =>
  audit.value?.headline ? audit.value.headline : '含数据、成本与参数搜索偏差等审计维度，不代表未来盈利概率'
)

function openAudit() {
  if (selectedId.value === null || selectedId.value === '') return
  pendingAuditRun.value = `run-${selectedId.value}`
  openResearch('audit-report', { run: selectedId.value })
}

const tabs = ['概览', '交易与成本', '持仓分析']
const activeTab = ref('概览')

// ---------- 格式化辅助 ----------
const num = (v) => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isNaN(n) ? null : n
}
const fmtPct = (v) => (num(v) === null ? '—' : `${Number(v).toFixed(2)}%`)
const fmtNum = (v) => (num(v) === null ? '—' : Number(v).toFixed(2))
const fmtMoney = (v) =>
  num(v) === null ? '—' : `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`

const finalEquity = computed(() => {
  const fe = num(result.value.final_equity)
  if (fe !== null) return fe
  const eq = result.value.equity
  if (Array.isArray(eq) && eq.length) return num(eq[eq.length - 1])
  return null
})

const totalCost = computed(() => {
  const r = result.value
  return num(r.total_cost ?? r.trading_cost ?? r.total_trading_cost ?? r.cost)
})

// 累计收益、最大回撤已在概览顶部，总交易成本在“交易与成本”里，这里不重复。
const metrics = computed(() => {
  const annual = num(result.value.annual_return)
  const turnover = num(result.value.annualized_turnover)
  return [
    { label: '最终权益', value: fmtMoney(finalEquity.value), tone: '' },
    { label: '年化收益', value: fmtPct(annual), tone: annual === null || annual === 0 ? '' : annual > 0 ? 'text-rose-300' : 'text-emerald-300' }, // 涨红跌绿
    { label: '年化换手', value: turnover === null ? '—' : `${turnover.toFixed(1)}%`, sub: '单边年化', tone: '' },
    { label: '夏普比率', value: fmtNum(result.value.sharpe), tone: '' },
    { label: '索提诺比率', value: fmtNum(result.value.sortino), tone: '' },
    { label: '卡玛比率', value: fmtNum(result.value.calmar), tone: '' },
  ]
})

const annualBreakdown = computed(() => current.value?.annual_breakdown || null)
const hasAnnualBenchmark = computed(() => Boolean(annualBreakdown.value?.rows?.some((r) => r.benchmark_return_pct != null)))
const annualCols = computed(() => [
  { key: 'year', label: '年份' },
  { key: 'return_pct', label: '策略收益', align: 'right' },
  ...(hasAnnualBenchmark.value ? [
    { key: 'benchmark_return_pct', label: `${annualBreakdown.value?.benchmark_name || '基准'}收益`, align: 'right' },
    { key: 'excess_return_pct', label: '超额收益', align: 'right' },
  ] : []),
  { key: 'max_drawdown_pct', label: '最大回撤', align: 'right' },
  { key: 'turnover_pct', label: '当年换手(单边)', align: 'right' },
  { key: 'fills', label: '成交笔数', align: 'right' },
  { key: 'trading_days', label: '交易日', align: 'right' },
])
const signedPct = (v) => {
  const n = num(v)
  return n === null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

// 和基准的对比。默认是回测时记录的基准（沪深 300），可以换成本地有行情的其他常用指数；
// 换过一次后记住这个选择。回测没有记录基准时为空。
const BENCHMARK_KEY = 'fq-benchmark'
const benchmark = ref(null)
const benchmarkLoading = ref(false)
const benchmarkOptions = computed(() => benchmarkChoices(current.value?.benchmark_options, benchmark.value))
function rememberedBenchmark() {
  try { return localStorage.getItem(BENCHMARK_KEY) || '' } catch { return '' }
}
async function chooseBenchmark(symbol, remember = true, control = null) {
  const id = selectedId.value
  benchmarkLoading.value = true
  try {
    const next = await getBacktestBenchmark(id, symbol)
    if (id !== selectedId.value) return
    // 自动沿用上次的选择时，只有能比较才换；否则留在回测记录的基准上。
    if (!remember && !next.comparable) return
    benchmark.value = next
    if (remember) { try { localStorage.setItem(BENCHMARK_KEY, symbol) } catch { /* 记不住也不影响比较 */ } }
  } catch (e) {
    if (remember) props.notify(e.message || '读取基准对比失败')
    // 没换成：下拉框回到正在显示的那个指数。
    if (control && benchmark.value) control.value = benchmark.value.symbol
  } finally {
    benchmarkLoading.value = false
  }
}
const comparisonCards = computed(() => benchmarkCards(benchmark.value))
const comparisonSeries = computed(() => benchmarkSeries(benchmark.value))
const comparisonNote = computed(() => benchmarkNote(benchmark.value))

const equitySeries = computed(() => [
  { label: '资金曲线', color: 'var(--fq-chart-strategy)', points: Array.isArray(result.value.equity) ? result.value.equity : [] },
])

// 交易与成本 / 持仓分析
const tradeCols = [
  { key: 'date', label: '时间' },
  { key: 'symbol', label: '标的' },
  { key: 'side', label: '方向' },
  { key: 'quantity', label: '数量', align: 'right' },
  { key: 'price', label: '价格', align: 'right' },
  { key: 'amount', label: '金额', align: 'right' },
  { key: 'fee', label: '手续费', align: 'right' },
  { key: 'reason_label', label: '说明' },
]
const positionCols = [
  { key: 'symbol', label: '标的' },
  { key: 'name', label: '名称' },
  { key: 'quantity', label: '数量', align: 'right' },
  { key: 'avg_price', label: '持仓均价', align: 'right' },
  { key: 'price', label: '现价', align: 'right' },
  { key: 'market_value', label: '市值', align: 'right' },
  { key: 'pnl', label: '盈亏', align: 'right' },
]

// ---------- 逻辑 ----------
async function loadDetail() {
  if (selectedId.value === null || selectedId.value === '') return
  detailLoading.value = true
  current.value = null
  benchmark.value = null
  audit.value = null
  try {
    current.value = await getBacktest(selectedId.value)
    benchmark.value = current.value.benchmark || null
    const preferred = rememberedBenchmark()
    if (benchmark.value && preferred !== benchmark.value.symbol && (current.value.benchmark_options || []).some((item) => item.symbol === preferred)) {
      chooseBenchmark(preferred, false)
    }
    if (props.routeContext.mode === 'reuse') {
      const config = current.value.result?.effective_config
      const reference = config?.strategy_reference || config?.strategy_plugin
      if (reference && strategyOptions.value.some((s) => s.value === reference)) {
        form.strategy = reference
        chooseStrategy()
        for (const key of ['from_date', 'to_date', 'initial_capital', 'max_positions', 'rebalance']) {
          if (config[key] != null) form[key] = config[key]
        }
        form.market = usableMarket(config.market, markets.value)
        if (!reference.startsWith('package:')) Object.assign(strategyParameters, config.strategy_parameters || {})
        if (config.execution || config.filters) syncExecFilterFromDefaults(config.execution, config.filters)
      }
    }
    audit.value = null
    // 评级随详情加载；明细缺失或审计失败时显示"待检查"，不阻塞结果展示。
    try {
      audit.value = await getRunAudit(`run-${selectedId.value}`)
    } catch {
      audit.value = null
    }
  } catch (e) {
    props.notify(e.message || '加载回测详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function onSubmit() {
  if (!selectedStrategy.value) return props.notify('请选择可执行策略')
  if (!riskEditor.value?.ready) return props.notify('风控配置尚未加载，请稍后或重试')
  if (riskEditor.value?.dirty) { riskOpen.value = true; return props.notify('请先保存修改的风控配置') }
  if (form.from_date >= form.to_date) return props.notify('开始日期需早于结束日期')
  running.value = true
  runError.value = ''

  try {
    const data = await submitBacktest({
      strategy: form.strategy.trim(),
      market: form.market,
      from_date: form.from_date,
      to_date: form.to_date,
      initial_capital: Number(form.initial_capital),
      max_positions: Number(form.max_positions),
      rebalance: form.rebalance,
      strategy_parameters: { ...strategyParameters },
      execution_overrides: currentExecOverrides.value,
      filter_overrides: currentFilterOverrides.value,
    })
    props.notify('回测已提交。可在「回测任务」中查看进度或取消任务。')
    tasksRefresh.value += 1
    activeTab.value = '概览'
    // 保存任务编号：刷新后重新订阅后台状态，成功后再打开结果。
    openResearch('backtest-review', { job: data.id })
  } catch (e) {
    runError.value = e.message || '回测失败'
    props.notify(e.message || '回测失败')
  } finally {
    running.value = false
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogErrors.value = []
  try {
    const [catalog, packages] = await Promise.all([getBacktestCatalog(), listPackages()])
    poolPreset.value = catalog.pool_preset || null
    benchmarkCoverage.value = catalog.benchmark_coverage || null
    if (catalog.execution_defaults) executionDefaults.value = catalog.execution_defaults
    if (catalog.filter_defaults) filterDefaults.value = catalog.filter_defaults
    if (!execFilterInitialized && (catalog.execution_defaults || catalog.filter_defaults)) {
      syncExecFilterFromDefaults(catalog.execution_defaults, catalog.filter_defaults)
      execFilterInitialized = true
    }
    strategyOptions.value = [
      ...(packages.items || []).map((p) => ({ value: `package:${p.package_id}`, label: `${p.name} · 规则策略`, top_n: p.top_n, rebalance: p.rebalance })),
      ...catalog.items,
    ]
    markets.value = catalog.markets || []
    form.market = usableMarket(form.market, markets.value)
    const requested = props.routeContext.strategy
    if (requested) {
      const keepCombination = requested === 'factor_composite' && form.strategy === requested && factorComposition.value.length
      form.strategy = strategyOptions.value.some((s) => s.value === requested) ? requested : ''
      if (!form.strategy) catalogErrors.value.unshift('选中的策略已删除或无法加载，请重新选择。')
      if (!keepCombination) chooseStrategy()
      if (form.strategy === 'factor_composite' && props.routeContext.mode === 'factor-combination') {
        const draft = takeFactorBacktestDraft()
        if (draft) {
          form.market = draft.market
          form.from_date = draft.from_date
          form.to_date = draft.to_date
          strategyParameters.factors_json = JSON.stringify(draft.factors)
        }
      }
    } else if (!strategyOptions.value.some((s) => s.value === form.strategy)) {
      form.strategy = catalog.default
      chooseStrategy()
    }
  } catch (e) { catalogErrors.value = [e.message || '加载策略目录失败']; strategyOptions.value = []; form.strategy = '' }
  finally { catalogLoading.value = false }
}
async function loadRouteRun() {
  const id = backtestId(props.routeContext.run)
  if (id === null) {
    selectedId.value = null
    current.value = null
    benchmark.value = null
    audit.value = null
    return
  }
  if (id === selectedId.value && current.value && props.routeContext.mode !== 'reuse') return
  selectedId.value = id
  await loadDetail()
}
watch(() => props.routeContext.strategy, (value) => {
  if (!value || catalogLoading.value) return
  form.strategy = strategyOptions.value.some((s) => s.value === value) ? value : ''
  chooseStrategy()
})
watch(() => props.routeContext.run, loadRouteRun)
watch(selectedId, (id) => setFocus('backtest-review', id ? { backtest: id } : null), { immediate: true })
// 第一次打开时，表单用设置页里的研究默认值；之后保留这次修改过的值。所选策略自带持仓数和调仓频率时以策略为准。
let preferencesApplied = false
async function applyPreferences() {
  if (preferencesApplied) return
  preferencesApplied = true
  try {
    Object.assign(form, backtestDefaults((await getPreferences()).preferences))
  } catch { /* 读不到就用页面自带的默认值 */ }
}
onActivated(async () => {
  await applyPreferences()
  await loadCatalog()
  await loadRouteRun()
})
</script>

<template>
  <div class="space-y-6">
    <!-- 标题 -->
    <div class="glass glass-sheen rounded-2xl p-6">
      <h1 class="text-xl font-bold text-white">策略回测</h1>
      <p class="mt-2 text-sm text-slate-400">选择策略，设置日期、资金和风控，确认后再运行。</p>
      <button class="mt-3 text-sm text-indigo-300" @click="openResearch('strategy-hub')">← 返回我的策略</button>
    </div>

    <!-- 新建回测 -->
    <SectionCard title="新建回测" hint="配置策略与市场区间，运行一次确定性回测">
      <p v-if="routeContext.mode === 'reuse'" class="mb-4 text-sm text-slate-400">已带入历史区间、资金、股票范围与策略参数；风控使用当前设置。</p>
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <FormField label="策略" type="select" v-model="form.strategy" :options="[{ value: '', label: catalogLoading ? '加载中…' : '请选择策略' }, ...strategyOptions]" :disabled="catalogLoading" @update:model-value="chooseStrategy" />
        <FormField label="股票范围" type="select" v-model="form.market" :options="marketOptions" />
        <FormField label="开始日期" type="date" v-model="form.from_date" />
        <FormField label="结束日期" type="date" v-model="form.to_date" />
        <FormField label="初始资金" type="number" v-model="form.initial_capital" :min="0" :step="10000" />
        <FormField label="最大持仓" type="number" v-model="form.max_positions" :min="1" :max="form.strategy.startsWith('package:') ? 50 : 500" :step="1" />
        <FormField label="调仓频率" type="select" v-model="form.rebalance" :options="rebalances" />
      </div>
      <p v-if="marketHint" class="mt-3 text-xs text-slate-400">{{ marketHint }}</p>
      <p v-if="presetNote" class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" :class="form.from_date < poolPreset?.snapshot_date ? 'text-amber-300' : 'text-slate-400'">
        <span>{{ presetNote }}</span>
        <button
          v-if="suggestedHistorical"
          type="button"
          class="font-medium text-indigo-300 underline hover:text-indigo-200"
          @click="form.market = suggestedHistorical.value"
        >
          改用{{ suggestedHistorical.label }}（按当时名单，无前视偏差）→
        </button>
      </p>
      <p v-if="coverageNote.text" class="mt-2 text-xs" :class="coverageNote.outside ? 'text-amber-300' : 'text-slate-400'">{{ coverageNote.text }}</p>
      <p v-for="(error, i) in catalogErrors" :key="i" role="alert" class="mt-3 text-sm text-amber-300">{{ error }}</p>
      <FactorCompositeEditor v-if="form.strategy === 'factor_composite'" v-model="strategyParameters.factors_json" class="mt-5" />
      <div v-if="selectedStrategy?.parameters?.length && form.strategy !== 'factor_composite'" class="mt-5 grid gap-4 border-t border-white/10 pt-5 md:grid-cols-2 xl:grid-cols-4">
        <FormField v-for="p in selectedStrategy.parameters" :key="p.name" v-model="strategyParameters[p.name]" :label="p.label" :type="p.choices?.length ? 'select' : p.kind === 'boolean' ? 'checkbox' : ['integer', 'number'].includes(p.kind) ? 'number' : 'text'" :options="(p.choices || []).map((v) => ({ value: v, label: v }))" :min="p.minimum" :max="p.maximum" :step="p.kind === 'integer' ? 1 : 'any'" :hint="p.description" />
      </div>
      <details :open="execFilterOpen" class="mt-5 rounded-xl border border-white/10 bg-white/5" @toggle="execFilterOpen = $event.target.open">
        <summary class="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm text-slate-300">
          <span class="font-medium text-white">交易成本与股票过滤</span>
          <span class="text-xs text-slate-400">{{ formExecSummary }} · {{ formFilterSummary }}</span>
        </summary>
        <div class="space-y-5 border-t border-white/10 p-4 text-sm">
          <div>
            <div class="mb-2.5 flex flex-wrap items-center justify-between gap-2">
              <p class="text-xs font-semibold text-white">交易成本设置（仅对本次回测生效）</p>
              <button type="button" class="text-xs text-indigo-300 hover:text-indigo-200" @click="resetExecFilterDefaults">恢复平台默认</button>
            </div>
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <FormField label="佣金率（万分之几，双边）" type="number" v-model="execForm.commission_wan" :min="0" :max="100" :step="0.5" hint="如 3 表示万三（0.03%）" />
              <FormField label="单笔最低佣金（元）" type="number" v-model="execForm.minimum_commission" :min="0" :max="100" :step="1" hint="A 股常见为 ¥5" />
              <FormField label="基础滑点（bps）" type="number" v-model="execForm.slippage_bps" :min="0" :max="200" :step="1" hint="5 bps = 0.05%（另叠加成交量冲击）" />
              <FormField label="固定印花税（万分之几，仅卖出）" type="number" v-model="execForm.stamp_tax_wan" :min="0" :max="100" :step="1" :disabled="execForm.historical_fees" hint="关闭历史分期税费时生效" />
            </div>
            <div class="mt-3">
              <FormField label="" type="checkbox" v-model="execForm.historical_fees" hint="按 A 股历史真实税费自动分期（2023-08-28 前卖出千一，之后卖出万五；过户费同步按历史分期）" />
            </div>
          </div>

          <div class="border-t border-white/10 pt-4">
            <p class="mb-2.5 text-xs font-semibold text-white">可交易性与股票过滤（仅对本次回测生效）</p>
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <div class="space-y-2.5">
                <FormField label="" type="checkbox" v-model="filterForm.exclude_st" hint="排除 ST / *ST 股票" />
                <FormField label="" type="checkbox" v-model="filterForm.exclude_suspended" hint="排除停牌股票" />
                <p class="text-xs text-slate-400">✓ 开盘一字涨停无法买入、开盘跌停无法卖出（引擎默认强制执行，不可关闭）</p>
              </div>
              <div>
                <FormField label="最少上市天数（交易日/自然日口径）" type="number" v-model="filterForm.minimum_listing_days" :min="0" :max="1000" :step="10" />
                <div class="mt-1.5 flex flex-wrap gap-2 text-xs">
                  <button type="button" class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-300 hover:bg-white/10" @click="filterForm.minimum_listing_days = 0">不限</button>
                  <button type="button" class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-300 hover:bg-white/10" @click="filterForm.minimum_listing_days = 60">60 天</button>
                  <button type="button" class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-300 hover:bg-white/10" @click="filterForm.minimum_listing_days = 250">250 天（约1年）</button>
                </div>
              </div>
              <div class="space-y-3">
                <FormField label="最少历史行情天数" type="number" v-model="filterForm.minimum_history_days" :min="0" :max="500" :step="10" />
                <FormField label="最低日均成交额（元，0 为不限）" type="number" v-model="filterForm.minimum_average_amount" :min="0" :step="1000000" />
              </div>
            </div>
          </div>
        </div>
      </details>
      <details :open="riskOpen" class="mt-3 rounded-xl border border-white/10 bg-white/5" @toggle="riskOpen = $event.target.open">
        <summary class="cursor-pointer px-4 py-3 text-sm text-slate-300">风险设置（含单一行业仓位上限） <span v-if="riskEditor?.dirty" class="text-amber-300">· 有未保存修改</span></summary>
        <div class="p-3 pt-0"><RiskSettings ref="riskEditor" :notify="notify" /></div>
      </details>
      <p v-if="runError" class="mt-4 text-sm text-rose-300">{{ runError }}</p>
      <div class="mt-5 flex flex-wrap items-center justify-end gap-3">
        <p v-if="running" class="text-xs text-slate-400" role="status">正在提交任务…</p>
        <button
          data-guide="backtest-run"
          @click="onSubmit"
          :disabled="running || catalogLoading || !selectedStrategy || !riskEditor?.ready"
          class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/40 transition hover:-translate-y-0.5 disabled:opacity-70"
        >
          {{ running ? '回测中…' : '运行回测' }}
        </button>
      </div>
    </SectionCard>

    <BacktestTasks :focus-job="routeContext.job" :refresh-key="tasksRefresh" @completed="taskCompleted" />

    <!-- 回测结果 -->
    <SectionCard title="回测结果" hint="一次回测的收益、风险、交易成本与持仓 · 基于历史数据，仅供研究参考">
      <template #actions>
        <button class="text-sm text-indigo-300 hover:text-indigo-200" @click="openResearch('run-library')">查看以前的回测 →</button>
      </template>

      <div v-if="detailLoading && !current" class="text-sm text-slate-400">加载中…</div>

      <EmptyState v-else-if="!current" text="运行回测后，结果显示在这里。以前的回测可以在「研究记录」里重新打开。" />

      <div v-else class="space-y-4">
        <!-- 元信息 -->
        <div class="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
          <span class="text-slate-400">策略</span>
          <span class="font-medium text-white">{{ shownStrategy }}</span>
          <span class="text-slate-400">股票范围</span>
          <span class="text-white">{{ marketLabel(current.market, markets) }}</span>
          <span class="text-slate-400">区间</span>
          <span class="text-white">{{ current.from_date }} ~ {{ current.to_date }}</span>
          <span class="text-slate-400">运行时间</span>
          <span class="text-white">{{ runTime(current.created_at) }}</span>
          <StatusPill :value="current.status || '—'" />
        </div>

        <!-- 子 Tab -->
        <div class="flex w-fit rounded-full border border-white/10 bg-white/5 p-0.5 text-xs">
          <button
            v-for="t in tabs"
            :key="t"
            @click="activeTab = t"
            class="rounded-full px-3 py-1 transition"
            :class="activeTab === t ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white' : 'text-slate-400 hover:text-slate-200'"
          >
            {{ t }}
          </button>
        </div>

        <div v-if="detailLoading" class="text-sm text-slate-400">加载中…</div>

        <div v-if="current" class="rounded-xl border border-amber-400/20 bg-white/5 p-4 text-xs text-slate-300">
          <p>数据状态：{{ validityLabel(result) }}；{{ result.metrics_reliable ? '指标可计算，请结合警告审阅' : '指标不可作为可信结论' }}</p>
          <p v-if="result.effective_config" class="mt-2">实际配置：{{ shownStrategy }} · ¥{{ Number(result.effective_config.initial_capital).toLocaleString() }} · 最多 {{ result.effective_config.max_positions }} 只 · {{ rebalances.find(r => r.value === result.effective_config.rebalance)?.label }}调仓 · {{ result.effective_config.from_date }} 至 {{ result.effective_config.to_date }}</p>
          <p v-if="resultExecutionSummary" class="mt-1.5">交易费率：{{ resultExecutionSummary }}</p>
          <p v-if="resultFilterSummary" class="mt-1.5">股票过滤：{{ resultFilterSummary }}</p>
          <p v-if="protectionSummary" class="mt-2">策略保护：{{ protectionSummary }}</p>
          <p v-if="result.pool?.name" class="mt-2">股票池：{{ poolLabel(result.pool) }}</p>
          <p v-if="result.pool?.snapshot_date && current.from_date < result.pool.snapshot_date" class="mt-1 text-amber-300">
            回测起点早于成分股名单快照，可能存在前视偏差。
          </p>
          <p v-for="(issue, index) in result.validity_issues || []" :key="index" class="mt-1 text-amber-300" :title="issue.code">{{ issue.message }}</p>
        </div>
        <!-- 概览 -->
        <div v-if="!detailLoading && activeTab === '概览'" class="space-y-4">
          <!-- 结论先行：收益 / 回撤 / 可信度评级 -->
          <section class="grid gap-5 sm:grid-cols-3">
            <MetricCard
              label="累计收益"
              :value="fmtPct(result.total_return)"
              :tone="num(result.total_return) === null || num(result.total_return) === 0 ? '' : num(result.total_return) > 0 ? 'text-rose-300' : 'text-emerald-300'"
            />
            <MetricCard label="最大回撤" :value="fmtPct(result.max_drawdown)" sub="资金曲线从峰值到谷底的最大跌幅" tone="text-emerald-300" />
            <MetricCard label="可信度评级" :value="gradeValue" :sub="gradeSub" :tone="gradeTone" />
          </section>
          <section class="grid gap-5 sm:grid-cols-2 xl:grid-cols-6">
            <MetricCard v-for="m in metrics" :key="m.label" :label="m.label" :value="m.value" :sub="m.sub" :tone="m.tone" />
          </section>
          <button
            @click="openAudit"
            class="rounded-full border border-indigo-400/40 bg-indigo-500/10 px-4 py-2 text-sm font-medium text-indigo-200 transition hover:bg-indigo-500/20"
          >
            查看完整可信度审计 →
          </button>
          <div class="flex flex-wrap gap-3 text-sm text-indigo-300">
            <button @click="openResearch('research', { baseline: `run-${selectedId}` })">参数验证 →</button>
            <button @click="openResearch('market-chart', { run: selectedId })">在K线上查看成交 →</button>
            <button
              v-if="paperPrefill(result.effective_config)"
              @click="openResearch('paper-accounts', {
                mode: 'new',
                strategy: result.effective_config.strategy_plugin === 'factor_composite' ? 'factor_composite' : result.effective_config.strategy_reference,
                run: selectedId,
              })"
            >用这套设置开模拟账户 →</button>
          </div>
          <BacktestHealthCard v-if="current.health_check" :health="current.health_check" />
          <!-- 第一次看到回测结果时问一句“有用吗” -->
          <UsefulPrompt feature="backtest-review" :context="{ run: selectedId }" />
          <BacktestAiReview :backtest-id="selectedId" :notify="notify" />
          <!-- 和基准比较：有完整的基准行情时显示两条累计收益曲线，否则只显示资金曲线。 -->
          <h3 v-if="benchmark" class="flex flex-wrap items-center gap-2 text-sm font-semibold text-white">
            <span>和</span>
            <select v-if="benchmarkOptions.length > 1" :value="benchmark.symbol" :disabled="benchmarkLoading" aria-label="基准指数"
              class="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm font-semibold text-white outline-none focus:border-indigo-400/40 disabled:opacity-60"
              @change="chooseBenchmark($event.target.value, true, $event.target)">
              <option v-for="item in benchmarkOptions" :key="item.value" :value="item.value" class="bg-ink">{{ item.label }}</option>
            </select>
            <span v-else>{{ benchmark.name }}</span>
            <span>比较</span>
          </h3>
          <section v-if="comparisonSeries.length" class="space-y-4" aria-label="和基准比较">
            <div class="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard v-for="card in comparisonCards" :key="card.label" :label="card.label" :value="card.value" :sub="card.sub" :tone="card.tone" />
            </div>
            <div class="rounded-xl border border-white/10 bg-white/5 p-4">
              <div class="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-400">
                <span>累计收益</span>
                <span v-for="line in comparisonSeries" :key="line.label" class="inline-flex items-center gap-1.5">
                  <span class="inline-block w-4 border-t-2" :style="{ borderColor: line.color, borderTopStyle: line.dashed ? 'dashed' : 'solid' }" />{{ line.label }} {{ line.end }}
                </span>
              </div>
              <LineChart class="mt-2" :series="comparisonSeries" :dates="result.nav_dates || []" unit="percent" :baseline="0" :height="260" :fill="false" />
            </div>
            <p class="text-xs text-slate-400">{{ comparisonNote }}</p>
          </section>
          <template v-else>
            <div class="rounded-xl border border-white/10 bg-white/5 p-4">
              <p class="text-xs text-slate-400">资金曲线</p>
              <LineChart class="mt-2" :series="equitySeries" :dates="result.nav_dates || []" unit="money" :baseline="Number(result.effective_config?.initial_capital) || null" :height="260" />
            </div>
            <p v-if="comparisonNote" class="text-xs text-slate-400">{{ comparisonNote }}</p>
          </template>

          <!-- 分年收益与换手 -->
          <div v-if="annualBreakdown?.rows?.length" class="rounded-xl border border-white/10 bg-white/5 p-4">
            <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h3 class="text-sm font-semibold text-white">分年收益与换手</h3>
              <span class="text-xs text-slate-400">
                全区间年化换手（单边）{{ result.annualized_turnover == null ? '—' : `${Number(result.annualized_turnover).toFixed(1)}%` }} · 后续年份以上年末收盘净值为基期，各年复利连乘等于总收益
              </span>
            </div>
            <DataTable :columns="annualCols" :rows="annualBreakdown.rows" empty="暂无分年数据">
              <template #cell-year="{ row }">
                <span class="font-medium text-white">{{ row.year }}</span>
                <span class="ml-1.5 text-[11px] text-slate-500">{{ row.start_date.slice(5) }}~{{ row.end_date.slice(5) }}</span>
              </template>
              <template #cell-return_pct="{ value }">
                <span class="font-semibold" :class="returnTone(value)">{{ signedPct(value) }}</span>
              </template>
              <template #cell-benchmark_return_pct="{ value }">
                <span :class="returnTone(value)">{{ signedPct(value) }}</span>
              </template>
              <template #cell-excess_return_pct="{ value }">
                <span class="font-medium" :class="returnTone(value)">{{ signedPct(value) }}</span>
              </template>
              <template #cell-max_drawdown_pct="{ value }">
                <span class="text-emerald-300">{{ value == null ? '—' : `${Number(value).toFixed(2)}%` }}</span>
              </template>
              <template #cell-turnover_pct="{ value }">
                <span class="tabular-nums text-slate-200">{{ value == null ? '—' : `${Number(value).toFixed(1)}%` }}</span>
              </template>
              <template #cell-fills="{ value }">{{ countText(value) }}</template>
            </DataTable>
          </div>
        </div>

        <!-- 交易与成本 -->
        <div v-else-if="activeTab === '交易与成本'" class="space-y-5">
          <section class="grid gap-5 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="总交易成本" :value="fmtMoney(totalCost)" :sub="costRatioPct" />
            <MetricCard label="佣金" :value="fmtMoney(result.commission)" />
            <MetricCard label="印花税" :value="fmtMoney(result.stamp_tax)" />
            <MetricCard label="滑点与冲击" :value="fmtMoney(result.slippage_cost)" />
            <MetricCard label="年化换手" :value="result.annualized_turnover == null ? '—' : `${Number(result.annualized_turnover).toFixed(1)}%`" sub="单边年化" />
          </section>
          <div class="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-xs text-slate-300">
            <span>订单数：<strong class="text-white">{{ countText(result.orders) }}</strong></span>
            <span>成交笔数：<strong class="text-white">{{ countText(result.fills) }}</strong></span>
            <span>日胜率：<strong :class="num(result.win_rate) === null ? 'text-white' : num(result.win_rate) >= 50 ? 'text-rose-300' : 'text-emerald-300'">{{ fmtPct(result.win_rate) }}</strong></span>
            <span v-if="resultExecutionSummary" class="text-slate-400">采用费率：{{ resultExecutionSummary }}</span>
          </div>
          <div>
            <p class="mb-3 text-xs text-slate-400">交易明细</p>
            <DataTable :columns="tradeCols" :rows="current.trades || []" empty="暂无交易记录">
              <template #cell-reason_label="{ row, value }">
                <span :class="tradeReasonClass(row.reason)">{{ value || '—' }}</span>
              </template>
            </DataTable>
          </div>
        </div>

        <!-- 持仓分析 -->
        <div v-else-if="activeTab === '持仓分析'">
          <p class="mb-3 text-xs text-slate-400">当前持仓</p>
          <EmptyState v-if="!(current.positions || []).length" text="暂无持仓" />
          <DataTable v-else :columns="positionCols" :rows="current.positions" empty="暂无持仓">
            <template #cell-pnl="{ value }"><span :class="returnTone(value)">{{ value }}</span></template>
          </DataTable>
        </div>
      </div>
    </SectionCard>
    <details class="glass rounded-2xl p-5">
      <summary class="cursor-pointer text-sm font-semibold text-slate-300">高级工具</summary>
      <div class="mt-4 flex flex-wrap gap-3">
        <button class="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5" @click="openResearch('strategy-forensics', { run: selectedId || '' })">成交核查</button>
      </div>
    </details>
  </div>
</template>
