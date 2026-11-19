<script setup>
import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import { marketSentiment } from '../../api.js'
import { openResearch } from '../researchNavigation.js'
import {
  SENTIMENT_TABS,
  SENTIMENT_WINDOWS,
  anomalyToneClass,
  breadthBadge,
  fmtAmount,
  fmtPct,
  fmtRatio,
  fmtSignedAmountDelta,
  fmtSignedPct,
  formatReadout,
  limitBadge,
  maBadge,
  signedTone,
  sliceSeriesForWindow,
  sortIndustries,
  styleNote,
  volumeBadge,
} from '../sentimentPresentation.js'
import SectionCard from '../ui/SectionCard.vue'

defineProps({
  user: { type: Object, default: null },
  notify: { type: Function, default: () => {} },
})

const windowDays = ref(60)
const activeTab = ref('breadth')
const data = ref(null)
const loading = ref(true)
const error = ref('')
const expandedAnomalyId = ref('')
const hoverIndex = ref(-1)

const indSort = reactive({ key: 'vol_ratio_20', descending: true })

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 一次性拉取 250 个交易日序列，切 60 / 120 / 250 日在本地 0ms 切片，无需重复请求。
    const res = await marketSentiment(250)
    data.value = res
    if (res?.anomalies?.length && !res.anomalies.some((a) => a.id === expandedAnomalyId.value)) {
      expandedAnomalyId.value = res.anomalies[0].id
    }
  } catch (e) {
    error.value = e.message || '加载市场情绪数据失败'
  } finally {
    loading.value = false
  }
}

function chooseWindow(win) {
  if (windowDays.value === win) return
  windowDays.value = win
  hoverIndex.value = -1
}

onMounted(() => load())
onActivated(() => {
  if (data.value) load()
})

const latest = computed(() => data.value?.latest || null)
const anomalies = computed(() => data.value?.anomalies || [])
const series = computed(() => sliceSeriesForWindow(data.value?.series || [], windowDays.value))
const sortedIndustries = computed(() => sortIndustries(data.value?.industries, indSort.key, indSort.descending))

const breadthTag = computed(() => breadthBadge(latest.value?.up_ratio, latest.value?.up_ratio_pct_250))
const volumeTag = computed(() => volumeBadge(latest.value?.amount_ratio_20))
const limitTag = computed(() => limitBadge(latest.value?.burst_rate))
const maTag = computed(() => maBadge(latest.value?.above_ma20_ratio))

const breadthBar = computed(() => {
  const b = latest.value
  if (!b || !b.total) return { up: 0, flat: 0, down: 0 }
  return {
    up: Math.round((b.up / b.total) * 1000) / 10,
    flat: Math.round((b.flat / b.total) * 1000) / 10,
    down: Math.round((b.down / b.total) * 1000) / 10,
  }
})

const currentTabMeta = computed(() => SENTIMENT_TABS.find((t) => t.key === activeTab.value) || SENTIMENT_TABS[0])

const hoveredRow = computed(() => {
  if (hoverIndex.value < 0 || hoverIndex.value >= series.value.length) return null
  return series.value[hoverIndex.value]
})
const readoutText = computed(() => formatReadout(activeTab.value, hoveredRow.value))

// ---------- 交互式 SVG 趋势图 ----------
const W = 800
const H = 220
const PAD_L = 46
const PAD_R = 46
const PAD_T = 16
const PAD_B = 26
const PW = W - PAD_L - PAD_R
const PH = H - PAD_T - PAD_B

function xPos(idx, count) {
  if (count <= 1) return PAD_L + PW / 2
  return PAD_L + (idx / (count - 1)) * PW
}

