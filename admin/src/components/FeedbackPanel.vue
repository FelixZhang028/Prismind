<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { adminFeedback, updateFeedback } from '../api.js'
import { number, pageName, time, usefulText } from '../format.js'

// 用户反馈：功能台里提的建议、第一次出结果后的“有用吗”、注销时匿名的离开原因。
// 上面是最近 30 天的汇总，下面是列表：可以按种类和状态筛选，标成已读、已处理，写一句备注（只有管理员看得到）。
const emit = defineEmits(['notify', 'changed'])
const PAGE = 100
const kind = ref('suggestion')
const status = ref('')
const data = ref(null)
const items = ref([])
const error = ref('')
const loading = ref(false)
const notes = ref({})
const saving = ref(0)

const summary = computed(() => data.value?.summary)
const leaveTotal = computed(() => (summary.value?.leave || []).reduce((sum, r) => sum + r.count, 0))
const more = computed(() => data.value && items.value.length < data.value.total)

async function load(append = false) {
  loading.value = true
  error.value = ''
  try {
    const result = await adminFeedback({ kind: kind.value, status: status.value, limit: PAGE, offset: append ? items.value.length : 0 })
    data.value = result
    items.value = append ? [...items.value, ...result.items] : result.items
    for (const item of result.items) notes.value[item.id] = item.admin_note
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
watch([kind, status], () => load())

async function save(item, patch) {
  saving.value = item.id
  try {
    const next = await updateFeedback(item.id, patch)
    Object.assign(item, next)
    if (patch.note !== undefined) emit('notify', '备注已保存')
    if (patch.status && data.value?.summary && item.kind === 'suggestion') {
      await load()                                   // 未读数字跟着变
      emit('changed')
    }
  } catch (e) {
    emit('notify', e.message || '保存失败')
  } finally {
    saving.value = 0
  }
}

const statusTone = { new: 'border-amber-400/40 text-amber-200', read: 'border-white/15 text-slate-300', done: 'border-emerald-400/40 text-emerald-200' }
const kindTone = { suggestion: 'text-indigo-200', useful: 'text-violet-200', leave: 'text-rose-200' }
</script>

<template>
  <div class="space-y-6">
    <p v-if="error" role="alert" class="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">{{ error }}</p>

    <section v-if="summary" class="grid gap-5 lg:grid-cols-3" aria-label="反馈汇总">
      <div class="glass rounded-2xl p-5">
        <h2 class="text-sm font-semibold text-white">没看过的建议</h2>
        <p class="mt-3 text-3xl font-bold text-white">{{ number(summary.unread) }}</p>
        <p class="mt-2 text-xs text-slate-500">标成“已读”或“已处理”以后就不算了</p>
      </div>
      <div class="glass rounded-2xl p-5">
        <h2 class="text-sm font-semibold text-white">结果有用吗（最近 {{ summary.days }} 天）</h2>
        <dl class="mt-3 space-y-2 text-sm">
          <div v-for="u in summary.useful" :key="u.feature" class="flex justify-between gap-3">
            <dt class="text-slate-400">{{ u.label }}</dt><dd class="text-slate-200">{{ usefulText(u) }}</dd>
          </div>
        </dl>
      </div>
      <div class="glass rounded-2xl p-5">
        <h2 class="text-sm font-semibold text-white">离开原因（最近 {{ summary.days }} 天，共 {{ leaveTotal }} 人）</h2>
        <dl class="mt-3 space-y-2 text-sm">
          <div v-for="r in summary.leave" :key="r.reason" class="flex items-center gap-3">
            <dt class="w-20 shrink-0 text-slate-400">{{ r.label }}</dt>
            <dd class="flex flex-1 items-center gap-2">
              <span class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10" aria-hidden="true"><span class="block h-full rounded-full bg-rose-400/70" :style="{ width: `${leaveTotal ? (r.count / leaveTotal) * 100 : 0}%` }" /></span>
              <span class="w-6 text-right text-slate-200">{{ r.count }}</span>
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <section class="glass rounded-2xl p-5" aria-label="反馈列表">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-sm font-semibold text-white">反馈列表</h2>
        <span v-if="data" class="text-xs text-slate-500">共 {{ number(data.total) }} 条</span>
        <select v-model="kind" aria-label="种类" class="ml-auto rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-200">
          <option value="">全部种类</option>
          <option v-for="(label, key) in data?.kinds || {}" :key="key" :value="key">{{ label }}</option>
        </select>
        <select v-model="status" aria-label="状态" class="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-200">
          <option value="">全部状态</option>
          <option v-for="(label, key) in data?.statuses || {}" :key="key" :value="key">{{ label }}</option>
        </select>
      </div>

      <p v-if="!loading && !items.length" class="mt-4 text-sm text-slate-500">没有符合条件的反馈。</p>
      <ul class="mt-4 divide-y divide-white/5">
        <li v-for="item in items" :key="item.id" class="py-4">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span class="font-medium" :class="kindTone[item.kind]">{{ data?.kinds?.[item.kind] || item.kind }}</span>
            <span>{{ time(item.created_at) }}</span>
            <span v-if="item.kind !== 'leave'">页面：{{ pageName(item.view) }}</span>
            <span v-if="item.context?.run">回测 run-{{ item.context.run }}</span>
            <span v-if="item.user">{{ item.user.name }}<template v-if="item.user.email"> · {{ item.user.email }}（同意联系）</template></span>
            <span v-else-if="item.kind === 'leave'">匿名</span>
            <span class="ml-auto rounded-full border px-2 py-0.5" :class="statusTone[item.status]">{{ data?.statuses?.[item.status] || item.status }}</span>
          </div>
          <p class="mt-2 text-sm text-slate-200">
            <template v-if="item.kind === 'useful'">{{ item.rating > 0 ? '👍 有用' : '👎 没用' }}<template v-if="item.text">：</template></template>
            <template v-else-if="item.kind === 'leave'">{{ item.reason }}<template v-if="item.text">：</template></template>
            <span class="whitespace-pre-wrap">{{ item.text }}</span>
          </p>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <button v-if="item.status !== 'read'" type="button" :disabled="saving === item.id" class="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/5" @click="save(item, { status: 'read' })">标为已读</button>
            <button v-if="item.status !== 'done'" type="button" :disabled="saving === item.id" class="rounded-full border border-emerald-400/30 px-3 py-1 text-xs text-emerald-200 hover:bg-emerald-400/10" @click="save(item, { status: 'done' })">标为已处理</button>
            <button v-if="item.status !== 'new'" type="button" :disabled="saving === item.id" class="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-400 hover:bg-white/5" @click="save(item, { status: 'new' })">改回新的</button>
            <form class="flex min-w-[16rem] flex-1 items-center gap-2" @submit.prevent="save(item, { note: notes[item.id] || '' })">
              <input v-model="notes[item.id]" maxlength="300" placeholder="备注（只有管理员看得到），例如：已在 #95 修复" aria-label="备注"
                class="flex-1 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200 placeholder-slate-500 outline-none focus:border-indigo-400/40" />
              <button type="submit" :disabled="saving === item.id || (notes[item.id] || '') === item.admin_note" class="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 disabled:opacity-40">保存备注</button>
            </form>
          </div>
        </li>
      </ul>
      <button v-if="more" type="button" :disabled="loading" class="mt-4 rounded-full border border-white/10 px-4 py-1.5 text-sm text-slate-300 hover:bg-white/5" @click="load(true)">{{ loading ? '加载中…' : '加载更多' }}</button>
    </section>
  </div>
</template>
