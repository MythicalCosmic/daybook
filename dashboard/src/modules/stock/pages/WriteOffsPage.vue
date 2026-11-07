<script setup lang="ts">
/**
 * Write-offs and their acts (Hisobdan chiqarish va dalolatnomalar): proposals waiting for
 * approval, approved unfit goods waiting for destruction (with the last day the law allows), and
 * destroyed ones with their act. `?new=1` proposes one.
 */
import { PackageX, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExportButton from "@/components/ExportButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useWriteoffs } from "../api";
import WriteOffFormDialog from "../components/WriteOffFormDialog.vue";
import { daysUntil, WRITEOFF_TONES } from "../lib";
import type { WriteOff } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const today = useCompanyToday();

const status = useRouteState("status", rs.string("open"));
const creating = useRouteState("new", rs.boolean(false));
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const params = computed(() => ({
  branch: branch.value,
  status: status.value === "open" ? "proposed,approved" : status.value === "all" ? undefined : status.value,
}));
const writeoffs = useWriteoffs(params);
const table = useDataTable({ id: "stock.writeoffs", pageSize: 300 });
const canPropose = computed(() => company.can(["stock.manage", "stock.operate"]));

const statusOptions = computed(() => [
  { value: "open", label: t("stock.writeoffs.open") },
  { value: "destroyed", label: t("stock.writeoffStatus.destroyed") },
  { value: "void", label: t("stock.writeoffStatus.void") },
  { value: "all", label: t("stock.receipts.all") },
]);
const hasCost = computed(() => (writeoffs.data.value ?? []).some((row) => row.value !== undefined));
const columns = computed<TableColumn<WriteOff>[]>(() => [
  { id: "number", header: t("stock.col.number"), width: 150, sticky: true },
  { id: "reason", header: t("stock.writeoff.reason"), minWidth: 160 },
  { id: "branch", header: t("stock.col.branch"), width: 140, value: (row) => row.branch.name },
  { id: "lines_count", header: t("stock.col.lines"), numeric: true, width: 90 },
  ...(hasCost.value ? [{ id: "value", header: t("stock.col.valueCost"), numeric: true, width: 140 } as TableColumn<WriteOff>] : []),
  { id: "destroy_by", header: t("stock.writeoff.destroyBy"), width: 170 },
  { id: "status", header: t("stock.col.status"), width: 160 },
]);

function open(row: WriteOff): void {
  void router.push(`/c/${company.currentId}/stock/write-offs/${row.id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.writeoffs')" :description="t('stock.writeoffs.description')">
      <template #actions>
        <ExportButton kind="inventory.writeoffs" :params="{ branch }" />
        <UiButton v-if="canPropose" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.writeoffs.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="writeoffs.data.value && !writeoffs.data.value.length && status === 'open'" class="ui-card">
      <EmptyState :icon="PackageX" :title="t('stock.writeoffs.emptyTitle')" :description="t('stock.writeoffs.emptyBody')" />
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="writeoffs.data.value"
      row-key="id"
      :loading="writeoffs.isPending.value"
      :fetching="writeoffs.isFetching.value"
      :error="writeoffs.error.value"
      :retry="() => writeoffs.refetch()"
      clickable
      hide-pagination
      csv-name="write-offs"
      @row-click="open"
    >
      <template #toolbar>
        <SegmentedControl v-model="status" :options="statusOptions" size="sm" />
      </template>
      <template #cell-number="{ row }"><span class="font-medium tabular-nums text-fg">{{ row.number || t("stock.writeoff.proposal", { id: row.id }) }}</span></template>
      <template #cell-reason="{ row }">{{ t(`stock.reason.${row.reason}`) }}</template>
      <template #cell-value="{ row }"><MoneyText :value="row.value" decimals="never" /></template>
      <template #cell-destroy_by="{ row }">
        <StatusPill
          v-if="row.destroy_by && row.status === 'approved'"
          :tone="daysUntil(row.destroy_by, today) <= 10 ? 'danger' : 'warning'"
          variant="plain"
          size="sm"
          :label="t('stock.writeoff.destroyByDay', { day: fmt.day(row.destroy_by), n: daysUntil(row.destroy_by, today) }, Math.max(0, daysUntil(row.destroy_by, today)))"
        />
        <span v-else-if="row.destroyed_at" class="text-xs text-muted">{{ fmt.instant(row.destroyed_at, "date") }}</span>
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="WRITEOFF_TONES[row.status]" size="sm" :label="t(`stock.writeoffStatus.${row.status}`)" /></template>
    </DataTable>

    <WriteOffFormDialog v-model:open="creating" reason="damaged" @saved="(id) => router.push(`/c/${company.currentId}/stock/write-offs/${id}`)" />
  </div>
</template>
