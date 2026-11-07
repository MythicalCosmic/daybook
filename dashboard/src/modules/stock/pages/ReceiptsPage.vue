<script setup lang="ts">
/**
 * Goods receipts (Kirim, nakladnoy): drafts the pharmacists are filling in, receipts waiting for
 * posting, and posted ones with their invoice, distributor, warnings and (with finance.view) the
 * total and the payable. `?new=1` starts one.
 */
import { PackagePlus, Truck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import { useDataTable } from "@/components/useDataTable";
import UiButton from "@/components/UiButton.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useReceipts, useSuppliers } from "../api";
import ReceiptFormDialog from "../components/ReceiptFormDialog.vue";
import { RECEIPT_TONES } from "../lib";
import type { Receipt } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();

const status = useRouteState("status", rs.string("open"));
const supplier = useRouteState("supplier", rs.string(""));
const search = useRouteState("q", rs.string(""));
const creating = useRouteState("new", rs.boolean(false));

const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const params = computed(() => ({
  branch: branch.value,
  status: status.value === "open" ? "draft,submitted" : status.value === "all" ? undefined : status.value,
  supplier: supplier.value || undefined,
  q: search.value || undefined,
}));
const receipts = useReceipts(params);
const suppliers = useSuppliers();
const table = useDataTable({ id: "stock.receipts", pageSize: 300 });
const canCreate = computed(() => company.can(["stock.manage", "stock.operate"]));

const statusOptions = computed(() => [
  { value: "open", label: t("stock.receipts.open") },
  { value: "posted", label: t("stock.receiptStatus.posted") },
  { value: "void", label: t("stock.receiptStatus.void") },
  { value: "all", label: t("stock.receipts.all") },
]);
const supplierOptions = computed(() => (suppliers.data.value ?? []).map((row) => ({ value: String(row.id), label: row.name })));
const supplierModel = computed({ get: () => supplier.value || null, set: (value: string | null) => (supplier.value = value ?? "") });

const hasCost = computed(() => (receipts.data.value ?? []).some((row) => row.total !== undefined));
const columns = computed<TableColumn<Receipt>[]>(() => [
  { id: "number", header: t("stock.col.number"), width: 150, sticky: true },
  { id: "invoice", header: t("stock.col.invoice"), minWidth: 170 },
  { id: "supplier", header: t("stock.col.supplier"), minWidth: 200, value: (row) => row.supplier.name },
  { id: "branch", header: t("stock.col.branch"), width: 130, value: (row) => row.branch.name },
  { id: "lines_count", header: t("stock.col.lines"), numeric: true, width: 90 },
  { id: "warnings", header: t("stock.col.warnings"), width: 120 },
  ...(hasCost.value ? [{ id: "total", header: t("stock.col.total"), numeric: true, width: 140 } as TableColumn<Receipt>] : []),
  { id: "due_on", header: t("stock.col.due"), width: 120 },
  { id: "status", header: t("stock.col.status"), width: 150 },
]);
const filtered = computed(() => Boolean(supplier.value || search.value || status.value !== "open"));

function open(row: Receipt): void {
  void router.push(`/c/${company.currentId}/stock/receipts/${row.id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.receipts')" :description="t('stock.receipts.description')">
      <template #actions>
        <UiButton v-if="canCreate" variant="primary" :icon="PackagePlus" @click="creating = true">{{ t("stock.receipts.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="receipts.data.value && !receipts.data.value.length && !filtered" class="ui-card">
      <EmptyState :icon="Truck" :title="t('stock.receipts.emptyTitle')" :description="t('stock.receipts.emptyBody')">
        <UiButton v-if="canCreate" variant="primary" :icon="PackagePlus" @click="creating = true">{{ t("stock.receipts.new") }}</UiButton>
      </EmptyState>
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="receipts.data.value"
      row-key="id"
      :loading="receipts.isPending.value"
      :fetching="receipts.isFetching.value"
      :error="receipts.error.value"
      :retry="() => receipts.refetch()"
      clickable
      hide-pagination
      :filtered="filtered"
      csv-name="receipts"
      @row-click="open"
      @clear-filters="
        status = 'open';
        supplier = '';
        search = '';
      "
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <SegmentedControl v-model="status" :options="statusOptions" size="sm" />
          <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-56" :placeholder="t('stock.receipts.search')" clearable />
          <SelectBox v-model="supplierModel" size="sm" class="w-56" :options="supplierOptions" clearable :placeholder="t('stock.filter.anySupplier')" />
        </div>
      </template>
      <template #cell-number="{ row }">
        <span class="font-medium tabular-nums text-fg">{{ row.number || t("stock.receipts.draftNumber", { id: row.id }) }}</span>
      </template>
      <template #cell-invoice="{ row }">
        <span class="flex flex-col">
          <span class="text-fg">{{ row.supplier_invoice_number || "—" }}</span>
          <span class="text-xs text-muted">{{ fmt.day(row.supplier_invoice_date) }}</span>
        </span>
      </template>
      <template #cell-warnings="{ row }">
        <StatusPill v-if="row.warnings.length" :tone="row.warnings.includes('recalled_series') || row.warnings.includes('not_licensed_branch') ? 'danger' : 'warning'" size="sm" :label="t('stock.receipts.warningsN', { n: row.warnings.length }, row.warnings.length)" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-total="{ row }"><MoneyText :value="row.total" decimals="never" /></template>
      <template #cell-due_on="{ row }">{{ row.due_on ? fmt.day(row.due_on) : "—" }}</template>
      <template #cell-status="{ row }"><StatusPill :tone="RECEIPT_TONES[row.status]" size="sm" :label="t(`stock.receiptStatus.${row.status}`)" /></template>
    </DataTable>

    <ReceiptFormDialog v-model:open="creating" @saved="(id) => router.push(`/c/${company.currentId}/stock/receipts/${id}`)" />
  </div>
</template>
