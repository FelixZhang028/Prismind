<script setup>
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { axisTicks, dateTicks, formatValue } from '../chartScale.js'

const props = defineProps({
  // [{ label, color, points: number[], dashed? }]；颜色可以是 CSS 变量，例如 var(--fq-chart-strategy)
  series: { type: Array, default: () => [] },
  height: { type: Number, default: 160 },
  fill: { type: Boolean, default: true },
  dates: { type: Array, default: () => [] }, // 和 points 一一对应的日期；有日期时画横轴、提示里显示日期
  unit: { type: String, default: 'number' }, // percent | money | number
  baseline: { type: Number, default: null }, // 参考线（收益曲线用 0）
})

const uid = useId() // 同一页有几张图时，渐变的编号不能重复

// 按容器的实际宽度画，文字不会被拉伸。
const box = ref(null)
const width = ref(600)
let observer = null
onMounted(() => {
  if (!box.value) return
  width.value = box.value.clientWidth || 600
  observer = new ResizeObserver(([entry]) => { width.value = Math.max(240, Math.round(entry.contentRect.width)) })
  observer.observe(box.value)
})
onBeforeUnmount(() => observer?.disconnect())

const finite = (v) => v !== null && v !== undefined && Number.isFinite(Number(v))
const length = computed(() => Math.max(0, ...props.series.map((s) => s.points?.length || 0)))
const hasData = computed(() => props.series.some((s) => (s.points || []).some(finite)))

const scale = computed(() => {
  const values = props.series.flatMap((s) => (s.points || []).filter(finite).map(Number))
  if (finite(props.baseline)) values.push(Number(props.baseline))
  const ticks = axisTicks(Math.min(...values), Math.max(...values))
  const labels = ticks.map((t) => formatValue(t, props.unit, true))
  const left = Math.max(...labels.map((l) => l.length)) * 6.6 + 12
  const bottom = props.dates.length ? 24 : 8
  return { ticks, labels, left, right: 12, top: 10, bottom, min: ticks[0], max: ticks[ticks.length - 1] }
})
const plotW = computed(() => Math.max(10, width.value - scale.value.left - scale.value.right))
const plotH = computed(() => Math.max(10, props.height - scale.value.top - scale.value.bottom))
const x = (i) => scale.value.left + (length.value <= 1 ? plotW.value / 2 : (i / (length.value - 1)) * plotW.value)
const y = (v) => scale.value.top + (1 - (v - scale.value.min) / (scale.value.max - scale.value.min || 1)) * plotH.value

