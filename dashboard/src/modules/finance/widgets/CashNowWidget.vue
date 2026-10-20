<script setup lang="ts">
/** Overview widget "Cash now" (plan §1.2 KPI strip): every account in so‘m at today's rate. */
import { Wallet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import KpiCard from "@/components/KpiCard.vue";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useCashFlow, useOverview } from "../api";

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
  if (!data) return undefined;
  let running = dec(data.start_cash);
  return data.series.map((point) => (running = running.plus(point.net)).toNumber());
});
const hint = computed(() => {
  const foreign = (cash.value?.by_currency ?? []).filter((row) => row.currency !== company.currency && row.amount !== "0.00");
  if (foreign.length) return foreign.map((row) => fmt.money(row.amount, row.currency)).join(" · ");
  return cash.value?.rate.stale ? t("finance.rates.staleShort") : t("finance.overview.allAccounts");
});
</script>

<template>
  <ErrorState v-if="overview.isError.value" compact :error="overview.error.value" :retry="() => overview.refetch()" class="h-full" />
  <KpiCard
    v-else
    class="h-full"
    :label="t('finance.overview.cashNow')"
    :value="cash?.total ?? null"
    format="money"
    compact
    :icon="Wallet"
    :hint="hint"
    :spark="spark"
    spark-color="var(--c-chart-2)"
    :loading="overview.isPending.value"
    :to="`/c/${companyId}/finance/accounts`"
  />
</template>
