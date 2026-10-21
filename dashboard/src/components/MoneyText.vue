<script setup lang="ts">
/**
 * An amount, formatted for the language without floats (plan §6.3):
 *   <MoneyText value="1250000.00" currency="UZS" />  → "1 250 000 so‘m" / "1 250 000 сум" / "1,250,000 UZS"
 *   <MoneyText value="12500000" compact />           → "12,5 mln so‘m" (the full amount in the tooltip)
 *   <MoneyText value="1240.00" currency="USD" :approx="{ value: '15624000', currency: 'UZS' }" />  → "$1,240.00 ≈ 15,6 mln so‘m"
 * `colored` paints negatives red and (with `sign="always"`) positives green.
 */
import { computed } from "vue";

import type { Currency, Money } from "@/api/types";
import { formatApprox, moneySign } from "@/lib/money";
import { useFormat } from "@/lib/useFormat";

const props = withDefaults(
  defineProps<{
    value: Money | number | null | undefined;
    currency?: Currency;
    compact?: boolean;
    sign?: "auto" | "always";
    colored?: boolean;
    /** Show "—" for null; `hidden` shows "•••" (a value the person may not see). */
    hidden?: boolean;
    approx?: { value: Money | number; currency: Currency } | null;
    decimals?: "auto" | "always" | "never";
  }>(),
  { currency: undefined, compact: false, sign: "auto", colored: false, hidden: false, approx: null, decimals: undefined },
);

const fmt = useFormat();

const text = computed(() => (props.hidden ? "•••" : fmt.money(props.value, props.currency, { compact: props.compact, sign: props.sign, decimals: props.decimals })));
const full = computed(() => (props.compact && !props.hidden ? fmt.money(props.value, props.currency, { sign: props.sign }) : undefined));
const hint = computed(() => (props.approx && !props.hidden ? formatApprox(props.approx.value, props.approx.currency, fmt.lang.value) : null));
const tone = computed(() => {
  if (!props.colored || props.hidden) return "";
  const s = moneySign(props.value);
  if (s < 0) return "text-danger";
  if (s > 0 && props.sign === "always") return "text-success";
  return "";
});
</script>

<template>
  <span class="whitespace-nowrap tabular-nums" :title="full">
    <span :class="tone">{{ text }}</span>
    <span v-if="hint" class="ml-1.5 text-[0.9em] font-normal text-subtle">{{ hint }}</span>
  </span>
</template>
