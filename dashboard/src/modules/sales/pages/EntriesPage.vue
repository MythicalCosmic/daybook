<script setup lang="ts">
/**
 * Single receipts (plan §1.7, Should): those recorded in Kassa during shifts (receipts mode) and
 * those entered here after the fact. Filters in the URL, void with a reason, "New receipt".
 */
import { Ban, Building2, Plus, ReceiptText } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useEntries, useOptions, useSalesMutation } from "../api";
import EntryDialog from "../components/EntryDialog.vue";
import { METHOD_ICONS } from "../format";
import type { Entry } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const options = useOptions();
const canManage = computed(() => company.can("sales.manage"));

const defs = computed<FilterDef[]>(() => [
  { key: "branch", label: t("sales.filter.branch"), type: "multi", icon: Building2, options: (options.data.value?.branches ?? []).map((b) => ({ value: String(b.id), label: b.name })) },
  { key: "kind", label: t("sales.entries.kind"), type: "select", icon: ReceiptText, options: [{ value: "sale", label: t("sales.entries.sale") }, { value: "refund", label: t("sales.entries.refund") }] },
  { key: "day", label: t("sales.filter.day"), type: "date-range", params: ["from", "to"] },
]);
const filters = useUrlFilters(defs);
const search = useRouteState<string>("q", rs.string(""));
const table = useDataTable({ id: "sales.entries", url: true });
watch([() => filters.params.value, search], () => table.resetPage(), { deep: true });
const query = useEntries(computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}), ...table.params.value })));

const columns = computed<TableColumn<Entry>[]>(() => [
  { id: "sold_at", header: t("sales.col.when"), width: 150, format: (v) => fmt.instant(String(v), "short") },
  { id: "note", header: t("sales.entries.what"), minWidth: 240, hideable: false },
  { id: "branch", header: t("sales.col.branch"), width: 130, value: (row) => row.branch.name },
  { id: "payments", header: t("sales.entries.payments"), width: 200 },
  { id: "source", header: t("sales.entries.source"), width: 140 },
  { id: "total", header: t("sales.col.amount"), numeric: true, width: 150, csv: (row) => row.total },
  ...(canManage.value ? [{ id: "actions", header: "", width: 56, hideable: false, align: "end" as const }] : []),
]);

const voidEntry = useSalesMutation((cid, vars: { id: number; reason: string }) => salesApi.voidEntry(cid, vars.id, vars.reason));
async function askVoid(row: Entry): Promise<void> {
  const answer = await confirm({ title: t("sales.entries.voidTitle"), message: t("sales.entries.voidBody", { amount: fmt.money(row.total) }), confirmLabel: t("sales.cash.void"), tone: "danger", reason: "required" });
  if (!answer) return;
  await voidEntry.mutateAsync({ id: row.id, reason: answer.reason });
  toast.success(t("sales.entries.voided"));
}
const dialog = ref(false);
const shiftMode = computed(() => options.data.value?.settings.mode === "shift_totals");
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('sales.entries.title')" :description="t('sales.entries.description')" class="!mb-0">
      <template v-if="canManage" #actions>
        <UiButton variant="primary" :icon="Plus" @click="dialog = true">{{ t("sales.entries.new") }}</UiButton>
      </template>
    </PageHeader>
    <InlineAlert v-if="shiftMode" tone="info" size="sm" :description="t('sales.entries.shiftMode')" dismissible />
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
      :empty-title="t('sales.entries.emptyTitle')"
      :empty-description="t('sales.entries.emptyBody')"
      :empty-icon="ReceiptText"
      csv-name="receipts"
      :row-class="(row) => (row.voided_at ? 'opacity-55' : undefined)"
      @clear-filters="(filters.clear(), (search = ''))"
    >
      <template #toolbar><FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable /></template>
      <template #cell-note="{ row }">
        <span class="flex min-w-0 flex-col">
          <span class="truncate font-medium text-fg">{{ row.note || t("sales.entries.receipt", { n: row.number || row.id }) }}</span>
          <span class="truncate text-xs text-muted">{{ [row.number, row.performed_by?.name, row.shift?.code].filter(Boolean).join(" · ") }}</span>
        </span>
      </template>
      <template #cell-payments="{ row }">
        <span class="flex flex-wrap gap-1">
          <span v-for="payment in row.payments" :key="payment.method.id" class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs text-fg">
            <component :is="METHOD_ICONS[payment.method.kind]" :size="11" class="text-subtle" />{{ payment.method.name }}
          </span>
        </span>
      </template>
      <template #cell-source="{ row }">
        <StatusPill v-if="row.voided_at" size="sm" tone="neutral" :label="t('sales.movement.status.void')" />
        <StatusPill v-else-if="row.kind === 'refund'" size="sm" tone="warning" :label="t('sales.entries.refund')" />
        <span v-else class="text-sm text-muted">{{ t(`sales.entries.from.${row.source}`) }}</span>
      </template>
      <template #cell-total="{ row }">
        <span :class="['font-semibold tabular-nums', row.kind === 'refund' ? 'text-warning' : 'text-fg']">{{ row.kind === "refund" ? "−" : "" }}<MoneyText :value="row.total" /></span>
      </template>
      <template #cell-actions="{ row }">
        <IconButton v-if="!row.voided_at" :icon="Ban" :label="t('sales.cash.void')" size="sm" @click.stop="askVoid(row)" />
      </template>
      <template #card="{ row }">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-fg">{{ row.note || t("sales.entries.receipt", { n: row.number || row.id }) }}</p>
            <p class="truncate text-xs text-muted">{{ row.branch.name }} · {{ fmt.instant(row.sold_at, "short") }}</p>
          </div>
          <MoneyText :value="row.total" class="text-sm font-semibold text-fg" />
        </div>
      </template>
    </DataTable>
    <EntryDialog v-model:open="dialog" />
  </div>
</template>