// 没有数值的点断开，不连成一条斜线。
const lines = computed(() => props.series.map((s, index) => {
  let d = ''
  let open = false
  ;(s.points || []).forEach((v, i) => {
    if (!finite(v)) { open = false; return }
    d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(Number(v)).toFixed(1)}`
    open = true
  })
  const points = (s.points || []).map((v, i) => [i, v]).filter(([, v]) => finite(v))
  const floor = y(finite(props.baseline) ? Number(props.baseline) : scale.value.min)
  const area = points.length > 1
    ? `${d}L${x(points[points.length - 1][0]).toFixed(1)},${floor.toFixed(1)}L${x(points[0][0]).toFixed(1)},${floor.toFixed(1)}Z`
    : ''
  return { ...s, index, d, area }
}))
const showArea = computed(() => props.fill && props.series.length === 1)
const xTicks = computed(() => dateTicks(props.dates, Math.max(2, Math.floor(plotW.value / 110))))

// ---------- 悬停：竖线找日期，提示里列出每条线在这一天的数值 ----------
const hover = ref(null)
function pick(event) {
  if (!length.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  const px = event.clientX - rect.left
  const ratio = (px - scale.value.left) / plotW.value
  hover.value = Math.min(length.value - 1, Math.max(0, Math.round(ratio * (length.value - 1))))
}
function step(delta) {
  hover.value = Math.min(length.value - 1, Math.max(0, (hover.value ?? (delta > 0 ? -1 : length.value)) + delta))
}
const readout = computed(() => {
  if (hover.value === null) return null
  const i = hover.value
  const rows = props.series.map((s) => ({ label: s.label, color: s.color, dashed: s.dashed, value: s.points?.[i] }))
    .filter((row) => finite(row.value))
  const left = x(i)
  return {
    x: left,
    date: props.dates[i] || '',
    rows: rows.map((row) => ({ ...row, text: formatValue(Number(row.value), props.unit), y: y(Number(row.value)) })),
    // 提示框放在竖线的另一侧，不挡住指着的地方
    side: left > scale.value.left + plotW.value / 2 ? 'left' : 'right',
  }
})
</script>

<template>
  <div ref="box" class="relative w-full">
    <svg v-if="hasData" :width="width" :height="height" class="block touch-none select-none outline-none" tabindex="0"
      role="img" :aria-label="series.map((s) => s.label).join('、') + ' 走势图'"
      @pointermove="pick" @pointerdown="pick" @pointerleave="hover = null" @blur="hover = null"
      @keydown.left.prevent="step(-1)" @keydown.right.prevent="step(1)">
      <defs>
        <linearGradient v-for="line in lines" :id="`${uid}-fill-${line.index}`" :key="line.index" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :style="{ stopColor: line.color, stopOpacity: 0.22 }" />
          <stop offset="100%" :style="{ stopColor: line.color, stopOpacity: 0 }" />
        </linearGradient>
      </defs>
      <!-- 横向网格和纵轴刻度：很淡，只帮助读数 -->
      <g class="text-slate-500">
        <template v-for="(tick, i) in scale.ticks" :key="tick">
          <line :x1="scale.left" :x2="scale.left + plotW" :y1="y(tick)" :y2="y(tick)" stroke="currentColor" stroke-opacity="0.15" />
          <text :x="scale.left - 8" :y="y(tick)" dy="0.32em" text-anchor="end" fill="currentColor" font-size="11">{{ scale.labels[i] }}</text>
        </template>
        <text v-for="tick in xTicks" :key="tick.index" :x="x(tick.index)" :y="height - 6" fill="currentColor" font-size="11"
          :text-anchor="tick.index === 0 ? 'start' : tick.index === length - 1 ? 'end' : 'middle'">{{ tick.label }}</text>
      </g>
      <line v-if="baseline !== null && baseline >= scale.min && baseline <= scale.max" class="text-slate-400"
        :x1="scale.left" :x2="scale.left + plotW" :y1="y(baseline)" :y2="y(baseline)" stroke="currentColor" stroke-opacity="0.55" stroke-dasharray="3 3" />
      <template v-for="line in lines" :key="line.index">
        <path v-if="showArea && line.area" :d="line.area" :fill="`url(#${uid}-fill-${line.index})`" />
      </template>
      <!-- 后面的线先画，第一条（通常是策略）在最上面 -->
      <path v-for="line in [...lines].reverse()" :key="`l${line.index}`" :d="line.d" fill="none" :style="{ stroke: line.color }"
        :stroke-width="line.index === 0 ? 2 : 1.5" :stroke-dasharray="line.dashed ? '5 4' : null" stroke-linecap="round" stroke-linejoin="round" />
      <g v-if="readout">
        <line class="text-slate-400" :x1="readout.x" :x2="readout.x" :y1="scale.top" :y2="scale.top + plotH" stroke="currentColor" stroke-opacity="0.5" />
        <circle v-for="row in readout.rows" :key="row.label" :cx="readout.x" :cy="row.y" r="4" :style="{ fill: row.color }"
          stroke-width="2" style="stroke: rgb(var(--fq-panel-rgb))" />
      </g>
    </svg>
    <div v-else class="flex items-center justify-center rounded-xl border border-dashed border-white/10 p-8 text-sm text-slate-500" :style="{ height: height + 'px' }">暂无数据</div>
    <div v-if="readout && readout.rows.length" class="pointer-events-none absolute top-1 z-10 min-w-[8rem] rounded-lg border border-white/10 px-3 py-2 text-xs shadow-lg"
      style="background: rgb(var(--fq-panel-rgb) / 0.96)"
      :style="readout.side === 'right' ? { left: `${readout.x + 12}px` } : { right: `${width - readout.x + 12}px` }">
      <p v-if="readout.date" class="mb-1 text-slate-400">{{ readout.date }}</p>
      <p v-for="row in readout.rows" :key="row.label" class="flex items-center gap-2 whitespace-nowrap">
        <span class="inline-block w-4 border-t-2" :style="{ borderColor: row.color, borderTopStyle: row.dashed ? 'dashed' : 'solid' }" />
        <span class="font-semibold tabular-nums text-white">{{ row.text }}</span>
        <span class="text-slate-400">{{ row.label }}</span>
      </p>
    </div>
  </div>
</template>
