<script setup lang="ts">
/**
 * The sales overview (plan §6.2 "Sales"): right now per branch, then the period's KPIs with deltas
 * (net, receipts, average check, cash share, cash differences), net by day against the previous
 * period and the month's target pace, branches compared, payment methods and their mix per branch,
 * when customers buy (weekday × hour) and the top cashiers. Period and branches live in the URL.
 */
import { ArrowRight, Banknote, Percent, Receipt, Scale, ShoppingBag, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import BarChart from "@/components/BarChart.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import ChartCard from "@/components/ChartCard.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import DonutChart from "@/components/DonutChart.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExportButton from "@/components/ExportButton.vue";
import HeatmapChart from "@/components/HeatmapChart.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import LineChart from "@/components/LineChart.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { rangeParams } from "@/lib/dateRange";
import { divide, isZero, sum } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useCashiers, useSummary, useTargets } from "../api";
import TodayBranches from "../components/TodayBranches.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const period = useRangeState({ preset: "month", compare: "prev" });
const branches = useRouteState<number[]>("branch", rs.numberList());
const params = computed(() => ({ ...rangeParams(period.value), ...(branches.value.length ? { branch: branches.value } : {}) }));

const byDay = useSummary(params, "day");
const byMethod = useSummary(params, "method");
const hours = useSummary(params, "weekday_hour");
const cashiers = useCashiers(params);
const month = computed(() => period.value.range.from.slice(0, 7));
const targets = useTargets(month);

const summary = computed(() => byDay.data.value);
const totals = computed(() => summary.value?.totals);
const previous = computed(() => summary.value?.previous ?? null);
const nothing = computed(() => !!summary.value && isZero(summary.value.totals.net) && summary.value.totals.shifts === 0 && (!previous.value || isZero(previous.value.net)));

const kpis = computed(() => {
  const now = totals.value;
  const before = previous.value;
  const spark = summary.value?.series.map((point) => point.net) ?? [];
  return [
    { id: "net", label: t("sales.kpi.net"), value: now?.net, previous: before?.net, format: "money" as const, compact: true, spark, icon: Banknote, deltaLabel: t("sales.kpi.vsPrevious") },
    { id: "receipts", label: t("sales.kpi.receipts"), value: now?.receipts, previous: before?.receipts, icon: Receipt, spark: summary.value?.series.map((p) => p.receipts) ?? [], sparkColor: "var(--c-chart-3)" },
    { id: "avg", label: t("sales.kpi.avgCheck"), value: now?.avg_check, previous: before?.avg_check, format: "money" as const, icon: ShoppingBag, sparkColor: "var(--c-chart-4)", spark: summary.value?.series.map((p) => p.avg_check ?? null) ?? [] },
    { id: "cash", label: t("sales.kpi.cashShare"), value: now ? Number(now.cash_share) : null, previous: before ? Number(before.cash_share) : null, format: "percent" as const, points: true, icon: Percent, hint: t("sales.kpi.cashShareHint") },
    { id: "diff", label: t("sales.kpi.difference"), value: now?.cash_difference, format: "money" as const, icon: Scale, hint: t("sales.kpi.differenceHint", { n: now?.shifts ?? 0 }, now?.shifts ?? 0) },
  ];
});

const categories = computed(() => summary.value?.series.map((point) => point.date ?? "") ?? []);
const netSeries = computed(() => [{ name: t("sales.chart.net"), data: summary.value?.series.map((p) => p.net) ?? [] }]);
const compareSeries = computed(() =>
  summary.value?.compare ? { name: t("sales.chart.previous"), data: summary.value.series.map((p) => p.previous_net ?? null) } : null,
);
/** The company's daily target for the month, when the period is that month. */
const dailyTarget = computed(() => {
  const company = targets.data.value?.targets.find((row) => row.scope === "company");
  if (!company || period.value.preset !== "month" || branches.value.length) return null;
  const value = divide(company.amount, company.days);
  return value ? { value, label: t("sales.chart.targetPerDay") } : null;
});

const branchRows = computed(() => summary.value?.breakdown ?? []);
const branchChart = computed(() => ({
  categories: branchRows.value.map((row) => row.label),
  series: [
    { name: t("sales.chart.thisPeriod"), data: branchRows.value.map((row) => row.net) },
    ...(summary.value?.compare ? [{ name: t("sales.chart.previous"), data: branchRows.value.map((row) => row.previous_net), dashed: true }] : []),
  ],
}));
const methodRows = computed(() => byMethod.data.value?.breakdown ?? []);
const donut = computed(() => methodRows.value.map((row) => ({ name: row.label, value: row.net })));
/** Method share per branch, as a 100% bar per branch (top methods, the rest as "Other"). */
const mix = computed(() => {
  const top = methodRows.value.slice(0, 4);
  const topKeys = new Set(top.map((row) => row.key));
  const rows = branchRows.value;
  const series = top.map((method) => ({
    name: method.label,
    data: rows.map((row) => row.methods?.find((m) => m.key === method.key)?.net ?? "0"),
    stack: "mix",
  }));
  if (methodRows.value.length > 4) {
    series.push({
      name: t("sales.chart.other"),
      data: rows.map((row) => sum((row.methods ?? []).filter((m) => !topKeys.has(m.key)).map((m) => m.net))),
      stack: "mix",
    });
  }
  return { categories: rows.map((row) => row.label), series };
});

