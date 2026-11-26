<script setup>
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { advancePaperAccount, createPaperAccount, deletePaperAccount, getBacktest, getBacktestCatalog, getPaperAccount, getPaperBacktestReference, listPackages, paperAccounts } from '../../api.js'
import { REBALANCE_OPTIONS } from '../preferences.js'
import { openResearch } from '../researchNavigation.js'
import { benchmarkCards, benchmarkNote, benchmarkSeries } from '../benchmarkPresentation.js'
import { CURRENT_POOL, marketChoices, marketLabel, usableMarket } from '../marketPresentation.js'
import { accountsLeft, checkMark, checkTone, nextRebalanceLabel, paperPrefill, parseFactorRows, returnText, returnTone, statusLabel, statusNote, statusTone } from '../paperPresentation.js'
import { takeFactorPaperDraft } from '../factorBacktestDraft.js'
import { tradeReasonClass } from '../ruleForm.js'
import SectionCard from '../ui/SectionCard.vue'
import FormField from '../ui/FormField.vue'
import FactorCompositeEditor from '../ui/FactorCompositeEditor.vue'
import MetricCard from '../ui/MetricCard.vue'
import LineChart from '../ui/LineChart.vue'
import DataTable from '../ui/DataTable.vue'
import EmptyState from '../ui/EmptyState.vue'

const props = defineProps({
  routeContext: { type: Object, default: () => ({}) },
  user: { type: Object, default: null },
  notify: { type: Function, default: () => {} },
})

const rebalances = REBALANCE_OPTIONS
const rebalanceLabel = (value) => rebalances.find((item) => item.value === value)?.label || value || ''

// ---------- 列表 ----------
const accounts = ref([])
const limit = ref(null)
const today = ref('')
const listLoading = ref(false)
const left = computed(() => accountsLeft(accounts.value.length, limit.value))

async function loadList() {
  listLoading.value = true
  try {
    const data = await paperAccounts()
    accounts.value = data.items || []
    limit.value = data.limit ?? null
    today.value = data.today || ''
  } catch (e) {
    props.notify(e.message || '读取模拟账户失败')
  } finally {
    listLoading.value = false
  }
}

// ---------- 新建 ----------
const STRATEGY_KINDS = [
  { value: 'rule_builder', label: '规则策略' },
  { value: 'factor_composite', label: '多因子合成' },
]
const packages = ref([])
const markets = ref([])
const marketOptions = computed(() => marketChoices(markets.value).map(option => {
  const entry = markets.value.find(item => item.value === option.value)
  return entry?.available && entry.usable_through && today.value > entry.usable_through
    ? { ...option, label: `${option.label}（成分股待更新）`, disabled: true }
    : option
}))
const form = reactive({
  strategy_kind: 'rule_builder',
  package_id: '',
  factors_json: '[]',
  name: '',
  market: CURRENT_POOL,
  initial_cash: 1000000,
  top_n: 10,
  rebalance: 'weekly',
})
const selectedMarket = computed(() => markets.value.find(item => item.value === form.market))
const selectedPackage = computed(() => packages.value.find(item => item.package_id === form.package_id))
const factorRows = computed(() => parseFactorRows(form.factors_json))
const canCreate = computed(() => {
  if (creating.value || prefillLoading.value || !marketAvailable(form.market) || left.value <= 0) return false
  return form.strategy_kind === 'factor_composite' ? factorRows.value.length > 0 : Boolean(selectedPackage.value)
})
const latestBacktest = ref(null)
const referenceBacktest = ref(null)
const referenceLoading = ref(false)
const referenceError = ref('')
const prefillLoading = ref(false)
let selection = 0
let appliedRoute = ''
const referenceSettings = computed(() => paperPrefill(referenceBacktest.value?.config))
const marketAvailable = (value) => marketOptions.value.some(option => option.value === value && !option.disabled)
const settingFields = [
  { key: 'top_n', label: '最多持股', format: value => `${value} 只` },
  { key: 'rebalance', label: '调仓频率', format: rebalanceLabel },
  { key: 'market', label: '股票范围', format: value => marketLabel(value, markets.value) },
  { key: 'initial_cash', label: '初始资金', format: value => money(value) },
]
const differences = computed(() => settingFields.filter(({ key }) =>
  referenceSettings.value?.[key] != null && String(form[key]) !== String(referenceSettings.value[key])))
