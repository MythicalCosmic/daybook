<script setup lang="ts">
/**
 * Distributors (Distribyutorlar) and their terms: the payment days that set a receipt's due date,
 * whether they are the importer or an official dealer of the imported medicines they bring (a
 * receipt from anyone else warns), delivery days, the smallest order and how orders are sent.
 * The distributor itself lives in Finance's party directory; this page keeps the stock terms.
 */
import { Pencil, Plus, Truck } from "@lucide/vue";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh, useSuppliers } from "../api";
import type { OrderChannel, Supplier } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();

const creating = useRouteState("new", rs.boolean(false));
const suppliers = useSuppliers();
const table = useDataTable({ id: "stock.suppliers", pageSize: 300 });
const canManage = computed(() => company.can("stock.manage"));

const columns = computed<TableColumn<Supplier>[]>(() => [
  { id: "name", header: t("stock.col.supplier"), minWidth: 240, sticky: true },
  { id: "terms", header: t("stock.supplier.terms"), width: 170 },
  { id: "official_dealer", header: t("stock.supplier.dealer"), width: 160 },
  { id: "delivery_days", header: t("stock.supplier.delivery"), width: 130 },
  { id: "min_order", header: t("stock.supplier.minOrder"), numeric: true, width: 140 },
  { id: "receipts", header: t("stock.supplier.receipts"), numeric: true, width: 110 },
  { id: "actions", header: "", width: 60, hideable: false },
]);

const editing = ref<Supplier | null>(null);
const dialog = ref(false);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({
  name: "",
  payment_terms_days: null as number | null,
  official_dealer: false,
  delivery_days: 1 as number | null,
  min_order: null as string | null,
  order_channel: "phone" as OrderChannel,
  telegram_username: "",
  notes: "",
});
const channelOptions = computed(() => (["telegram", "email", "phone", "portal", "other"] as const).map((value) => ({ value, label: t(`stock.channel.${value}`) })));

function edit(row: Supplier | null): void {
  editing.value = row;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, {
    name: row?.name ?? "",
    payment_terms_days: row?.payment_terms_days ?? null,
    official_dealer: row?.official_dealer ?? false,
    delivery_days: row?.delivery_days ?? 1,
    min_order: row?.min_order ?? null,
    order_channel: row?.order_channel ?? "phone",
    telegram_username: row?.telegram_username ?? "",
    notes: row?.notes ?? "",
  });
  dialog.value = true;
}
if (creating.value) edit(null);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!editing.value && !form.name.trim()) {
    errors.name = t("stock.supplier.errName");
    return;
  }
  saving.value = true;
  const input = {
    payment_terms_days: form.payment_terms_days,
    official_dealer: form.official_dealer,
    delivery_days: form.delivery_days ?? 1,
    min_order: form.min_order || null,
    order_channel: form.order_channel,
    telegram_username: form.telegram_username.trim(),
    notes: form.notes,
  };
  try {
    const cid = company.currentId ?? 0;
    if (editing.value) await stockApi.updateSupplier(cid, editing.value.id, input);
    else await stockApi.createSupplier(cid, { name: form.name.trim(), ...input });
    toast.success(t("stock.supplier.saved"));
    refresh();
    dialog.value = false;
    creating.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["name", "payment_terms_days"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.suppliers')" :description="t('stock.suppliers.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="edit(null)">{{ t("stock.suppliers.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="suppliers.data.value && !suppliers.data.value.length" class="ui-card">
      <EmptyState :icon="Truck" :title="t('stock.suppliers.emptyTitle')" :description="t('stock.suppliers.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="edit(null)">{{ t("stock.suppliers.new") }}</UiButton>
      </EmptyState>
    </div>
    <DataTable
      v-else
      :state="table"
      :columns="columns"
      :rows="suppliers.data.value"
      row-key="id"
      :loading="suppliers.isPending.value"
      :error="suppliers.error.value"
      :retry="() => suppliers.refetch()"
      hide-pagination
      csv-name="distributors"
    >
      <template #cell-name="{ row }">
        <span class="flex flex-col">
          <span class="font-medium text-fg">{{ row.name }}</span>
          <span v-if="row.phone || row.telegram_username" class="text-xs text-muted">{{ [row.phone, row.telegram_username ? `@${row.telegram_username}` : ""].filter(Boolean).join(" · ") }}</span>
        </span>
      </template>
      <template #cell-terms="{ row }">{{ row.payment_terms_days ? t("stock.supplier.termsDays", { n: row.payment_terms_days }, row.payment_terms_days) : t("stock.supplier.onDelivery") }}</template>
      <template #cell-official_dealer="{ row }">
        <StatusPill v-if="row.official_dealer" tone="success" size="sm" :label="t('stock.supplier.official')" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-delivery_days="{ row }">{{ t("stock.supplier.deliveryDays", { n: row.delivery_days }, row.delivery_days) }}</template>
      <template #cell-min_order="{ row }">
        <MoneyText v-if="row.min_order" :value="row.min_order" decimals="never" />
        <span v-else class="text-subtle">—</span>
      </template>
      <template #cell-actions="{ row }">
        <IconButton v-if="canManage" :icon="Pencil" size="sm" :label="t('common.edit')" @click="edit(row)" />
      </template>
    </DataTable>

    <UiDialog v-model:open="dialog" :title="editing ? editing.name : t('stock.suppliers.newTitle')" :description="t('stock.suppliers.formDescription')" size="md" @update:open="(value) => !value && (creating = false)">
      <div class="flex flex-col gap-3">
        <FormField v-if="!editing" :label="t('stock.supplier.name')" :error="errors.name" required>
          <TextInput v-model="form.name" :maxlength="200" />
        </FormField>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('stock.supplier.terms')" :hint="t('stock.supplier.termsHint')" :error="errors.payment_terms_days">
            <NumberInput v-model="form.payment_terms_days" :min="0" :max="365" :suffix="t('stock.supplier.days')" />
          </FormField>
          <FormField :label="t('stock.supplier.delivery')">
            <NumberInput v-model="form.delivery_days" :min="0" :max="60" :suffix="t('stock.supplier.days')" />
          </FormField>
          <FormField :label="t('stock.supplier.minOrder')" optional>
            <MoneyInput v-model="form.min_order" />
          </FormField>
          <FormField :label="t('stock.supplier.channel')">
            <SelectBox v-model="form.order_channel" :options="channelOptions" />
          </FormField>
        </div>
        <FormField :label="t('stock.supplier.telegram')" optional>
          <TextInput v-model="form.telegram_username" :maxlength="64" prefix="@" />
        </FormField>
        <ToggleSwitch v-model="form.official_dealer" :label="t('stock.supplier.dealer')" :description="t('stock.supplier.dealerHint')" />
        <FormField :label="t('stock.field.note')" optional>
          <TextArea v-model="form.notes" :rows="2" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="dialog = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
