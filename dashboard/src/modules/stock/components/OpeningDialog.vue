<script setup lang="ts">
/**
 * Opening stock: what is on the shelf before the books moved here, entered by series, expiry and
 * cost per pack (Get started's "Enter opening stock"). The retail price is proposed from the
 * markup and, for a prescription medicine, kept under its legal cap.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import { packsAndParts } from "../lib";
import type { Product } from "../types";
import ProductPicker from "./ProductPicker.vue";

const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const product = ref<Product | null>(null);
const form = reactive({
  branch: null as number | null,
  product: null as number | null,
  series: "",
  expires_on: null as string | null,
  packs: null as number | null,
  parts: null as number | null,
  unit_cost: null as string | null,
  retail_price: null as string | null,
});

watch(open, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, { product: null, series: "", expires_on: null, packs: null, parts: null, unit_cost: null, retail_price: null });
  product.value = null;
  if (form.branch === null && company.branchFilter.length === 1) form.branch = company.branchFilter[0] ?? null;
});

const per = computed(() => product.value?.units_per_pack ?? 1);
const total = computed(() => (form.packs ?? 0) * per.value + (form.parts ?? 0));

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.branch) errors.branch = t("stock.opening.errBranch");
  if (!form.product) errors.product = t("stock.opening.errProduct");
  if (!form.series.trim()) errors.series = t("stock.opening.errSeries");
  if (!form.expires_on) errors.expires_on = t("stock.opening.errExpiry");
  if (total.value <= 0) errors.packs = t("stock.opening.errQuantity");
  if (!form.unit_cost) errors.unit_cost = t("stock.opening.errCost");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await stockApi.opening(company.currentId ?? 0, {
      branch: form.branch!,
      product: form.product!,
      series: form.series.trim(),
      expires_on: form.expires_on!,
      packs: String(form.packs ?? 0),
      parts: String(form.parts ?? 0),
      unit_cost: form.unit_cost!,
      retail_price: form.retail_price || null,
    });
    toast.success(t("stock.opening.saved", { qty: packsAndParts(total.value, per.value, product.value?.part_label ?? "", t) }));
    refresh();
    // Keep the branch and the dialog open for the next series.
    Object.assign(form, { series: "", expires_on: null, packs: null, parts: null, unit_cost: null, retail_price: null });
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["branch", "product", "series", "expires_on", "packs", "unit_cost"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.opening.title')" :description="t('stock.opening.description')" size="md">
    <div class="flex flex-col gap-3">
      <FormField :label="t('stock.field.branch')" :error="errors.branch" required>
        <BranchPicker v-model="form.branch" :clearable="false" />
      </FormField>
      <FormField :label="t('stock.field.product')" :error="errors.product" required>
        <ProductPicker v-model="form.product" :invalid="!!errors.product" @change="(row) => (product = row)" />
      </FormField>
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('stock.field.series')" :error="errors.series" required>
          <TextInput v-model="form.series" :maxlength="40" mono />
        </FormField>
        <FormField :label="t('stock.field.expiresOn')" :error="errors.expires_on" required>
          <DatePicker v-model="form.expires_on" />
        </FormField>
        <FormField :label="t('stock.field.packs')" :error="errors.packs">
          <NumberInput v-model="form.packs" :min="0" />
        </FormField>
        <FormField v-if="per > 1" :label="t('stock.field.looseParts', { label: product?.part_label || t('stock.drawer.parts') })">
          <NumberInput v-model="form.parts" :min="0" :max="per - 1" />
        </FormField>
        <FormField :label="t('stock.field.unitCost')" :hint="t('stock.opening.costHint')" :error="errors.unit_cost" required>
          <MoneyInput v-model="form.unit_cost" />
        </FormField>
        <FormField :label="t('stock.field.retailPrice')" :hint="t('stock.opening.priceHint')" optional>
          <MoneyInput v-model="form.retail_price" />
        </FormField>
      </div>
      <p v-if="product && total > 0" class="text-sm text-muted">{{ t("stock.opening.total", { qty: packsAndParts(total, per, product.part_label, t) }) }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
      <UiButton variant="primary" :loading="saving" @click="save">{{ t("stock.opening.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
