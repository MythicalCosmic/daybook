<script setup lang="ts">
/**
 * Start a goods receipt (Kirim, nakladnoy): the pharmacy, the distributor and its invoice. The due
 * date follows the distributor's payment terms unless given. The lines are added on the receipt's
 * page, where it is sent for posting and posted.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useRefresh, useSuppliers } from "../api";

const open = defineModel<boolean>("open", { default: false });
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();
const refresh = useRefresh();
const suppliers = useSuppliers(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ branch: null as number | null, supplier: null as number | null, invoice: "", date: null as string | null, due: null as string | null, note: "" });

watch(open, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, { supplier: null, invoice: "", date: today.value, due: null, note: "" });
  if (form.branch === null && company.branchFilter.length === 1) form.branch = company.branchFilter[0] ?? null;
});

const supplierOptions = computed(() =>
  (suppliers.data.value ?? []).map((row) => ({
    value: row.id,
    label: row.name,
    description: row.payment_terms_days ? t("stock.supplier.termsDays", { n: row.payment_terms_days }, row.payment_terms_days) : t("stock.supplier.onDelivery"),
  })),
);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.branch) errors.branch = t("stock.receipt.errBranch");
  if (!form.supplier) errors.supplier = t("stock.receipt.errSupplier");
  if (!form.date) errors.supplier_invoice_date = t("stock.receipt.errDate");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const detail = await stockApi.createReceipt(company.currentId ?? 0, {
      branch: form.branch!,
      supplier: form.supplier!,
      supplier_invoice_number: form.invoice.trim(),
      supplier_invoice_date: form.date!,
      due_on: form.due,
      note: form.note.trim(),
    });
    toast.success(t("stock.receipt.created"));
    refresh();
    emit("saved", detail.receipt.id);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["branch", "supplier", "supplier_invoice_number", "supplier_invoice_date", "due_on"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.receipt.newTitle')" :description="t('stock.receipt.newDescription')" size="md">
    <div class="flex flex-col gap-3">
      <FormField :label="t('stock.field.branch')" :error="errors.branch" required>
        <BranchPicker v-model="form.branch" :clearable="false" />
      </FormField>
      <FormField :label="t('stock.field.supplier')" :error="errors.supplier" :hint="!supplierOptions.length ? t('stock.receipt.noSuppliers') : undefined" required>
        <SelectBox v-model="form.supplier" :options="supplierOptions" clearable :placeholder="t('stock.receipt.pickSupplier')" />
      </FormField>
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('stock.field.invoiceNumber')" :error="errors.supplier_invoice_number">
          <TextInput v-model="form.invoice" :maxlength="40" mono />
        </FormField>
        <FormField :label="t('stock.field.invoiceDate')" :error="errors.supplier_invoice_date" required>
          <DatePicker v-model="form.date" />
        </FormField>
      </div>
      <FormField :label="t('stock.field.dueOn')" :hint="t('stock.receipt.dueHint')" :error="errors.due_on" optional>
        <DatePicker v-model="form.due" clearable />
      </FormField>
      <FormField :label="t('stock.field.note')" optional>
        <TextArea v-model="form.note" :rows="2" :maxlength="2000" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="receipt-create" @click="save">{{ t("stock.receipt.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
