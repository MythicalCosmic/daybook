<script setup lang="ts">
/**
 * An amount in a table cell: right-aligned, tabular, negatives in red, zero muted, an optional
 * second line ("≈ $98", "of 2 400 000"). Put `align: "end"` on the column too.
 *
 *   <template #cell-amount="{ row }"><MoneyCell :value="row.amount" :currency="row.currency" /></template>
 */
import { computed } from "vue";

import type { Currency, Money } from "@/api/types";
import { formatApprox, moneySign } from "@/lib/money";
import { useFormat } from "@/lib/useFormat";

const props = withDefaults(
  defineProps<{
    value: Money | number | null | undefined;
    currency?: Currency;
    /** "always" adds + to income rows and paints them green. */
    sign?: "auto" | "always";
    compact?: boolean;
    colored?: boolean;
    hidden?: boolean;
    approx?: { value: Money | number; currency: Currency } | null;
    sub?: string;
    strong?: boolean;
  }>(),
  { currency: undefined, sign: "auto", compact: false, colored: true, hidden: false, approx: null, sub: undefined, strong: false },
);

const fmt = useFormat();
const direction = computed(() => moneySign(props.value));
const text = computed(() =>
  props.hidden ? "•••" : props.value === null || props.value === undefined || props.value === "" ? "—" : fmt.money(props.value, props.currency, { compact: props.compact, sign: props.sign }),
);
const second = computed(() => props.sub ?? (props.approx && !props.hidden ? formatApprox(props.approx.value, props.approx.currency, fmt.lang.value) : null));
</script>

<template>
  <span class="flex min-w-0 flex-col items-end text-right leading-tight">
    <span
      :class="[
        'whitespace-nowrap tabular-nums',
        strong ? 'font-semibold' : 'font-medium',
        hidden || direction === 0 ? 'text-muted' : colored && direction < 0 ? 'text-danger' : colored && sign === 'always' && direction > 0 ? 'text-success' : 'text-fg',
      ]"
      >{{ text }}</span
    >
    <span v-if="second" class="mt-0.5 whitespace-nowrap text-xs tabular-nums text-subtle">{{ second }}</span>
  </span>
</template>