function buildLinePath(values, min, max) {
  const span = max - min || 1
  const n = values.length
  let d = ''
  let pen = false
  for (let i = 0; i < n; i++) {
    const v = values[i]
    if (v == null || !Number.isFinite(Number(v))) {
      pen = false
      continue
    }
    const px = xPos(i, n).toFixed(1)
    const py = (PAD_T + PH - ((Number(v) - min) / span) * PH).toFixed(1)
    d += `${pen ? 'L' : 'M'}${px},${py}`
    pen = true
  }
  return d
}

const chartModel = computed(() => {
  const rows = series.value
  const n = rows.length
  if (!n) return null
  const barW = Math.max(2, (PW / n) * 0.55)
  const ticks = [0, Math.floor(n / 2), n - 1]
    .filter((v, i, arr) => arr.indexOf(v) === i)
    .map((idx) => ({
      x: xPos(idx, n),
      label: rows[idx].date,
      anchor: idx === 0 ? 'start' : idx === n - 1 ? 'end' : 'middle',
    }))

  if (activeTab.value === 'breadth') {
    const maxAmt = Math.max(1e12, ...rows.map((r) => Number(r.amount) || 0)) * 1.15
    const bars = rows.map((r, i) => {
      const h = ((Number(r.amount) || 0) / maxAmt) * PH
      return { x: xPos(i, n) - barW / 2, y: PAD_T + PH - h, w: barW, h }
    })
    return {
      legend: [
        { label: '全市场成交额', color: '#6366f1', kind: 'bar' },
        { label: '上涨家数占比（%）', color: '#fb7185', kind: 'line' },
      ],
      bars,
      barColor: '#6366f1',
      barOpacity: 0.38,
      lines: [{ d: buildLinePath(rows.map((r) => (r.up_ratio == null ? null : r.up_ratio * 100)), 0, 100), color: '#fb7185' }],
      leftTop: '100%',
      leftBottom: '0%',
      rightTop: fmtAmount(maxAmt),
      rightColor: '#818cf8',
      ticks,
    }
  }

  if (activeTab.value === 'limits') {
    const maxCount = Math.max(30, ...rows.map((r) => Math.max(r.limit_up || 0, r.limit_down || 0))) * 1.15
    const halfW = Math.max(1.5, barW * 0.55)
    const upBars = rows.map((r, i) => {
      const h = ((r.limit_up || 0) / maxCount) * PH
      return { x: xPos(i, n) - halfW, y: PAD_T + PH - h, w: halfW, h }
    })
    const downBars = rows.map((r, i) => {
      const h = ((r.limit_down || 0) / maxCount) * PH
      return { x: xPos(i, n), y: PAD_T + PH - h, w: halfW, h }
    })
    const maxBurst = Math.max(50, ...rows.map((r) => (r.burst_rate == null ? 0 : r.burst_rate * 100))) * 1.1
    return {
      legend: [
        { label: '涨停数', color: '#fb7185', kind: 'bar' },
        { label: '跌停数', color: '#34d399', kind: 'bar' },
        { label: '炸板率（%）', color: '#fbbf24', kind: 'line' },
      ],
      upBars,
      downBars,
      lines: [{ d: buildLinePath(rows.map((r) => (r.burst_rate == null ? null : r.burst_rate * 100)), 0, maxBurst), color: '#fbbf24' }],
      leftTop: `${Math.round(maxCount)}家`,
      leftBottom: '0',
      rightTop: `${Math.round(maxBurst)}%`,
      rightColor: '#fbbf24',
      ticks,
    }
  }

  if (activeTab.value === 'ma') {
    return {
      legend: [
        { label: '站上 20 日均线（%）', color: '#818cf8', kind: 'line' },
        { label: '站上 60 日均线（%）', color: '#c084fc', kind: 'line' },
      ],
      refLines: [
        { y: PAD_T + PH * 0.15, label: '85%', color: '#fb7185' },
        { y: PAD_T + PH * 0.85, label: '15%', color: '#34d399' },
      ],
      lines: [
        { d: buildLinePath(rows.map((r) => (r.above_ma20_ratio == null ? null : r.above_ma20_ratio * 100)), 0, 100), color: '#818cf8' },
        { d: buildLinePath(rows.map((r) => (r.above_ma60_ratio == null ? null : r.above_ma60_ratio * 100)), 0, 100), color: '#c084fc' },
      ],
      leftTop: '100%',
      leftBottom: '0%',
      ticks,
    }
  }

  const sHs = rows.map((r) => (r.hs300_cum == null ? null : r.hs300_cum * 100))
  const sZ5 = rows.map((r) => (r.zz500_cum == null ? null : r.zz500_cum * 100))
  const sMed = rows.map((r) => (r.median_cum == null ? null : r.median_cum * 100))
  const finiteVals = [...sHs, ...sZ5, ...sMed].filter((v) => v != null && Number.isFinite(v))
  const min = Math.min(-2, ...(finiteVals.length ? finiteVals : [0]))
  const max = Math.max(2, ...(finiteVals.length ? finiteVals : [0]))
  const zeroY = PAD_T + PH - ((0 - min) / (max - min || 1)) * PH
  return {
    legend: [
      { label: '沪深 300', color: '#38bdf8', kind: 'line' },
      { label: '中证 500', color: '#c084fc', kind: 'line' },
      { label: '全市场中位数', color: '#fb7185', kind: 'line' },
    ],
    zeroY,
    lines: [
      { d: buildLinePath(sHs, min, max), color: '#38bdf8' },
      { d: buildLinePath(sZ5, min, max), color: '#c084fc' },
      { d: buildLinePath(sMed, min, max), color: '#fb7185' },
    ],
    leftTop: `${max.toFixed(1)}%`,
    leftBottom: `${min.toFixed(1)}%`,
    ticks,
  }
})

