<script setup lang="ts">
/**
 * CashCountBreakdown (plan §6.3, E's own component): a banknote count as the cashier entered it
 * ("200 000 × 3 = 600 000"), largest note first, with the total. With `compare` it shows a second
 * count beside the first (opening float and closing count), aligned row by row.
 */
import { Banknote } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import MoneyText from "@/components/MoneyText.vue";
import { multiply, sum } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";

const props = withDefaults(
  defineProps<{
    count: Record<string, number> | null | undefined;
    title?: string;
    compare?: Record<string, number> | null;
    compareTitle?: string;
  }>(),
  { title: undefined, compare: null, compareTitle: undefined },
);

const { t } = useI18n();
const fmt = useFormat();

const notes = computed(() => {
  const all = new Set([...Object.keys(props.count ?? {}), ...Object.keys(props.compare ?? {})]);
  return [...all].filter((note) => (props.count?.[note] ?? 0) > 0 || (props.compare?.[note] ?? 0) > 0).sort((a, b) => Number(b) - Number(a));
});
const total = (count: Record<string, number> | null | undefined) => sum(Object.entries(count ?? {}).map(([note, pieces]) => multiply(note, pieces)));
const empty = computed(() => notes.value.length === 0);
</script>

<template>
  <div class="rounded-[12px] border border-line">
    <div v-if="empty" class="flex items-center gap-2 px-4 py-3 text-sm text-muted">
      <Banknote :size="15" class="text-subtle" aria-hidden="true" />{{ t("sales.count.none") }}
    </div>
    <table v-else class="w-full text-sm tabular-nums">
      <thead>
        <tr class="border-b border-line text-xs text-muted">
          <th class="px-4 py-2 text-left font-medium">{{ t("sales.count.note") }}</th>
          <th class="px-3 py-2 text-right font-medium">{{ title ?? t("sales.count.pieces") }}</th>
          <th v-if="compare" class="px-3 py-2 text-right font-medium">{{ compareTitle }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="note in notes" :key="note" class="border-b border-line last:border-b-0">
          <td class="px-4 py-1.5 font-medium text-fg">{{ fmt.number(note) }}</td>
          <td class="px-3 py-1.5 text-right text-muted">
            <template v-if="count?.[note]">× {{ count[note] }} = <span class="text-fg">{{ fmt.number(multiply(note, count[note]!)) }}</span></template>
            <template v-else>—</template>
          </td>
          <td v-if="compare" class="px-3 py-1.5 text-right text-muted">
            <template v-if="compare[note]">× {{ compare[note] }} = <span class="text-fg">{{ fmt.number(multiply(note, compare[note]!)) }}</span></template>
            <template v-else>—</template>
          </td>
        </tr>
      </tbody>
      <tfoot>
        <tr class="bg-surface-2/60 font-semibold">
          <td class="rounded-bl-[12px] px-4 py-2 text-fg">{{ t("sales.count.total") }}</td>
          <td class="px-3 py-2 text-right text-fg"><MoneyText :value="total(count)" /></td>
          <td v-if="compare" class="rounded-br-[12px] px-3 py-2 text-right text-fg"><MoneyText :value="total(compare)" /></td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>
