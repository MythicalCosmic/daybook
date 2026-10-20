<script setup lang="ts">
/**
 * A number (counts, minutes, percentages, days): `null` when empty, clamped to `min`/`max`, rounded
 * to `decimals`. ↑/↓ step (Shift ×10), the side buttons too. Accepts "1 200", "12,5" and "12.5" and
 * shows the number grouped for the language when the field isn't focused. Money uses MoneyInput.
 */
import { ChevronDown, ChevronUp } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { formatNumber } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";

import { controlSizeClass, controlState, useControl, type ControlSize } from "./field";

defineOptions({ inheritAttrs: false });

const model = defineModel<number | null>({ default: null });

const props = withDefaults(
  defineProps<{
    min?: number;
    max?: number;
    step?: number;
    decimals?: number;
    placeholder?: string;
    suffix?: string;
    prefix?: string;
    size?: ControlSize;
    steppers?: boolean;
    disabled?: boolean;
    readonly?: boolean;
    invalid?: boolean;
    id?: string;
    /** Group thousands when not focused ("12 500"). */
    grouping?: boolean;
  }>(),
  {
    min: undefined,
    max: undefined,
    step: 1,
    decimals: 0,
    placeholder: undefined,
    suffix: undefined,
    prefix: undefined,
    size: "md",
    steppers: true,
    disabled: false,
    readonly: false,
    invalid: false,
    id: undefined,
    grouping: true,
  },
);

const { t } = useI18n();
const fmt = useFormat();
const control = useControl(props);
const input = ref<HTMLInputElement | null>(null);
const focused = ref(false);
const text = ref("");

function round(value: number): number {
  const factor = 10 ** props.decimals;
  return Math.round(value * factor) / factor;
}

function clamp(value: number): number {
  let next = value;
  if (props.min !== undefined) next = Math.max(props.min, next);
  if (props.max !== undefined) next = Math.min(props.max, next);
  return round(next);
}

/** "1 200,5" → 1200.5; junk → null. */
function parse(raw: string): number | null {
  const cleaned = raw.replace(/[\s  ']/g, "").replace(/[−–]/g, "-").replace(",", ".");
  if (!cleaned || cleaned === "-" || cleaned === ".") return null;
  if (!/^-?\d*\.?\d*$/.test(cleaned)) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

function display(value: number | null, active: boolean): string {
  if (value === null) return "";
  if (active || !props.grouping) return String(value).replace(".", fmt.lang.value === "en" ? "." : ",");
  return formatNumber(value, fmt.lang.value, props.decimals);
}

watch(
  [model, () => fmt.lang.value],
  () => {
    if (!focused.value) text.value = display(model.value, false);
  },
  { immediate: true },
);

function onInput(event: Event): void {
  text.value = (event.target as HTMLInputElement).value;
  const value = parse(text.value);
  if (text.value.trim() === "") model.value = null;
  else if (value !== null) model.value = round(value);
}

function onFocus(): void {
  focused.value = true;
  text.value = display(model.value, true);
}

function onBlur(): void {
  focused.value = false;
  if (model.value !== null) model.value = clamp(model.value);
  text.value = display(model.value, false);
}

function stepBy(direction: 1 | -1, multiplier = 1): void {
  if (control.disabled.value || props.readonly) return;
  const base = model.value ?? (direction > 0 ? (props.min ?? 0) - props.step : (props.max ?? 0) + props.step);
  model.value = clamp(base + direction * props.step * multiplier);
  text.value = display(model.value, focused.value);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "ArrowUp" || event.key === "ArrowDown") {
    event.preventDefault();
    stepBy(event.key === "ArrowUp" ? 1 : -1, event.shiftKey ? 10 : 1);
  }
}

const atMin = computed(() => props.min !== undefined && model.value !== null && model.value <= props.min);
const atMax = computed(() => props.max !== undefined && model.value !== null && model.value >= props.max);

defineExpose({ focus: () => input.value?.focus(), el: input });
</script>

<template>
  <div
    :class="['ui-control', controlSizeClass[size], steppers && '!pr-0', $attrs.class]"
    :style="$attrs.style as never"
    v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value, readonly })"
    @click="input?.focus()"
  >
    <span v-if="prefix" class="ui-adorn text-muted">{{ prefix }}</span>
    <input
      :id="control.id.value"
      ref="input"
      :value="text"
      type="text"
      inputmode="decimal"
      role="spinbutton"
      class="ui-input tabular-nums"
      :placeholder="placeholder"
      :disabled="control.disabled.value"
      :readonly="readonly"
      :aria-valuenow="model ?? undefined"
      :aria-valuemin="min"
      :aria-valuemax="max"
      :aria-invalid="control.invalid.value || undefined"
      :aria-describedby="control.describedBy.value"
      :required="control.required.value || undefined"
      v-bind="{ ...$attrs, class: undefined, style: undefined }"
      @input="onInput"
      @focus="onFocus"
      @blur="onBlur"
      @keydown="onKeydown"
    />
    <span v-if="suffix" class="ui-adorn text-muted" :class="steppers && 'pr-1'">{{ suffix }}</span>
    <span v-if="steppers && !readonly" class="flex h-full shrink-0 flex-col self-stretch border-l border-line">
      <button
        type="button"
        tabindex="-1"
        class="grid flex-1 place-items-center px-1.5 text-subtle transition-colors hover:bg-highlight hover:text-fg disabled:opacity-40"
        :aria-label="t('common.number.increase')"
        :disabled="control.disabled.value || atMax"
        @click.stop="stepBy(1)"
      >
        <ChevronUp :size="12" />
      </button>
      <button
        type="button"
        tabindex="-1"
        class="grid flex-1 place-items-center border-t border-line px-1.5 text-subtle transition-colors hover:bg-highlight hover:text-fg disabled:opacity-40"
        :aria-label="t('common.number.decrease')"
        :disabled="control.disabled.value || atMin"
        @click.stop="stepBy(-1)"
      >
        <ChevronDown :size="12" />
      </button>
    </span>
  </div>
</template>
