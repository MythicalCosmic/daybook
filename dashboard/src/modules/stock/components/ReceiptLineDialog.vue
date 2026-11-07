<script setup lang="ts">
/**
 * One line of a receipt: the product, its series and expiry as printed on the pack, packs and the
 * cost per pack from the invoice (VAT included), and the retail price. The price is proposed from
 * the pricing rules (for a prescription medicine at most its legal cap); a price typed above the
 * cap is lowered to it when the receipt is posted.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import { qtyText } from "../lib";
import type { Product, ReceiptLine, ReceiptLineInput } from "../types";
import ProductPicker from "./ProductPicker.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ receiptId: number; line?: ReceiptLine | null; showCost: boolean }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const product = ref<{ units_per_pack: number; part_label: string; rx_required: boolean } | null>(null);
const form = reactive({
  product: null as number | null,
  series: "",
  expires_on: null as string | null,
  made_on: null as string | null,
  packs: null as number | null,
  unit_cost: null as string | null,
  vat: null as number | null,
  retail_price: null as string | null,
  supplier_rx: "unknown" as "unknown" | "yes" | "no",
});
const editing = computed(() => !!props.line);

watch(open, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  const line = props.line;
  Object.assign(form, {
    product: line?.product.id ?? null,
    series: line?.series ?? "",
    expires_on: line?.expires_on ?? null,
    made_on: line?.made_on ?? null,
    packs: line ? Number(line.packs) : null,
    unit_cost: line?.unit_cost ?? null,
    vat: line?.vat_percent ? Number(line.vat_percent) : null,
    retail_price: line?.retail_price ?? null,
    supplier_rx: line?.supplier_rx === true ? "yes" : line?.supplier_rx === false ? "no" : "unknown",
  });
  product.value = line ? { units_per_pack: line.units_per_pack, part_label: "", rx_required: line.rx_required } : null;
});

function picked(row: Product | null): void {
  product.value = row ? { units_per_pack: row.units_per_pack, part_label: row.part_label, rx_required: row.rx_required } : null;
  if (row?.vat_percent && form.vat === null) form.vat = Number(row.vat_percent);
}

const parts = computed(() => (form.packs ?? 0) * (product.value?.units_per_pack ?? 1));
const rxOptions = computed(() => [
  { value: "unknown" as const, label: t("stock.line.rxUnknown") },
  { value: "yes" as const, label: t("stock.line.rxYes") },
  { value: "no" as const, label: t("stock.line.rxNo") },
]);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.product) errors.product = t("stock.line.errProduct");
  if (!form.series.trim()) errors.series = t("stock.line.errSeries");
  if (!form.expires_on) errors.expires_on = t("stock.line.errExpiry");
  if (!form.packs || form.packs <= 0) errors.packs = t("stock.line.errPacks");
  if (!editing.value && !form.unit_cost) errors.unit_cost = t("stock.line.errCost");
  if (Object.keys(errors).length) return;
  saving.value = true;
  const input: ReceiptLineInput = {
    product: form.product!,
    series: form.series.trim(),
    expires_on: form.expires_on!,
    made_on: form.made_on,
    packs: String(form.packs),
    unit_cost: form.unit_cost ?? "0",
    vat_percent: form.vat === null ? null : String(form.vat),
    retail_price: form.retail_price || null,
    supplier_rx: form.supplier_rx === "unknown" ? null : form.supplier_rx === "yes",
  };
  const cid = company.currentId ?? 0;
  try {
    if (editing.value) {
      const changes: Partial<ReceiptLineInput> = { ...input };
      // Without finance.view the cost isn't shown, so it isn't sent back either.
      if (!props.showCost && !form.unit_cost) delete changes.unit_cost;
      await stockApi.updateLine(cid, props.receiptId, props.line!.id, changes);
    } else {
      await stockApi.addLine(cid, props.receiptId, input);
    }
    toast.success(t("stock.line.saved"));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["product", "series", "expires_on", "packs", "unit_cost", "retail_price"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('stock.line.editTitle') : t('stock.line.newTitle')" size="md">
    <div class="flex flex-col gap-3">
      <FormField :label="t('stock.field.product')" :error="errors.product" required>
        <ProductPicker v-model="form.product" :initial="line ? line.product : null" :invalid="!!errors.product" @change="picked" />
      </FormField>
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('stock.field.series')" :error="errors.series" required>
          <TextInput v-model="form.series" :maxlength="40" mono data-testid="line-series" />
        </FormField>
        <FormField :label="t('stock.field.expiresOn')" :error="errors.expires_on" required>
          <DatePicker v-model="form.expires_on" />
        </FormField>
        <FormField :label="t('stock.field.packs')" :hint="product && product.units_per_pack > 1 && parts ? t('stock.line.partsTotal', { n: qtyText(parts), label: product.part_label || t('stock.drawer.parts') }) : undefined" :error="errors.packs" required>
          <NumberInput v-model="form.packs" :min="0" :decimals="3" />
        </FormField>
        <FormField :label="t('stock.field.madeOn')" optional>
          <DatePicker v-model="form.made_on" clearable />
        </FormField>
        <FormField v-if="showCost || !editing" :label="t('stock.field.unitCost')" :hint="t('stock.line.costHint')" :error="errors.unit_cost" :required="!editing">
          <MoneyInput v-model="form.unit_cost" />
        </FormField>
        <FormField :label="t('stock.field.vat')" optional>
          <NumberInput v-model="form.vat" :min="0" :max="99" :decimals="2" suffix="%" />
        </FormField>
        <FormField class="col-span-2" :label="t('stock.field.retailPrice')" :hint="product?.rx_required ? t('stock.line.rxPriceHint') : t('stock.line.priceHint')" :error="errors.retail_price" optional>
          <MoneyInput v-model="form.retail_price" />
        </FormField>
      </div>
      <FormField :label="t('stock.line.supplierRx')" :hint="t('stock.line.supplierRxHint')">
        <SegmentedControl v-model="form.supplier_rx" :options="rxOptions" size="sm" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="line-save" @click="save">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
