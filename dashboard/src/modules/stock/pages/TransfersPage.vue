<script setup lang="ts">
/**
 * Transfers between pharmacies (Filiallararo ko‘chirish): drafts, transfers on the way, received
 * ones and disputes, for the pharmacies you work with (sending or receiving). A row opens the
 * transfer (`?transfer=<id>`); `?new=1` starts one.
 */
import { ArrowRightLeft, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useDataTable } from "@/components/useDataTable";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useTransfers } from "../api";
import TransferDrawer from "../components/TransferDrawer.vue";
import TransferFormDialog from "../components/TransferFormDialog.vue";
import { TRANSFER_TONES } from "../lib";
import type { Transfer } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();

const status = useRouteState("status", rs.string("active"));
const creating = useRouteState("new", rs.boolean(false));
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const params = computed(() => ({
  branch: branch.value,
  status: status.value === "active" ? "draft,sent,disputed" : status.value === "all" ? undefined : status.value,
}));
const transfers = useTransfers(params);
const table = useDataTable({ id: "stock.transfers", pageSize: 300 });
const canManage = computed(() => company.can("stock.manage"));

const statusOptions = computed(() => [
  { value: "active", label: t("stock.transfers.active") },
  { value: "received", label: t("stock.transferStatus.received") },
  { value: "void", label: t("stock.transferStatus.void") },
  { value: "all", label: t("stock.receipts.all") },
]);
const columns = computed<TableColumn<Transfer>[]>(() => [
  { id: "number", header: t("stock.col.number"), width: 150, sticky: true },
  { id: "route", header: t("stock.col.route"), minWidth: 240 },
  { id: "lines_count", header: t("stock.col.lines"), numeric: true, width: 90 },
  { id: "sent_at", header: t("stock.transfer.sentAt"), width: 150 },
  { id: "status", header: t("stock.col.status"), width: 150 },
]);

function open(row: Transfer): void {
  patchQuery(router, { transfer: String(row.id) });
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.transfers')" :description="t('stock.transfers.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.transfers.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="transfers.data.value && !transfers.data.value.length && status === 'active'" class="ui-card">
      <EmptyState :icon="ArrowRightLeft" :title="t('stock.transfers.emptyTitle')" :description="t('stock.transfers.emptyBody')">
        <UiButton v-if="canManage" variant="secondary" :icon="Plus" @click="creating = true">{{ t("stock.transfers.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="transfers.data.value"
      row-key="id"
      :loading="transfers.isPending.value"
      :fetching="transfers.isFetching.value"
      :error="transfers.error.value"
      :retry="() => transfers.refetch()"
      clickable
      hide-pagination
      csv-name="transfers"
      @row-click="open"
    >
      <template #toolbar>
        <SegmentedControl v-model="status" :options="statusOptions" size="sm" />
      </template>
      <template #cell-number="{ row }"><span class="font-medium tabular-nums text-fg">{{ row.number || t("stock.transfer.draft") }}</span></template>
      <template #cell-route="{ row }">{{ row.from_branch.name }} → {{ row.to_branch.name }}</template>
      <template #cell-sent_at="{ row }">{{ row.sent_at ? fmt.instant(row.sent_at, "short") : "—" }}</template>
      <template #cell-status="{ row }"><StatusPill :tone="TRANSFER_TONES[row.status]" size="sm" :label="t(`stock.transferStatus.${row.status}`)" /></template>
    </DataTable>

    <TransferDrawer />
    <TransferFormDialog v-model:open="creating" @saved="(id) => patchQuery(router, { transfer: String(id), new: undefined })" />
  </div>
</template>
