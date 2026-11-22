<script setup>
import { computed } from 'vue'
import { healthBadgeClass, healthCardBorderClass, normalizeHealthCheck } from '../healthPresentation.js'

const props = defineProps({
  health: { type: Object, default: null },
})

const view = computed(() => normalizeHealthCheck(props.health))
</script>

<template>
  <section v-if="view" aria-label="回测白话体检" class="rounded-2xl border border-white/10 bg-white/5 p-5">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 class="text-sm font-semibold text-white">回测白话体检</h3>
        <p class="mt-0.5 text-xs text-slate-400">按本次真实成交与逐日持仓自动排查 4 类常见陷阱，不依赖 AI 猜测。</p>
      </div>
      <span :class="healthBadgeClass(view.summaryStatus)">{{ view.summaryBadge }}</span>
    </div>

    <div class="mt-4 grid gap-3 md:grid-cols-2">
      <article
        v-for="item in view.items"
        :key="item.key"
        class="min-w-0 rounded-xl border p-4 transition"
        :class="healthCardBorderClass(item.status)"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h4 class="text-xs font-semibold text-slate-300">{{ item.title }}</h4>
          <span v-if="item.tag" :class="healthBadgeClass(item.status)">{{ item.tag }}</span>
        </div>
        <p class="mt-2 text-sm font-medium leading-relaxed text-white">{{ item.headline }}</p>
        <p v-if="item.detail" class="mt-1.5 text-xs leading-relaxed text-slate-400">{{ item.detail }}</p>
      </article>
    </div>
  </section>
</template>
