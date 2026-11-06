<script setup lang="ts">
/**
 * Lines (plan §14.7): every sale line the cash-register program reported, with its receipt,
 * batch, price per pack and, for prescription medicines, the legal cap it was checked against.
 * Filters in the URL: branch, business day, status (matched, waiting for a match, not goods),
 * prescription items only, sold above the legal price. Costs only for finance.view.
 */
import { Building2, ListFilter, ReceiptText, ShieldAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useLines, useOptions } from "../api";
import { packsAndParts } from "../format";
import type { SaleLine } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const options = useOptions();
const costs = computed(() => company.can("finance.view"));

const defs = computed<FilterDef[]>(() => [
  { key: "branch", label: t("sales.filter.branch"), type: "multi", icon: Building2, options: (options.data.value?.branches ?? []).map((b) => ({ value: String(b.id), label: b.name })) },
  { key: "day", label: t("sales.filter.day"), type: "date-range", params: ["from", "to"] },
  {
    key: "status",
    label: t("sales.filter.status"),
    type: "select",
    icon: ListFilter,
    options: [
      { value: "matched", label: t("sales.lines.status.matched") },
      { value: "waiting", label: t("sales.lines.status.waiting") },
      { value: "skipped", label: t("sales.lines.status.skipped") },
    ],
  },
  { key: "rx", label: t("sales.lines.rxOnly"), type: "boolean", icon: ReceiptText },
  { key: "cap", label: t("sales.lines.capOnly"), type: "boolean", icon: ShieldAlert },
]);
const filters = useUrlFilters(defs);
const search = useRouteState<string>("q", rs.string(""));
const importId = useRouteState<number | null>("import", rs.optionalNumber());
const table = useDataTable({ id: "sales.lines", url: true });
table.resetPageOn(() => [filters.params.value, search.value, importId.value]);
const query = useLines(
  computed(() => ({
    ...filters.params.value,
    ...(search.value ? { q: search.value } : {}),
    ...(importId.value ? { import: importId.value } : {}),
    ...table.params.value,
  })),
);

/** A count without trailing zeros: 2, 0.5, 1.333. */
function amount(value: number): string {
  const decimals = Number.isInteger(value) ? 0 : Math.min(3, String(value).split(".")[1]?.length ?? 0);
  return fmt.number(value, decimals);
}

/** "3 packs 1 blister": the parts as whole packs and the parts left over. */
function quantity(row: SaleLine): string {
  if (row.status !== "matched") {
    const count = Number(row.quantity);
    return t(row.unit === "pack" ? "sales.lines.packs" : "sales.lines.parts", { n: amount(count) }, count);
  }
  const { packs, rest } = packsAndParts(row.quantity, row.parts_per_pack);
  const packText = t("sales.lines.packs", { n: amount(packs) }, packs);
  if (row.parts_per_pack <= 1 || !rest) return packText;
  const restText = t("sales.lines.parts", { n: amount(rest) }, rest);
  return packs ? `${packText} ${restText}` : restText;
}

