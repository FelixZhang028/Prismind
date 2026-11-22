<script setup>
import { computed } from 'vue'
import { annualIcRows, fdrBadge, formatPValue, styleCorrelationSummary } from '../factorPresentation.js'
import { neutralizationCoverageSummary } from '../neutralizationPresentation.js'
import DataTable from './DataTable.vue'
import LineChart from './LineChart.vue'
import SectionCard from './SectionCard.vue'

const props = defineProps({ report: { type: Object, required: true } })
const coverage = computed(() => neutralizationCoverageSummary(props.report.neutralization_coverage))
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
const navSeries = computed(() => {
  const base = Array.from({ length: props.report.n_groups }, (_, i) => {
    const label = `G${i + 1}`
    return { label, color: groupColors[i], points: props.report.group_nav.map((row) => row[label]) }
  })
  const netTopKey = `net_G${props.report.n_groups}`
  if (props.report.cost_summary && props.report.group_nav.some((row) => row[netTopKey] != null)) {
    base.push({
      label: `G${props.report.n_groups}（扣成本）`,
      color: '#f59e0b',
      dashed: true,
      points: props.report.group_nav.map((row) => row[netTopKey]),
    })
  }
  return base
})
const spreadSeries = computed(() => {
  const lines = [{
    label: `G${props.report.n_groups} − G1（毛）`,
    color: '#a78bfa',
    points: props.report.group_nav.map((row) => pct(row.long_short)),
  }]
  if (props.report.cost_summary && props.report.group_nav.some((row) => row.net_long_short != null)) {
    lines.push({
      label: `G${props.report.n_groups} − G1（扣成本）`,
      color: '#f59e0b',
      dashed: true,
      points: props.report.group_nav.map((row) => pct(row.net_long_short)),
    })
  }
  return lines
})
const costSummary = computed(() => props.report.cost_summary || null)
const fmtSignedPct = (value) => (value == null ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`)
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
  { key: 'hacT', label: 'HAC t 值', align: 'right' },
  { key: 'hacP', label: 'HAC p 值', align: 'right' },
  { key: 'fdrQ', label: 'BH-FDR q 值', align: 'right' },
  { key: 'verdict', label: '多重检验结论' },
  { key: 'observations', label: '有效交易日', align: 'right' },
]
const decayRows = computed(() => props.report.decay.map((row) => {
  const badge = fdrBadge(row.fdr_q)
  return {
    period: `${row.horizon} 个交易日`,
    rankIc: fmt(row.rank_ic),
    ir: fmt(row.rank_ic_ir),
    hacT: row.hac_t == null ? '—' : Number(row.hac_t).toFixed(2),
    hacP: formatPValue(row.hac_p),
    fdrQ: formatPValue(row.fdr_q),
    verdict: badge.label,
    verdictTone: badge.tone,
    observations: row.observations,
  }
}))
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
const annualColumns = [
  { key: 'year', label: '年份' },
  { key: 'observations', label: '有效交易日', align: 'right' },
  { key: 'rankIc', label: '平均 Rank IC', align: 'right' },
  { key: 'ir', label: 'Rank IC IR', align: 'right' },
  { key: 'positiveRatio', label: '正 IC 占比', align: 'right' },
  { key: 'hacT', label: 'HAC t 值', align: 'right' },
  { key: 'hacP', label: 'HAC p 值', align: 'right' },
]
const annualRows = computed(() => annualIcRows(props.report.annual))
const styleColumns = [
  { key: 'label', label: '常见风格维度' },
  { key: 'corrText', label: '横截面 Spearman 相关', align: 'right' },
  { key: 'tilt', label: '偏向判断' },
  { key: 'observations', label: '有效交易日', align: 'right' },
]
const styleSummary = computed(() => styleCorrelationSummary(props.report.style_correlations))
</script>

<template>
  <SectionCard
    v-if="coverage"
    title="中性化覆盖率与实际日期范围"
    :hint="`所选区间 ${coverage.requestedRange}，回归 / 处理实际使用 ${coverage.effectiveRange}。仅统计同时具备所需历史暴露的样本，不用未来数据补齐。`"
  >
    <div class="mb-4 flex flex-wrap gap-2">
      <div
        v-for="item in coverage.metrics"
        :key="item.label"
        class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs"
      >
        <span class="text-slate-400">{{ item.label }}：</span>
        <span class="font-medium text-white">{{ item.value }}</span>
      </div>
    </div>
    <p
      v-if="coverage.insufficient"
      class="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
    >
      {{ coverage.warning }}
    </p>
    <div class="max-h-80 overflow-y-auto">
      <DataTable :columns="coverage.columns" :rows="coverage.rows" empty="暂无按年覆盖率数据" />
    </div>
  </SectionCard>

  <SectionCard title="滚动 IC IR" hint="最近 60 个交易日的 IC 均值除以标准差。至少有 20 个有效观测才计算。">
    <p class="mb-3 text-xs text-slate-400">{{ rankIcCoverage }}</p>
    <LineChart :series="irSeries" :dates="irDates" :height="190" :baseline="0" />
  </SectionCard>

  <SectionCard
    v-if="annualRows.length"
    title="分年份 Rank IC 表现"
    hint="按自然年拆解选股能力，查看因子在哪些年份有效、哪些年份失效；t 值已用 Newey-West HAC 修正持有期重叠自相关。"
  >
    <DataTable :columns="annualColumns" :rows="annualRows" empty="暂无分年份数据" />
  </SectionCard>

  <SectionCard
    v-if="styleSummary.rows.length"
    title="常见风格相关性速查"
    hint="衡量调整方向后的因子值与常见 A 股风格（规模、波动、动量、换手、估值）的横截面 Spearman 相关，便于判断是否与已有风格高度重合。"
  >
    <p
      v-if="styleSummary.warning"
      class="mb-3 rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
    >
      {{ styleSummary.warning }}
    </p>
    <DataTable :columns="styleColumns" :rows="styleSummary.rows" empty="暂无可用风格数据">
      <template #cell-tilt="{ row, value }">
        <span
          :class="row.high_overlap
            ? 'inline-block rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-xs text-amber-200'
            : 'text-xs text-slate-300'"
        >
          {{ row.high_overlap ? `${value}（高度重合）` : value }}
        </span>
      </template>
    </DataTable>
  </SectionCard>

  <SectionCard title="分组净值" :hint="`每 ${report.horizon} 个交易日分组一次。G1 因子排名最低，G${report.n_groups} 最高。组内等权，从 1 开始累计${costSummary ? `；虚线为按单边 ${costSummary.cost_bps} bps 扣减换仓成本后的最高组净值` : '，不计交易成本'}。`">
    <p class="mb-3 text-xs text-slate-400">
      以信号次日收盘价建仓。组内用有完整价格的股票计算。有效 {{ report.nav_periods }} 期，{{ report.nav_skipped }} 期因分组数据不足跳过。
    </p>
    <LineChart :series="navSeries" :dates="navDates" :height="230" :baseline="1" />
  </SectionCard>

  <SectionCard title="头尾组累计收益差" :hint="`每期以 G${report.n_groups} 收益减去 G1 收益，按固定名义本金累计${costSummary ? `；同时对比单边 ${costSummary.cost_bps} bps 扣成本前后` : ''}。`">
    <div v-if="costSummary" class="mb-3 flex flex-wrap gap-2 text-xs">
      <div class="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
        <span class="text-slate-400">单边估算成本：</span>
        <span class="font-medium text-white">{{ costSummary.cost_bps }} bps（{{ (costSummary.cost_bps / 100).toFixed(2) }}%）</span>
      </div>
      <div class="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
        <span class="text-slate-400">最高组累计（毛 → 净）：</span>
        <span class="font-medium text-white">{{ fmtSignedPct(costSummary.gross_top_return) }} → {{ fmtSignedPct(costSummary.net_top_return) }}</span>
      </div>
      <div class="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
        <span class="text-slate-400">头尾组累计差（毛 → 净）：</span>
        <span class="font-medium text-white">{{ fmtSignedPct(costSummary.gross_long_short_total) }} → {{ fmtSignedPct(costSummary.net_long_short_total) }}</span>
      </div>
      <div class="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
        <span class="text-slate-400">每期净多空均值：</span>
        <span class="font-medium text-white">{{ fmtSignedPct(costSummary.net_long_short_mean) }}</span>
      </div>
    </div>
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

  <SectionCard title="因子衰减" hint="对照不同持有期的 Rank IC、Rank IC IR 与 BH-FDR 多重检验校正后的 q 值，避免因同时试多个持有期而把碰运气当有效。">
    <DataTable :columns="decayColumns" :rows="decayRows" empty="暂无数据">
      <template #cell-verdict="{ row }">
        <span :class="row.verdictTone">{{ row.verdict }}</span>
      </template>
    </DataTable>
  </SectionCard>
</template>
