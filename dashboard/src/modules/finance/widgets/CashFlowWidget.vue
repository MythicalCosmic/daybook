<script setup lang="ts">
/** Overview widget "Cash flow, 30 days": money in and out of the accounts per day. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import { useFormat } from "@/lib/useFormat";

import { useCashFlow } from "../api";
import { useCssColor } from "../colors";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const css = useCssColor();
const fmt = useFormat();
const flow = useCashFlow({ preset: "last_30", group: "day" });
const data = computed(() => flow.data.value);
const series = computed(() => [
  { name: t("finance.overview.moneyIn"), data: (data.value?.series ?? []).map((p) => p.income), color: css("var(--c-success)") },
  { name: t("finance.overview.moneyOut"), data: (data.value?.series ?? []).map((p) => p.expense), color: css("var(--c-chart-1)") },
]);
const empty = computed(() => !!data.value && data.value.series.every((p) => p.income === "0.00" && p.expense === "0.00"));
</script>

<template>
  <ChartCard
    class="h-full"
    :title="t('finance.widget.cashFlow')"
    :value="data ? fmt.money(data.totals.net, undefined, { sign: 'always', compact: true }) : undefined"
    :subtitle="t('finance.widget.cashFlowSub')"
    :loading="flow.isPending.value"
    :error="flow.error.value"
    :retry="() => flow.refetch()"
    :empty="empty"
    :empty-text="t('finance.overview.cashFlowEmpty')"
    height="200px"
  >
    <template #actions>
      <RouterLink :to="`/c/${props.companyId}/finance/reports/cash-flow`" class="rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">{{ t("common.viewAll") }}</RouterLink>
    </template>
    <BarChart :categories="(data?.series ?? []).map((p) => p.date)" :series="series" value-format="money" x-format="day" height="200px" />
  </ChartCard>
</template>