function onChartMove(event) {
  const n = series.value.length
  if (!n) return
  const svg = event.currentTarget
  const rect = svg.getBoundingClientRect()
  if (!rect.width) return
  const relX = ((event.clientX - rect.left) / rect.width) * W
  const idx = Math.max(0, Math.min(n - 1, Math.round(((relX - PAD_L) / PW) * Math.max(1, n - 1))))
  hoverIndex.value = idx
}

function toggleAnomaly(id) {
  expandedAnomalyId.value = expandedAnomalyId.value === id ? '' : id
}

function sortBy(key) {
  if (indSort.key === key) indSort.descending = !indSort.descending
  else Object.assign(indSort, { key, descending: true })
}
const sortMark = (key) => (indSort.key !== key ? '' : indSort.descending ? ' ↓' : ' ↑')
const openEventStudy = () => openResearch('event-study')
</script>

<template>
  <div class="space-y-6">
    <!-- 标题区 -->
    <section class="glass glass-sheen relative overflow-hidden rounded-2xl p-6">
      <div class="pointer-events-none absolute -right-10 -top-10 h-44 w-44 rounded-full bg-indigo-500/20 blur-3xl" />
      <div class="relative flex flex-wrap items-end justify-between gap-4">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span>① 研究</span>
            <span>/</span>
            <span>市场情绪与异动</span>
            <span v-if="latest" class="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-slate-300">
              截至 {{ latest.day }} 收盘
            </span>
          </div>
          <h1 class="mt-2 text-2xl font-bold text-white">市场情绪与异动</h1>
          <p class="mt-1.5 max-w-2xl text-sm text-slate-400">
            基于本地日线收盘数据统计全市场宽度、量能、涨跌停生态与客观异动，并用历史数据检验同类异动的后续表现。仅描述历史统计，不构成投资建议。
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span class="text-slate-400">趋势窗口</span>
          <div class="inline-flex rounded-full border border-white/10 bg-white/5 p-0.5">
            <button
              v-for="w in SENTIMENT_WINDOWS"
              :key="w"
              type="button"
              :aria-pressed="windowDays === w"
              class="rounded-full px-3 py-1 font-medium transition"
              :class="windowDays === w ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white' : 'text-slate-400 hover:text-slate-200'"
              @click="chooseWindow(w)"
            >
              {{ w }} 日
            </button>
          </div>
        </div>
      </div>
    </section>

    <p v-if="error" role="alert" class="rounded-xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="load()">重试</button>
    </p>
    <p v-else-if="loading && !latest" role="status" class="text-sm text-slate-400">
      正在计算日频市场情绪与历史异动统计（首次加载需聚合全历史日线，之后毫秒级读取）…
    </p>
    <p v-else-if="!latest" class="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-slate-400">
      平台还没有本地日线行情，管理员更新数据后即可查看市场情绪与异动。
    </p>

    <template v-if="latest">
      <!-- 第一区：4 张核心温度卡片 -->
      <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="核心市场温度">
        <!-- 1. 市场宽度 -->
        <div class="glass flex flex-col justify-between gap-3 rounded-2xl p-5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs text-slate-400">市场宽度（上涨占比）</span>
            <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="breadthTag.tone">{{ breadthTag.text }}</span>
          </div>
          <div>
            <div class="flex items-baseline gap-2 tabular-nums">
              <span class="text-2xl font-bold" :class="latest.up_ratio >= 0.5 ? 'text-rose-300' : 'text-emerald-300'">
                {{ fmtPct(latest.up_ratio) }}
              </span>
              <span class="text-xs text-slate-400">{{ latest.up.toLocaleString() }} 涨 / {{ latest.down.toLocaleString() }} 跌</span>
            </div>
            <p class="mt-1 text-xs text-slate-400 tabular-nums">
              全市场中位数 <span class="font-medium" :class="signedTone(latest.median_ret)">{{ fmtSignedPct(latest.median_ret) }}</span>
              · 沪深300 <span class="font-medium" :class="signedTone(latest.hs300_ret)">{{ fmtSignedPct(latest.hs300_ret) }}</span>
            </p>
          </div>
          <div class="space-y-1">
            <div class="flex h-2 overflow-hidden rounded-full bg-white/10">
              <div class="bg-rose-400/80" :style="{ width: `${breadthBar.up}%` }" />
              <div class="bg-slate-400/50" :style="{ width: `${breadthBar.flat}%` }" />
              <div class="bg-emerald-400/80" :style="{ width: `${breadthBar.down}%` }" />
            </div>
            <div class="flex justify-between text-xs text-slate-500">
              <span>普跌</span>
              <span class="text-slate-400">{{ styleNote(latest.style_spread) }}</span>
              <span>普涨</span>
            </div>
          </div>
        </div>

        <!-- 2. 量能温度 -->
        <div class="glass flex flex-col justify-between gap-3 rounded-2xl p-5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs text-slate-400">量能温度（全市场）</span>
            <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="volumeTag.tone">{{ volumeTag.text }}</span>
          </div>
          <div>
            <div class="flex items-baseline gap-2 tabular-nums">
              <span class="text-2xl font-bold text-white">{{ fmtAmount(latest.amount) }}</span>
              <span class="text-xs font-medium" :class="(latest.amount_ratio_20 ?? 1) >= 1 ? 'text-rose-300' : 'text-slate-400'">
                {{ fmtRatio(latest.amount_ratio_20) }} 20日均
              </span>
            </div>
            <p class="mt-1 text-xs text-slate-400 tabular-nums">
              较昨日 <span :class="signedTone(latest.amount_delta_1d)">{{ fmtSignedAmountDelta(latest.amount_delta_1d) }}</span>
              <template v-if="latest.amount_pct_250 != null"> · 近 1 年 {{ Math.round(latest.amount_pct_250 * 100) }}% 分位</template>
            </p>
          </div>
          <div class="space-y-1">
            <div class="h-2 overflow-hidden rounded-full bg-white/10">
              <div class="h-full rounded-full bg-indigo-400" :style="{ width: `${Math.round((latest.amount_pct_250 ?? 0) * 100)}%` }" />
            </div>
            <div class="flex justify-between text-xs text-slate-500">
              <span>缩量</span>
              <span>近 250 日分位 {{ latest.amount_pct_250 != null ? `${Math.round(latest.amount_pct_250 * 100)}%` : '—' }}</span>
              <span>放量</span>
            </div>
          </div>
        </div>

        <!-- 3. 涨跌停生态 -->
        <div class="glass flex flex-col justify-between gap-3 rounded-2xl p-5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs text-slate-400">涨跌停生态</span>
            <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="limitTag.tone">{{ limitTag.text }}</span>
          </div>
          <div>
            <div class="flex items-baseline gap-2 tabular-nums">
              <span class="text-2xl font-bold text-rose-300">{{ latest.limit_up }}</span>
              <span class="text-xs text-slate-400">涨停 /</span>
              <span class="text-xl font-bold text-emerald-300">{{ latest.limit_down }}</span>
              <span class="text-xs text-slate-400">跌停</span>
            </div>
            <p class="mt-1 text-xs text-slate-400 tabular-nums">
              炸板 {{ latest.burst_count }} 只（炸板率 {{ fmtPct(latest.burst_rate) }}）· 最高 {{ latest.max_streak }} 连板
            </p>
          </div>
          <div class="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs">
            <span class="text-slate-400">昨日涨停今日均溢价</span>
            <span class="font-semibold tabular-nums" :class="signedTone(latest.prev_limit_up_ret)">
              {{ fmtSignedPct(latest.prev_limit_up_ret) }}
            </span>
          </div>
        </div>

        <!-- 4. 中期均线温度 -->
        <div class="glass flex flex-col justify-between gap-3 rounded-2xl p-5">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs text-slate-400">中期均线温度</span>
            <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="maTag.tone">{{ maTag.text }}</span>
          </div>
          <div>
            <div class="flex items-baseline gap-2 tabular-nums">
              <span class="text-2xl font-bold text-white">{{ fmtPct(latest.above_ma20_ratio) }}</span>
              <span class="text-xs text-slate-400">站上 20 日均线</span>
            </div>
            <p class="mt-1 text-xs text-slate-400 tabular-nums">
              站上 60 日均线：<span class="font-medium text-slate-200">{{ fmtPct(latest.above_ma60_ratio) }}</span>
              <template v-if="latest.above_ma60_prev5 != null">（5 日前 {{ fmtPct(latest.above_ma60_prev5) }}）</template>
            </p>
          </div>
          <div class="space-y-1">
            <div class="relative h-2 overflow-hidden rounded-full bg-white/10">
              <div class="absolute bottom-0 left-[15%] top-0 w-px bg-emerald-400/70" />
              <div class="absolute bottom-0 left-[85%] top-0 w-px bg-rose-400/70" />
              <div class="h-full rounded-full bg-violet-400" :style="{ width: `${Math.round((latest.above_ma20_ratio ?? 0) * 100)}%` }" />
            </div>
            <div class="flex justify-between text-xs text-slate-500">
              <span>15% 冰点</span>
              <span>正常区间</span>
              <span>85% 过热</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 第二区：近期市场级异动 + 历史同类统计 -->
      <SectionCard
        title="近期市场级异动（点击查看历史同类统计）"
        hint="按固定客观规则自动识别近 10 个交易日触发的大盘级异动，并给出全历史同类出现后的后续表现统计"
      >
        <p v-if="!anomalies.length" class="text-sm text-slate-400">
          近 10 个交易日未触发极端放量/地量、极端普涨/冰点、高炸板率或大盘剧烈分化异动，市场整体运行在常规波动区间。
        </p>
        <div v-else class="divide-y divide-white/5 rounded-xl border border-white/10 bg-white/5">
          <div v-for="item in anomalies" :key="item.id" class="space-y-3 p-4">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1 space-y-1">
                <div class="flex flex-wrap items-center gap-2 text-xs">
                  <span class="font-mono tabular-nums text-slate-400">{{ item.date }}</span>
                  <span class="rounded-full border px-2 py-0.5 font-medium" :class="anomalyToneClass(item.tone)">{{ item.tag }}</span>
                  <span class="text-sm font-semibold text-white">{{ item.title }}</span>
                </div>
                <p class="text-xs text-slate-400">{{ item.detail }}</p>
              </div>
              <button
                type="button"
                class="shrink-0 rounded-full border px-3 py-1 text-xs font-medium transition"
                :class="expandedAnomalyId === item.id
                  ? 'border-indigo-400/50 bg-indigo-500/15 text-indigo-200'
                  : 'border-white/10 text-slate-300 hover:border-indigo-400/40 hover:text-indigo-200'"
                @click="toggleAnomaly(item.id)"
              >
                {{ expandedAnomalyId === item.id ? '收起历史统计 ▲' : `历史同类统计（${item.history?.count ?? 0} 次）→` }}
              </button>
            </div>

            <div
              v-if="expandedAnomalyId === item.id && item.history"
              class="space-y-3 rounded-xl border border-white/10 bg-white/5 p-4"
            >
              <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span class="text-slate-200">
                  历史同类异动后续表现（{{ item.history.span }} · 共触发 <strong class="text-white">{{ item.history.count }}</strong> 次）
                </span>
                <button type="button" class="text-indigo-300 hover:text-indigo-200" @click="openEventStudy">
                  去事件研究自定义检验 →
                </button>
              </div>
              <div class="overflow-x-auto">
                <table class="w-full min-w-[480px] text-left text-xs tabular-nums">
                  <thead>
                    <tr class="border-b border-white/10 text-slate-400">
                      <th class="pb-2 pr-3 font-medium">观察口径</th>
                      <th class="pb-2 px-2 text-right font-medium">后 1 日均值（上涨占比）</th>
                      <th class="pb-2 px-2 text-right font-medium">后 5 日均值（上涨占比）</th>
                      <th class="pb-2 pl-2 text-right font-medium">后 20 日均值（上涨占比）</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-white/5">
                    <tr v-for="row in item.history.rows" :key="row.target">
                      <td class="py-2 pr-3 font-medium text-slate-200">{{ row.target }}</td>
                      <td class="py-2 px-2 text-right">
                        <span class="font-medium" :class="signedTone(row.mean_1d)">{{ fmtSignedPct(row.mean_1d) }}</span>
                        <span class="ml-1 text-slate-400">({{ fmtPct(row.win_1d, 0) }})</span>
                      </td>
                      <td class="py-2 px-2 text-right">
                        <span class="font-medium" :class="signedTone(row.mean_5d)">{{ fmtSignedPct(row.mean_5d) }}</span>
                        <span class="ml-1 text-slate-400">({{ fmtPct(row.win_5d, 0) }})</span>
                      </td>
                      <td class="py-2 pl-2 text-right">
                        <span class="font-medium" :class="signedTone(row.mean_20d)">{{ fmtSignedPct(row.mean_20d) }}</span>
                        <span class="ml-1 text-slate-400">({{ fmtPct(row.win_20d, 0) }})</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p class="text-xs text-slate-500">{{ item.history.note }}</p>
            </div>
          </div>
        </div>
      </SectionCard>

      <!-- 第三区：多维度情绪趋势图 -->
      <SectionCard title="情绪与异动趋势" :hint="currentTabMeta.subtitle">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div class="flex flex-wrap gap-1.5 text-xs">
            <button
              v-for="tab in SENTIMENT_TABS"
              :key="tab.key"
              type="button"
              :aria-pressed="activeTab === tab.key"
              class="rounded-full border px-3 py-1 font-medium transition"
              :class="activeTab === tab.key
                ? 'border-indigo-400/50 bg-indigo-500/20 text-indigo-200'
                : 'border-white/10 bg-white/5 text-slate-400 hover:text-slate-200'"
              @click="activeTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>
          <p class="font-mono text-xs tabular-nums text-slate-300">{{ readoutText }}</p>
        </div>

        <div v-if="chartModel" class="space-y-2">
          <div class="flex flex-wrap items-center gap-4 text-xs text-slate-400">
            <span v-for="l in chartModel.legend" :key="l.label" class="inline-flex items-center gap-1.5">
              <span
                class="inline-block"
                :class="l.kind === 'bar' ? 'h-2.5 w-2.5 rounded-sm' : 'h-0.5 w-3.5 rounded'"
                :style="{ background: l.color }"
              />
              {{ l.label }}
            </span>
          </div>

          <div class="w-full overflow-hidden rounded-xl border border-white/10 bg-white/5 p-2">
            <svg
              :viewBox="`0 0 ${W} ${H}`"
              class="block h-auto w-full select-none text-slate-300"
              @mousemove="onChartMove"
              @mouseleave="hoverIndex = -1"
            >
              <line
                v-for="k in 5"
                :key="k"
                :x1="PAD_L"
                :x2="W - PAD_R"
                :y1="PAD_T + (PH * (k - 1)) / 4"
                :y2="PAD_T + (PH * (k - 1)) / 4"
                stroke="currentColor"
                stroke-opacity="0.1"
                stroke-dasharray="3 3"
              />

              <!-- 成交额柱 -->
              <rect
                v-for="(bar, i) in chartModel.bars || []"
                :key="'b-' + i"
                :x="bar.x"
                :y="bar.y"
                :width="bar.w"
                :height="bar.h"
                rx="1"
                :fill="chartModel.barColor"
                :fill-opacity="chartModel.barOpacity"
              />

              <!-- 涨跌停柱 -->
              <rect
                v-for="(bar, i) in chartModel.upBars || []"
                :key="'u-' + i"
                :x="bar.x"
                :y="bar.y"
                :width="bar.w"
                :height="bar.h"
                fill="#fb7185"
                fill-opacity="0.45"
              />
              <rect
                v-for="(bar, i) in chartModel.downBars || []"
                :key="'d-' + i"
                :x="bar.x"
                :y="bar.y"
                :width="bar.w"
                :height="bar.h"
                fill="#34d399"
                fill-opacity="0.7"
              />

              <!-- 均线冰点/过热参考线 -->
              <template v-for="ref in chartModel.refLines || []" :key="ref.label">
                <line :x1="PAD_L" :x2="W - PAD_R" :y1="ref.y" :y2="ref.y" :stroke="ref.color" stroke-opacity="0.55" stroke-dasharray="4 4" />
                <text :x="W - PAD_R + 4" :y="ref.y + 3" :fill="ref.color" font-size="10">{{ ref.label }}</text>
              </template>

              <!-- 零轴 -->
              <line
                v-if="chartModel.zeroY != null"
                :x1="PAD_L"
                :x2="W - PAD_R"
                :y1="chartModel.zeroY"
                :y2="chartModel.zeroY"
                stroke="currentColor"
                stroke-opacity="0.3"
              />

              <!-- 折线 -->
              <path
                v-for="(ln, i) in chartModel.lines"
                :key="'l-' + i"
                :d="ln.d"
                fill="none"
                :stroke="ln.color"
                stroke-width="2"
              />

              <!-- 坐标标签 -->
              <text x="4" :y="PAD_T + 8" fill="currentColor" opacity="0.55" font-size="10">{{ chartModel.leftTop }}</text>
              <text x="4" :y="PAD_T + PH" fill="currentColor" opacity="0.55" font-size="10">{{ chartModel.leftBottom }}</text>
              <text v-if="chartModel.rightTop" :x="W - 4" :y="PAD_T + 8" text-anchor="end" :fill="chartModel.rightColor" opacity="0.85" font-size="10">{{ chartModel.rightTop }}</text>

              <text
                v-for="t in chartModel.ticks"
                :key="t.label"
                :x="t.x"
                :y="H - 6"
                :text-anchor="t.anchor"
                fill="currentColor"
                opacity="0.55"
                font-size="10"
              >
                {{ t.label }}
              </text>

              <!-- 悬停竖线 -->
              <line
                v-if="hoverIndex >= 0"
                :x1="xPos(hoverIndex, series.length)"
                :x2="xPos(hoverIndex, series.length)"
                :y1="PAD_T"
                :y2="PAD_T + PH"
                stroke="currentColor"
                stroke-opacity="0.45"
                stroke-dasharray="2 2"
              />
            </svg>
          </div>
        </div>
      </SectionCard>

      <!-- 第四区：行业量能异动与涨停分布表 -->
      <SectionCard
        title="行业量能异动与涨停分布（证监会行业）"
        hint="按非停牌非 ST 股票统计（剔除成分不足 5 只的行业），点击列标题排序；仅展示行业汇总，不列推荐个股榜"
      >
        <p v-if="!sortedIndustries.length" class="text-sm text-slate-400">暂无行业分类统计数据。</p>
        <div v-else class="max-h-96 overflow-auto">
          <table class="w-full min-w-[620px] text-left text-xs tabular-nums">
            <thead class="bg-white/5 text-slate-400">
              <tr class="border-b border-white/10">
                <th class="py-2.5 pr-3 font-medium">行业</th>
                <th class="py-2.5 px-3 text-right font-medium">
                  <button type="button" class="hover:text-white" @click="sortBy('change')">平均涨跌幅{{ sortMark('change') }}</button>
                </th>
                <th class="py-2.5 px-3 text-right font-medium">
                  <button type="button" class="hover:text-white" @click="sortBy('vol_ratio_20')">较 20 日量比{{ sortMark('vol_ratio_20') }}</button>
                </th>
                <th class="py-2.5 px-3 text-right font-medium">
                  <button type="button" class="hover:text-white" @click="sortBy('amount_share')">成交额占比{{ sortMark('amount_share') }}</button>
                </th>
                <th class="py-2.5 px-3 text-right font-medium">
                  <button type="button" class="hover:text-white" @click="sortBy('limit_up')">涨停 / 跌停{{ sortMark('limit_up') }}</button>
                </th>
                <th class="py-2.5 pl-3 text-right font-medium">
                  <button type="button" class="hover:text-white" @click="sortBy('up_ratio')">上涨占比{{ sortMark('up_ratio') }}</button>
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              <tr v-for="row in sortedIndustries" :key="row.name" class="hover:bg-white/5">
                <td class="py-2.5 pr-3 font-medium text-slate-200">
                  {{ row.name }}
                  <span class="ml-1 text-slate-500">({{ row.count }})</span>
                </td>
                <td class="py-2.5 px-3 text-right font-medium" :class="signedTone(row.change)">
                  {{ fmtSignedPct(row.change) }}
                </td>
                <td class="py-2.5 px-3 text-right" :class="(row.vol_ratio_20 ?? 0) >= 1.3 ? 'font-semibold text-amber-300' : 'text-slate-200'">
                  {{ fmtRatio(row.vol_ratio_20) }}
                </td>
                <td class="py-2.5 px-3 text-right text-slate-400">{{ fmtPct(row.amount_share) }}</td>
                <td class="py-2.5 px-3 text-right">
                  <span class="text-rose-300">{{ row.limit_up }}</span>
                  <span class="text-slate-500"> / </span>
                  <span class="text-emerald-300">{{ row.limit_down }}</span>
                </td>
                <td class="py-2.5 pl-3 text-right text-slate-200">{{ fmtPct(row.up_ratio) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </template>
  </div>
</template>
