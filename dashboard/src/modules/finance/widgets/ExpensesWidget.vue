<script setup lang="ts">
/**
 * Overview widget "Expenses this month" against the same days of last month (lower is better),
 * with where the money went: the biggest categories as one bar and their shares, so the tile says
 * something useful at any height the Overview grid gives it.
 */
import { ArrowUpRight, TrendingDown } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import { shareText } from "@/components/chartCard";
import DeltaBadge from "@/components/DeltaBadge.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { changePercent } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";

import { useOverview } from "../api";
import { distinctColors, isZeroMoney, share } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const overview = useOverview();
const month = computed(() => overview.data.value?.month);
const change = computed(() => (month.value && !isZeroMoney(month.value.previous.expense) ? changePercent(month.value.expense, month.value.previous.expense) : null));
const parts = computed(() => {
  const total = month.value?.expense ?? "0";
  const rows = (overview.data.value?.top_expenses ?? []).slice(0, 3);
  // No two parts of one bar in the same colour (categories often share one of eight).
  const colors = distinctColors(rows);
  return rows.map((row, index) => ({ ...row, color: colors[index]!, percent: share(row.amount, total) }));
});
// The rows the number counts: the transactions list's P&L filter, as the finance overview links them.
const to = computed(() => ({ path: `/c/${props.companyId}/finance/transactions`, query: { pnl: "expense", from: month.value?.from, to: month.value?.to } }));
</script>

<template>
  <RouterLink :to="to" class="ui-card group flex h-full min-h-[148px] min-w-0 flex-col p-4 transition-colors @container hover:border-line-strong" :aria-busy="overview.isPending.value || undefined">
    <div class="flex items-start gap-2">
      <TrendingDown :size="15" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
      <span class="kpi-label" :title="t('finance.overview.expensesMonth')">{{ t("finance.overview.expensesMonth") }}</span>
      <ArrowUpRight :size="15" class="mt-px shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <!-- A failed load keeps the tile and its label, like every KPI tile (KpiCard). -->
    <ErrorState v-if="overview.isError.value" class="mt-2.5" compact bare :error="overview.error.value" :retry="() => overview.refetch()" @click.stop.prevent />
    <template v-else-if="overview.isPending.value">
      <SkeletonBlock class="mt-2.5" width="62%" height="26px" />
      <SkeletonBlock class="mt-auto" height="44px" />
    </template>
    <template v-else-if="month">
      <p class="kpi-value mt-1.5 truncate" :title="fmt.money(month.expense)">
        {{ fmt.money(month.expense, undefined, { compact: true, decimals: "never" }) }}
      </p>
      <DeltaBadge class="mt-1 self-start" :value="change" inverse :suffix="t('finance.overview.vsLastMonth')" />
      <div v-if="parts.length" class="mt-auto pt-3">
        <div class="flex h-2 overflow-hidden rounded-full bg-surface-2" role="img" :aria-label="t('finance.overview.topExpenses')">
          <span v-for="part in parts" :key="part.id" class="h-full first:rounded-l-full" :style="{ width: `${part.percent}%`, background: part.color }" />
        </div>
        <ul class="mt-2 flex flex-col gap-1">
          <li v-for="part in parts" :key="part.id" class="flex items-center gap-2 text-xs">
            <span class="size-2 shrink-0 rounded-full" :style="{ background: part.color }" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate text-muted">{{ part.name }}</span>
            <span class="shrink-0 font-semibold tabular-nums text-fg">{{ shareText(part.percent, fmt.lang.value) }}</span>
          </li>
        </ul>
      </div>
    </template>
  </RouterLink>
</template>
