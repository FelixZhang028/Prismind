<script setup>
// 新手引导：把页面变暗，只亮出要点的那个按钮（电脑上侧栏里对应的那一项也亮），旁边用气泡说明。
// 完整引导：开头 → 条件选股 → 建规则策略 → 回测 → 模拟账户 → 结尾，“下一步”会自动打开下一页；
// 引导期间页面不能点，免得走丢。only：首页“开始使用”点“去做”时只亮那一步，这时可以直接点亮着的按钮。
// 要亮的元素在页面里标 data-guide="..."，侧栏项标 data-guide-nav="..."；找不到时气泡放在屏幕中间，照样能往下走。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  GUIDE_STEPS, bubblePlacement, guideStep, isPhone, scrollTargetY, spotlightBox, stepNumber,
} from '../workspace/guideSteps.js'
import { openResearch } from '../workspace/researchNavigation.js'

const props = defineProps({
  only: { type: String, default: '' },
  activeView: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const steps = computed(() => (props.only ? [guideStep(props.only)].filter(Boolean) : GUIDE_STEPS))
const index = ref(0)
const step = computed(() => steps.value[index.value])
const number = computed(() => stepNumber(step.value))
const isLast = computed(() => index.value === steps.value.length - 1)

// 宽度不算滚动条，气泡不会压在滚动条上
const screenSize = () => ({ width: document.documentElement.clientWidth || window.innerWidth, height: window.innerHeight })
const viewport = ref(screenSize())
const phone = computed(() => isPhone(viewport.value.width))
const target = ref(null)        // 高亮框（相对屏幕）
const navBox = ref(null)        // 电脑上侧栏里的那一项
const searching = ref(true)     // 正在等页面把按钮画出来
const bubble = ref(null)
const bubbleSize = ref({ width: 340, height: 200 })
const holes = computed(() => [target.value, navBox.value].filter(Boolean))
const placement = computed(() => bubblePlacement(target.value, bubbleSize.value, viewport.value))

function targetName(item) {
  return (phone.value && item.targetMobile) || item.target
}
function findTarget(item) {
  const name = item && targetName(item)
  if (!name) return null
  // 同一个名字可能有两处（例如空列表和表单），取第一个看得见的
  return [...document.querySelectorAll(`[data-guide="${name}"]`)].find((el) => el.getClientRects().length) || null
}
function findNav(item) {
  if (phone.value || !item?.nav) return null
  const el = document.querySelector(`[data-guide-nav="${item.nav}"]`)
  return el && el.getClientRects().length ? el : null
}

function measure() {
  viewport.value = screenSize()
  const el = findTarget(step.value)
  target.value = el ? spotlightBox(el.getBoundingClientRect()) : null
  const nav = findNav(step.value)
  navBox.value = nav ? spotlightBox(nav.getBoundingClientRect(), 3) : null
  if (bubble.value) {
    const box = bubble.value.getBoundingClientRect()
    if (Math.abs(box.height - bubbleSize.value.height) > 1) bubbleSize.value = { width: 340, height: box.height }
  }
}

// 换到一步：需要的话先打开那一页，等按钮出现（页面是异步加载的，最多等 4 秒），滚到看得见的地方，再量位置。
let run = 0
async function show() {
  const current = ++run
  const item = step.value
  searching.value = true
  target.value = null
  navBox.value = null
  if (!props.only && item.view && props.activeView !== item.view) openResearch(item.view)
  let el = null
  if (item.target) {
    for (let tries = 0; tries < 40 && !el; tries += 1) {
      await new Promise((resolve) => setTimeout(resolve, tries ? 100 : 0))
      if (current !== run) return
      el = findTarget(item)
    }
  }
  findNav(item)?.scrollIntoView({ block: 'nearest' })
  if (el) {
    await nextTick()
    const sheet = phone.value ? bubble.value?.getBoundingClientRect().height || 220 : 0
    const y = scrollTargetY(el.getBoundingClientRect(), screenSize(), window.scrollY, sheet)
    if (y !== null) window.scrollTo({ top: y, behavior: 'instant' })
  }
  if (current !== run) return
  searching.value = false
  measure()
  await nextTick()
  measure()
  bubble.value?.querySelector('[data-primary]')?.focus({ preventScroll: true })
}

function next() {
  if (isLast.value) return emit('close', 'done')
  index.value += 1
}
function prev() {
  if (index.value > 0) index.value -= 1
}
function skip() { emit('close', 'skipped') }

// 只亮一步时，点亮着的按钮或页面别处都直接关掉气泡（点击照常生效）。
function onPointerDown(event) {
  if (props.only && !bubble.value?.contains(event.target)) emit('close', 'done')
}
function onKey(event) {
  if (event.key === 'Escape') skip()
  else if (!props.only && event.key === 'ArrowRight') next()
  else if (!props.only && event.key === 'ArrowLeft') prev()
}
let frame = 0
function onLayout() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(measure)
}
let timer = 0
onMounted(() => {
  window.addEventListener('resize', onLayout)
  window.addEventListener('scroll', onLayout, { passive: true, capture: true })
  window.addEventListener('keydown', onKey)
  document.addEventListener('pointerdown', onPointerDown, true)
  timer = window.setInterval(() => { if (!searching.value) measure() }, 400)   // 页面数据加载完、布局会变
  show()
})
onUnmounted(() => {
  run += 1
  window.removeEventListener('resize', onLayout)
  window.removeEventListener('scroll', onLayout, { capture: true })
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('pointerdown', onPointerDown, true)
  window.clearInterval(timer)
  cancelAnimationFrame(frame)
})
watch(index, show)

const bubbleStyle = computed(() => {
  if (phone.value) return {}
  const place = placement.value
  return { top: `${place.top}px`, left: `${place.left}px`, width: `${place.width}px` }
})
</script>

<template>
  <div class="guide-root fixed inset-0 z-[70]" :class="only ? 'pointer-events-none' : ''">
    <!-- 变暗的一层，在要亮的地方挖洞 -->
    <svg class="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      <defs>
        <mask id="guide-holes">
          <rect width="100%" height="100%" fill="white" />
          <rect v-for="(box, i) in holes" :key="i" :x="box.left" :y="box.top" :width="box.width" :height="box.height" rx="12" fill="black" />
        </mask>
      </defs>
      <rect class="guide-dim" width="100%" height="100%" mask="url(#guide-holes)" />
    </svg>
    <div v-for="(box, i) in holes" :key="`ring-${i}`" class="guide-ring pointer-events-none absolute rounded-xl"
      :class="i === 0 ? 'guide-ring--main' : ''"
      :style="{ top: `${box.top}px`, left: `${box.left}px`, width: `${box.width}px`, height: `${box.height}px` }" />

    <!-- 气泡：电脑上在按钮旁边，手机上固定在底部 -->
    <div v-show="!searching" ref="bubble" role="dialog" aria-modal="true" aria-labelledby="guide-title" aria-describedby="guide-text"
      class="guide-bubble pointer-events-auto absolute rounded-2xl p-4"
      :class="phone ? 'guide-bubble--sheet' : ''" :style="bubbleStyle">
      <span v-if="!phone && placement.arrow !== null" class="guide-arrow" :class="`guide-arrow--${placement.side}`" :style="{ left: `${placement.arrow}px` }" aria-hidden="true" />
      <div v-if="number" class="flex items-center gap-2">
        <span class="text-xs text-slate-400">第 {{ number.current }} / {{ number.total }} 步</span>
        <span class="ml-auto flex gap-1" aria-hidden="true">
          <span v-for="n in number.total" :key="n" class="h-1.5 w-4 rounded-full" :class="n <= number.current ? 'bg-indigo-400' : 'bg-white/15'" />
        </span>
      </div>
      <h2 id="guide-title" class="text-base font-semibold text-white" :class="number ? 'mt-2' : ''">{{ step.title }}</h2>
      <p id="guide-text" class="mt-1.5 text-sm leading-relaxed text-slate-300">{{ step.text }}</p>

      <div class="mt-4 flex items-center gap-2 whitespace-nowrap">
        <template v-if="only">
          <button type="button" data-primary class="guide-primary ml-auto" @click="emit('close', 'done')">知道了</button>
        </template>
        <template v-else>
          <button v-if="!isLast" type="button" class="px-1 py-1.5 text-sm text-slate-400 transition hover:text-slate-200" @click="skip">
            {{ index === 0 ? '以后再说' : '跳过' }}
          </button>
          <button v-if="index > 0" type="button" class="ml-auto rounded-full border border-white/10 px-3.5 py-1.5 text-sm text-slate-300 transition hover:bg-white/5" @click="prev">上一步</button>
          <button type="button" data-primary class="guide-primary" :class="index > 0 ? '' : 'ml-auto'" @click="next">
            {{ index === 0 ? '开始' : isLast ? '完成' : '下一步' }}
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.guide-dim { fill: rgba(2, 6, 23, 0.68); }
:global(html[data-theme='light'] .guide-dim) { fill: rgba(15, 23, 42, 0.42); }
.guide-ring {
  box-shadow: 0 0 0 2px rgba(129, 140, 248, 0.55);
  transition: top 0.2s ease, left 0.2s ease, width 0.2s ease, height 0.2s ease;
}
.guide-ring--main {
  box-shadow: 0 0 0 2px rgb(129, 140, 248), 0 0 0 6px rgba(129, 140, 248, 0.25);
  animation: guide-pulse 1.8s ease-in-out infinite;
}
@keyframes guide-pulse {
  50% { box-shadow: 0 0 0 2px rgb(129, 140, 248), 0 0 0 10px rgba(129, 140, 248, 0.08); }
}
.guide-bubble {
  background: rgb(19, 22, 36);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.5);
  transition: top 0.2s ease, left 0.2s ease;
}
:global(html[data-theme='light'] .guide-bubble) {
  background: #fff;
  border-color: rgba(15, 23, 42, 0.12);
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.22);
}
.guide-bubble--sheet {
  left: 0; right: 0; bottom: 0; top: auto;
  border-radius: 1rem 1rem 0 0;
  padding-bottom: calc(1rem + env(safe-area-inset-bottom));
}
.guide-primary {
  border-radius: 9999px;
  padding: 0.375rem 1.1rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #fff;
  background-image: linear-gradient(to right, rgb(99, 102, 241), rgb(139, 92, 246));
  box-shadow: 0 8px 20px -6px rgba(99, 102, 241, 0.6);
}
.guide-primary:focus-visible { outline: 2px solid rgb(165, 180, 252); outline-offset: 2px; }
.guide-arrow {
  position: absolute;
  width: 12px; height: 12px;
  margin-left: -6px;
  background: inherit;
  transform: rotate(45deg);
  border: inherit;
}
.guide-arrow--below { top: -7px; border-right: 0; border-bottom: 0; }
.guide-arrow--above { bottom: -7px; border-left: 0; border-top: 0; }
@media (prefers-reduced-motion: reduce) {
  .guide-ring, .guide-ring--main, .guide-bubble { animation: none; transition: none; }
}
</style>
