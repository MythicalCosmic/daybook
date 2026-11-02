<script setup lang="ts">
/**
 * A payroll amount exactly as the server sent it, or "hidden" when the server left it out
 * (someone without payroll.view): never "0" for an amount the viewer may not see.
 * `cell` lays it out like MoneyCell (right-aligned, a second line); otherwise inline text.
 * `quietZero` dims an exact zero (still printed) so the columns' real amounts stand out.
 */
import { EyeOff } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency, Money } from "@/api/types";
import MoneyCell from "@/components/MoneyCell.vue";
import MoneyText from "@/components/MoneyText.vue";
import { dec } from "@/lib/decimal";

import { hasAmount } from "../lib";

const props = withDefaults(
  defineProps<{
    value: Money | null | undefined;
    currency?: Currency;
    cell?: boolean;
    sign?: "auto" | "always";
    colored?: boolean;
    strong?: boolean;
    compact?: boolean;
    sub?: string;
    quietZero?: boolean;
  }>(),
  { currency: undefined, cell: false, sign: "auto", colored: false, strong: false, compact: false, sub: undefined, quietZero: false },
);

const { t } = useI18n();
const dim = computed(() => props.quietZero && hasAmount(props.value) && dec(props.value).isZero());
</script>

<template>
  <template v-if="hasAmount(value)">
    <MoneyCell v-if="cell" :class="dim && 'opacity-40'" :value="value" :currency="currency" :sign="dim ? 'auto' : sign" :colored="colored && !dim" :strong="strong" :compact="compact" :sub="sub" />
    <MoneyText v-else :class="dim && 'opacity-40'" :value="value" :currency="currency" :sign="dim ? 'auto' : sign" :colored="colored && !dim" :compact="compact" />
  </template>
  <span v-else :class="['inline-flex items-center gap-1 whitespace-nowrap text-sm font-medium text-subtle', cell && 'justify-end']" :title="t('payroll.hiddenHint')" data-hidden-amount>
    <EyeOff :size="13" aria-hidden="true" />{{ t("payroll.hidden") }}
  </span>
</template>
