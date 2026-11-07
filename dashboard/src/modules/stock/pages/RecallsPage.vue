<script setup lang="ts">
/**
 * Recalled and rejected series (Brak seriyalar): a regulator's list or a distributor's letter. On
 * registering, every matching batch in every pharmacy leaves sale and each pharmacy holding it gets
 * a "remove this series" task. A recall closes once every found pack was written off. A row opens
 * it (`?recall=<id>`); `?new=1` registers one.
 */
import { PackageX, Plus, ShieldAlert } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError, unshownFieldError } from "@/api/http";
import DataTable from "@/components/DataTable.vue";
import DatePicker from "@/components/DatePicker.vue";
import DescriptionList from "@/components/DescriptionList.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useRecalls, useRefresh } from "../api";
import ProductPicker from "../components/ProductPicker.vue";
import WriteOffFormDialog from "../components/WriteOffFormDialog.vue";
import { num, packsAndParts } from "../lib";
import type { BatchPrefill, FoundRow, Recall } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const route = useRoute();
const router = useRouter();
const today = useCompanyToday();
const refresh = useRefresh();

const status = useRouteState("status", rs.string("open"));
const creating = useRouteState("new", rs.boolean(false));
const recalls = useRecalls(computed(() => ({ status: status.value === "all" ? undefined : status.value })));
const table = useDataTable({ id: "stock.recalls", pageSize: 200 });
const canManage = computed(() => company.can("stock.manage"));
const canPropose = computed(() => company.can(["stock.manage", "stock.operate"]));

const statusOptions = computed(() => [
  { value: "open", label: t("stock.recallStatus.open") },
  { value: "closed", label: t("stock.recallStatus.closed") },
  { value: "all", label: t("stock.receipts.all") },
]);
const columns = computed<TableColumn<Recall>[]>(() => [
  { id: "received_on", header: t("stock.recall.receivedOn"), width: 130, sticky: true },
  { id: "name", header: t("stock.col.name"), minWidth: 240, value: (row) => row.product?.name ?? row.inn_or_name },
  { id: "series", header: t("stock.col.series"), width: 130 },
  { id: "found", header: t("stock.recall.found"), width: 170 },
  { id: "status", header: t("stock.col.status"), width: 120 },
]);

const selectedId = computed(() => Number(route.query.recall ?? 0) || 0);
const selected = computed(() => (recalls.data.value ?? []).find((row) => row.id === selectedId.value) ?? null);
function open(row: Recall): void {
  patchQuery(router, { recall: String(row.id) });
}

const form = reactive({ product: null as number | null, name: "", series: "", reason: "", source: "", received: null as string | null });
const errors = reactive<Record<string, string | undefined>>({});
const saving = ref(false);
watch(creating, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, { product: null, name: "", series: "", reason: "", source: "", received: today.value });
});
async function register(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.product && !form.name.trim()) errors.product = t("stock.recall.errProduct");
  if (!form.series.trim()) errors.series = t("stock.recall.errSeries");
  if (!form.reason.trim()) errors.reason = t("stock.recall.errReason");
  if (!form.source.trim()) errors.source = t("stock.recall.errSource");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const recall = await stockApi.createRecall(company.currentId ?? 0, {
      product: form.product,
      inn_or_name: form.name.trim(),
      series: form.series.trim(),
      reason: form.reason.trim(),
      source: form.source.trim(),
      received_on: form.received ?? today.value,
    });
    toast.success(recall.found.length ? t("stock.recall.foundToast", { n: recall.found.length }, recall.found.length) : t("stock.recall.notFoundToast"));
    refresh();
    creating.value = false;
    patchQuery(router, { recall: String(recall.id), new: undefined });
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["product", "series", "reason", "source"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}

const closing = ref(false);
async function close(recall: Recall): Promise<void> {
  closing.value = true;
  try {
    await stockApi.closeRecall(company.currentId ?? 0, recall.id);
    toast.success(t("stock.recall.closedToast"));
    refresh();
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    closing.value = false;
  }
}

