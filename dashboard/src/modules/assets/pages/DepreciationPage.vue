<script setup lang="ts">
/**
 * Depreciation (Amortizatsiya): what the assets cost each month of a year, by category or by
 * branch, posted months as posted and the rest of the year as planned, with the tax book's total
 * when the company keeps one; then the roll-forward of the period (what it owned at the start,
 * what came in and left, depreciation and write-downs, what it owns at the end), the way an
 * accountant checks the register against the books.
 */
import { Info } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BarChart from "@/components/BarChart.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useDepreciation, useMovement } from "../api";
import { monthKey } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const thisYear = new Date().getFullYear();
const year = useRouteState("year", rs.number(thisYear));
const group = useRouteState("group", rs.string("category"));
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));

const report = useDepreciation(computed(() => ({ year: year.value, group: group.value, branch: branch.value })));
const movement = useMovement(computed(() => ({ from: `${year.value}-01-01`, to: year.value === thisYear ? undefined : `${year.value}-12-31`, branch: branch.value })));

const yearOptions = computed(() => Array.from({ length: 7 }, (_, index) => thisYear + 1 - index).map((value) => ({ value, label: String(value) })));

const chart = computed(() => {
  const data = report.data.value;
  if (!data) return null;
  const through = data.posted_through;
  const posted = data.totals.map((amount, index) => (data.months[index] <= through ? amount : null));
  const planned = data.totals.map((amount, index) => (data.months[index] > through ? amount : null));
  return { categories: data.months.map(monthKey), posted, planned };
});

const columns = computed(() => [
  { key: "open_book", label: t("assets.movement.open") },
  { key: "in_cost", label: t("assets.movement.in") },
  { key: "out_cost", label: t("assets.movement.out") },
  { key: "depreciation", label: t("assets.movement.depreciation") },
  { key: "written_down", label: t("assets.movement.writtenDown") },
  { key: "close_cost", label: t("assets.movement.closeCost") },
  { key: "close_depreciation", label: t("assets.movement.closeDepreciation") },
  { key: "close_book", label: t("assets.movement.close") },
] as const);
</script>

<template>
  <div>
    <PageHeader :title="t('assets.nav.depreciation')" :description="t('assets.depreciation.description')">
      <template #actions>
        <SelectBox v-model="year" size="sm" class="w-28" :options="yearOptions" />
        <SegmentedControl
          v-model="group"
          size="sm"
          :options="[
            { value: 'category', label: t('assets.depreciation.byCategory') },
            { value: 'branch', label: t('assets.depreciation.byBranch') },
          ]"
        />
        <ExportButton kind="assets.register" />
      </template>
    </PageHeader>

    <InlineAlert tone="info" :icon="Info" class="mb-4">{{ t("assets.depreciation.explain") }}</InlineAlert>

    <ErrorState v-if="report.isError.value" :error="report.error.value" :retry="() => report.refetch()" />
    <template v-else>
      <PageSection variant="card" class="mb-4" :title="t('assets.depreciation.chartTitle', { year })">
        <template #actions>
          <span class="text-sm text-muted">{{ t("assets.depreciation.total") }}</span>
          <span class="text-base font-semibold tabular-nums text-fg"><MoneyText v-if="report.data.value" :value="report.data.value.total" decimals="never" /></span>
        </template>
        <SkeletonBlock v-if="report.isPending.value" height="240px" radius="12px" />
        <BarChart
          v-else-if="chart"
          :categories="chart.categories"
          :series="[
            { name: t('assets.item.posted'), data: chart.posted, stack: 'm' },
            { name: t('assets.item.planned'), data: chart.planned, stack: 'm', dashed: true },
          ]"
          value-format="money"
          x-format="month"
          height="240px"
          legend
        />
      </PageSection>

      <PageSection v-if="report.data.value" variant="card" class="mb-4" :title="group === 'branch' ? t('assets.depreciation.tableBranch') : t('assets.depreciation.tableCategory')" flush>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[960px] text-sm" data-testid="depreciation-table">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th class="sticky left-0 bg-surface px-4 py-2 font-medium">{{ group === "branch" ? t("assets.col.branch") : t("assets.field.category") }}</th>
                <th v-for="month in report.data.value.months" :key="month" class="px-2 py-2 text-right font-medium capitalize">{{ fmt.day(month, "monthYear").split(" ")[0] }}</th>
                <th class="px-4 py-2 text-right font-semibold">{{ t("assets.depreciation.total") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in report.data.value.groups" :key="String(row.id) + row.name" class="border-t border-line">
                <td class="sticky left-0 bg-surface px-4 py-2 font-medium text-fg">
                  {{ row.name || t("assets.form.companyLevel") }}
                  <span class="block text-xs font-normal text-muted">{{ t("assets.depreciation.assets", { n: row.assets }) }}</span>
                </td>
                <td v-for="(amount, index) in row.amounts" :key="index" class="px-2 py-2 text-right tabular-nums" :class="report.data.value.months[index] > report.data.value.posted_through ? 'text-muted' : 'text-fg'">
                  <MoneyText v-if="Number(amount)" :value="amount" compact />
                  <span v-else class="text-subtle">·</span>
                </td>
                <td class="px-4 py-2 text-right font-semibold tabular-nums"><MoneyText :value="row.total" decimals="never" /></td>
              </tr>
              <tr class="border-t-2 border-line font-semibold">
                <td class="sticky left-0 bg-surface px-4 py-2">{{ t("assets.depreciation.total") }}</td>
                <td v-for="(amount, index) in report.data.value.totals" :key="index" class="px-2 py-2 text-right tabular-nums"><MoneyText :value="amount" compact /></td>
                <td class="px-4 py-2 text-right tabular-nums"><MoneyText :value="report.data.value.total" decimals="never" /></td>
              </tr>
              <tr v-if="report.data.value.tax" class="border-t border-line text-muted">
                <td class="sticky left-0 bg-surface px-4 py-2">{{ t("assets.depreciation.taxRow") }}</td>
                <td v-for="(amount, index) in report.data.value.tax" :key="index" class="px-2 py-2 text-right tabular-nums"><MoneyText :value="amount" compact /></td>
                <td class="px-4 py-2 text-right tabular-nums"><MoneyText :value="report.data.value.tax_total" decimals="never" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!report.data.value.groups.length" class="px-4 py-6 text-center text-sm text-muted">{{ t("assets.depreciation.empty") }}</p>
      </PageSection>

      <PageSection v-if="movement.data.value" variant="card" :title="t('assets.movement.title')" :description="t('assets.movement.body', { from: fmt.day(movement.data.value.start, 'medium'), to: fmt.day(movement.data.value.end, 'medium') })" flush>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[900px] text-sm" data-testid="movement-table">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th class="px-4 py-2 font-medium">{{ t("assets.field.category") }}</th>
                <th v-for="column in columns" :key="column.key" class="px-2 py-2 text-right font-medium">{{ column.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in movement.data.value.lines" :key="line.id" class="border-t border-line">
                <td class="px-4 py-2 font-medium text-fg">{{ line.name }}</td>
                <td v-for="column in columns" :key="column.key" class="px-2 py-2 text-right tabular-nums"><MoneyText :value="line[column.key]" decimals="never" /></td>
              </tr>
              <tr class="border-t-2 border-line font-semibold">
                <td class="px-4 py-2">{{ t("assets.depreciation.total") }}</td>
                <td v-for="column in columns" :key="column.key" class="px-2 py-2 text-right tabular-nums"><MoneyText :value="movement.data.value.total[column.key]" decimals="never" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </PageSection>
    </template>
  </div>
</template>
