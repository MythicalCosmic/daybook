<script setup lang="ts" generic="V extends string | number">
/**
 * A choice between a few options that deserve a sentence each, as cards (pay type, AI model,
 * "Standard / Deep analysis"). Arrow keys move between cards.
 *
 *   <RadioCards v-model="payType" :options="[{ value: 'monthly', label: …, description: …, icon: CalendarDays }]" :columns="3" />
 */
import { RadioGroupIndicator, RadioGroupItem, RadioGroupRoot } from "reka-ui";
import type { Component } from "vue";

import { useControl } from "./field";

export interface RadioCardOption<T> {
  value: T;
  label: string;
  description?: string;
  icon?: Component;
  /** Short text on the right ("≈ 120 so‘m per question", "Recommended"). */
  badge?: string;
  disabled?: boolean;
}

const model = defineModel<V | null>({ default: null });

const props = withDefaults(
  defineProps<{
    options: RadioCardOption<V>[];
    columns?: 1 | 2 | 3 | 4;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    orientation?: "horizontal" | "vertical";
  }>(),
  { columns: 2, disabled: false, invalid: false, id: undefined, orientation: "horizontal" },
);

const control = useControl(props);
const grid = { 1: "", 2: "@sm:grid-cols-2", 3: "@sm:grid-cols-2 @2xl:grid-cols-3", 4: "@sm:grid-cols-2 @4xl:grid-cols-4" } as const;

function onUpdate(value: unknown): void {
  model.value = value as V;
}
</script>

<template>
  <div class="@container min-w-0">
  <RadioGroupRoot
    :id="control.id.value"
    :model-value="model ?? undefined"
    :disabled="control.disabled.value"
    :aria-labelledby="control.labelId.value"
    :aria-describedby="control.describedBy.value"
    :orientation="orientation"
    loop
    :class="['grid grid-cols-1 gap-2', grid[columns]]"
    @update:model-value="onUpdate"
  >
    <RadioGroupItem
      v-for="option in options"
      :key="String(option.value)"
      :value="option.value"
      :disabled="option.disabled"
      :class="[
        'pressable group relative flex items-start gap-3 rounded-[10px] border bg-surface p-3 text-left outline-offset-2',
        'border-line hover:border-line-strong data-[state=checked]:border-primary data-[state=checked]:bg-accent-soft/40',
        'data-[state=checked]:shadow-[0_0_0_1px_var(--c-primary)] data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50',
        control.invalid.value && 'border-danger',
      ]"
    >
      <span
        v-if="option.icon"
        class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted transition-colors group-data-[state=checked]:bg-primary group-data-[state=checked]:text-on-primary dark:bg-surface-3"
      >
        <component :is="option.icon" :size="16" aria-hidden="true" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block text-base font-semibold leading-5 text-fg">{{ option.label }}</span>
        <span v-if="option.description" class="mt-0.5 block text-sm text-muted">{{ option.description }}</span>
        <span v-if="option.badge" class="mt-2 inline-flex whitespace-nowrap rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold tabular-nums text-muted group-data-[state=checked]:bg-surface dark:bg-surface-3">{{ option.badge }}</span>
      </span>
      <span
        class="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border border-line-strong bg-surface transition-colors group-data-[state=checked]:border-primary"
        aria-hidden="true"
      >
        <RadioGroupIndicator class="size-2 rounded-full bg-primary" />
      </span>
    </RadioGroupItem>
  </RadioGroupRoot>
  </div>
</template>
