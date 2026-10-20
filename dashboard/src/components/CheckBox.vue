<script setup lang="ts">
/**
 * A checkbox with an optional label and description. `indeterminate` shows the dash (a "select all"
 * with some rows chosen). Without a label it needs `aria-label`.
 *
 *   <CheckBox v-model="form.values.notify" :label="t('tasks.notify')" :description="t('tasks.notifyHint')" />
 */
import { Check, Minus } from "@lucide/vue";
import { CheckboxIndicator, CheckboxRoot } from "reka-ui";
import { computed, useId } from "vue";

import { useControl } from "./field";

const model = defineModel<boolean>({ default: false });

const props = withDefaults(
  defineProps<{
    label?: string;
    description?: string;
    indeterminate?: boolean;
    disabled?: boolean;
    invalid?: boolean;
    id?: string;
    size?: "sm" | "md";
  }>(),
  { label: undefined, description: undefined, indeterminate: false, disabled: false, invalid: false, id: undefined, size: "md" },
);

const control = useControl(props);
const descriptionId = useId();
const state = computed<boolean | "indeterminate">(() => (props.indeterminate ? "indeterminate" : model.value));

function update(value: boolean | "indeterminate"): void {
  model.value = value === true;
}
</script>

<template>
  <label
    :class="['group inline-flex min-w-0 items-start gap-2.5', control.disabled.value ? 'cursor-not-allowed opacity-55' : 'cursor-pointer']"
    :for="control.id.value"
  >
    <CheckboxRoot
      :id="control.id.value"
      :model-value="state"
      :disabled="control.disabled.value"
      :aria-invalid="control.invalid.value || undefined"
      :aria-describedby="[description ? descriptionId : null, control.describedBy.value].filter(Boolean).join(' ') || undefined"
      :class="[
        'pressable grid shrink-0 place-items-center rounded-[5px] border bg-surface shadow-xs outline-offset-2',
        size === 'sm' ? 'mt-px size-[15px]' : 'mt-[2px] size-4',
        'border-line-strong group-hover:border-[color-mix(in_srgb,var(--c-text)_35%,transparent)]',
        'data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-on-primary',
        'data-[state=indeterminate]:border-primary data-[state=indeterminate]:bg-primary data-[state=indeterminate]:text-on-primary',
        control.invalid.value && 'border-danger',
      ]"
      @update:model-value="update"
    >
      <CheckboxIndicator class="grid place-items-center">
        <Minus v-if="state === 'indeterminate'" :size="size === 'sm' ? 10 : 12" :stroke-width="3" />
        <Check v-else :size="size === 'sm' ? 10 : 12" :stroke-width="3" />
      </CheckboxIndicator>
    </CheckboxRoot>
    <span v-if="label || description || $slots.default" class="min-w-0">
      <span v-if="label || $slots.default" :class="['block font-medium text-fg', size === 'sm' ? 'text-sm' : 'text-base']"><slot>{{ label }}</slot></span>
      <span v-if="description" :id="descriptionId" class="mt-0.5 block text-sm text-muted">{{ description }}</span>
    </span>
  </label>
</template>
