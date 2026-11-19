<script setup>
import { computed } from 'vue'
import DataTable from './DataTable.vue'
import LineChart from './LineChart.vue'
import SectionCard from './SectionCard.vue'

const props = defineProps({ report: { type: Object, required: true } })
const groupColors = ['#38bdf8', '#818cf8', '#a78bfa', '#f472b6', '#fb7185', '#fb923c', '#facc15', '#a3e635', '#34d399', '#2dd4bf']
const datesOf = (rows) => rows.map(({ date }) => date)
const pct = (value) => value == null ? null : value * 100
const fmt = (value) => value == null ? '—' : value.toFixed(3)

const irDates = computed(() => datesOf(props.report.daily_ic))
const rankIcCoverage = computed(() => {
  const dates = props.report.daily_ic.filter((row) => row.rank_ic != null).map(({ date }) => date)
  if (!dates.length) return '所选区间内没有有效 Rank IC 观测。'
  const last = dates[dates.length - 1]
  const span = dates[0] === last ? last : `${dates[0]} 至 ${last}`
  return `有效 Rank IC 覆盖 ${span}（${dates.length} / ${irDates.value.length} 个交易日）。`
})
const irSeries = computed(() => [
  { label: 'IC IR', color: '#818cf8', points: props.report.daily_ic.map((row) => row.ic_ir) },
  { label: 'Rank IC IR', color: '#a78bfa', points: props.report.daily_ic.map((row) => row.rank_ic_ir) },
])
const navDates = computed(() => datesOf(props.report.group_nav))
const navSeries = computed(() => Array.from({ length: props.report.n_groups }, (_, i) => {
  const label = `G${i + 1}`
  return { label, color: groupColors[i], points: props.report.group_nav.map((row) => row[label]) }
}))
const spreadSeries = computed(() => [{
  label: `G${props.report.n_groups} − G1`,
  color: '#a78bfa',
  points: props.report.group_nav.map((row) => pct(row.long_short)),
}])
const turnoverDates = computed(() => datesOf(props.report.rebalance_turnover))
const turnoverAverage = computed(() => {
  const valid = props.report.rebalance_turnover.map(({ turnover }) => turnover).filter(Number.isFinite)
  return valid.length ? `${pct(valid.reduce((sum, value) => sum + value, 0) / valid.length).toFixed(2)}%` : '—'
})
const turnoverSeries = computed(() => [{
  label: '最高组调仓期成员更替率',
  color: '#38bdf8',
  points: props.report.rebalance_turnover.map((row) => pct(row.turnover)),
}])
const decayColumns = [
  { key: 'period', label: '持有期' },
  { key: 'rankIc', label: '平均 Rank IC', align: 'right' },
  { key: 'ir', label: 'Rank IC IR', align: 'right' },
  { key: 'observations', label: '有效交易日', align: 'right' },
]
const decayRows = computed(() => props.report.decay.map((row) => ({
  period: `${row.horizon} 个交易日`,
  rankIc: fmt(row.rank_ic),
  ir: fmt(row.rank_ic_ir),
  observations: row.observations,
})))
const industryColumns = [
  { key: 'industry', label: '行业（证监会）' },
  { key: 'group_count', label: '组内股票数', align: 'right' },
  { key: 'groupWeight', label: '最高组权重', align: 'right' },
  { key: 'poolWeight', label: '同日入组样本权重', align: 'right' },
]
const industry = computed(() => props.report.industry_distribution)
const industryRows = computed(() => industry.value?.rows.map((row) => ({
  ...row,
  groupWeight: `${pct(row.group_weight).toFixed(1)}%`,
  poolWeight: `${pct(row.pool_weight).toFixed(1)}%`,
})) || [])
</script>

<template>
  <SectionCard title="滚动 IC IR" hint="最近 60 个交易日的 IC 均值除以标准差。至少有 20 个有效观测才计算。">
    <p class="mb-3 text-xs text-slate-400">{{ rankIcCoverage }}</p>
    <LineChart :series="irSeries" :dates="irDates" :height="190" :baseline="0" />
  </SectionCard>

  <SectionCard title="分组净值" :hint="`每 ${report.horizon} 个交易日分组一次。G1 因子排名最低，G${report.n_groups} 最高。组内等权，从 1 开始累计，不计交易成本。`">
    <p class="mb-3 text-xs text-slate-400">
      以信号次日收盘价建仓。组内用有完整价格的股票计算。有效 {{ report.nav_periods }} 期，{{ report.nav_skipped }} 期因分组数据不足跳过。
    </p>
    <LineChart :series="navSeries" :dates="navDates" :height="230" :baseline="1" />
  </SectionCard>

  <SectionCard title="头尾组累计收益差" :hint="`每期以 G${report.n_groups} 收益减去 G1 收益，按固定名义本金累计。`">
    <LineChart :series="spreadSeries" :dates="navDates" :height="190" unit="percent" :baseline="0" />
  </SectionCard>

  <SectionCard v-if="industry" title="最高组行业分布" :hint="`最近一个持有窗口完整的信号日 ${industry.date}。G${report.n_groups} 共 ${industry.group_count} 只，同日入组样本共 ${industry.pool_count} 只。以当日已记录的行业按等权计算。`">
    <div class="max-h-80 overflow-y-auto">
      <DataTable :columns="industryColumns" :rows="industryRows" />
    </div>
  </SectionCard>

  <SectionCard title="最高组调仓期成员更替率" :hint="`每隔 ${report.horizon} 个交易日比较最高组。每个点等于本期新增成员数除以本期最高组人数，日均卡片则逐日比较后取平均。`">
    <p class="mb-3 text-xs text-slate-400">调仓期平均 {{ turnoverAverage }}</p>
    <LineChart :series="turnoverSeries" :dates="turnoverDates" :height="190" unit="percent" :baseline="0" />
  </SectionCard>

  <SectionCard title="因子衰减" hint="对照不同持有期的 Rank IC 和 Rank IC IR，查看因子的预测能力如何随持有期变化。">
    <DataTable :columns="decayColumns" :rows="decayRows" empty="暂无数据" />
  </SectionCard>
</template>
