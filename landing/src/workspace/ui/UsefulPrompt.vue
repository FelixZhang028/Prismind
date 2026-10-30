<script setup>
// “这个结果对你有用吗？”：事件研究、策略回测、AI 个股分析第一次出结果时问一次。
// 点了有用或没用就记下；之后可以补一句“哪里可以更好”，不补也行。回答过的功能以后不再问。
import { onMounted, ref } from 'vue'
import { rateUseful, usefulAnswered } from '../../api.js'
import { SUGGESTION_MAX, loadAnswered, markAnswered, shouldAsk } from '../feedback.js'

const props = defineProps({
  feature: { type: String, required: true },       // event-study / backtest-review / agent-lab
  context: { type: Object, default: () => ({}) },  // 例如 { run: 8 }，方便复现
})

const step = ref('hidden') // hidden | ask | comment | thanks
const text = ref('')
const busy = ref(false)
onMounted(async () => {
  const answered = await loadAnswered(usefulAnswered)
  if (shouldAsk(answered, props.feature)) step.value = 'ask'
})

async function rate(value) {
  busy.value = true
  try {
    await rateUseful({ feature: props.feature, rating: value, context: props.context })
    markAnswered(props.feature)
    step.value = 'comment'
  } catch {
    step.value = 'hidden'      // 记不下来就算了，不打扰
  } finally {
    busy.value = false
  }
}
async function comment() {
  const value = text.value.trim()
  if (value) {
    try { await rateUseful({ feature: props.feature, text: value.slice(0, SUGGESTION_MAX) }) } catch { /* 评价已经记下了 */ }
  }
  step.value = 'thanks'
  setTimeout(() => (step.value = 'hidden'), 2500)
}
</script>

<template>
  <section v-if="step !== 'hidden'" class="rounded-xl border border-indigo-400/20 bg-indigo-500/5 px-4 py-3" aria-label="这个结果对你有用吗">
    <div v-if="step === 'ask'" class="flex flex-wrap items-center gap-3 text-sm">
      <span class="text-slate-200">这个结果对你有用吗？</span>
      <button type="button" :disabled="busy" class="rounded-full border border-white/10 px-3 py-1 text-slate-200 hover:bg-white/10" @click="rate(1)">👍 有用</button>
      <button type="button" :disabled="busy" class="rounded-full border border-white/10 px-3 py-1 text-slate-200 hover:bg-white/10" @click="rate(-1)">👎 没用</button>
      <button type="button" class="ml-auto text-xs text-slate-500 hover:text-slate-300" @click="step = 'hidden'">以后再说</button>
    </div>
    <form v-else-if="step === 'comment'" class="flex flex-wrap items-center gap-2 text-sm" @submit.prevent="comment">
      <span class="text-slate-300">谢谢！哪里可以更好？</span>
      <input v-model="text" maxlength="500" placeholder="选填，一句话就行" aria-label="哪里可以更好"
        class="min-w-[12rem] flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-white outline-none placeholder:text-slate-500 focus:border-indigo-400/50" />
      <button type="submit" class="rounded-full bg-indigo-500/80 px-4 py-1.5 text-white hover:bg-indigo-500">{{ text.trim() ? '发送' : '不用了' }}</button>
    </form>
    <p v-else class="text-sm text-slate-300">收到了，谢谢。</p>
  </section>
</template>
