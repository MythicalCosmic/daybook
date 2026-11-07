<script setup lang="ts">
/**
 * The expiry board (Yaroqlilik muddati): what has expired and what expires within 30, 60 and 90
 * days, each bucket with its value, and every batch with its quantity. Select batches to send them
 * to another pharmacy (where they sell sooner), mark them down, or write them off. Expired goods
 * can't be sold or sent; they wait for a write-off and destruction.
 */
import { ArrowRightLeft, Hourglass, PackageX, Tag } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExportButton from "@/components/ExportButton.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useExpiry, useRefresh } from "../api";
import ProductDrawer from "../components/ProductDrawer.vue";
import TransferFormDialog from "../components/TransferFormDialog.vue";
import WriteOffFormDialog from "../components/WriteOffFormDialog.vue";
import { BATCH_TONES, num, packsAndParts } from "../lib";
import type { BatchPrefill, BucketKey, ExpiryRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const refresh = useRefresh();

const within = useRouteState("within", rs.number(90));
const bucket = useRouteState("bucket", rs.string("all"));
// The expiry digest links here with its pharmacy (`?branch=`); otherwise the top bar's filter.
const branchParam = useRouteState("branch", rs.optionalNumber());
const branch = computed(() => branchParam.value ?? (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const board = useExpiry(computed(() => ({ branch: branch.value, within: within.value })));
const table = useDataTable({ id: "stock.expiry", pageSize: 500 });
const canManage = computed(() => company.can("stock.manage"));
const canPropose = computed(() => company.can(["stock.manage", "stock.operate"]));

const buckets = computed(() => board.data.value?.buckets ?? []);
const hasCost = computed(() => buckets.value.some((row) => row.value !== undefined));
const rows = computed(() => {
  const all = buckets.value.flatMap((row) => row.rows);
  return bucket.value === "all" ? all : (buckets.value.find((row) => row.key === bucket.value)?.rows ?? []);
});
const BUCKET_TONES: Record<BucketKey, "danger" | "warning" | "info" | "neutral"> = { expired: "danger", d30: "warning", d60: "info", d90: "neutral" };
const withinOptions = computed(() => [30, 60, 90].map((value) => ({ value, label: t("stock.expiry.within", { n: value }) })));

const columns = computed<TableColumn<ExpiryRow>[]>(() => [
  { id: "product", header: t("stock.col.name"), minWidth: 260, sticky: true },
  { id: "series", header: t("stock.col.series"), width: 130 },
  { id: "branch", header: t("stock.col.branch"), width: 130 },
  { id: "expires_on", header: t("stock.col.expiresOn"), width: 160 },
  { id: "quantity", header: t("stock.col.onHand"), numeric: true, width: 160 },
  { id: "retail_value", header: t("stock.col.valueRetail"), numeric: true, width: 140 },
  ...(hasCost.value ? [{ id: "value", header: t("stock.col.valueCost"), numeric: true, width: 140 } as TableColumn<ExpiryRow>] : []),
]);

function bucketLabel(key: BucketKey): string {
  return t(`stock.expiry.bucket.${key}`);
}

function open(row: ExpiryRow): void {
  patchQuery(router, { product: String(row.product_id) });
}

function picked(ids: string[]): ExpiryRow[] {
  const set = new Set(ids);
  return rows.value.filter((row) => set.has(String(row.id)));
}

const transferOpen = ref(false);
const writeoffOpen = ref(false);
const markdownOpen = ref(false);
const prefill = ref<BatchPrefill[]>([]);
const prefillBranch = ref<number | null>(null);
const markdownRows = ref<ExpiryRow[]>([]);
const markdownPrice = ref<string | null>(null);
const busy = ref(false);

function oneBranch(selection: ExpiryRow[]): number | null {
  const branches = new Set(selection.map((row) => row.branch_id));
  if (branches.size !== 1) {
    toast.error(t("stock.expiry.oneBranch"));
    return null;
  }
  return selection[0]!.branch_id;
}

function toPrefill(selection: ExpiryRow[]): BatchPrefill[] {
  return selection.map((row) => ({ product: { id: row.product_id, name: row.product }, unitsPerPack: row.units_per_pack, partLabel: "", batchId: row.batch_id, series: row.series, quantity: num(row.quantity) }));
}

function startTransfer(ids: string[]): void {
  const selection = picked(ids);
  if (selection.some((row) => row.expired)) {
    toast.error(t("stock.expiry.expiredCantMove"));
    return;
  }
  const from = oneBranch(selection);
  if (from === null) return;
  prefillBranch.value = from;
  prefill.value = toPrefill(selection);
  transferOpen.value = true;
}

function startWriteoff(ids: string[]): void {
  const selection = picked(ids);
  const from = oneBranch(selection);
  if (from === null) return;
  prefillBranch.value = from;
  prefill.value = toPrefill(selection);
  writeoffOpen.value = true;
}

function startMarkdown(ids: string[]): void {
  markdownRows.value = picked(ids).filter((row) => !row.expired);
  markdownPrice.value = null;
  if (!markdownRows.value.length) {
    toast.error(t("stock.expiry.expiredCantSell"));
    return;
  }
  markdownOpen.value = true;
}

async function applyMarkdown(clear: () => void): Promise<void> {
  if (!markdownPrice.value) return;
  busy.value = true;
  try {
    for (const row of markdownRows.value) await stockApi.markdown(company.currentId ?? 0, row.id, markdownPrice.value);
    toast.success(t("stock.expiry.markedDown", { n: markdownRows.value.length }, markdownRows.value.length));
    markdownOpen.value = false;
    clear();
    refresh();
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.expiry')" :description="t('stock.expiry.description')">
      <template #actions>
        <SegmentedControl v-model="within" :options="withinOptions" size="sm" />
        <ExportButton kind="inventory.expiry" :params="{ branch, within }" />
      </template>
    </PageHeader>

    <div class="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="expiry-buckets">
      <button
        v-for="row in buckets"
        :key="row.key"
        type="button"
        :class="['ui-card flex flex-col gap-1 p-4 text-start transition-colors', bucket === row.key ? 'ring-2 ring-accent' : 'hover:bg-surface-2/40']"
        :data-bucket="row.key"
        @click="bucket = bucket === row.key ? 'all' : row.key"
      >
        <StatusPill :tone="BUCKET_TONES[row.key]" size="sm" :label="bucketLabel(row.key)" />
        <span class="text-xl font-semibold tabular-nums text-fg">{{ fmt.number(row.count) }}</span>
        <span class="text-xs text-muted">
          <template v-if="row.value !== undefined">{{ t("stock.expiry.atCost") }} <MoneyText :value="row.value" compact /> · </template>
          {{ t("stock.expiry.atRetail") }} <MoneyText :value="row.retail_value" compact />
        </span>
      </button>
    </div>

    <div v-if="board.data.value && !rows.length" class="ui-card">
      <EmptyState :icon="Hourglass" :title="t('stock.expiry.emptyTitle')" :description="t('stock.expiry.emptyBody', { n: within })" />
    </div>

    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="rows"
      row-key="id"
      :loading="board.isPending.value"
      :fetching="board.isFetching.value"
      :error="board.error.value"
      :retry="() => board.refetch()"
      :selectable="canPropose"
      clickable
      hide-pagination
      csv-name="expiry"
      @row-click="open"
    >
      <template #cell-product="{ row }">
        <span class="flex min-w-0 flex-col">
          <span class="truncate font-medium text-fg">{{ row.product }}</span>
          <StatusPill v-if="row.status !== 'sellable'" :tone="BATCH_TONES[row.status]" size="sm" :label="t(`stock.batchStatus.${row.status}`)" />
        </span>
      </template>
      <template #cell-expires_on="{ row }">
        <StatusPill :tone="row.expired ? 'danger' : row.days_left <= 30 ? 'warning' : 'info'" variant="plain" size="sm" :label="row.expired ? t('stock.expiry.expiredOn', { day: fmt.day(row.expires_on) }) : t('stock.expiry.daysLeft', { day: fmt.day(row.expires_on), n: row.days_left }, row.days_left)" />
      </template>
      <template #cell-quantity="{ row }">{{ packsAndParts(row.quantity, row.units_per_pack, "", t) }}</template>
      <template #cell-retail_value="{ row }"><MoneyText :value="row.retail_value" decimals="never" /></template>
      <template #cell-value="{ row }"><MoneyText :value="row.value" decimals="never" /></template>
      <template #bulk="{ selected, clear }">
        <UiButton v-if="canManage" size="sm" :icon="ArrowRightLeft" @click="startTransfer(selected)">{{ t("stock.expiry.transfer") }}</UiButton>
        <UiButton v-if="canManage" size="sm" :icon="Tag" @click="startMarkdown(selected)">{{ t("stock.expiry.markdown") }}</UiButton>
        <UiButton size="sm" variant="danger" :icon="PackageX" @click="startWriteoff(selected)">{{ t("stock.expiry.writeoff") }}</UiButton>
        <UiDialog v-model:open="markdownOpen" :title="t('stock.expiry.markdownTitle', { n: markdownRows.length }, markdownRows.length)" :description="t('stock.expiry.markdownBody')" size="sm">
          <FormField :label="t('stock.expiry.newPrice')">
            <MoneyInput v-model="markdownPrice" />
          </FormField>
          <template #footer>
            <UiButton variant="ghost" @click="markdownOpen = false">{{ t("common.cancel") }}</UiButton>
            <UiButton variant="primary" :disabled="!markdownPrice" :loading="busy" @click="applyMarkdown(clear)">{{ t("common.apply") }}</UiButton>
          </template>
        </UiDialog>
      </template>
    </DataTable>

    <ProductDrawer />
    <TransferFormDialog v-model:open="transferOpen" :from="prefillBranch" :prefill="prefill" @saved="(id) => router.push(`/c/${company.currentId}/stock/transfers?transfer=${id}`)" />
    <WriteOffFormDialog
      v-model:open="writeoffOpen"
      :branch="prefillBranch"
      reason="expired"
      :prefill="prefill"
      @saved="(id) => router.push(`/c/${company.currentId}/stock/write-offs/${id}`)"
    />
  </div>
</template>
