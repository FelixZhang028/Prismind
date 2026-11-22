<script setup>
import { computed, onActivated, onMounted, ref } from 'vue'
import { listFactors } from '../../api.js'
import { openResearch } from '../researchNavigation.js'
import { FACTOR_STANDARDIZATIONS } from '../factorBacktestDraft.js'
import { parseFactorRows, serializeFactorRows } from '../paperPresentation.js'
import FormField from './FormField.vue'

const props = defineProps({
  modelValue: { type: String, default: '[]' },
  disabled: { type: Boolean, default: false },
  showFactorLabLink: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue'])

const availableFactors = ref([])
const factorToAdd = ref('')

async function loadFactorCatalog() {
  try {
    const res = await listFactors()
    availableFactors.value = res.factors || []
  } catch {
    if (!availableFactors.value.length) availableFactors.value = []
  }
}

onMounted(loadFactorCatalog)
onActivated(loadFactorCatalog)

const factorMap = computed(() => new Map(availableFactors.value.map((f) => [f.name, f])))

const rows = computed(() => parseFactorRows(props.modelValue))
const standardizationValue = computed(() => rows.value[0]?.standardization || 'zscore')
const standardizationLabel = computed(() => FACTOR_STANDARDIZATIONS.find(
  (option) => option.value === standardizationValue.value,
)?.label || 'Z-score')

const addableOptions = computed(() => {
  const chosen = new Set(rows.value.map((row) => row.name))
  return availableFactors.value
    .filter((f) => !chosen.has(f.name))
    .map((f) => ({ value: f.name, label: `${f.display_name || f.name}（${f.name} · ${f.direction === -1 ? '默认反向' : '默认正向'}）` }))
})

function updateRows(nextRows) {
  emit('update:modelValue', serializeFactorRows(nextRows))
}

function setDirection(index, dir) {
  const next = rows.value.map((row, idx) => (idx === index ? { ...row, direction: Number(dir) === -1 ? -1 : 1 } : { ...row }))
  updateRows(next)
}

function setWeight(index, value) {
  const numVal = Number(value)
  if (!Number.isFinite(numVal) || numVal <= 0) return
  const next = rows.value.map((row, idx) => (idx === index ? { ...row, weight: numVal } : { ...row }))
  updateRows(next)
}

function removeRow(index) {
  const next = rows.value.filter((_, idx) => idx !== index).map((row) => ({ ...row }))
  emit('update:modelValue', next.length ? serializeFactorRows(next) : '[]')
}

function setStandardization(value) {
  const next = rows.value.map((row) => ({ ...row, standardization: value }))
  if (next.length) updateRows(next)
}

function addRow() {
  const name = factorToAdd.value
  if (!name) return
  const meta = factorMap.value.get(name)
  const base = rows.value.map((row) => ({ ...row }))
  base.push({
    name,
    display_name: meta?.display_name || name,
    weight: 1,
    direction: meta?.direction === -1 ? -1 : 1,
    clip: Boolean(base[0]?.clip ?? true),
    missing: base[0]?.missing || 'drop',
    standardization: base[0]?.standardization || 'zscore',
  })
  updateRows(base)
  factorToAdd.value = ''
}

function displayLabel(row) {
  return row.display_name || row.custom_factor?.display_name || factorMap.value.get(row.name)?.display_name || row.name
}
</script>

<template>
  <div class="space-y-3 rounded-xl border border-white/10 bg-white/5 p-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <p class="text-sm font-semibold text-white">因子组合配置 · {{ standardizationLabel }}</p>
        <p class="mt-0.5 text-xs text-slate-400">
          可为每个因子直接设置方向（正向越大越好 / 反向越小越好）与正数权重<template v-if="showFactorLabLink">；也可从<a class="mx-1 cursor-pointer text-indigo-300 hover:text-indigo-200" href="?view=factor-lab" @click.prevent="openResearch('factor-lab')">因子研究</a>带入</template>。
        </p>
      </div>
      <select
        v-if="rows.length"
        :value="standardizationValue"
        :disabled="disabled"
        aria-label="截面标准化"
        class="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-white outline-none focus:border-indigo-400/40 disabled:opacity-60"
        @change="setStandardization($event.target.value)"
      >
        <option v-for="o in FACTOR_STANDARDIZATIONS" :key="o.value" :value="o.value" class="bg-ink">{{ o.label }}</option>
      </select>
    </div>

    <div v-if="rows.length" class="space-y-2">
      <div v-for="(factor, index) in rows" :key="`${factor.name}-${index}`" class="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300">
        <span class="min-w-0 flex-1 truncate font-medium text-white">
          {{ displayLabel(factor) }}
          <span class="ml-1 text-xs font-normal text-slate-500">{{ factor.name }}</span>
          <code v-if="factor.custom_factor?.expression" class="ml-1 text-xs font-normal text-slate-400">{{ factor.custom_factor.expression }}</code>
        </span>
        <select
          :value="factor.direction === -1 ? -1 : 1"
          :disabled="disabled"
          :aria-label="`${factor.name} 方向`"
          class="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs text-white outline-none focus:border-indigo-400/40 disabled:opacity-60"
          @change="setDirection(index, $event.target.value)"
        >
          <option :value="1" class="bg-ink">正向（越大越好）</option>
          <option :value="-1" class="bg-ink">反向（越小越好）</option>
        </select>
        <label class="inline-flex items-center gap-1 text-xs text-slate-400">
          权重
          <input
            type="number"
            min="0.01"
            step="0.05"
            :disabled="disabled"
            :value="factor.weight ?? 1"
            :aria-label="`${factor.name} 权重`"
            class="w-20 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-right text-xs text-white outline-none focus:border-indigo-400/40 disabled:opacity-60"
            @change="setWeight(index, $event.target.value)"
          />
        </label>
        <button type="button" :disabled="disabled" class="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-rose-300 disabled:opacity-40" @click="removeRow(index)">移除</button>
      </div>
    </div>
    <p v-else class="rounded-xl border border-dashed border-white/10 px-3 py-2.5 text-xs text-slate-400">
      暂未选择因子。请在下方添加至少 1 个因子，或从「因子研究」一键带入已验证的多因子组合。
    </p>

    <div v-if="addableOptions.length" class="flex flex-wrap items-center gap-2">
      <select v-model="factorToAdd" :disabled="disabled" aria-label="添加因子" class="min-w-[220px] flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-white outline-none focus:border-indigo-400/40 disabled:opacity-60">
        <option value="" class="bg-ink">选择一个因子添加到组合…</option>
        <option v-for="o in addableOptions" :key="o.value" :value="o.value" class="bg-ink">{{ o.label }}</option>
      </select>
      <button type="button" :disabled="disabled || !factorToAdd" class="rounded-full border border-indigo-400/40 bg-indigo-500/15 px-3.5 py-1.5 text-xs font-medium text-indigo-200 transition hover:bg-indigo-500/25 disabled:opacity-40" @click="addRow">+ 添加因子</button>
    </div>

    <details class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-400">
      <summary class="cursor-pointer">高级：查看 / 编辑原始 JSON（支持 direction: 1 或 -1）</summary>
      <div class="mt-2">
        <FormField
          label="因子组合定义"
          type="textarea"
          :rows="3"
          :disabled="disabled"
          :model-value="modelValue"
          hint='JSON 列表，如 [{"name": "momentum_20", "weight": 1.0, "direction": -1}]'
          @update:model-value="emit('update:modelValue', $event)"
        />
      </div>
    </details>
  </div>
</template>
