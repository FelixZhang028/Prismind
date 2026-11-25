<script setup>
import { computed } from 'vue'
import { openResearch, strategyReference } from '../researchNavigation.js'
const props = defineProps({
  asset: { type: Object, required: true },
  updated: { type: Boolean, default: false },
  mode: { type: String, default: '' }, // 'created' | 'updated' | 'saved_as_new'
})
const effectiveMode = computed(() => props.mode || (props.updated ? 'updated' : 'created'))
const heading = computed(() => (
  effectiveMode.value === 'saved_as_new'
    ? '已另存为新策略'
    : effectiveMode.value === 'updated'
      ? '策略修改已保存'
      : '策略已保存'
))
const detail = computed(() => {
  const name = props.asset.name || props.asset.display_name
  if (effectiveMode.value === 'saved_as_new') {
    return `${name} · 已作为独立新策略加入「我的策略」，原策略保持不变。可直接去回测，或继续编辑这份新策略。`
  }
  if (effectiveMode.value === 'updated') {
    return `${name} · 已更新到「我的策略」，后续回测与模拟账户将使用最新规则。`
  }
  return `${name} · 已加入「我的策略」。下一步确认回测配置。`
})
</script>
<template>
  <section class="glass glass-sheen rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-5" aria-live="polite">
    <h2 class="font-semibold text-emerald-300">{{ heading }}</h2>
    <p class="mt-2 text-sm text-slate-200">{{ detail }}</p>
    <div class="mt-4 flex flex-wrap gap-3">
      <button class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-4 py-2 text-sm font-semibold text-white transition hover:-translate-y-0.5" @click="openResearch('backtest-review', { strategy: strategyReference(asset) })">去回测</button>
      <button class="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/5" @click="openResearch('paper-accounts', { mode: 'new', strategy: strategyReference(asset) })">开模拟账户</button>
      <button class="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/5" @click="openResearch('strategy-hub')">返回我的策略</button>
    </div>
  </section>
</template>
