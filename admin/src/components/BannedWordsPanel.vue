<script setup>
import { computed, onMounted, ref } from 'vue'
import { addBannedWords, bannedWords, deleteBannedWord } from '../api.js'

// 昵称违禁词：内置的防止冒充平台，删不掉；自己加的马上生效。注册和用户自己改昵称时检查，管理员改的不检查。
const emit = defineEmits(['notify', 'changed'])
const items = ref([])
const wordMax = ref(20)
const error = ref('')
const draft = ref('')
const saving = ref(false)
const removing = ref('')
const keyword = ref('')

const builtin = computed(() => items.value.filter((i) => i.builtin))
const custom = computed(() => {
  const word = keyword.value.trim().toLowerCase()
  return items.value.filter((i) => !i.builtin && (!word || i.word.toLowerCase().includes(word)))
})
const customCount = computed(() => items.value.filter((i) => !i.builtin).length)

async function load() {
  error.value = ''
  try {
    const data = await bannedWords()
    items.value = data.items
    wordMax.value = data.word_max
  } catch (e) {
    error.value = e.message || '加载失败'
  }
}
onMounted(load)

async function add() {
  if (!draft.value.trim()) return
  saving.value = true
  try {
    const { added, skipped } = await addBannedWords(draft.value)
    draft.value = ''
    const parts = [added.length ? `加了 ${added.length} 个` : '没有新加的词']
    if (skipped.length) parts.push(`${skipped.length} 个已经有了：${skipped.join('、')}`)
    emit('notify', parts.join('；'))
    await load()
    emit('changed')                                          // 用户列表里重新标出含违禁词的昵称
  } catch (e) {
    emit('notify', e.message || '添加失败')
  } finally {
    saving.value = false
  }
}

async function remove(word) {
  if (!window.confirm(`删掉违禁词「${word}」？删掉以后，含这个词的昵称就能用了。`)) return
  removing.value = word
  try {
    await deleteBannedWord(word)
    emit('notify', `已删掉「${word}」`)
    await load()
    emit('changed')
  } catch (e) {
    emit('notify', e.message || '删除失败')
  } finally {
    removing.value = ''
  }
}

const time = (value) => (value ? new Date(value).toLocaleString() : '—')
</script>

<template>
  <div class="space-y-6">
    <p v-if="error" role="alert" class="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-200">{{ error }}</p>

    <section class="glass rounded-2xl p-5" aria-label="加违禁词">
      <h2 class="text-sm font-semibold text-white">加违禁词</h2>
      <p class="mt-2 text-sm text-slate-400">注册和用户自己改昵称时检查：昵称里只要包含其中一个词就不能用。比较时不分大小写、全角半角，也会先去掉空格和符号，所以“管 理 员”“官-方”也会被拦下。管理员改的昵称不检查。</p>
      <form class="mt-4 space-y-3" @submit.prevent="add">
        <textarea v-model="draft" rows="3" aria-label="要加的违禁词"
          placeholder="可以一次粘贴很多个，用空格、逗号、顿号或换行分开"
          class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-400/40" />
        <div class="flex flex-wrap items-center gap-3">
          <button type="submit" :disabled="saving || !draft.trim()" class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50">{{ saving ? '添加中…' : '添加' }}</button>
          <span class="text-xs text-slate-500">每个词最多 {{ wordMax }} 个字，重复的会自动跳过；加了马上生效。</span>
        </div>
      </form>
    </section>

    <section class="glass rounded-2xl p-5" aria-label="内置的违禁词">
      <h2 class="text-sm font-semibold text-white">内置的词</h2>
      <p class="mt-2 text-xs text-slate-500">防止有人冒充平台，写在程序里，不能删除。</p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span v-for="i in builtin" :key="i.word" class="rounded-full border border-violet-400/30 bg-violet-400/10 px-3 py-1 text-sm text-violet-200">{{ i.word }}</span>
      </div>
    </section>

    <section class="glass rounded-2xl p-5" aria-label="自己加的违禁词">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-sm font-semibold text-white">自己加的词</h2>
        <span class="text-xs text-slate-500">共 {{ customCount }} 个</span>
        <input v-if="customCount" v-model="keyword" placeholder="搜索" aria-label="搜索违禁词"
          class="ml-auto w-40 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-sm text-slate-200 placeholder-slate-500 outline-none focus:border-indigo-400/40" />
      </div>
      <p v-if="!customCount" class="mt-4 text-sm text-slate-500">还没有加过。</p>
      <div v-else class="mt-4 overflow-x-auto">
        <table class="[&_td]:whitespace-nowrap [&_th]:whitespace-nowrap [&_td]:px-3 [&_th]:px-3 [&_td:first-child]:pl-0 [&_th:first-child]:pl-0 [&_td:last-child]:pr-0 [&_th:last-child]:pr-0 w-full min-w-[520px] text-left text-sm">
          <thead>
            <tr class="text-xs text-slate-500">
              <th class="pb-3 font-medium">词</th>
              <th class="pb-3 font-medium">谁加的</th>
              <th class="pb-3 font-medium">添加时间</th>
              <th class="pb-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-white/5">
            <tr v-for="i in custom" :key="i.word" class="text-slate-300">
              <td class="py-3 font-medium text-white">{{ i.word }}</td>
              <td class="py-3 text-slate-400">{{ i.created_by || '—' }}</td>
              <td class="py-3 text-slate-400">{{ time(i.created_at) }}</td>
              <td class="py-3 text-right">
                <button type="button" :disabled="removing === i.word" class="rounded-full border border-rose-400/30 px-3 py-1 text-xs text-rose-300 transition hover:bg-rose-400/10 disabled:opacity-50" @click="remove(i.word)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="!custom.length" class="py-6 text-center text-sm text-slate-500">没有符合条件的词。</p>
      </div>
    </section>
  </div>
</template>
