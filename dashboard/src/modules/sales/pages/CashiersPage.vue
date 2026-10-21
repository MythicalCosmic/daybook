<script setup lang="ts">
/**
 * The cashier scorecard (plan §1.7): per cashier for the period, shifts, sales, average check, how
 * often their count matched (within the tolerance), shortages and surpluses with totals, late
 * openings, disputes. Three highlights on top; a row opens that cashier's shifts.
 */
import { Award, Medal, ShieldCheck, TriangleAlert, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import BranchPicker from "@/components/BranchPicker.vue";
import DataTable from "@/components/DataTable.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import type { TableColumn } from "@/components/table";
import UiBadge from "@/components/UiBadge.vue";
import { useDataTable } from "@/components/useDataTable";
import { rangeParams } from "@/lib/dateRange";
import { compare, isZero } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useRangeState } from "@/lib/useRangeState";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useCashiers } from "../api";
import type { CashierScore } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();

const period = useRangeState({ preset: "month" });
const branches = useRouteState<number[]>("branch", rs.numberList());
const params = computed(() => ({ ...rangeParams({ ...period.value, compare: "none" }), ...(branches.value.length ? { branch: branches.value } : {}) }));
const query = useCashiers(params);
const rows = computed(() => query.data.value?.results ?? []);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const table = useDataTable({ id: "sales.cashiers", ordering: "-net", url: true, hidden: ["avg_per_shift", "surpluses", "avg_hours"] });
const sorted = computed(() => {
  const ordering = table.ordering.value || "-net";
  const field = ordering.replace(/^-/, "") as keyof CashierScore;
  const desc = ordering.startsWith("-");
  const money = ["net", "avg_per_shift", "avg_check", "shortage_total", "difference_total"];
  return [...rows.value].sort((a, b) => {
    const left = a[field];
    const right = b[field];
    let result: number;
    if (money.includes(String(field))) result = compare(String(left ?? "0"), String(right ?? "0"));
    else result = Number(left ?? -1) - Number(right ?? -1);
    return desc ? -result : result;
  });
});

const highlights = computed(() => {
  const list = rows.value.filter((row) => row.shifts > 0);
  if (!list.length) return [];
  const top = [...list].sort((a, b) => compare(b.net, a.net))[0]!;
  const accurate = [...list].filter((row) => row.accuracy !== null && row.shifts >= 3).sort((a, b) => Number(b.accuracy) - Number(a.accuracy) || b.shifts - a.shifts)[0];
  const attention = [...list].filter((row) => row.shortages > 0 || row.disputed > 0).sort((a, b) => compare(a.shortage_total, b.shortage_total))[0];
  return [
    { key: "top", icon: Award, tone: "primary", label: t("sales.cashiers.topSeller"), member: top.member, value: fmt.money(top.net, undefined, { compact: true }), detail: t("sales.cashiers.shiftsN", { n: top.shifts }, top.shifts) },
    accurate && { key: "accurate", icon: ShieldCheck, tone: "success", label: t("sales.cashiers.mostAccurate"), member: accurate.member, value: fmt.percent(Number(accurate.accuracy), 0), detail: t("sales.cashiers.withinTolerance") },
    attention && {
      key: "attention",
      icon: TriangleAlert,
      tone: "danger",
      label: t("sales.cashiers.attention"),
      member: attention.member,
      value: fmt.money(attention.shortage_total, undefined, { compact: true }),
      detail: t("sales.cashiers.shortagesN", { n: attention.shortages }, attention.shortages),
    },
  ].filter(Boolean) as Array<{ key: string; icon: typeof Award; tone: string; label: string; member: { id: number; name: string }; value: string; detail: string }>;
});

const columns = computed<TableColumn<CashierScore>[]>(() => [
  { id: "member", header: t("sales.col.cashier"), minWidth: 196, hideable: false, sticky: true, value: (row) => row.member.name },
  { id: "shifts", header: t("sales.col.shifts"), sortable: true, numeric: true, width: 100 },
  { id: "net", header: t("sales.col.net"), sortable: true, numeric: true, width: 150, csv: (row) => row.net },
  { id: "avg_per_shift", header: t("sales.col.perShift"), sortable: true, numeric: true, width: 140, csv: (row) => row.avg_per_shift },
  { id: "avg_check", header: t("sales.col.avgCheck"), sortable: true, numeric: true, width: 124, csv: (row) => row.avg_check },
  { id: "accuracy", header: t("sales.col.accuracy"), sortable: true, width: 140, hint: t("sales.cashiers.accuracyHint") },
  { id: "shortages", header: t("sales.col.shortages"), sortable: "shortage_total", numeric: true, width: 140, csv: (row) => row.shortage_total },
  { id: "surpluses", header: t("sales.col.surpluses"), numeric: true, width: 110 },
  { id: "late_opens", header: t("sales.col.lateOpens"), sortable: true, numeric: true, width: 132 },
  { id: "verified", header: t("sales.col.checks"), width: 124 },
  { id: "avg_hours", header: t("sales.col.hours"), numeric: true, width: 100, format: (v) => t("sales.cashiers.hours", { n: String(v) }) },
]);

