<script setup>
// 提建议：一句话就能提交，自动带上是在哪个页面提的。侧栏底部和头像菜单都能打开。
import { computed, nextTick, onMounted, ref } from 'vue'
import { submitSuggestion } from '../../api.js'
import { SUGGESTION_MAX, lengthNote, suggestionContext } from '../feedback.js'

const props = defineProps({
  view: { type: String, default: '' },
  viewLabel: { type: String, default: '' },
  routeContext: { type: Object, default: () => ({}) },
  notify: { type: Function, default: () => {} },
})
const emit = defineEmits(['close'])
const githubUrl = 'https://github.com/FelixZhang028/Prismind/issues/new/choose'

const text = ref('')
const contactOk = ref(false)
const sending = ref(false)
const error = ref('')
const box = ref(null)
const note = computed(() => lengthNote(text.value, SUGGESTION_MAX))
const tooLong = computed(() => text.value.trim().length > SUGGESTION_MAX)
onMounted(() => nextTick(() => box.value?.focus()))

async function send() {
  error.value = ''
  if (!text.value.trim()) return (error.value = '写一句建议再提交')
  if (tooLong.value) return (error.value = `最多 ${SUGGESTION_MAX} 个字`)
  sending.value = true
  try {
    await submitSuggestion({ text: text.value.trim(), view: props.view, contact_ok: contactOk.value, context: suggestionContext(props.routeContext) })
    props.notify('收到了，谢谢。处理以后会在更新说明里告诉大家。')
    emit('close')
  } catch (e) {
    error.value = e.message || '提交失败，请稍后再试'
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" @click.self="emit('close')" @keydown.esc="emit('close')">
    <form class="glass glass-sheen w-full max-w-lg rounded-2xl p-6" role="dialog" aria-modal="true" aria-labelledby="suggest-title" @submit.prevent="send">
      <h2 id="suggest-title" class="text-lg font-bold text-white">提建议</h2>
      <p class="mt-1 text-sm text-slate-400">哪里不好用、看不懂，或者想要什么功能，一句话就行。</p>
      <textarea ref="box" v-model="text" rows="4" maxlength="600" aria-label="建议"
        placeholder="回测结果里能不能显示每只股票赚了多少？"
        class="mt-4 w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-indigo-400/50" />
      <div class="mt-1 flex justify-between text-xs">
        <span class="text-slate-500">{{ viewLabel ? `来自页面：${viewLabel}` : '' }}</span>
        <span :class="tooLong ? 'text-rose-300' : 'text-slate-500'">{{ note }}</span>
      </div>
      <label class="mt-3 flex items-center gap-2 text-sm text-slate-300">
        <input v-model="contactOk" type="checkbox" class="h-4 w-4 rounded border-white/20 bg-white/5 accent-indigo-500" />
        可以用注册邮箱联系我
      </label>
      <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">{{ error }}</p>
      <div class="mt-5 flex items-center justify-between gap-3">
        <a :href="githubUrl" target="_blank" rel="noopener noreferrer" class="text-xs text-slate-500 hover:text-slate-300">开发者也可以在 GitHub 提 Issue ↗</a>
        <div class="flex gap-2">
          <button type="button" class="rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5" @click="emit('close')">取消</button>
          <button type="submit" :disabled="sending" class="rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-semibold text-white disabled:opacity-60">{{ sending ? '提交中…' : '提交' }}</button>
        </div>
      </div>
    </form>
  </div>
</template>
