<script setup>
import { computed, onActivated, onMounted, ref } from 'vue'
import {
  CATEGORY_STYLE,
  CHANGELOG_CATEGORIES,
  filterChangelogEntries,
  latestChangelogDate,
  markChangelogSeen,
} from '../changelog.js'
import { openResearch } from '../researchNavigation.js'
import SectionCard from '../ui/SectionCard.vue'

const category = ref('all')
const entries = computed(() => filterChangelogEntries(category.value))
const latestDate = latestChangelogDate()

function notifySeen() {
  markChangelogSeen()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('fq-changelog-seen'))
  }
}

onMounted(notifySeen)
onActivated(notifySeen)
</script>

<template>
  <div class="space-y-6">
    <div class="glass glass-sheen rounded-2xl p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-xl font-bold text-white">更新日志</h1>
          <p class="mt-2 text-sm text-slate-400">
            记录平台在因子研究、回测引擎、模拟账户与数据质量上的重要功能上线与修复。最近更新：{{ latestDate }}。
          </p>
        </div>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <div class="inline-flex flex-wrap rounded-full border border-white/10 bg-white/5 p-1" role="tablist" aria-label="更新分类">
        <button
          v-for="item in CHANGELOG_CATEGORIES"
          :key="item.value"
          type="button"
          role="tab"
          :aria-selected="category === item.value"
          class="rounded-full px-3.5 py-1.5 text-xs font-medium transition"
          :class="category === item.value ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          @click="category = item.value"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <div v-if="!entries.length" class="rounded-2xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-400">
      该分类下暂无更新记录。
    </div>

    <div v-else class="space-y-5">
      <SectionCard
        v-for="entry in entries"
        :key="entry.id"
        :title="entry.title"
        :hint="entry.date"
      >
        <ul class="space-y-3">
          <li
            v-for="(item, idx) in entry.items"
            :key="`${entry.id}-${idx}`"
            class="rounded-xl border border-white/10 bg-white/5 p-4"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span
                class="inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium"
                :class="CATEGORY_STYLE[item.category]?.tone || 'border-white/10 bg-white/5 text-slate-300'"
              >
                {{ CATEGORY_STYLE[item.category]?.label || item.category }}
              </span>
              <span class="text-sm font-medium text-white">{{ item.summary }}</span>
            </div>
            <p class="mt-2 text-xs leading-relaxed text-slate-300">{{ item.detail }}</p>
            <button
              v-if="item.action"
              type="button"
              class="mt-2.5 text-xs font-medium text-indigo-300 transition hover:text-indigo-200"
              @click="openResearch(item.action.view)"
            >
              {{ item.action.label }} →
            </button>
          </li>
        </ul>
      </SectionCard>
    </div>
  </div>
</template>
