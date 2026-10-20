<script setup lang="ts">
/**
 * Days of the week as seven toggles, Monday first. Values follow the backend (Python's
 * `date.weekday()`): 0 = Monday … 6 = Sunday. `presets` adds "Every day · Mon–Fri · Weekend".
 *
 *   <WeekdayPicker v-model="routine.weekdays" presets />
 */
import { ToggleGroupItem, ToggleGroupRoot } from "reka-ui";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useControl } from "./field";

const model = defineModel<number[]>({ default: () => [] });

const props = withDefaults(defineProps<{ presets?: boolean; disabled?: boolean; size?: "sm" | "md"; id?: string; invalid?: boolean }>(), {
  presets: false,
  disabled: false,
  size: "md",
  id: undefined,
  invalid: false,
});

const { t } = useI18n();
const control = useControl(props);
const DAYS = [0, 1, 2, 3, 4, 5, 6] as const;

const PRESETS: Array<{ id: string; days: number[] }> = [
  { id: "every", days: [0, 1, 2, 3, 4, 5, 6] },
  { id: "workdays", days: [0, 1, 2, 3, 4] },
  { id: "weekend", days: [5, 6] },
];

const sorted = (days: readonly number[]) => [...new Set(days)].sort((a, b) => a - b);
const active = computed(() => PRESETS.find((preset) => sorted(preset.days).join() === sorted(model.value).join())?.id ?? null);

function onUpdate(value: unknown): void {
  const list = Array.isArray(value) ? value.map((v) => Number(v)) : [];
  model.value = sorted(list);
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <ToggleGroupRoot
      :id="control.id.value"
      type="multiple"
      :model-value="model.map(String)"
      :disabled="control.disabled.value"
      :aria-labelledby="control.labelId.value"
      :aria-describedby="control.describedBy.value"
      class="flex flex-wrap gap-1"
      loop
      @update:model-value="onUpdate"
    >
      <ToggleGroupItem
        v-for="day in DAYS"
        :key="day"
        :value="String(day)"
        :aria-label="t(`common.weekday.long.${day}`)"
        :class="[
          'pressable grid place-items-center rounded-full border font-semibold outline-offset-2',
          size === 'sm' ? 'size-7 text-[11px]' : 'size-9 text-xs',
          'border-line-strong bg-surface text-muted hover:border-[color-mix(in_srgb,var(--c-text)_35%,transparent)] hover:text-fg',
          'data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-on-primary',
          day >= 5 && 'data-[state=off]:text-subtle',
          control.invalid.value && 'border-danger',
          'disabled:cursor-not-allowed disabled:opacity-50',
        ]"
      >
        {{ t(`common.weekday.short.${day}`) }}
      </ToggleGroupItem>
    </ToggleGroupRoot>
    <div v-if="presets" class="flex flex-wrap gap-1">
      <button
        v-for="preset in PRESETS"
        :key="preset.id"
        type="button"
        :disabled="control.disabled.value"
        :class="[
          'rounded-full px-2 py-0.5 text-xs font-semibold transition-colors disabled:opacity-50',
          active === preset.id ? 'bg-accent-soft text-accent-fg' : 'text-muted hover:bg-highlight hover:text-fg',
        ]"
        @click="model = [...preset.days]"
      >
        {{ t(`common.weekday.preset.${preset.id}`) }}
      </button>
    </div>
  </div>
</template>
