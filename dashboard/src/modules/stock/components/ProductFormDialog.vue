<script setup lang="ts">
/**
 * Add or correct a catalogue item: what it is (name, INN, form, strength, parts in a pack), the
 * law's marks (prescription only, the e-prescription group, controlled class, restricted channel,
 * socially significant, the mandatory list), storage, codes and registration, and its list price.
 * Prices of medicines on stock come from their batches; the list price is for items without one.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useCategories, useManufacturers, useRefresh } from "../api";
import { CONTROL_CLASSES, DOSAGE_FORMS, PRODUCT_KINDS, STORAGES, type ControlClass, type DosageForm, type Product, type ProductInput, type ProductKind, type Storage } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ product?: Product | null }>();
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const manufacturers = useManufacturers(open);
const categories = useCategories(open);

const editing = computed(() => !!props.product);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

function blank() {
  return {
    name: "",
    trade_name: "",
    inn: "",
    kind: "medicine" as ProductKind,
    dosage_form: null as DosageForm | null,
    strength: "",
    units_per_pack: 1 as number | null,
    part_label: "",
    manufacturer: null as number | null,
    category: null as number | null,
    rx_required: false,
    e_rx_group: false,
    control_class: "none" as ControlClass,
    restricted_channel: false,
    storage: "room" as Storage,
    light_sensitive: false,
    barcode: "",
    sku: "",
    mxik_code: "",
    registration_number: "",
    registration_until: null as string | null,
    marking_required: false,
    vat_percent: null as number | null,
    socially_significant: false,
    mandatory_list: false,
    reference_price: null as string | null,
    reference_price_on: null as string | null,
    sale_price: null as string | null,
    part_price: null as string | null,
    track_stock: true,
    is_active: true,
  };
}
const form = reactive(blank());

watch(
  () => [open.value, props.product] as const,
  ([isOpen, product]) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, blank());
    if (!product) return;
    Object.assign(form, {
      name: product.name,
      trade_name: product.trade_name,
      inn: product.inn,
      kind: product.kind,
      dosage_form: product.dosage_form || null,
      strength: product.strength,
      units_per_pack: product.units_per_pack,
      part_label: product.part_label,
      manufacturer: product.manufacturer?.id ?? null,
      category: product.category?.id ?? null,
      rx_required: product.rx_required,
      e_rx_group: product.e_rx_group,
      control_class: product.control_class,
      restricted_channel: product.restricted_channel,
      storage: product.storage,
      light_sensitive: product.light_sensitive,
      barcode: product.barcode,
      sku: product.sku,
      mxik_code: product.mxik_code,
      registration_number: product.registration_number,
      registration_until: product.registration_until,
      marking_required: product.marking_required,
      vat_percent: product.vat_percent === null ? null : Number(product.vat_percent),
      socially_significant: product.socially_significant,
      mandatory_list: product.mandatory_list,
      reference_price: product.reference_price,
      reference_price_on: product.reference_price_on,
      sale_price: product.sale_price,
      part_price: product.part_price,
      track_stock: product.track_stock,
      is_active: product.is_active,
    });
  },
  { immediate: true },
);

const kindOptions = computed(() => PRODUCT_KINDS.map((value) => ({ value, label: t(`stock.kind.${value}`) })));
const formOptions = computed(() => DOSAGE_FORMS.map((value) => ({ value, label: t(`stock.dosage.${value}`) })));
const controlOptions = computed(() => CONTROL_CLASSES.map((value) => ({ value, label: t(`stock.control.${value}`) })));
const storageOptions = computed(() => STORAGES.map((value) => ({ value, label: t(`stock.storage.${value}`) })));
const manufacturerOptions = computed(() => (manufacturers.data.value ?? []).map((row) => ({ value: row.id, label: row.name, description: row.country || undefined })));
const categoryOptions = computed(() => {
  const rows = categories.data.value ?? [];
  const names = new Map(rows.map((row) => [row.id, row.name]));
  return rows.map((row) => ({ value: row.id, label: row.parent ? `${names.get(row.parent) ?? ""} › ${row.name}` : row.name }));
});
const isMedicine = computed(() => form.kind === "medicine");

async function addManufacturer(name: string): Promise<void> {
  const text = name.trim();
  if (!text) return;
  const row = await stockApi.createManufacturer(company.currentId ?? 0, { name: text });
  await manufacturers.refetch();
  form.manufacturer = row.id;
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.name.trim()) errors.name = t("stock.form.errName");
  if (!form.units_per_pack || form.units_per_pack < 1) errors.units_per_pack = t("stock.form.errParts");
  if (Object.keys(errors).length) return;
  saving.value = true;
  const input: ProductInput = {
    name: form.name.trim(),
    trade_name: form.trade_name.trim(),
    inn: form.inn.trim(),
    kind: form.kind,
    dosage_form: form.dosage_form ?? "",
    strength: form.strength.trim(),
    units_per_pack: form.units_per_pack ?? 1,
    part_label: form.part_label.trim(),
    manufacturer: form.manufacturer,
    category: form.category,
    rx_required: form.rx_required,
    e_rx_group: form.e_rx_group,
    control_class: form.control_class,
    restricted_channel: form.restricted_channel,
    storage: form.storage,
    light_sensitive: form.light_sensitive,
    barcode: form.barcode.trim(),
    sku: form.sku.trim(),
    mxik_code: form.mxik_code.trim(),
    registration_number: form.registration_number.trim(),
    registration_until: form.registration_until,
    marking_required: form.marking_required,
    vat_percent: form.vat_percent === null ? null : String(form.vat_percent),
    socially_significant: form.socially_significant,
    mandatory_list: form.mandatory_list,
    reference_price: form.reference_price || null,
    reference_price_on: form.reference_price_on,
    part_price: form.part_price || null,
    track_stock: form.track_stock,
    is_active: form.is_active,
  };
  if (form.sale_price) input.sale_price = form.sale_price;
  const cid = company.currentId ?? 0;
  try {
    const id = editing.value ? (await stockApi.updateProduct(cid, props.product!.id, input)).product.id : (await stockApi.createProduct(cid, input)).id;
    toast.success(editing.value ? t("stock.form.saved") : t("stock.form.created"));
    refresh();
    emit("saved", id);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["name", "units_per_pack", "barcode", "sku"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('stock.form.editTitle') : t('stock.form.newTitle')" :description="t('stock.form.description')" size="lg">
    <div class="flex flex-col gap-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField class="sm:col-span-2" :label="t('stock.field.name')" :hint="t('stock.form.nameHint')" :error="errors.name" required>
          <TextInput v-model="form.name" :maxlength="200" data-testid="product-name" />
        </FormField>
        <FormField :label="t('stock.field.inn')" :hint="t('stock.form.innHint')" :error="errors.inn">
          <TextInput v-model="form.inn" :maxlength="200" />
        </FormField>
        <FormField :label="t('stock.field.tradeName')" optional>
          <TextInput v-model="form.trade_name" :maxlength="120" />
        </FormField>
        <FormField :label="t('stock.field.kind')">
          <SelectBox v-model="form.kind" :options="kindOptions" />
        </FormField>
        <FormField :label="t('stock.field.dosageForm')" optional>
          <SelectBox v-model="form.dosage_form" :options="formOptions" clearable :placeholder="t('stock.form.noForm')" />
        </FormField>
        <FormField :label="t('stock.field.strength')" :hint="t('stock.form.strengthHint')" optional>
          <TextInput v-model="form.strength" :maxlength="40" />
        </FormField>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('stock.field.unitsPerPack')" :hint="t('stock.form.partsHint')" :error="errors.units_per_pack">
            <NumberInput v-model="form.units_per_pack" :min="1" :max="1000" />
          </FormField>
          <FormField :label="t('stock.field.partLabel')" optional>
            <TextInput v-model="form.part_label" :maxlength="12" :placeholder="t('stock.form.partLabelPlaceholder')" :disabled="(form.units_per_pack ?? 1) <= 1" />
          </FormField>
        </div>
        <FormField :label="t('stock.field.manufacturer')" optional>
          <ComboBox v-model="form.manufacturer" :options="manufacturerOptions" clearable creatable :placeholder="t('stock.form.pickManufacturer')" @create="addManufacturer" />
        </FormField>
        <FormField :label="t('stock.field.category')" optional>
          <SelectBox v-model="form.category" :options="categoryOptions" clearable :placeholder="t('stock.form.noCategory')" />
        </FormField>
      </div>

      <section v-if="isMedicine" class="flex flex-col gap-3 rounded-[12px] border border-line p-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("stock.form.lawTitle") }}</h3>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <ToggleSwitch v-model="form.rx_required" :label="t('stock.field.rxRequired')" :description="t('stock.form.rxHint')" />
          <ToggleSwitch v-model="form.e_rx_group" :label="t('stock.field.eRxGroup')" :description="t('stock.form.eRxHint')" />
          <ToggleSwitch v-model="form.socially_significant" :label="t('stock.field.social')" :description="t('stock.form.socialHint')" />
          <ToggleSwitch v-model="form.mandatory_list" :label="t('stock.field.mandatory')" :description="t('stock.form.mandatoryHint')" />
          <ToggleSwitch v-model="form.restricted_channel" :label="t('stock.field.restricted')" :description="t('stock.form.restrictedHint')" />
          <ToggleSwitch v-model="form.marking_required" :label="t('stock.field.marking')" />
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('stock.field.controlClass')" :hint="t('stock.form.controlHint')">
            <SelectBox v-model="form.control_class" :options="controlOptions" />
          </FormField>
          <FormField :label="t('stock.field.vat')" :hint="t('stock.form.vatHint')" optional>
            <NumberInput v-model="form.vat_percent" :min="0" :max="99" :decimals="2" suffix="%" />
          </FormField>
          <FormField :label="t('stock.field.referencePrice')" :hint="t('stock.form.referenceHint')" optional>
            <MoneyInput v-model="form.reference_price" />
          </FormField>
          <FormField :label="t('stock.field.referenceOn')" optional>
            <DatePicker v-model="form.reference_price_on" clearable />
          </FormField>
          <FormField :label="t('stock.field.registration')" optional>
            <TextInput v-model="form.registration_number" :maxlength="40" />
          </FormField>
          <FormField :label="t('stock.field.registrationUntil')" optional>
            <DatePicker v-model="form.registration_until" clearable />
          </FormField>
        </div>
      </section>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('stock.field.storage')">
          <SelectBox v-model="form.storage" :options="storageOptions" />
        </FormField>
        <div class="flex items-end pb-1">
          <ToggleSwitch v-model="form.light_sensitive" :label="t('stock.field.lightSensitive')" />
        </div>
        <FormField :label="t('stock.field.barcode')" :error="errors.barcode" optional>
          <TextInput v-model="form.barcode" :maxlength="32" mono inputmode="numeric" />
        </FormField>
        <FormField :label="t('stock.field.sku')" :error="errors.sku" optional>
          <TextInput v-model="form.sku" :maxlength="64" mono />
        </FormField>
        <FormField :label="t('stock.field.mxik')" :hint="t('stock.form.mxikHint')" optional>
          <TextInput v-model="form.mxik_code" :maxlength="17" mono inputmode="numeric" />
        </FormField>
        <FormField :label="t('stock.field.salePrice')" :hint="t('stock.form.salePriceHint')" optional>
          <MoneyInput v-model="form.sale_price" />
        </FormField>
        <FormField :label="t('stock.field.partPrice')" :hint="t('stock.form.partPriceHint')" optional>
          <MoneyInput v-model="form.part_price" :disabled="(form.units_per_pack ?? 1) <= 1" />
        </FormField>
      </div>
      <InlineAlert v-if="form.rx_required" tone="info" size="sm">{{ t("stock.form.capNote") }}</InlineAlert>
      <div class="flex flex-wrap gap-4">
        <ToggleSwitch v-model="form.track_stock" :label="t('stock.field.trackStock')" />
        <ToggleSwitch v-model="form.is_active" :label="t('stock.field.active')" />
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="product-save" @click="save">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
