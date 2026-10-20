<script setup lang="ts">
/**
 * A label, an optional hint and an error around one control. The control inside picks up the id,
 * `aria-describedby` and the invalid state by itself (components/field.ts):
 *
 *   <FormField :label="t('finance.amount')" :error="form.errors.amount" required>
 *     <MoneyInput v-model="form.values.amount" />
 *   </FormField>
 *
 * `layout="inline"` puts the label on the left from tablet width up (settings panels).
 */
import { CircleAlert } from "@lucide/vue";
import { computed, useId } from "vue";
import { useI18n } from "vue-i18n";

import { provideField } from "./field";

const props = withDefaults(
  defineProps<{
    label?: string;
    hint?: string;
    error?: string | null;
    required?: boolean;
    optional?: boolean;
    disabled?: boolean;
    layout?: "stacked" | "inline";
    /** Use when the control renders its own id. */
    for?: string;
    /** Shows "12/200" under the field. */
    count?: number;
    max?: number;
  }>(),
  {
    label: undefined,
    hint: undefined,
    error: undefined,
    required: false,
    optional: false,
    disabled: false,
    layout: "stacked",
    for: undefined,
    count: undefined,
    max: undefined,
  },
);

const { t } = useI18n();
const base = useId();
const id = computed(() => props.for ?? `${base}-control`);
const labelId = `${base}-label`;
const hintId = `${base}-hint`;
const errorId = `${base}-error`;

const describedBy = computed(() => [props.hint ? hintId : null, props.error ? errorId : null].filter(Boolean).join(" ") || undefined);

provideField({
  id: id.value,
  labelId,
  describedBy,
  invalid: computed(() => !!props.error),
  disabled: computed(() => props.disabled),
  required: computed(() => props.required),
});
</script>

<template>
  <div
    :class="[
      'flex min-w-0 flex-col gap-1.5',
      layout === 'inline' && 'sm:grid sm:grid-cols-[minmax(160px,220px)_minmax(0,1fr)] sm:items-start sm:gap-x-6',
    ]"
  >
    <div v-if="label || $slots.label" :class="['flex min-w-0 flex-col gap-0.5', layout === 'inline' && 'sm:pt-1.5']">
      <label :id="labelId" :for="id" :class="['flex items-baseline gap-1.5 text-sm font-semibold', disabled ? 'text-subtle' : 'text-fg']">
        <slot name="label">{{ label }}</slot>
        <span v-if="required" class="text-danger" aria-hidden="true">*</span>
        <span v-else-if="optional" class="text-xs font-normal text-subtle">{{ t("common.optional") }}</span>
      </label>
      <p v-if="hint && layout === 'inline'" :id="hintId" class="hidden text-xs text-muted sm:block">{{ hint }}</p>
    </div>
    <div class="flex min-w-0 flex-col gap-1.5">
      <slot :id="id" :described-by="describedBy" :invalid="!!error" />
      <div v-if="error || (hint && layout !== 'inline') || count !== undefined" class="flex items-start gap-3">
        <p v-if="error" :id="errorId" class="flex min-w-0 flex-1 items-start gap-1.5 text-xs font-medium text-danger" role="alert">
          <CircleAlert :size="13" class="mt-px" aria-hidden="true" />
          <span>{{ error }}</span>
        </p>
        <p v-else-if="hint && layout !== 'inline'" :id="hintId" class="min-w-0 flex-1 text-xs text-muted">{{ hint }}</p>
        <span v-else class="flex-1" />
        <span
          v-if="count !== undefined"
          :class="['shrink-0 text-xs tabular-nums', max !== undefined && count > max ? 'font-semibold text-danger' : 'text-subtle']"
          >{{ max !== undefined ? `${count}/${max}` : count }}</span
        >
      </div>
      <p v-if="hint && layout === 'inline'" class="text-xs text-muted sm:hidden">{{ hint }}</p>
    </div>
  </div>
</template>