const columns = computed<TableColumn<SaleLine>[]>(() => [
  { id: "sold_at", header: t("sales.col.when"), width: 140, value: (row) => row.receipt.sold_at, format: (v) => fmt.instant(String(v), "short") },
  { id: "name", header: t("sales.lines.col.item"), minWidth: 240, hideable: false, value: (row) => row.product?.name ?? row.name },
  { id: "receipt", header: t("sales.lines.col.receipt"), width: 120, value: (row) => row.receipt.number },
  { id: "branch", header: t("sales.col.branch"), width: 120, value: (row) => row.branch.name },
  { id: "series", header: t("sales.lines.col.series"), width: 110, value: (row) => row.batch?.series || row.series },
  { id: "quantity", header: t("sales.lines.col.quantity"), width: 140, numeric: true, value: (row) => quantity(row), csv: (row) => row.quantity },
  { id: "pack_price", header: t("sales.lines.col.packPrice"), width: 130, numeric: true, csv: (row) => row.pack_price },
  { id: "cap", header: t("sales.lines.col.cap"), width: 130, numeric: true, hint: t("sales.lines.capHint"), csv: (row) => row.cap ?? "" },
  { id: "total", header: t("sales.lines.col.total"), width: 130, numeric: true, csv: (row) => row.total },
  ...(costs.value ? [{ id: "cost", header: t("sales.lines.col.cost"), width: 120, numeric: true, csv: (row: SaleLine) => row.cost ?? "" }] : []),
  { id: "cashier", header: t("sales.lines.col.cashier"), width: 140, value: (row) => row.cashier?.name || row.cashier?.code || "" },
]);
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('sales.lines.title')" :description="t('sales.lines.description')" class="!mb-0" />
    <InlineAlert v-if="options.data.value && options.data.value.settings.sales_lines !== 'import'" tone="info" size="sm" :description="t('sales.lines.offHint')" />
    <InlineAlert v-if="importId" tone="neutral" size="sm" :description="t('sales.lines.oneImport')" dismissible @dismiss="importId = null" />
    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      row-key="id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="filters.active.value > 0 || !!search"
      :empty-title="t('sales.lines.emptyTitle')"
      :empty-description="t('sales.lines.emptyBody')"
      :empty-icon="ReceiptText"
      csv-name="sale-lines"
      :row-class="(row: SaleLine) => (row.over_cap ? 'bg-danger-soft/40' : undefined)"
      @clear-filters="(filters.clear(), (search = ''))"
    >
      <template #toolbar><FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable /></template>
      <template #cell-name="{ row }">
        <span class="flex min-w-0 flex-col">
          <span class="flex items-center gap-1.5">
            <span class="truncate font-medium text-fg" :title="row.product?.name ?? row.name">{{ row.product?.name ?? row.name }}</span>
            <StatusPill v-if="row.product?.rx_required" size="sm" tone="info" :dot="false" :label="t('sales.lines.rx')" />
            <StatusPill v-if="row.receipt.kind === 'refund'" size="sm" tone="warning" :label="t('sales.entries.refund')" />
          </span>
          <span class="truncate text-xs text-muted">
            <span class="font-mono">{{ row.code }}</span>
            <template v-if="row.status !== 'matched'"> · {{ t(`sales.lines.status.${row.status}`) }}</template>
            <template v-if="row.rx_number"> · {{ t("sales.lines.prescription", { n: row.rx_number }) }}</template>
          </span>
        </span>
      </template>
      <template #cell-pack_price="{ row }">
        <span :class="['tabular-nums', row.over_cap ? 'font-semibold text-danger' : 'text-fg']"><MoneyText :value="row.pack_price" /></span>
      </template>
      <template #cell-cap="{ row }">
        <span v-if="row.cap" class="tabular-nums text-muted"><MoneyText :value="row.cap" /></span>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-total="{ row }">
        <span :class="['font-semibold tabular-nums', row.receipt.kind === 'refund' ? 'text-warning' : 'text-fg']">{{ row.receipt.kind === "refund" ? "−" : "" }}<MoneyText :value="row.total" /></span>
      </template>
      <template #cell-cost="{ row }">
        <MoneyText v-if="row.cost" :value="row.cost" class="tabular-nums text-muted" />
        <span v-else class="text-subtle" :title="t('sales.lines.noCost')">—</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-center justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-fg">{{ row.product?.name ?? row.name }}</p>
            <p class="truncate text-xs text-muted">{{ row.branch.name }} · {{ fmt.instant(row.receipt.sold_at, "short") }} · {{ quantity(row) }}</p>
            <StatusPill v-if="row.over_cap" class="mt-1" size="sm" tone="danger" :label="t('sales.lines.overCap', { cap: fmt.money(row.cap) })" />
          </div>
          <span class="shrink-0 text-sm font-semibold tabular-nums text-fg"><MoneyText :value="row.total" /></span>
        </div>
      </template>
    </DataTable>
  </div>
</template>