function open(row: CashierScore): void {
  void router.push({ path: `/c/${company.currentId}/sales/shifts`, query: { cashier: String(row.member.id), from: period.value.range.from, to: period.value.range.to } });
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('sales.cashiers.title')" :description="t('sales.cashiers.description')" class="!mb-0">
      <template #actions>
        <div class="w-[210px] max-sm:w-full"><BranchPicker v-model="branches" multiple :placeholder="t('sales.filter.allBranches')" /></div>
        <DateRangePicker v-model="period" :compare="false" align="end" />
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid gap-3 sm:grid-cols-3"><SkeletonBlock v-for="n in 3" :key="n" height="92px" radius="12px" /></div>
    <div v-else-if="highlights.length" class="grid gap-3 sm:grid-cols-3">
      <article v-for="card in highlights" :key="card.key" class="ui-card flex items-center gap-3 p-4">
        <span
          :class="[
            'grid size-10 shrink-0 place-items-center rounded-[11px]',
            card.tone === 'success' ? 'bg-success-soft text-success' : card.tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-accent-soft text-accent-fg',
          ]"
          aria-hidden="true"
        >
          <component :is="card.icon" :size="19" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-xs font-medium text-muted">{{ card.label }}</p>
          <p class="truncate text-base font-semibold text-fg">{{ card.member.name }}</p>
          <p class="truncate text-xs text-subtle">{{ card.detail }}</p>
        </div>
        <p class="shrink-0 text-md font-semibold tabular-nums text-fg">{{ card.value }}</p>
      </article>
    </div>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="sorted"
      :total="sorted.length"
      :row-key="(row: CashierScore) => row.member.id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      clickable
      hide-pagination
      :empty-title="t('sales.cashiers.emptyTitle')"
      :empty-description="t('sales.cashiers.emptyBody')"
      :empty-icon="Users"
      csv-name="cashier-scorecard"
      @row-click="open"
    >
      <template #cell-member="{ row }">
        <PersonCell :person="row.member" size="sm" :subtitle="row.branches.join(', ')" />
      </template>
      <template #cell-net="{ row }"><MoneyText :value="row.net" class="font-semibold" /></template>
      <template #cell-avg_per_shift="{ row }"><MoneyText :value="row.avg_per_shift" compact /></template>
      <template #cell-avg_check="{ row }"><MoneyText :value="row.avg_check" decimals="never" /></template>
      <template #cell-accuracy="{ row }">
        <div v-if="row.accuracy !== null" class="flex items-center gap-2">
          <ProgressBar class="w-16" size="xs" :value="Number(row.accuracy)" :tone="Number(row.accuracy) >= 90 ? 'success' : Number(row.accuracy) >= 70 ? 'warning' : 'danger'" />
          <span class="text-sm font-semibold tabular-nums text-fg">{{ fmt.percent(Number(row.accuracy), 0) }}</span>
        </div>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-shortages="{ row }">
        <span v-if="row.shortages" class="flex flex-col items-end">
          <span class="font-semibold tabular-nums text-danger"><MoneyText :value="row.shortage_total" compact /></span>
          <span class="text-xs text-muted">{{ t("sales.cashiers.timesN", { n: row.shortages }, row.shortages) }}</span>
        </span>
        <span v-else-if="isZero(row.shortage_total)" class="text-subtle">—</span>
        <MoneyText v-else :value="row.shortage_total" compact class="text-muted" />
      </template>
      <template #cell-verified="{ row }">
        <span class="flex flex-wrap items-center gap-1">
          <UiBadge size="sm" tone="success"><Medal :size="11" class="mr-0.5 inline" />{{ row.verified }}</UiBadge>
          <UiBadge v-if="row.disputed" size="sm" tone="danger">{{ t("sales.cashiers.disputedN", { n: row.disputed }) }}</UiBadge>
          <UiBadge v-if="row.forced" size="sm" tone="warning">{{ t("sales.cashiers.forcedN", { n: row.forced }) }}</UiBadge>
        </span>
      </template>
      <template #card="{ row }">
        <div class="flex items-center gap-3">
          <PersonCell :person="row.member" size="sm" :subtitle="t('sales.cashiers.shiftsN', { n: row.shifts }, row.shifts)" class="min-w-0 flex-1" />
          <div class="text-right">
            <MoneyText :value="row.net" compact class="block text-sm font-semibold text-fg" />
            <span class="text-xs text-muted">{{ row.accuracy !== null ? `${row.accuracy}%` : "—" }}</span>
          </div>
        </div>
      </template>
    </DataTable>
  </div>
</template>
