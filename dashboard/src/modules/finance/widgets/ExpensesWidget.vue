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
import DeltaBadge from "@/components/DeltaBadge.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { changePercent } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";

import { useOverview } from "../api";
import { colorFor, isZeroMoney, share } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const overview = useOverview();
const month = computed(() => overview.data.value?.month);
const change = computed(() => (month.value && !isZeroMoney(month.value.previous.expense) ? changePercent(month.value.expense, month.value.previous.expense) : null));
const parts = computed(() => {
  const total = month.value?.expense ?? "0";
  return (overview.data.value?.top_expenses ?? []).slice(0, 3).map((row) => ({ ...row, color: colorFor(row.id, row.color), percent: share(row.amount, total) }));
});
const to = computed(() => ({ path: `/c/${props.companyId}/finance/transactions`, query: { kind: "expense", from: month.value?.from, to: month.value?.to } }));
</script>

<template>
  <ErrorState v-if="overview.isError.value" compact :error="overview.error.value" :retry="() => overview.refetch()" class="h-full" />
  <RouterLink v-else :to="to" class="ui-card group flex h-full min-h-[148px] min-w-0 flex-col p-4 transition-colors @container hover:border-line-strong" :aria-busy="overview.isPending.value || undefined">
    <div class="flex items-center gap-2">
      <TrendingDown :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-muted" :title="t('finance.overview.expensesMonth')">{{ t("finance.overview.expensesMonth") }}</span>
      <ArrowUpRight :size="15" class="shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <template v-if="overview.isPending.value">
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
            <span class="shrink-0 font-semibold tabular-nums text-fg">{{ fmt.number(part.percent, 0) }}%</span>
          </li>
        </ul>
      </div>
    </template>
  </RouterLink>
</template>
