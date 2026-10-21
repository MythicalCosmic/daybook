<script setup lang="ts">
/** One category (with its subcategories) month by month, against its monthly average. */
import { Tags } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import ComboBox from "@/components/ComboBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";

import { useCategories, useCategoryTrend } from "../../api";
import { useCssColor } from "../../colors";
import { categoryOptions, colorFor, findCategory } from "../../lib";

const props = defineProps<{ branch: number[] }>();

const { t } = useI18n();
const css = useCssColor();
const fmt = useFormat();
const categories = useCategories();
const category = useRouteState("category", rs.optionalNumber());
const months = useRouteState("months", rs.enum(["6", "12", "24"] as const, "6"));
const options = computed(() => categoryOptions(categories.data.value, null));
const params = computed(() => ({ category: category.value, months: months.value, ...(props.branch.length ? { branch: props.branch } : {}) }));
const query = useCategoryTrend(params, computed(() => !!category.value));
const data = computed(() => query.data.value);
const node = computed(() => findCategory(categories.data.value, category.value));

watch(
  () => categories.data.value,
  (tree) => {
    if (category.value || !tree?.length) return;
    const goods = tree.find((n) => n.system_code === "goods") ?? tree.find((n) => n.kind === "expense");
    if (goods) category.value = goods.id;
  },
  { immediate: true },
);

const kpis = computed(() => [
  { id: "total", label: t("finance.reports.trendTotal", { n: months.value }), value: data.value?.total ?? null, format: "money" as const, compact: true },
  { id: "average", label: t("finance.reports.trendAverage"), value: data.value?.average ?? null, format: "money" as const, compact: true },
  { id: "last", label: t("finance.reports.trendThisMonth"), value: data.value?.series.at(-1)?.amount ?? null, previous: data.value?.series.at(-2)?.amount, format: "money" as const, compact: true, inverse: data.value?.category.kind === "expense" },
]);
const labels = computed(() => (data.value?.series ?? []).map((point) => point.date));
const series = computed(() => [{ name: data.value?.category.name ?? "", data: (data.value?.series ?? []).map((p) => p.amount), color: css(node.value ? colorFor(node.value.id, node.value.color) : "var(--c-chart-1)") }]);
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <ComboBox v-model="category" :options="options" class="w-full sm:w-72" :placeholder="t('finance.reports.pickCategory')" />
      <SegmentedControl
        v-model="months"
        size="sm"
        :options="[
          { value: '6', label: t('finance.reports.months', { n: 6 }) },
          { value: '12', label: t('finance.reports.months', { n: 12 }) },
          { value: '24', label: t('finance.reports.months', { n: 24 }) },
        ]"
      />
      <span class="flex-1" />
      <ExportButton v-if="category" kind="finance.category_trend" :params="params" size="sm" />
    </div>
    <div v-if="!category" class="ui-card">
      <EmptyState :icon="Tags" :title="t('finance.reports.pickCategory')" :description="t('finance.reports.trendHint')" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="3" />
      <ChartCard :title="data?.category.name ?? t('finance.reports.trend')" :subtitle="data ? t('finance.reports.averageLine', { amount: fmt.money(data.average, undefined, { compact: true }) }) : undefined" :loading="query.isPending.value" height="300px">
        <BarChart :categories="labels" :series="series" value-format="money" x-format="month" height="300px" :target="data ? { value: data.average, label: t('finance.reports.trendAverage') } : null" />
      </ChartCard>
    </template>
  </div>
</template>
