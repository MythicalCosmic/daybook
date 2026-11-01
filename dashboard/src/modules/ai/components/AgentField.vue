<script setup lang="ts">
/**
 * One agent setting, drawn from its `field` (contract §5): a switch for yes/no, a stepper with its
 * unit for numbers, a time picker, and side-by-side buttons (or a select, for many) for choices.
 * Values leave already checked against the field (`coerceValue`).
 */
import { computed } from "vue";

import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { coerceValue, fieldControl } from "../lib";
import type { AgentConfigValue, AgentField } from "../types";

const props = withDefaults(defineProps<{ field: AgentField; value: AgentConfigValue | undefined; disabled?: boolean; saving?: boolean }>(), {
  disabled: false,
  saving: false,
});
const emit = defineEmits<{ change: [value: AgentConfigValue] }>();

const { isPhone } = useBreakpoints();
// Side-by-side choices are too small for a finger: phones get the select instead.
const control = computed(() => {
  const chosen = fieldControl(props.field);
  return chosen.kind === "segmented" && isPhone.value ? { kind: "select" as const, options: chosen.options } : chosen;
});
const size = computed(() => (isPhone.value ? "lg" : "md"));

function change(value: unknown): void {
  const next = coerceValue(props.field, value);
  if (next === null || next === props.value) return;
  emit("change", next);
}
</script>

<template>
  <ToggleSwitch
    v-if="control.kind === 'switch'"
    layout="row"
    :model-value="value === true"
    :label="field.label"
    :description="field.help || undefined"
    :loading="saving"
    :disabled="disabled"
    :data-field="field.key"
    @update:model-value="change"
  />
  <FormField v-else :label="field.label" :hint="field.help || undefined" :disabled="disabled" :data-field="field.key">
    <NumberInput
      v-if="control.kind === 'stepper'"
      class="max-w-[220px]"
      :model-value="typeof value === 'number' ? value : null"
      :min="control.min"
      :max="control.max"
      :step="1"
      :suffix="control.unit || undefined"
      :size="size"
      steppers
      :disabled="disabled"
      @update:model-value="(next: number | null) => next !== null && change(next)"
    />
    <TimePicker
      v-else-if="control.kind === 'time'"
      class="max-w-[160px]"
      :model-value="typeof value === 'string' ? value : null"
      :step="15"
      :size="size"
      :disabled="disabled"
      @update:model-value="(next: string | null) => next && change(next)"
    />
    <SegmentedControl
      v-else-if="control.kind === 'segmented'"
      :model-value="String(value ?? '')"
      :options="control.options.map((option) => ({ value: option.value, label: option.label }))"
      :disabled="disabled"
      :aria-label="field.label"
      @update:model-value="change"
    />
    <SelectBox
      v-else
      class="sm:max-w-[320px]"
      :size="size"
      :model-value="String(value ?? '')"
      :options="control.options.map((option) => ({ value: option.value, label: option.label }))"
      :disabled="disabled"
      @update:model-value="(next) => next !== null && change(next)"
    />
  </FormField>
</template>
