<script setup lang="ts">
/**
 * Cash flow (plan §4.7 `reports/cash-flow/`): money in and out of the accounts per day, week or
 * month, and a statement from the opening cash through operating, equipment, loans, owner money,
 * transfers, opening balances and the revaluation of dollars held to the closing cash, which is
 * the accounts' balance at that day's rate (the same as "Cash now").
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";

import { periodParams, useCashFlow } from "../../api";
import { useCssColor } from "../../colors";
import { comparablePrevious, isNegative, isZeroMoney } from "../../lib";

const props = defineProps<{ branch: number[] }>();

const { t } = useI18n();
const css = useCssColor();
const fmt = useFormat();
const period = useRangeState({ preset: "last_30", compare: "prev" });
const group = useRouteState("group", rs.enum(["auto", "day", "week", "month"] as const, "auto"));
const params = computed(() => ({ ...periodParams(period.value), ...(group.value !== "auto" ? { group: group.value } : {}), ...(props.branch.length ? { branch: props.branch } : {}) }));
const query = useCashFlow(params);
const data = computed(() => query.data.value);

const kpis = computed(() => {
  const d = data.value;
  const vs = d?.compare ? t("finance.reports.vsPrevious") : undefined;
  // A net that crossed zero shows the previous period's net, not "−115 %".
  const netBefore = comparablePrevious(d?.totals.net, d?.previous?.net);
  const netHint = d?.previous && netBefore === undefined ? t("finance.reports.previousAmount", { amount: fmt.money(d.previous.net, undefined, { compact: true, sign: "always" }) }) : undefined;
  return [
    { id: "in", label: t("finance.tx.moneyIn"), value: d?.totals.income ?? null, previous: d?.previous?.income, format: "money" as const, compact: true, deltaLabel: vs },
    { id: "out", label: t("finance.tx.moneyOut"), value: d?.totals.expense ?? null, previous: d?.previous?.expense, format: "money" as const, compact: true, inverse: true, deltaLabel: vs },
    { id: "net", label: t("finance.tx.net"), value: d?.totals.net ?? null, previous: netBefore ?? undefined, hint: netHint, format: "money" as const, compact: true, deltaLabel: vs },
    { id: "end", label: t("finance.reports.closingCash"), value: d?.end_cash ?? null, format: "money" as const, compact: true, hint: d ? t("finance.reports.openingCash", { amount: fmt.money(d.start_cash, undefined, { compact: true }) }) : undefined },
  ];
});
const xFormat = computed(() => (data.value?.group === "month" ? "month" : "day"));
const categories = computed(() => (data.value?.series ?? []).map((point) => point.date));
const series = computed(() => [
  { name: t("finance.tx.moneyIn"), data: (data.value?.series ?? []).map((p) => p.income), color: css("var(--c-success)") },
  { name: t("finance.tx.moneyOut"), data: (data.value?.series ?? []).map((p) => p.expense), color: css("var(--c-chart-1)") },
]);
const empty = computed(() => !!data.value && data.value.series.every((p) => isZeroMoney(p.income) && isZeroMoney(p.expense)));
/** Sections with nothing in them (no loans, no opening balances this period) are left out; operating always shows. */
const breakdown = computed(() => (data.value?.breakdown ?? []).filter((row) => row.key === "operating" || !isZeroMoney(row.income) || !isZeroMoney(row.expense)));
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <DateRangePicker v-model="period" />
      <SegmentedControl
        v-model="group"
        size="sm"
        :options="[
          { value: 'auto', label: t('finance.reports.auto') },
          { value: 'day', label: t('finance.reports.byDay') },
          { value: 'week', label: t('finance.reports.byWeek') },
          { value: 'month', label: t('finance.reports.byMonth') },
        ]"
      />
      <span class="flex-1" />
      <ExportButton kind="finance.cash_flow" :params="params" size="sm" />
    </div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" />
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <ChartCard :title="t('finance.reports.cashFlowChart')" :loading="query.isPending.value" :empty="empty" :empty-text="t('finance.overview.cashFlowEmpty')" height="360px">
          <BarChart :categories="categories" :series="series" value-format="money" :x-format="xFormat" height="360px" legend />
        </ChartCard>
        <section class="ui-card p-4" :aria-label="t('finance.reports.statement')">
          <h3 class="mb-1 text-sm font-semibold text-fg">{{ t("finance.reports.statement") }}</h3>
          <p class="mb-3 text-xs text-muted">{{ t("finance.reports.statementHint") }}</p>
          <SkeletonBlock v-if="query.isPending.value" height="260px" />
          <dl v-else-if="data" class="flex flex-col text-sm">
            <div class="flex items-center justify-between border-b border-line py-2">
              <dt class="font-medium text-muted">{{ t("finance.reports.openingCashLabel") }}</dt>
              <dd class="font-semibold tabular-nums text-fg"><MoneyText :value="data.start_cash" decimals="never" /></dd>
            </div>
            <div v-for="row in breakdown" :key="row.key" class="flex items-center justify-between gap-3 border-b border-line py-2">
              <dt class="min-w-0">
                <span class="block truncate text-fg">{{ t(`finance.reports.section.${row.key}`) }}</span>
                <span class="block truncate text-xs text-subtle">
                  +{{ fmt.money(row.income, undefined, { compact: true }) }} · −{{ fmt.money(row.expense, undefined, { compact: true }) }}
                </span>
              </dt>
              <dd :class="['shrink-0 font-semibold tabular-nums', isNegative(row.net) ? 'text-danger' : isZeroMoney(row.net) ? 'text-subtle' : 'text-success']">
                <MoneyText :value="row.net" sign="always" decimals="never" />
              </dd>
            </div>
            <div class="flex items-center justify-between py-2.5">
              <dt class="font-semibold text-fg">{{ t("finance.reports.closingCash") }}</dt>
              <dd class="text-md font-semibold tabular-nums text-fg"><MoneyText :value="data.end_cash" decimals="never" /></dd>
            </div>
          </dl>
        </section>
      </div>
    </template>
  </div>
</template>
