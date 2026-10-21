<script setup lang="ts">
/**
 * Overview widget "Cash now" (plan §1.2 KPI strip): every account in so‘m at today's rate, the
 * dollars inside it, and the last 30 days of cash as a trend that fills the tile (the Overview grid
 * gives a tile the height of the tallest one in its row).
 */
import { ArrowUpRight, Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import SparkLine from "@/components/SparkLine.vue";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useCashFlow, useOverview } from "../api";
import { isZeroMoney } from "../lib";

defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const overview = useOverview();
const cash = computed(() => overview.data.value?.cash);
// The last 30 days of cash, end of each day (the same query as the cash-flow widget).
const flow = useCashFlow({ preset: "last_30", group: "day" });
const spark = computed(() => {
  const data = flow.data.value;
  if (!data) return [];
  let running = dec(data.start_cash);
  return data.series.map((point) => (running = running.plus(point.net)).toNumber());
});
const firstDay = computed(() => flow.data.value?.series[0]?.date ?? null);
const foreign = computed(() => (cash.value?.by_currency ?? []).filter((row) => row.currency !== company.currency && !isZeroMoney(row.amount)));
const hint = computed(() => {
  if (foreign.value.length) return `${foreign.value.map((row) => fmt.money(row.amount, row.currency)).join(" · ")} ${t("finance.overview.included")}`;
  return cash.value?.rate.stale ? t("finance.rates.staleShort") : t("finance.overview.allAccounts");
});
</script>

<template>
  <RouterLink :to="`/c/${companyId}/finance/accounts`" class="ui-card group flex h-full min-h-[148px] min-w-0 flex-col p-4 transition-colors @container hover:border-line-strong" :aria-busy="overview.isPending.value || undefined">
    <div class="flex items-center gap-2">
      <Wallet :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-muted" :title="t('finance.overview.cashNow')">{{ t("finance.overview.cashNow") }}</span>
      <ArrowUpRight :size="15" class="shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <!-- A failed load keeps the tile and its label, like every KPI tile (KpiCard). -->
    <ErrorState v-if="overview.isError.value" class="mt-2.5" compact bare :error="overview.error.value" :retry="() => overview.refetch()" @click.stop.prevent />
    <template v-else-if="overview.isPending.value">
      <SkeletonBlock class="mt-2.5" width="62%" height="26px" />
      <SkeletonBlock class="mt-auto" height="44px" />
    </template>
    <template v-else-if="cash">
      <p class="kpi-value mt-1.5 truncate" :title="fmt.money(cash.total)">
        {{ fmt.money(cash.total, undefined, { compact: true, decimals: "never" }) }}
      </p>
      <p class="mt-0.5 truncate text-xs text-muted">{{ hint }}</p>
      <div v-if="spark.length > 1" class="mt-auto pt-3">
        <SparkLine :data="spark" fluid :width="240" :height="44" :dot="false" color="var(--c-chart-2)" :label="t('finance.widget.cashTrend')" />
        <div class="mt-1 flex justify-between text-[11px] tabular-nums text-subtle">
          <span>{{ firstDay ? fmt.day(firstDay, "short") : "" }}</span>
          <span>{{ t("finance.widget.today") }}</span>
        </div>
      </div>
    </template>
  </RouterLink>
</template>
