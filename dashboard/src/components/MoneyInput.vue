<script setup lang="ts">
/**
 * An amount of money (plan §6.3). The value is the API's decimal string ("1250000.00") or null;
 * the field groups digits live as you type ("1 250 000", "1,250,000"), keeps the caret beside the
 * same digit, and never turns the amount into a float. With several `currencies` a toggle sits at
 * the end; bind it with `v-model:currency`.
 *
 *   <MoneyInput v-model="form.values.amount" v-model:currency="form.values.currency" :currencies="['UZS', 'USD']" />
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency, Money } from "@/api/types";
import { currencyLabel } from "@/lib/money";
import { fractionDigits, maskMoney, moneyToText } from "@/lib/moneyMask";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { controlSizeClass, controlState, useControl, type ControlSize } from "./field";

defineOptions({ inheritAttrs: false });

const model = defineModel<Money | null>({ default: null });
const currencyModel = defineModel<Currency | undefined>("currency", { default: undefined });

const props = withDefaults(
  defineProps<{
    currencies?: Currency[];
    /** Fraction digits; default 2 for USD, 0 for so‘m (a value that has tiyins still shows them). */
    decimals?: number;
    negative?: boolean;
    placeholder?: string;
    size?: ControlSize;
    disabled?: boolean;
    readonly?: boolean;
    invalid?: boolean;
    id?: string;
  }>(),
  { currencies: undefined, decimals: undefined, negative: false, placeholder: undefined, size: "md", disabled: false, readonly: false, invalid: false, id: undefined },
);

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const control = useControl(props);
const input = ref<HTMLInputElement | null>(null);

const options = computed<Currency[]>(() => (props.currencies?.length ? props.currencies : [company.currency]));
const currency = computed<Currency>(() => {
  const chosen = currencyModel.value;
  return chosen && options.value.includes(chosen) ? chosen : options.value[0]!;
});
const decimals = computed(() => Math.max(props.decimals ?? (currency.value === "USD" ? 2 : 0), fractionDigits(model.value)));

const text = ref("");
let lastEmitted: Money | null | undefined;

function render(): void {
  text.value = moneyToText(model.value, fmt.lang.value, decimals.value);
}

watch(
  model,
  (value) => {
    if (value !== lastEmitted) render();
  },
  { immediate: true },
);
watch(() => fmt.lang.value, render);

function onInput(event: Event): void {
  const el = event.target as HTMLInputElement;
  const result = maskMoney(el.value, el.selectionStart ?? el.value.length, fmt.lang.value, {
    decimals: decimals.value,
    negative: props.negative,
  });
  el.value = result.text;
  text.value = result.text;
  // Restore the caret after Vue's patch (the value is already in place, so nothing moves it).
  if (document.activeElement === el) el.setSelectionRange(result.caret, result.caret);
  lastEmitted = result.value;
  model.value = result.value;
}

const GROUP_CHARS = /[   ,]/;

/** Deleting next to a group separator deletes the digit beyond it instead of doing nothing. */
function onKeydown(event: KeyboardEvent): void {
  const el = event.target as HTMLInputElement;
  const start = el.selectionStart ?? 0;
  if (start !== el.selectionEnd) return;
  if (event.key === "Backspace" && start > 0 && GROUP_CHARS.test(el.value[start - 1]!) && !(fmt.lang.value !== "en" && el.value[start - 1] === ",")) {
    el.setSelectionRange(start - 1, start - 1);
  } else if (event.key === "Delete" && GROUP_CHARS.test(el.value[start] ?? "") && !(fmt.lang.value !== "en" && el.value[start] === ",")) {
    el.setSelectionRange(start + 1, start + 1);
  }
}

function onBlur(): void {
  // Drop a dangling decimal mark ("12,").
  render();
}

function pick(next: Currency): void {
  if (control.disabled.value || props.readonly) return;
  currencyModel.value = next;
}

defineExpose({ focus: () => input.value?.focus(), el: input });
</script>

<template>
  <div
    :class="['ui-control', controlSizeClass[size], options.length > 1 && '!pr-1', $attrs.class]"
    :style="$attrs.style as never"
    v-bind="controlState({ invalid: control.invalid.value, disabled: control.disabled.value, readonly })"
    @click="input?.focus()"
  >
    <input
      :id="control.id.value"
      ref="input"
      :value="text"
      type="text"
      inputmode="decimal"
      autocomplete="off"
      class="ui-input text-right font-medium tabular-nums"
      :placeholder="placeholder ?? '0'"
      :disabled="control.disabled.value"
      :readonly="readonly"
      :aria-invalid="control.invalid.value || undefined"
      :aria-describedby="control.describedBy.value"
      :required="control.required.value || undefined"
      v-bind="{ ...$attrs, class: undefined, style: undefined }"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
    />
    <span v-if="options.length === 1" class="ui-adorn text-muted">{{ currencyLabel(currency, fmt.lang.value) }}</span>
    <span
      v-else
      role="radiogroup"
      :aria-label="t('common.money.currency')"
      class="flex shrink-0 rounded-[5px] bg-surface-2 p-0.5 dark:bg-surface-3"
      @click.stop
    >
      <button
        v-for="option in options"
        :key="option"
        type="button"
        role="radio"
        :aria-checked="option === currency"
        :disabled="control.disabled.value || readonly"
        :class="[
          'h-[22px] min-w-[30px] rounded-[4px] px-1.5 text-xs font-semibold transition-colors',
          option === currency ? 'bg-surface text-fg shadow-raised' : 'text-muted hover:text-fg',
        ]"
        @click="pick(option)"
      >
        {{ currencyLabel(option, fmt.lang.value) }}
      </button>
    </span>
  </div>
</template>
