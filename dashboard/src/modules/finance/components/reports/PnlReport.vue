<script setup lang="ts">
/** Profit and loss: the period's headline numbers, income against expenses per period, the tree table. */
import { ChartColumn, ChevronsDownUp, ChevronsUpDown, Plus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { periodParams, usePnl } from "../../api";
import { useCssColor } from "../../colors";
import { dropEmptyCompare, trimLeadingPeriods } from "../../lib";
import { openQuickAdd } from "../../quickAdd";
import PnlTable from "./PnlTable.vue";

const props = defineProps<{ branch: number[] }>();

const { t } = useI18n();
const css = useCssColor();
const fmt = useFormat();
const period = useRangeState({ preset: "year", compare: "prev" });
const group = useRouteState("group", rs.enum(["month", "quarter"] as const, "month"));
const params = computed(() => ({ ...periodParams(period.value), group: group.value, ...(props.branch.length ? { branch: props.branch } : {}) }));
const query = usePnl(params);
const data = computed(() => (query.data.value ? dropEmptyCompare(trimLeadingPeriods(query.data.value)) : undefined));
const table = ref<InstanceType<typeof PnlTable> | null>(null);
const company = useCompanyStore();
const empty = computed(() => !!data.value && !data.value.income.nodes.length && !data.value.expense.nodes.length);
const expanded = ref(false);

const kpis = computed(() => {
  const d = data.value;
  const vs = d?.compare ? t("finance.reports.vsPrevious") : undefined;
  return [
    { id: "income", label: t("finance.reports.income"), value: d?.income.total ?? null, previous: d?.income.previous ?? undefined, format: "money" as const, compact: true, deltaLabel: vs },
    { id: "expense", label: t("finance.reports.expenses"), value: d?.expense.total ?? null, previous: d?.expense.previous ?? undefined, format: "money" as const, compact: true, inverse: true, deltaLabel: vs },
    { id: "profit", label: t("finance.reports.profit"), value: d?.profit.total ?? null, previous: d?.profit.previous ?? undefined, format: "money" as const, compact: true, deltaLabel: vs },
    {
      id: "margin",
      label: t("finance.reports.margin"),
      value: d?.margin.total !== null && d?.margin.total !== undefined ? Number(d.margin.total) : null,
      previous: d?.margin.previous !== null && d?.margin.previous !== undefined ? Number(d.margin.previous) : undefined,
      format: "percent" as const,
      points: true,
      deltaLabel: vs,
    },
  ];
});

const labels = computed(() => (data.value?.periods ?? []).map((p) => (p.key.includes("Q") ? p.key.replace("-", " ") : fmt.day(`${p.key}-01`, "monthYear"))));
const series = computed(() => [
  { name: t("finance.reports.income"), data: data.value?.income.amounts ?? [], color: css("var(--c-success)") },
  { name: t("finance.reports.expenses"), data: data.value?.expense.amounts ?? [], color: css("var(--c-chart-1)") },
  { name: t("finance.reports.profit"), data: data.value?.profit.amounts ?? [], color: css("var(--c-chart-3)") },
]);

function toggleAll(): void {
  expanded.value = !expanded.value;
  table.value?.expandAll(expanded.value);
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <DateRangePicker v-model="period" />
      <SegmentedControl
        v-model="group"
        size="sm"
        :options="[
          { value: 'month', label: t('finance.reports.byMonth') },
          { value: 'quarter', label: t('finance.reports.byQuarter') },
        ]"
      />
      <span class="flex-1" />
      <UiButton v-if="!empty" variant="ghost" size="sm" :icon="expanded ? ChevronsDownUp : ChevronsUpDown" @click="toggleAll">{{ expanded ? t("finance.reports.collapse") : t("finance.reports.expand") }}</UiButton>
      <ExportButton kind="finance.pnl" :params="params" size="sm" />
    </div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="grid" />
      <ChartCard v-if="(data?.periods.length ?? 0) > 1 && !empty" :title="t('finance.reports.pnlChart')" :loading="query.isPending.value" height="220px">
        <BarChart :categories="labels" :series="series" value-format="money" height="220px" legend />
      </ChartCard>
      <SkeletonBlock v-if="query.isPending.value" height="420px" radius="12px" />
      <div v-else-if="empty" class="ui-card">
        <EmptyState :icon="ChartColumn" :title="t('finance.reports.pnlEmptyTitle')" :description="t('finance.reports.pnlEmpty')">
          <UiButton v-if="company.can('finance.record')" variant="primary" :icon="Plus" @click="openQuickAdd('expense')">{{ t("finance.cmd.record") }}</UiButton>
        </EmptyState>
      </div>
      <PnlTable v-else-if="data" ref="table" :data="data" />
    </template>
  </div>
</template>
