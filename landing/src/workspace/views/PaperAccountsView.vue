<script setup>
import { computed, onActivated, reactive, ref, watch } from 'vue'
import { advancePaperAccount, createPaperAccount, deletePaperAccount, getBacktest, getBacktestCatalog, getPaperAccount, listPackages, paperAccounts } from '../../api.js'
import { REBALANCE_OPTIONS } from '../preferences.js'
import { openResearch } from '../researchNavigation.js'
import { benchmarkCards, benchmarkNote, benchmarkSeries } from '../benchmarkPresentation.js'
import { CURRENT_POOL, marketChoices, usableMarket } from '../marketPresentation.js'
import { accountsLeft, checkMark, checkTone, paperPrefill, returnText, returnTone, statusLabel, statusNote, statusTone } from '../paperPresentation.js'
import SectionCard from '../ui/SectionCard.vue'
import FormField from '../ui/FormField.vue'
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
const packages = ref([])
const markets = ref([])
const marketOptions = computed(() => marketChoices(markets.value))
const form = reactive({ package_id: '', name: '', market: CURRENT_POOL, initial_cash: 1000000, top_n: 10, rebalance: 'weekly' })
// 指数：每个调仓日只在当天的成分股里选（回测页的“开始日期不能早于…”这里用不到，开始日期总是今天）。
const formMarketNote = computed(() => (form.market === CURRENT_POOL ? '' : '每个调仓日只在当天的指数成分股里选股。'))
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

function choosePackage() {
  const item = packages.value.find((p) => p.package_id === form.package_id)
  if (item) Object.assign(form, { top_n: item.top_n, rebalance: item.rebalance })
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

// 从回测结果页过来：带上那次回测的策略和设置。
async function applyPrefill() {
  if (props.routeContext.mode !== 'new') return
  const reference = String(props.routeContext.strategy || '')
  if (reference.startsWith('package:')) {
    form.package_id = reference.slice('package:'.length)
    choosePackage()
  }
  showCreate()
  if (!props.routeContext.run) return
  try {
    const backtest = await getBacktest(String(props.routeContext.run).replace(/^run-/, ''))
    const prefill = paperPrefill(backtest.result?.effective_config)
    if (prefill) Object.assign(form, prefill, { market: usableMarket(prefill.market || form.market, markets.value) })
  } catch { /* 读不到那次回测就用策略自己的设置 */ }
}

async function onCreate() {
  if (!form.package_id) return props.notify('请选择一个规则策略')
  creating.value = true
  try {
    const account = await createPaperAccount({
      package_id: form.package_id,
      name: form.name.trim(),
      market: form.market,
      initial_cash: Number(form.initial_cash),
      top_n: Number(form.top_n),
      rebalance: form.rebalance,
    })
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
watch(() => [props.routeContext.mode, props.routeContext.strategy, props.routeContext.run], applyPrefill)
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
        固定一套规则策略，从今天开始，每个交易日收盘数据更新后自动推进到最新一天。只显示已经成交的记录和收盘持仓，按你设定的规则计算，不是投资建议。
      </p>
    </div>

    <!-- 详情 -->
    <SectionCard v-if="routeContext.account" :title="current?.display_name || '模拟账户'" hint="创建时锁住的规则和设置 · 每个交易日自动推进">
      <template #actions>
        <button class="text-sm text-indigo-300 hover:text-indigo-200" @click="openResearch('paper-accounts')">← 全部模拟账户</button>
      </template>
      <EmptyState v-if="missing" text="没有找到这个模拟账户，可能已经删除。" />
      <div v-else-if="!current" class="text-sm text-slate-400">加载中…</div>
      <div v-else class="space-y-5">
        <div class="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
          <span class="inline-flex rounded-full border px-2.5 py-0.5 text-xs" :class="statusTone(current.status)">{{ statusLabel(current.status) }}</span>
          <span class="whitespace-nowrap"><span class="text-slate-400">策略 </span><span class="text-white">{{ current.strategy_name }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">股票范围 </span><span class="text-white">{{ current.market_label }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">开始 </span><span class="text-white">{{ current.start_date }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">初始资金 </span><span class="text-white">{{ money(current.initial_cash) }}</span></span>
          <span class="whitespace-nowrap"><span class="text-slate-400">持股 </span><span class="text-white">最多 {{ current.top_n }} 只 · {{ rebalanceLabel(current.rebalance) }}调仓</span></span>
        </div>
        <p v-if="note" class="text-sm" :class="current.status === 'FAILED' ? 'text-rose-300' : 'text-slate-300'">{{ note }}</p>
        <p v-if="current.describe_text" class="text-xs text-slate-400">锁住的规则：{{ current.describe_text }}</p>

        <div class="flex flex-wrap gap-3">
          <button :disabled="advancing" class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/40 transition hover:-translate-y-0.5 disabled:opacity-70" @click="onAdvance">
            {{ advancing ? '推进中…' : '马上推进' }}
          </button>
          <button v-if="current.result?.run_id" class="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-200 hover:bg-white/5" @click="openResearch('market-chart', { run: `paper-${current.account_id}` })">在K线上查看成交</button>
          <button class="rounded-full border border-rose-400/30 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10" @click="onDelete">删除</button>
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
            <DataTable :columns="tradeCols" :rows="trades" empty="还没有成交" />
          </div>
        </template>
      </div>
    </SectionCard>

    <!-- 列表 -->
    <SectionCard title="我的模拟账户" :hint="limit === null ? '数量不限' : `每人最多 ${limit} 个，还能建 ${left} 个`">
      <div v-if="listLoading && !accounts.length" class="text-sm text-slate-400">加载中…</div>
      <div v-else-if="!accounts.length" class="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-400">
        <p>还没有模拟账户。选一个规则策略，就能从今天开始跟踪。</p>
        <button class="mt-4 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5"
          @click="packages.length ? showCreate() : openResearch('strategy-studio')">{{ packages.length ? '新建模拟账户' : '先新建一个规则策略' }}</button>
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
      <div v-if="!packages.length" class="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-400">
        <p>模拟账户使用规则策略，你还没有规则策略。可以从模板开始，一两分钟就能建好；保存后点「开模拟账户」会回到这里。</p>
        <button class="mt-4 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5" @click="openResearch('strategy-studio')">去新建规则策略</button>
      </div>
      <template v-else>
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <FormField label="规则策略" type="select" v-model="form.package_id" :options="packageOptions" @update:model-value="choosePackage" />
          <FormField label="股票范围" type="select" v-model="form.market" :options="marketOptions" />
          <FormField label="名称（可不填）" v-model="form.name" placeholder="默认用策略名和日期" />
          <FormField label="初始资金" type="number" v-model="form.initial_cash" :min="10000" :step="10000" />
          <FormField label="最多持股" type="number" v-model="form.top_n" :min="1" :max="50" :step="1" />
          <FormField label="调仓频率" type="select" v-model="form.rebalance" :options="rebalances" />
        </div>
        <p v-if="formMarketNote" class="mt-3 text-xs text-slate-400">{{ formMarketNote }}</p>
        <p class="mt-3 text-xs text-slate-400">
          创建时会把策略规则、股票范围（选股票池时是现在的股票池）和现在的风控设置复制一份锁住，以后修改它们都不影响这个账户。风控可以先在「策略回测」页的风险设置里改好。
        </p>
        <div class="mt-5 flex justify-end">
          <button :disabled="creating || !form.package_id || left <= 0"
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