const hourLabels = Array.from({ length: 17 }, (_, i) => String(i + 7).padStart(2, "0"));
const weekdays = computed(() => Array.from({ length: 7 }, (_, i) => t(`common.weekday.short.${i}`)));
const heat = computed<Array<[number, number, string]>>(() =>
  (hours.data.value?.series ?? [])
    .filter((cell) => (cell.hour ?? 0) >= 7)
    .map((cell) => [(cell.hour ?? 0) - 7, cell.weekday ?? 0, cell.net ?? "0"]),
);
const topCashiers = computed(() => (cashiers.data.value?.results ?? []).slice(0, 5));
const base = computed(() => `/c/${company.currentId}/sales`);
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('sales.title')" :description="t('sales.overview.description')" class="!mb-0">
      <template #actions>
        <div class="w-[210px] max-sm:w-full"><BranchPicker v-model="branches" multiple :placeholder="t('sales.filter.allBranches')" /></div>
        <DateRangePicker v-model="period" align="end" />
        <ExportButton kind="sales.daily" :params="params" variant="ghost" />
      </template>
    </PageHeader>

    <section class="flex flex-col gap-2.5" :aria-label="t('sales.today.title')">
      <div class="flex items-center gap-2">
        <span class="size-2 rounded-full bg-success" aria-hidden="true" />
        <h2 class="text-sm font-semibold text-fg">{{ t("sales.today.title") }}</h2>
        <span class="flex-1" />
        <RouterLink :to="`${base}/cash`" class="inline-flex items-center gap-1 text-sm font-semibold text-muted hover:text-fg">{{ t("sales.today.whereCash") }}<ArrowRight :size="14" /></RouterLink>
      </div>
      <TodayBranches />
    </section>

    <div v-if="nothing" class="ui-card">
      <EmptyState :icon="Store" :title="t('sales.overview.emptyTitle')" :description="t('sales.overview.emptyBody')">
        <UiButton variant="primary" :to="`${base}/setup`">{{ t("sales.overview.emptyAction") }}</UiButton>
      </EmptyState>
    </div>

    <template v-else>
      <KpiStrip :items="kpis" :loading="byDay.isPending.value" />

      <div class="grid gap-4 xl:grid-cols-3">
        <ChartCard
          class="xl:col-span-2"
          :title="t('sales.chart.netByDay')"
          :subtitle="summary ? fmt.range(summary.range) : undefined"
          :value="totals ? fmt.money(totals.net, undefined, { compact: true }) : undefined"
          :loading="byDay.isPending.value"
          :error="byDay.error.value"
          :retry="() => byDay.refetch()"
          height="260px"
        >
          <LineChart :categories="categories" :series="netSeries" :compare="compareSeries" :target="dailyTarget" value-format="money" x-format="day" height="260px" />
        </ChartCard>
        <ChartCard
          :title="t('sales.chart.methods')"
          :subtitle="t('sales.chart.methodsSub')"
          :loading="byMethod.isPending.value"
          :error="byMethod.error.value"
          :retry="() => byMethod.refetch()"
          :empty="!!byMethod.data.value && !methodRows.length"
          height="260px"
        >
          <DonutChart :slices="donut" value-format="money" :center-label="t('sales.chart.total')" height="260px" legend="bottom" />
        </ChartCard>
      </div>

      <div class="grid gap-4 xl:grid-cols-2">
        <ChartCard :title="t('sales.chart.branches')" :subtitle="t('sales.chart.branchesSub')" :loading="byDay.isPending.value" :empty="!!summary && !branchRows.length">
          <BarChart :categories="branchChart.categories" :series="branchChart.series" value-format="money" />
        </ChartCard>
        <ChartCard :title="t('sales.chart.mix')" :subtitle="t('sales.chart.mixSub')" :loading="byDay.isPending.value || byMethod.isPending.value" :empty="!!summary && !branchRows.length">
          <BarChart :categories="mix.categories" :series="mix.series" horizontal normalize stacked :height="`${Math.max(160, mix.categories.length * 64 + 70)}px`" />
        </ChartCard>
      </div>

      <div class="grid gap-4 xl:grid-cols-3">
        <ChartCard
          class="xl:col-span-2"
          :title="t('sales.chart.hours')"
          :subtitle="hours.data.value?.estimated ? t('sales.chart.hoursEstimated') : t('sales.chart.hoursSub')"
          :loading="hours.isPending.value"
          :error="hours.error.value"
          :retry="() => hours.refetch()"
          height="280px"
        >
          <HeatmapChart :x="hourLabels" :y="weekdays" :values="heat" value-format="money" :label="t('sales.chart.net')" height="280px" />
        </ChartCard>
        <section class="ui-card flex min-w-0 flex-col">
          <header class="flex items-center gap-2 px-4 pb-2 pt-4">
            <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("sales.cashiers.top") }}</h3>
            <RouterLink :to="{ path: `${base}/cashiers`, query: $route.query }" class="inline-flex items-center gap-1 text-sm font-semibold text-muted hover:text-fg">{{ t("common.viewAll") }}<ArrowRight :size="14" /></RouterLink>
          </header>
          <ol v-if="topCashiers.length" class="flex flex-col px-2 pb-2">
            <li v-for="(row, index) in topCashiers" :key="row.member.id" class="flex items-center gap-3 rounded-[10px] px-2 py-2">
              <span class="w-4 text-center text-xs font-semibold text-subtle">{{ index + 1 }}</span>
              <UserAvatar :name="row.member.name" :size="30" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-fg">{{ row.member.name }}</span>
                <span class="block truncate text-xs text-muted">{{ t("sales.cashiers.line", { shifts: row.shifts, accuracy: row.accuracy ?? "—" }, row.shifts) }}</span>
              </span>
              <MoneyText :value="row.net" compact class="text-sm font-semibold text-fg" />
            </li>
          </ol>
          <p v-else class="px-4 pb-4 text-sm text-muted">{{ t("sales.cashiers.none") }}</p>
        </section>
      </div>
    </template>
  </div>
</template>
