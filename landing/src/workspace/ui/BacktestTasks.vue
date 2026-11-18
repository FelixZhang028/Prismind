<script setup>
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { listBacktestJobs, getBacktestJob, cancelBacktestJob } from '../../api.js'
import { openResearch } from '../researchNavigation.js'
import { backtestTimestamp } from '../runRecords.js'
import SectionCard from './SectionCard.vue'

const props = defineProps({
  focusJob: { type: String, default: '' },
  refreshKey: { type: Number, default: 0 },
  category: { type: String, default: 'backtest' },
})
const emit = defineEmits(['completed', 'view'])
const title = computed(() => props.category === 'factor' ? '因子评估任务' : '回测任务')
const jobs = ref([])
const expanded = ref(false)
const previewLimit = 3
const hiddenCount = computed(() => Math.max(0, jobs.value.length - previewLimit))
const visibleJobs = computed(() => {
  if (expanded.value || !hiddenCount.value) return jobs.value
  const selectedIndex = jobs.value.findIndex((job) => job.id === props.focusJob)
  if (selectedIndex >= previewLimit) {
    return [...jobs.value.slice(0, previewLimit - 1), jobs.value[selectedIndex]]
  }
  return jobs.value.slice(0, previewLimit)
})
const error = ref('')
const cancelling = ref('')
const labels = { QUEUED: '排队中', RUNNING: '计算中', CANCELLING: '正在取消', CANCELLED: '已取消', TIMED_OUT: '已超时', FAILED: '失败', SUCCEEDED: '已完成' }
const active = (job) => ['QUEUED', 'RUNNING', 'CANCELLING'].includes(job.state)
const seen = new Set()
const elapsed = (job) => Math.max(0, Math.floor(((job.finished_at ? new Date(job.finished_at).getTime() : Date.now()) - new Date(job.started_at).getTime()) / 1000))
let timer, enabled = false, loading = false, generation = 0

async function refresh() {
  if (!enabled || loading) return
  loading = true
  const version = generation
  try {
    const data = await listBacktestJobs(props.category)
    if (props.focusJob && !(data.items || []).some((j) => j.id === props.focusJob)) {
      try { data.items = [...(data.items || []), await getBacktestJob(props.focusJob)] }
      catch (e) { if (e.status !== 404) throw e }
    }
    if (!enabled || version !== generation) return
    const previous = new Map(jobs.value.map((j) => [j.id, j.state]))
    jobs.value = data.items || []
    error.value = ''
    for (const job of jobs.value) {
      if (job.state === 'SUCCEEDED' && !seen.has(job.id) && (job.id === props.focusJob || ['RUNNING', 'QUEUED', 'CANCELLING'].includes(previous.get(job.id)))) {
        seen.add(job.id)
        emit('completed', job)
      }
    }
  } catch (e) {
    if (enabled && version === generation) error.value = `暂时无法读取任务状态：${e.message}。计算仍在后台运行，将自动重试。`
  } finally {
    loading = false
    if (enabled) { clearTimeout(timer); timer = setTimeout(refresh, 2000) }
  }
}
function start() { if (!enabled) { enabled = true; refresh() } }
function stop() { enabled = false; generation += 1; clearTimeout(timer) }
async function cancel(job) {
  cancelling.value = job.id
  try { await cancelBacktestJob(job.id); await refresh() }
  catch (e) { error.value = e.message }
  finally { cancelling.value = '' }
}
function viewResult(job) {
  if (props.category === 'factor') emit('view', job)
  else openResearch('backtest-review', { run: job.result_id })
}
onMounted(start)
onActivated(start)
onDeactivated(stop)
onUnmounted(stop)
watch(() => [props.refreshKey, props.focusJob], refresh)
</script>

<template>
  <SectionCard :title="title" hint="切换页面或关闭浏览器后，任务仍会继续。回测和因子评估合计最多有 5 个待完成任务。">
    <p v-if="error" role="alert" class="mb-3 text-sm text-amber-300">{{ error }}</p>
    <p v-if="!jobs.length && !error" class="text-sm text-slate-400">暂无{{ title }}</p>
    <div class="space-y-3">
      <article v-for="job in visibleJobs" :key="job.id" class="rounded-xl border border-white/10 p-3" :class="job.id === focusJob ? 'bg-indigo-500/10' : ''">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm text-white">{{ job.label }} <span class="ml-2 text-slate-400">{{ labels[job.state] }}</span></p>
          <div class="flex gap-3 text-sm">
            <button v-if="job.state === 'SUCCEEDED'" class="text-indigo-300" @click="viewResult(job)">查看结果</button>
            <button v-if="active(job)" :disabled="job.state === 'CANCELLING' || cancelling === job.id" class="text-rose-300 disabled:opacity-50" @click="cancel(job)">取消任务</button>
          </div>
        </div>
        <p class="mt-1 text-xs text-slate-400" role="status">
          {{ job.stage }}<template v-if="job.state === 'QUEUED'"> · 队列位置 {{ job.queue_position }}（有空闲名额且当前账户可运行时启动）</template>
          <template v-if="job.state === 'RUNNING' && job.total"> · 已处理 {{ job.completed }} / {{ job.total }} 个交易日</template>
          <template v-if="job.state === 'RUNNING'"> · 已用时 {{ elapsed(job) }} 秒 · 运行上限 {{ Math.round(job.timeout_seconds / 60) }} 分钟</template>
        </p>
        <progress v-if="job.state === 'RUNNING' && job.total" :value="job.completed" :max="job.total" class="mt-2 h-2 w-full accent-indigo-400" :aria-label="`已处理 ${job.completed} / ${job.total} 个交易日`" />
        <p class="mt-1 text-xs text-slate-500">提交于 {{ backtestTimestamp(job.created_at) }}</p>
      </article>
    </div>
    <div v-if="hiddenCount" class="mt-3 flex justify-center">
      <button
        type="button"
        :aria-expanded="expanded"
        class="rounded-full border border-white/10 px-4 py-2 text-sm text-indigo-200 hover:border-indigo-400/40"
        @click="expanded = !expanded"
      >
        {{ expanded ? '收起' : `查看更多（还有 ${hiddenCount} 条）` }}
      </button>
    </div>
  </SectionCard>
</template>
