<script setup lang="ts">
/**
 * Defektura: what customers asked for that a pharmacy couldn't give (entered at the counter, from
 * the app or here), and the mandatory-list medicines the daily check found missing. Each request
 * is ordered, arrives or is cancelled; the open ones are what to buy next. `?new=1` adds one.
 */
import { ClipboardX, Plus } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh, useRequests } from "../api";
import ProductPicker from "../components/ProductPicker.vue";
import { num, qtyText } from "../lib";
import type { MissingRequest, RequestStatus } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();

const status = useRouteState("status", rs.string("open"));
const creating = useRouteState("new", rs.boolean(false));
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const requests = useRequests(computed(() => ({ branch: branch.value, status: status.value === "all" ? undefined : status.value })));
const table = useDataTable({ id: "stock.defektura", pageSize: 300 });
const canEdit = computed(() => company.can(["stock.manage", "stock.operate"]));

const STATUSES: RequestStatus[] = ["open", "ordered", "fulfilled", "cancelled"];
const STATUS_TONES: Record<RequestStatus, "warning" | "info" | "success" | "neutral"> = { open: "warning", ordered: "info", fulfilled: "success", cancelled: "neutral" };
const statusOptions = computed(() => [
  { value: "open", label: t("stock.requestStatus.open") },
  { value: "ordered", label: t("stock.requestStatus.ordered") },
  { value: "fulfilled", label: t("stock.requestStatus.fulfilled") },
  { value: "all", label: t("stock.receipts.all") },
]);
const changeOptions = computed(() => STATUSES.map((value) => ({ value, label: t(`stock.requestStatus.${value}`) })));

const columns = computed<TableColumn<MissingRequest>[]>(() => [
  { id: "requested_at", header: t("stock.defektura.asked"), width: 150, sticky: true },
  { id: "name", header: t("stock.col.name"), minWidth: 240 },
  { id: "packs", header: t("stock.field.packs"), numeric: true, width: 90 },
  { id: "branch", header: t("stock.col.branch"), width: 140, value: (row) => row.branch_ref.name },
  { id: "phone", header: t("stock.defektura.phone"), width: 150, value: (row) => row.customer_phone },
  { id: "status", header: t("stock.col.status"), width: 170 },
]);

async function change(row: MissingRequest, value: RequestStatus | null): Promise<void> {
  if (!value || value === row.status) return;
  try {
    await stockApi.setRequestStatus(company.currentId ?? 0, row.id, value);
    refresh();
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  }
}

const form = reactive({ branch: null as number | null, product: null as number | null, name: "", packs: 1 as number | null, phone: "" });
const saving = ref(false);
const error = ref<string | null>(null);
watch(creating, (value) => {
  if (!value) return;
  error.value = null;
  Object.assign(form, { product: null, name: "", packs: 1, phone: "" });
  if (form.branch === null && company.branchFilter.length === 1) form.branch = company.branchFilter[0] ?? null;
});
async function save(): Promise<void> {
  error.value = null;
  if (!form.branch || (!form.product && !form.name.trim())) {
    error.value = t("stock.defektura.errItem");
    return;
  }
  saving.value = true;
  try {
    await stockApi.addRequest(company.currentId ?? 0, {
      branch: form.branch,
      product: form.product,
      name: form.name.trim(),
      packs: String(form.packs ?? 1),
      customer_phone: form.phone.trim(),
    });
    toast.success(t("stock.defektura.saved"));
    refresh();
    creating.value = false;
  } catch (err) {
    error.value = isApiError(err) ? err.message : t("common.error.generic");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.defektura')" :description="t('stock.defektura.description')">
      <template #actions>
        <UiButton v-if="canEdit" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.defektura.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="requests.data.value && !requests.data.value.length && status === 'open'" class="ui-card">
      <EmptyState :icon="ClipboardX" :title="t('stock.defektura.emptyTitle')" :description="t('stock.defektura.emptyBody')" />
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="requests.data.value"
      row-key="id"
      :loading="requests.isPending.value"
      :error="requests.error.value"
      :retry="() => requests.refetch()"
      hide-pagination
      csv-name="defektura"
    >
      <template #toolbar><SegmentedControl v-model="status" :options="statusOptions" size="sm" /></template>
      <template #cell-requested_at="{ row }">{{ fmt.instant(row.requested_at, "short") }}</template>
      <template #cell-name="{ row }">
        <span class="flex flex-col">
          <span class="text-fg">{{ row.product_ref?.name ?? row.name }}</span>
          <span v-if="row.source === 'mandatory'" class="text-xs text-warning">{{ t("stock.defektura.fromMandatory") }}</span>
          <span v-else-if="row.requested_by" class="text-xs text-muted">{{ row.requested_by.name }}</span>
        </span>
      </template>
      <template #cell-packs="{ row }">{{ qtyText(num(row.packs)) }}</template>
      <template #cell-status="{ row }">
        <SelectBox v-if="canEdit" :model-value="row.status" :options="changeOptions" size="sm" class="w-40" @update:model-value="(value: RequestStatus | null) => change(row, value)" />
        <StatusPill v-else :tone="STATUS_TONES[row.status]" size="sm" :label="t(`stock.requestStatus.${row.status}`)" />
      </template>
    </DataTable>

    <UiDialog v-model:open="creating" :title="t('stock.defektura.newTitle')" :description="t('stock.defektura.newDescription')" size="sm">
      <div class="flex flex-col gap-3">
        <FormField :label="t('stock.field.branch')" required>
          <BranchPicker v-model="form.branch" :clearable="false" />
        </FormField>
        <FormField :label="t('stock.field.product')" :hint="t('stock.defektura.productHint')">
          <ProductPicker v-model="form.product" />
        </FormField>
        <FormField v-if="!form.product" :label="t('stock.defektura.name')">
          <TextInput v-model="form.name" :maxlength="200" />
        </FormField>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('stock.field.packs')">
            <NumberInput v-model="form.packs" :min="1" :max="1000" />
          </FormField>
          <FormField :label="t('stock.defektura.phone')" :hint="t('stock.defektura.phoneHint')" optional>
            <TextInput v-model="form.phone" type="tel" :maxlength="16" inputmode="tel" />
          </FormField>
        </div>
        <p v-if="error" class="text-sm text-danger">{{ error }}</p>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
