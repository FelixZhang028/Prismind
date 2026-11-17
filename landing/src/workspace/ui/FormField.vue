<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, default: '' },
  type: { type: String, default: 'text' }, // text | number | date | select | textarea | checkbox
  modelValue: { type: [String, Number, Boolean], default: '' },
  options: { type: Array, default: () => [] }, // [{ value, label }]
  wrapSelection: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  min: { type: Number, default: null },
  max: { type: Number, default: null },
  step: { type: [Number, String], default: null },
  disabled: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  rows: { type: Number, default: 3 },
})
const emit = defineEmits(['update:modelValue'])
const selectedLabel = computed(() => props.options.find((option) => String(option.value) === String(props.modelValue))?.label || props.placeholder)
</script>

<template>
  <label class="block">
    <span class="mb-1 block text-xs text-slate-400">{{ label }}</span>
    <div v-if="type === 'select'" :class="wrapSelection && 'relative min-w-0 rounded-xl border border-white/10 bg-white/5 focus-within:border-indigo-400/40'">
      <span v-if="wrapSelection" aria-hidden="true" class="flex min-h-10 items-center gap-3 px-3 py-2.5 text-sm text-white" :class="disabled && 'opacity-50'">
        <span class="min-w-0 flex-1 whitespace-normal [overflow-wrap:anywhere]">{{ selectedLabel }}</span>
        <span class="h-1.5 w-1.5 shrink-0 -translate-y-0.5 rotate-45 border-b border-r border-current" />
      </span>
      <select
        :value="modelValue"
        :disabled="disabled"
        :class="wrapSelection
          ? 'absolute inset-0 h-full w-full cursor-pointer text-sm text-white opacity-0 disabled:cursor-default'
          : 'w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/40 disabled:opacity-50'"
        @change="emit('update:modelValue', $event.target.value)"
      >
        <option v-for="o in options" :key="o.value" :value="o.value" :disabled="o.disabled" class="bg-ink">{{ o.label }}</option>
      </select>
    </div>
    <textarea
      v-else-if="type === 'textarea'"
      :value="modelValue"
      :placeholder="placeholder"
      :rows="rows"
      :disabled="disabled"
      class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/40 disabled:opacity-50"
      @input="emit('update:modelValue', $event.target.value)"
    />
    <div v-else-if="type === 'checkbox'" class="flex items-center gap-2.5 pt-1">
      <input
        type="checkbox"
        :checked="modelValue"
        :disabled="disabled"
        class="h-4 w-4 rounded border-white/20 bg-white/5 accent-indigo-500"
        @change="emit('update:modelValue', $event.target.checked)"
      />
      <span class="text-sm text-slate-300">{{ hint || label }}</span>
    </div>
    <input
      v-else
      :type="type === 'number' ? 'number' : type"
      :value="modelValue"
      :placeholder="placeholder"
      :min="min"
      :max="max"
      :step="step"
      :disabled="disabled"
      class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white outline-none focus:border-indigo-400/40 disabled:opacity-50"
      @input="emit('update:modelValue', $event.target.value)"
    />
    <p v-if="type !== 'checkbox' && hint" class="mt-1 text-xs text-slate-500">{{ hint }}</p>
  </label>
</template>