const creating = ref(false)
const createSection = ref(null)
// 把新建表单滚到眼前：从别的页面带着策略过来、或点了空列表里的按钮时。
function showCreate() {
  createSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const packageOptions = computed(() => [
  { value: '', label: packages.value.length ? '请选择策略' : '还没有规则策略' },
  ...packages.value.map((item) => ({ value: item.package_id, label: item.name })),
])

function chooseStrategyKind(kind) {
  if (form.strategy_kind === kind) return selection
  const version = ++selection
  form.strategy_kind = kind
  latestBacktest.value = null
  referenceBacktest.value = null
  referenceError.value = ''
  prefillLoading.value = false
  if (kind === 'factor_composite') {
    referenceLoading.value = true
    loadBacktestReference('factor_composite', version)
  } else if (selectedPackage.value) {
    referenceLoading.value = true
    loadBacktestReference(form.package_id, version)
  } else {
    referenceLoading.value = false
  }
  return version
}

function choosePackage(id) {
  const version = ++selection
  form.strategy_kind = 'rule_builder'
  form.package_id = id
  const item = selectedPackage.value
  if (item) Object.assign(form, { top_n: item.top_n, rebalance: item.rebalance })
  latestBacktest.value = null
  referenceBacktest.value = null
  referenceError.value = ''
  prefillLoading.value = false
  referenceLoading.value = !!item
  if (item) loadBacktestReference(id, version)
  return version
}

async function loadBacktestReference(id, version) {
  try {
    const { backtest } = await getPaperBacktestReference(id)
    if (version !== selection) return
    latestBacktest.value = backtest
    referenceBacktest.value ??= backtest
  } catch {
    if (version === selection) referenceError.value = '最近一次回测设置加载失败。'
  } finally {
    if (version === selection) referenceLoading.value = false
  }
}

function applyBacktestSettings(backtest) {
  const settings = paperPrefill(backtest?.config)
  if (!settings || settings.strategy_kind !== form.strategy_kind) return
  if (settings.strategy_kind === 'rule_builder' && settings.package_id !== form.package_id) return
  const { strategy_kind, package_id, market, top_n, ...parameters } = settings
  referenceBacktest.value = backtest
  Object.assign(form, parameters)
  if (top_n != null) form.top_n = Math.min(50, Math.max(1, Number(top_n)))
  if (market && marketAvailable(market)) form.market = market
}

function backtestSummary(backtest) {
  const settings = paperPrefill(backtest?.config)
  const items = settingFields.filter(({ key }) => settings?.[key] != null)
    .map(({ label, key, format }) => `${label} ${format(settings[key])}`)
  if (settings?.strategy_kind === 'factor_composite') {
    const count = parseFactorRows(settings.factors_json).length
    if (count) items.unshift(`${count} 个因子`)
  }
  return items.join(' · ')
}

function backtestTime(backtest) {
  const date = new Date(backtest.created_at)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN')
}

async function loadOptions() {
  try {
    const [catalog, saved] = await Promise.all([getBacktestCatalog(), listPackages()])
    markets.value = catalog.markets || []
    packages.value = saved.items || []
    form.market = usableMarket(form.market, markets.value)
  } catch (e) {
    props.notify(e.message || '读取策略失败')
  }
}

// 从回测结果页或因子研究页过来：带上策略/因子组合和设置。
async function applyPrefill() {
  if (props.routeContext.mode !== 'new') { appliedRoute = ''; return }
  const reference = String(props.routeContext.strategy || '')
  if (reference === 'factor_composite') {
    const draft = takeFactorPaperDraft()
    if (draft?.factors?.length) {
      const version = ++selection
      form.strategy_kind = 'factor_composite'
      form.factors_json = JSON.stringify(draft.factors)
      if (draft.market && marketAvailable(draft.market)) form.market = draft.market
      latestBacktest.value = null
      referenceBacktest.value = null
      referenceError.value = ''
      prefillLoading.value = false
      referenceLoading.value = true
      loadBacktestReference('factor_composite', version)
      appliedRoute = 'factor_composite/draft'
      showCreate()
      return
    }
    const run = String(props.routeContext.run || '').replace(/^run-/, '')
    const route = `factor_composite/${run}`
    if (appliedRoute === route) return
    appliedRoute = route
    const version = ++selection
    form.strategy_kind = 'factor_composite'
    latestBacktest.value = null
    referenceBacktest.value = null
    referenceError.value = ''
    referenceLoading.value = true
    loadBacktestReference('factor_composite', version)
    showCreate()
    if (!run) return
    prefillLoading.value = true
    try {
      const backtest = await getBacktest(run)
      if (version === selection && props.routeContext.mode === 'new')
        applyBacktestSettings({ id: backtest.id, created_at: backtest.created_at, config: backtest.result?.effective_config })
    } catch {
      if (version === selection) props.notify('这次回测设置加载失败，请手动配置因子组合。')
    } finally {
      if (version === selection) prefillLoading.value = false
    }
    return
  }

  const packageId = reference.startsWith('package:') ? reference.slice('package:'.length) : ''
  if (!packages.value.some(item => item.package_id === packageId)) return
  const run = String(props.routeContext.run || '').replace(/^run-/, '')
  const route = `${packageId}/${run}`
  if (appliedRoute === route) return
  appliedRoute = route
  const version = choosePackage(packageId)
  showCreate()
  if (!run) return
  prefillLoading.value = true
  try {
    const backtest = await getBacktest(run)
    if (version === selection && props.routeContext.mode === 'new')
      applyBacktestSettings({ id: backtest.id, created_at: backtest.created_at, config: backtest.result?.effective_config })
  } catch {
    if (version === selection) props.notify('这次回测设置加载失败，表单使用策略保存值。')
  } finally {
    if (version === selection) prefillLoading.value = false
  }
}

async function onCreate() {
  if (!canCreate.value) return
  creating.value = true
  try {
    const payload = form.strategy_kind === 'factor_composite'
      ? {
          strategy_kind: 'factor_composite',
          factors_json: form.factors_json,
          name: form.name.trim(),
          market: form.market,
          initial_cash: Number(form.initial_cash),
          top_n: Number(form.top_n),
          rebalance: form.rebalance,
        }
      : {
          strategy_kind: 'rule_builder',
          package_id: form.package_id,
          name: form.name.trim(),
          market: form.market,
          initial_cash: Number(form.initial_cash),
          top_n: Number(form.top_n),
          rebalance: form.rebalance,
        }
    const account = await createPaperAccount(payload)
    props.notify('模拟账户已创建')
    form.name = ''
    await loadList()
    openResearch('paper-accounts', { account: account.account_id })
  } catch (e) {
    props.notify(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

// ---------- 详情 ----------
const current = ref(null)
const detailLoading = ref(false)
// 只有读失败时才说“没有找到”；还没读完时显示“加载中”。
const missing = ref(false)
const advancing = ref(false)
const tab = ref('持仓')
const result = computed(() => current.value?.result || {})
const note = computed(() => statusNote(current.value))
const comparisonCards = computed(() => benchmarkCards(current.value?.benchmark))
const comparisonSeries = computed(() => benchmarkSeries(current.value?.benchmark))
const comparisonNote = computed(() => benchmarkNote(current.value?.benchmark))
const equitySeries = computed(() => [{ label: '资金曲线', color: 'var(--fq-chart-strategy)', points: Array.isArray(result.value.equity) ? result.value.equity : [] }])
const tradingDays = computed(() => (Array.isArray(result.value.equity) ? result.value.equity.length : 0))
const money = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`)
const pct = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : `${Number(v).toFixed(2)}%`)

const tradeCols = [
  { key: 'date', label: '成交日' },
  { key: 'symbol', label: '代码' },
  { key: 'side', label: '方向' },
  { key: 'quantity', label: '数量', align: 'right' },
  { key: 'price', label: '价格', align: 'right' },
  { key: 'amount', label: '金额', align: 'right' },
  { key: 'fee', label: '手续费', align: 'right' },
  { key: 'reason_label', label: '说明' },
]
const positionCols = [
  { key: 'symbol', label: '代码' },
  { key: 'name', label: '名称' },
  { key: 'quantity', label: '数量', align: 'right' },
  { key: 'avg_price', label: '持仓均价', align: 'right' },
  { key: 'price', label: '收盘价', align: 'right' },
  { key: 'market_value', label: '市值', align: 'right' },
  { key: 'pnl', label: '盈亏', align: 'right' },
]
// 成交按时间倒序：最近的在最上面。
const trades = computed(() => [...(current.value?.trades || [])].reverse())

async function loadDetail() {
  const id = props.routeContext.account
  missing.value = false
  if (!id) { current.value = null; return }
  if (current.value?.account_id !== id) current.value = null
  detailLoading.value = true
  try {
    current.value = await getPaperAccount(id)
  } catch (e) {
    current.value = null
    missing.value = true
    props.notify(e.message || '读取模拟账户失败')
  } finally {
    detailLoading.value = false
  }
}

async function onAdvance() {
  if (!current.value) return
  advancing.value = true
  try {
    current.value = await advancePaperAccount(current.value.account_id)
    props.notify(current.value.status === 'FAILED' ? '推进没有完成，原因写在状态下面' : '已推进到最新一天')
    await loadList()
  } catch (e) {
    props.notify(e.message || '推进失败')
  } finally {
    advancing.value = false
  }
}

async function onDelete() {
  if (!current.value || !confirm(`删除模拟账户「${current.value.display_name}」？结果会一起删除，不能恢复。`)) return
  try {
    await deletePaperAccount(current.value.account_id)
    props.notify('模拟账户已删除')
    current.value = null
    await loadList()
    openResearch('paper-accounts')
  } catch (e) {
    props.notify(e.message || '删除失败')
  }
}

watch(() => props.routeContext.account, loadDetail)
watch(() => [props.routeContext.mode, props.routeContext.strategy, props.routeContext.run, props.routeContext.source], applyPrefill)
onActivated(async () => {
  await Promise.all([loadList(), loadOptions()])
  await applyPrefill()
  await loadDetail()
})
</script>

<template>
  <div class="space-y-6">
    <div class="glass glass-sheen rounded-2xl p-6">
      <h1 class="text-xl font-bold text-white">模拟账户</h1>
      <p class="mt-2 text-sm text-slate-400">
        固定一套规则策略或多因子合成组合，从今天开始，每个交易日收盘数据更新后自动推进到最新一天。只显示已经成交的记录和收盘持仓，按你设定的规则计算，不是投资建议。
      </p>
    </div>

    <!-- 详情 -->
    <SectionCard v-if="routeContext.account" :title="current?.display_name || '模拟账户'" hint="创建时锁住的策略和设置 · 每个交易日自动推进">
      <template #actions>
        <button class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/40 transition hover:-translate-y-0.5" @click="openResearch('paper-accounts')">← 全部模拟账户</button>
      </template>
      <EmptyState v-if="missing" text="没有找到这个模拟账户，可能已经删除。" />
      <div v-else-if="!current" class="text-sm text-slate-400">加载中…</div>
      <div v-else class="space-y-5">
        <div class="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
          <span class="inline-flex rounded-full border px-2.5 py-0.5 text-xs" :class="statusTone(current.status)">{{ statusLabel(current.status) }}</span>
          <span v-if="current.strategy_kind === 'factor_composite'" class="inline-flex rounded-full border border-indigo-400/30 bg-indigo-500/10 px-2.5 py-0.5 text-xs text-indigo-200">多因子合成</span>
          <span class="whitespace-nowrap"><span class="text-slate-400">策略 </span><span class="text-white">{{ current.strategy_name }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">股票范围 </span><span class="text-white">{{ current.market_label }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">开始 </span><span class="text-white">{{ current.start_date }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">初始资金 </span><span class="text-white">{{ money(current.initial_cash) }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">持股 </span><span class="text-white">最多 {{ current.top_n }} 只 · {{ rebalanceLabel(current.rebalance) }}调仓</span></span>
          <span v-if="nextRebalanceLabel(current)" class="whitespace-nowrap"><span class="text-slate-400">下次调仓 </span><span class="text-indigo-200">{{ nextRebalanceLabel(current) }}</span></span>
        </div>
        <p v-if="note" class="text-sm" :class="current.status === 'FAILED' ? 'text-rose-300' : 'text-slate-300'">{{ note }}</p>
        <div v-if="current.describe_text || current.factors?.length" class="space-y-2">
          <p v-if="current.describe_text" class="text-xs text-slate-400">
            {{ current.strategy_kind === 'factor_composite' ? '锁住的因子组合：' : '锁住的规则：' }}{{ current.describe_text }}
          </p>
          <div v-if="current.factors?.length" class="flex flex-wrap gap-2">
            <span
              v-for="f in current.factors"
              :key="f.name"
              :title="f.expression || f.name"
              class="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300"
            >
              <span class="font-medium text-white">{{ f.display_name || f.name }}</span>
              <span :class="f.direction === -1 ? 'text-amber-300' : 'text-emerald-300'">{{ f.direction === -1 ? '反向' : '正向' }}</span>
              <span class="text-slate-400">× {{ f.weight }}</span>
              <span v-if="f.has_custom_factor" class="text-indigo-300">· 自定义</span>
            </span>
          </div>
        </div>

        <div>
          <div class="flex flex-wrap gap-3">
            <button :disabled="advancing" class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/40 transition hover:-translate-y-0.5 disabled:opacity-70" aria-describedby="paper-advance-help" @click="onAdvance">
              {{ advancing ? '推进中…' : '马上推进' }}
            </button>
            <button v-if="current.result?.run_id" class="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-200 hover:bg-white/5" @click="openResearch('market-chart', { run: `paper-${current.account_id}` })">在K线上查看成交</button>
            <button class="rounded-full border border-rose-400/30 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10" @click="onDelete">删除</button>
          </div>
          <!-- 后台本来就会自动推进，这里说明按钮只是“不用等” -->
          <p id="paper-advance-help" class="mt-2 text-xs text-slate-400">
            「马上推进」：后台每 5 分钟会自动检查新行情并推进。点它就不用等，现在就重算到本地行情的最新一天；设置不会变，也不会算到还没有数据的日子。推进失败时，补好数据后可以点它重试。
          </p>
        </div>

        <!-- 检查 -->
        <ul class="space-y-1.5 rounded-xl border border-white/10 bg-white/5 p-4 text-sm" aria-label="账户检查">
          <li v-for="item in current.checks" :key="item.title" class="flex gap-2">
            <span class="w-4 shrink-0 text-center font-bold" :class="checkTone(item.severity)">{{ checkMark(item.severity) }}</span>
            <span><span class="font-medium text-white">{{ item.title }}</span><span class="text-slate-300">：{{ item.detail }}</span></span>
          </li>
        </ul>

        <template v-if="current.result?.run_id">
          <section class="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="累计收益" :value="pct(result.total_return)" :tone="returnTone(result.total_return)" />
            <MetricCard label="最大回撤" :value="pct(result.max_drawdown)" tone="text-emerald-300" />
            <MetricCard label="当前权益" :value="money(result.final_equity)" :sub="`截至 ${current.last_date}`" />
            <MetricCard label="运行交易日" :value="String(tradingDays)" :sub="`交易成本 ${money(result.total_cost)}`" />
          </section>

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

          <div class="flex w-fit rounded-full border border-white/10 bg-white/5 p-0.5 text-xs">
            <button v-for="t in ['持仓', '成交记录']" :key="t" class="rounded-full px-3 py-1 transition"
              :class="tab === t ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white' : 'text-slate-400 hover:text-slate-200'" @click="tab = t">{{ t }}</button>
          </div>
          <div v-if="tab === '持仓'">
            <p class="mb-3 text-xs text-slate-400">{{ current.last_date }} 收盘时的持仓</p>
            <DataTable :columns="positionCols" :rows="current.positions || []" empty="收盘时没有持仓">
              <template #cell-pnl="{ value }"><span :class="returnTone(value)">{{ value }}</span></template>
            </DataTable>
          </div>
          <div v-else>
            <p class="mb-3 text-xs text-slate-400">已经成交的记录（共 {{ current.trades.length }} 笔，最近的在上面）</p>
            <DataTable :columns="tradeCols" :rows="trades" empty="还没有成交">
              <template #cell-reason_label="{ row, value }">
                <span :class="tradeReasonClass(row.reason)">{{ value || '—' }}</span>
              </template>
            </DataTable>
          </div>
        </template>
      </div>
    </SectionCard>

    <!-- 列表 -->
    <SectionCard title="我的模拟账户" :hint="limit === null ? '数量不限' : `每人最多 ${limit} 个，还能建 ${left} 个`">
      <div v-if="listLoading && !accounts.length" class="text-sm text-slate-400">加载中…</div>
      <div v-else-if="!accounts.length" class="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-400">
        <p>还没有模拟账户。选一个规则策略，或配一组多因子合成组合，就能从今天开始跟踪。</p>
        <button class="mt-4 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5"
          @click="showCreate()">新建模拟账户</button>
      </div>
      <div v-else class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <button v-for="item in accounts" :key="item.account_id" type="button"
          class="rounded-xl border bg-white/5 p-4 text-left transition hover:bg-white/10"
          :class="item.account_id === routeContext.account ? 'border-indigo-400/50' : 'border-white/10'"
          @click="openResearch('paper-accounts', { account: item.account_id })">
          <div class="flex items-start justify-between gap-3">
            <span class="font-medium text-white">{{ item.display_name }}</span>
            <span class="inline-flex shrink-0 rounded-full border px-2 py-0.5 text-xs" :class="statusTone(item.status)">{{ statusLabel(item.status) }}</span>
          </div>
          <p class="mt-1 text-xs text-slate-400">{{ item.strategy_name }} · {{ item.market_label }}</p>
          <div class="mt-3 flex items-end justify-between">
            <span class="text-xs text-slate-400">{{ item.start_date }} 开始<template v-if="item.last_date"> · 推进到 {{ item.last_date }}</template></span>
            <span class="text-lg font-semibold" :class="returnTone(item.total_return)">{{ returnText(item.total_return) }}</span>
          </div>
        </button>
      </div>
    </SectionCard>

    <!-- 新建 -->
    <div ref="createSection">
    <SectionCard title="新建模拟账户" :hint="`开始日期：今天（${today || '—'}），不能选以前的日期`">
      <div class="mb-5 flex flex-wrap items-center gap-3">
        <div class="inline-flex rounded-full border border-white/10 bg-white/5 p-1" role="tablist" aria-label="策略类型">
          <button
            v-for="item in STRATEGY_KINDS"
            :key="item.value"
            type="button"
            role="tab"
            :aria-selected="form.strategy_kind === item.value"
            class="rounded-full px-4 py-1.5 text-sm font-medium transition"
            :class="form.strategy_kind === item.value ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'"
            @click="chooseStrategyKind(item.value)"
          >{{ item.label }}</button>
        </div>
        <span class="text-xs text-slate-400">
          {{ form.strategy_kind === 'factor_composite' ? '按多因子权重每日截面打分选股，支持正向/反向与自定义因子' : '使用策略创建页保存的规则策略' }}
        </span>
      </div>

      <div v-if="form.strategy_kind === 'rule_builder' && !packages.length" class="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-400">
        <p>你还没有规则策略。可以从模板开始，一两分钟就能建好；也可以切换到上方「多因子合成」直接用因子组合开模拟账户。</p>
        <div class="mt-4 flex flex-wrap justify-center gap-3">
          <button data-guide="paper-create" class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5" @click="openResearch('strategy-studio')">去新建规则策略</button>
          <button type="button" class="rounded-full border border-white/10 bg-white/5 px-5 py-2 text-sm text-slate-200 transition hover:bg-white/10" @click="chooseStrategyKind('factor_composite')">改用多因子合成 →</button>
        </div>
      </div>
      <template v-else>
        <div v-if="form.strategy_kind === 'factor_composite'" class="mb-4">
          <FactorCompositeEditor v-model="form.factors_json" :disabled="prefillLoading" />
        </div>
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <FormField v-if="form.strategy_kind === 'rule_builder'" label="规则策略" type="select" :model-value="form.package_id" :options="packageOptions" @update:model-value="choosePackage" />
          <FormField label="股票范围" type="select" v-model="form.market" :options="marketOptions" :disabled="prefillLoading" />
          <FormField label="名称（可不填）" v-model="form.name" placeholder="默认用策略名和日期" />
          <FormField label="初始资金" type="number" v-model="form.initial_cash" :min="10000" :step="10000" :disabled="prefillLoading" />
          <FormField label="最多持股" type="number" v-model="form.top_n" :min="1" :max="50" :step="1" :disabled="prefillLoading" />
          <FormField label="调仓频率" type="select" v-model="form.rebalance" :options="rebalances" :disabled="prefillLoading" />
        </div>
        <div v-if="selectedPackage || form.strategy_kind === 'factor_composite'" class="mt-4 space-y-2 rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300" aria-live="polite">
          <p v-if="selectedPackage && form.strategy_kind === 'rule_builder'">策略保存值 · 最多持股 {{ selectedPackage.top_n }} 只 · {{ rebalanceLabel(selectedPackage.rebalance) }}调仓</p>
          <p v-else-if="form.strategy_kind === 'factor_composite'">当前配置 · 已选 {{ factorRows.length }} 个因子 · 最多持股 {{ form.top_n }} 只 · {{ rebalanceLabel(form.rebalance) }}调仓</p>
          <p v-if="referenceLoading">正在加载最近一次回测…</p>
          <p v-else-if="referenceError">{{ referenceError }}</p>
          <div v-else-if="latestBacktest" class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p>最近一次{{ form.strategy_kind === 'factor_composite' ? '因子合成' : '' }}回测 · {{ backtestTime(latestBacktest) }} · {{ backtestSummary(latestBacktest) }}</p>
            <button type="button" class="text-indigo-300 hover:text-indigo-200 disabled:opacity-60" :disabled="prefillLoading" @click="applyBacktestSettings(latestBacktest)">使用这次回测设置</button>
          </div>
          <p v-else>暂无可对照的回测。</p>
          <p v-if="referenceBacktest && referenceBacktest.id !== latestBacktest?.id">
            带入的回测 · {{ backtestTime(referenceBacktest) }} · {{ backtestSummary(referenceBacktest) }}
          </p>
          <p v-if="referenceSettings?.market && !marketAvailable(referenceSettings.market)" class="text-amber-200">
            回测使用的股票范围当前不可选，请核对表单里的股票范围。
          </p>
          <ul v-if="differences.length" class="space-y-1 text-amber-200">
            <li v-for="{ key, label, format } in differences" :key="key">与回测设置不同 · {{ label }} {{ format(form[key]) }}，回测为 {{ format(referenceSettings[key]) }}</li>
          </ul>
        </div>
        <div v-if="selectedMarket?.start_date" class="mt-3 space-y-1 text-xs text-slate-400">
          <p>每个调仓日只在当天的指数成分股里选股。历史名单从 {{ selectedMarket.start_date }} 开始，核对到 {{ selectedMarket.end_date }}。</p>
          <p v-for="period in selectedMarket.partial_membership" :key="period.start_date" class="text-amber-200">
            {{ period.start_date }} 至 {{ period.end_date }} 的本地记录有 {{ period.count }} 只成分股。
          </p>
        </div>
        <p class="mt-3 text-xs text-slate-400">
          开户首个交易日收盘即按规则建仓、下一交易日开盘成交，之后按所选调仓频率（每周末/每月末/每季末最后交易日）定期调仓，避免月中或季中开户长时间空仓。创建时会把{{ form.strategy_kind === 'factor_composite' ? '因子组合快照（含自定义因子定义）' : '策略规则' }}、股票范围（选股票池时是现在的股票池）和现在的风控设置复制一份锁住，以后修改它们都不影响这个账户。风控可以先在「策略回测」页的风险设置里改好。
        </p>
        <div class="mt-5 flex justify-end">
          <button data-guide="paper-create" :disabled="!canCreate"
            class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/40 transition hover:-translate-y-0.5 disabled:opacity-70"
            @click="onCreate">
            {{ creating ? '创建中…' : left <= 0 ? '已达到数量上限' : '创建模拟账户' }}
          </button>
        </div>
      </template>
    </SectionCard>
    </div>
  </div>
</template>