const writeoffOpen = ref(false);
const writeoffBranch = ref<number | null>(null);
const writeoffPrefill = ref<BatchPrefill[]>([]);
function writeOff(recall: Recall, row: FoundRow): void {
  const rows = recall.found.filter((item) => item.branch_id === row.branch_id && num(item.left) > 0);
  writeoffBranch.value = row.branch_id;
  writeoffPrefill.value = rows.map((item) => ({ product: { id: item.product_id, name: item.product }, unitsPerPack: 1, partLabel: "", batchId: item.batch_id, series: item.series, quantity: num(item.left) }));
  writeoffOpen.value = true;
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.recalls')" :description="t('stock.recalls.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="creating = true">{{ t("stock.recalls.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="recalls.data.value && !recalls.data.value.length && status === 'open'" class="ui-card">
      <EmptyState :icon="ShieldAlert" :title="t('stock.recalls.emptyTitle')" :description="t('stock.recalls.emptyBody')" />
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="recalls.data.value"
      row-key="id"
      :loading="recalls.isPending.value"
      :error="recalls.error.value"
      :retry="() => recalls.refetch()"
      clickable
      hide-pagination
      csv-name="recalls"
      @row-click="open"
    >
      <template #toolbar><SegmentedControl v-model="status" :options="statusOptions" size="sm" /></template>
      <template #cell-received_on="{ row }">{{ fmt.day(row.received_on) }}</template>
      <template #cell-series="{ row }"><span class="font-mono text-xs">{{ row.series }}</span></template>
      <template #cell-found="{ row }">
        <StatusPill v-if="row.found.length" :tone="num(row.left) > 0 ? 'danger' : 'success'" size="sm" :label="num(row.left) > 0 ? t('stock.recall.leftN', { n: row.found.length }, row.found.length) : t('stock.recall.allOff')" />
        <span v-else class="text-xs text-muted">{{ t("stock.recall.notFound") }}</span>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="row.status === 'open' ? 'warning' : 'neutral'" size="sm" :label="t(`stock.recallStatus.${row.status}`)" /></template>
    </DataTable>

    <UiDrawer query-key="recall" :title="selected ? `${selected.product?.name ?? selected.inn_or_name} · ${selected.series}` : t('stock.recall.title')" size="md">
      <div v-if="selected" class="flex flex-col gap-4" data-testid="recall-drawer">
        <DescriptionList
          layout="rows"
          :items="[
            { key: 'reason', label: t('stock.recall.reason'), value: selected.reason },
            { key: 'source', label: t('stock.recall.source'), value: selected.source },
            { key: 'received', label: t('stock.recall.receivedOn'), value: fmt.day(selected.received_on) },
          ]"
        />
        <section>
          <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("stock.recall.foundTitle") }}</h3>
          <ul class="divide-y divide-line rounded-[12px] border border-line">
            <li v-for="row in selected.found" :key="`${row.branch_id}-${row.batch_id}`" class="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
              <span class="min-w-0 flex-1">
                <span class="block text-fg">{{ row.branch }}</span>
                <span class="block text-xs text-muted">{{ row.product }} · {{ t("stock.batch.series", { series: row.series }) }}</span>
              </span>
              <span :class="['tabular-nums', num(row.left) > 0 ? 'font-medium text-danger' : 'text-success']">
                {{ num(row.left) > 0 ? t("stock.recall.leftQty", { qty: packsAndParts(row.left, 1, "", t) }) : t("stock.recall.writtenOff") }}
              </span>
              <UiButton v-if="num(row.left) > 0 && canPropose && selected.status === 'open'" size="sm" variant="secondary" :icon="PackageX" @click="writeOff(selected, row)">{{ t("stock.recall.writeOff") }}</UiButton>
            </li>
            <li v-if="!selected.found.length" class="px-3 py-3 text-sm text-muted">{{ t("stock.recall.notFoundBody") }}</li>
          </ul>
        </section>
        <InlineAlert v-if="selected.status === 'closed'" tone="success" size="sm">{{ t("stock.recall.closedNote", { day: selected.closed_at ? fmt.instant(selected.closed_at, "date") : "" }) }}</InlineAlert>
      </div>
      <template v-if="selected && selected.status === 'open' && canManage" #footer>
        <UiButton variant="primary" :disabled="num(selected.left) > 0" :loading="closing" @click="close(selected)">{{ t("stock.recall.close") }}</UiButton>
      </template>
    </UiDrawer>

    <UiDialog v-model:open="creating" :title="t('stock.recalls.newTitle')" :description="t('stock.recalls.newDescription')" size="md">
      <div class="flex flex-col gap-3">
        <FormField :label="t('stock.field.product')" :hint="t('stock.recall.productHint')" :error="errors.product">
          <ProductPicker v-model="form.product" />
        </FormField>
        <FormField v-if="!form.product" :label="t('stock.recall.innOrName')" optional>
          <TextInput v-model="form.name" :maxlength="200" />
        </FormField>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('stock.field.series')" :error="errors.series" required>
            <TextInput v-model="form.series" :maxlength="40" mono />
          </FormField>
          <FormField :label="t('stock.recall.receivedOn')" required>
            <DatePicker v-model="form.received" />
          </FormField>
        </div>
        <FormField :label="t('stock.recall.reason')" :error="errors.reason" required>
          <TextInput v-model="form.reason" :maxlength="200" />
        </FormField>
        <FormField :label="t('stock.recall.source')" :hint="t('stock.recall.sourceHint')" :error="errors.source" required>
          <TextInput v-model="form.source" :maxlength="200" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" data-testid="recall-save" @click="register">{{ t("stock.recall.register") }}</UiButton>
      </template>
    </UiDialog>

    <WriteOffFormDialog v-model:open="writeoffOpen" :branch="writeoffBranch" reason="recall" :prefill="writeoffPrefill" :recall="selected?.id ?? null" @saved="(id) => router.push(`/c/${company.currentId}/stock/write-offs/${id}`)" />
  </div>
</template>
