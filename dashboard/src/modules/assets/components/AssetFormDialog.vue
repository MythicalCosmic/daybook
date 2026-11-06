<script setup lang="ts">
/**
 * Add or correct an asset. The category fills in its useful life, method and residual value
 * (the owner can change them); the preview under the numbers says what it will cost a month and
 * when it is used up. From a purchase (`purchase`), the cost, day, branch and supplier come from
 * that expense, which then leaves the P&L. Once a month of it is in Finance, the depreciation
 * facts are history: the form says so and keeps them read-only (the page's actions change them).
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { assetsApi, useCategories, useRefresh } from "../api";
import type { AssetDetail, AssetInput, Method, Purchase } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ asset?: AssetDetail | null; purchase?: Purchase | null }>();
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const categories = useCategories(open);

const editing = computed(() => !!props.asset);
const locked = computed(() => !!props.asset?.booked);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const touched = reactive({ life: false, method: false, salvage: false });

const form = reactive({
  category: null as number | null,
  name: "",
  number: "",
  model: "",
  serial: "",
  branch: null as number | null,
  purchased_on: null as string | null,
  in_service_on: null as string | null,
  cost: null as string | null,
  salvage_value: null as string | null,
  life_months: null as number | null,
  method: "straight_line" as Method,
  declining_factor: 2,
  total_units: null as number | null,
  unit: "",
  opening_accumulated: null as string | null,
  books_depreciation: true,
  supplier_name: "",
  responsible: null as number | null,
  custodian: null as number | null,
  warranty_until: null as string | null,
  insurance_until: null as string | null,
  service_months: null as number | null,
  verify_months: null as number | null,
  notes: "",
});

const companyToday = useCompanyToday();

watch(
  () => [open.value, props.asset, props.purchase] as const,
  ([isOpen, asset, purchase]) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(touched, { life: !!asset, method: !!asset, salvage: !!asset });
    Object.assign(form, {
      category: asset?.asset.category.id ?? null,
      name: asset?.asset.name ?? purchase?.description ?? "",
      number: asset?.asset.number ?? "",
      model: asset?.asset.model ?? "",
      serial: asset?.serial ?? "",
      branch: asset?.asset.branch?.id ?? purchase?.branch?.id ?? null,
      purchased_on: asset?.purchased_on ?? purchase?.occurred_on ?? null,
      in_service_on: asset?.asset.in_service_on ?? purchase?.occurred_on ?? companyToday.value,
      cost: asset?.values.cost ?? purchase?.base_amount ?? null,
      salvage_value: asset?.values.salvage_value ?? null,
      life_months: asset?.life_months ?? null,
      method: asset?.method ?? "straight_line",
      declining_factor: Number(asset?.declining_factor ?? 2),
      total_units: asset?.total_units ? Number(asset.total_units) : null,
      unit: asset?.unit ?? "",
      opening_accumulated: asset?.opening_accumulated ?? null,
      books_depreciation: asset?.books_depreciation ?? true,
      supplier_name: asset?.supplier_name ?? purchase?.counterparty?.name ?? "",
      responsible: asset?.responsible?.id ?? null,
      custodian: null,
      warranty_until: asset?.warranty_until ?? null,
      insurance_until: asset?.insurance_until ?? null,
      service_months: asset?.service_months ?? null,
      verify_months: asset?.verify_months ?? null,
      notes: asset?.notes ?? "",
    });
  },
  { immediate: true },
);

const category = computed(() => categories.data.value?.find((row) => row.id === form.category) ?? null);
const lowValue = computed(() => category.value?.kind === "low_value");
const categoryOptions = computed(() =>
  (categories.data.value ?? []).filter((row) => row.is_active || row.id === form.category).map((row) => ({
    value: row.id,
    label: row.name,
    description: row.life_months ? t("assets.form.categoryLife", { years: fmt.number(row.life_months / 12, 1) }) : t(`assets.kind.${row.kind}`),
  })),
);
const methodOptions = computed(() =>
  (["straight_line", "declining", "sum_of_years", "units"] as const).map((value) => ({ value, label: t(`assets.method.${value}`), description: t(`assets.methodHint.${value}`) })),
);

// The category's defaults, until the owner picks their own.
watch(category, (row) => {
  if (!row || editing.value) return;
  if (!touched.life) form.life_months = row.life_months;
  if (!touched.method) form.method = row.kind === "low_value" ? "none" : row.method === "none" ? "straight_line" : row.method;
  if (!touched.salvage && form.cost) form.salvage_value = Number(row.salvage_percent) ? String(((Number(form.cost) * Number(row.salvage_percent)) / 100).toFixed(2)) : null;
  if (form.service_months === null) form.service_months = row.service_months;
  if (form.verify_months === null) form.verify_months = row.verify_months;
});

/** What it will cost a month, straight line: the honest first guess shown while typing. */
const preview = computed(() => {
  if (lowValue.value || !form.cost || !form.life_months || form.method === "units") return null;
  const base = Number(form.cost) - Number(form.salvage_value || 0) - Number(form.opening_accumulated || 0);
  if (base <= 0) return null;
  const monthly = base / form.life_months;
  const start = form.in_service_on ? new Date(`${form.in_service_on}T00:00:00Z`) : new Date();
  const end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + form.life_months, 1));
  return { monthly: monthly.toFixed(2), end: end.toISOString().slice(0, 10), declining: form.method !== "straight_line" };
});

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.category) errors.category = t("assets.form.errCategory");
  if (!form.name.trim()) errors.name = t("assets.form.errName");
  if (!lowValue.value && !locked.value) {
    if (!form.cost) errors.cost = t("assets.form.errCost");
    if (form.method !== "units" && !form.life_months) errors.life_months = t("assets.form.errLife");
    if (form.method === "units" && !form.total_units) errors.total_units = t("assets.form.errUnits");
  }
  if (Object.keys(errors).length) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  const input: AssetInput = {
    category: form.category ?? undefined,
    name: form.name.trim(),
    model: form.model.trim(),
    serial: form.serial.trim(),
    branch: form.branch,
    supplier_name: form.supplier_name.trim(),
    responsible: form.responsible,
    warranty_until: form.warranty_until,
    insurance_until: form.insurance_until,
    service_months: form.service_months,
    verify_months: form.verify_months,
    notes: form.notes,
  };
  if (form.number.trim()) input.number = form.number.trim();
  if (!locked.value) {
    Object.assign(input, {
      purchased_on: form.purchased_on,
      in_service_on: form.in_service_on,
      salvage_value: form.salvage_value || null,
      method: lowValue.value ? "none" : form.method,
      life_months: lowValue.value ? null : form.life_months,
      declining_factor: String(form.declining_factor),
      total_units: form.method === "units" && form.total_units ? String(form.total_units) : null,
      unit: form.unit.trim(),
      opening_accumulated: form.opening_accumulated || null,
      books_depreciation: form.books_depreciation,
    });
    if (!props.purchase) input.cost = form.cost || "0";
  }
  if (!editing.value && props.purchase) {
    input.purchase_transaction = props.purchase.id;
    delete input.purchased_on;
  }
  if (!editing.value && form.custodian) input.custodian = form.custodian;
  try {
    const page = editing.value ? await assetsApi.update(cid, props.asset!.asset.id, input) : await assetsApi.create(cid, input);
    toast.success(editing.value ? t("assets.form.saved") : t("assets.form.created", { number: page.asset.number }));
    refresh();
    emit("saved", page.asset.id);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["category", "name", "cost", "life_months", "total_units"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    :title="editing ? t('assets.form.editTitle') : purchase ? t('assets.form.fromPurchaseTitle') : t('assets.form.newTitle')"
    :description="editing ? undefined : t('assets.form.newDescription')"
    size="lg"
  >
    <div class="flex flex-col gap-5">
      <InlineAlert v-if="purchase" tone="info" :title="t('assets.form.purchaseTitle', { amount: fmt.money(purchase.base_amount, undefined, { decimals: 'never' }), day: fmt.day(purchase.occurred_on, 'medium') })">
        {{ t("assets.form.purchaseBody") }}
      </InlineAlert>
      <InlineAlert v-if="locked" tone="warning" :title="t('assets.form.lockedTitle')">{{ t("assets.form.lockedBody") }}</InlineAlert>

      <section class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("assets.form.what") }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.field.category')" :error="errors.category" required>
            <SelectBox v-model="form.category" :options="categoryOptions" :placeholder="t('assets.form.pickCategory')" />
          </FormField>
          <FormField :label="t('assets.field.name')" :error="errors.name" required>
            <TextInput v-model="form.name" :maxlength="120" :placeholder="t('assets.form.namePlaceholder')" />
          </FormField>
          <FormField :label="t('assets.field.model')" optional>
            <TextInput v-model="form.model" :maxlength="80" :placeholder="t('assets.form.modelPlaceholder')" />
          </FormField>
          <FormField :label="t('assets.field.serial')" optional>
            <TextInput v-model="form.serial" :maxlength="64" mono />
          </FormField>
          <FormField :label="t('assets.field.number')" :hint="editing ? undefined : t('assets.form.numberHint')" :error="errors.number" optional>
            <TextInput v-model="form.number" :maxlength="24" mono :placeholder="t('assets.form.numberPlaceholder')" />
          </FormField>
          <FormField :label="t('assets.field.branch')" :error="errors.branch" optional>
            <BranchPicker v-model="form.branch" clearable :placeholder="t('assets.form.companyLevel')" />
          </FormField>
        </div>
      </section>

      <section v-if="!lowValue" class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("assets.form.value") }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.field.cost')" :hint="t('assets.form.costHint')" :error="errors.cost" required>
            <MoneyInput v-model="form.cost" :disabled="locked || !!purchase" />
          </FormField>
          <FormField :label="t('assets.field.salvage')" :hint="t('assets.form.salvageHint')" :error="errors.salvage_value" optional>
            <MoneyInput v-model="form.salvage_value" :disabled="locked" @update:model-value="touched.salvage = true" />
          </FormField>
          <FormField :label="t('assets.field.purchasedOn')" optional>
            <DatePicker v-model="form.purchased_on" :max="companyToday" :disabled="locked || !!purchase" clearable />
          </FormField>
          <FormField :label="t('assets.field.inServiceOn')" :hint="t('assets.form.inServiceHint')" :error="errors.in_service_on">
            <DatePicker v-model="form.in_service_on" :disabled="locked" clearable />
          </FormField>
          <FormField :label="t('assets.field.method')" :error="errors.method">
            <SelectBox v-model="form.method" :options="methodOptions" :disabled="locked" @update:model-value="touched.method = true" />
          </FormField>
          <FormField v-if="form.method !== 'units'" :label="t('assets.field.life')" :hint="form.life_months ? t('assets.form.lifeYears', { years: fmt.number(form.life_months / 12, 1) }) : t('assets.form.lifeHint')" :error="errors.life_months" required>
            <NumberInput v-model="form.life_months" :min="1" :max="1200" :suffix="t('assets.form.months')" :disabled="locked" @update:model-value="touched.life = true" />
          </FormField>
          <template v-else>
            <FormField :label="t('assets.field.totalUnits')" :hint="t('assets.form.unitsHint')" :error="errors.total_units" required>
              <NumberInput v-model="form.total_units" :min="1" :disabled="locked" />
            </FormField>
            <FormField :label="t('assets.field.unit')" optional>
              <TextInput v-model="form.unit" :maxlength="16" :placeholder="t('assets.form.unitPlaceholder')" :disabled="locked" />
            </FormField>
          </template>
          <FormField v-if="form.method === 'declining'" :label="t('assets.field.factor')" :hint="t('assets.form.factorHint')">
            <NumberInput v-model="form.declining_factor" :min="1" :max="3" :step="0.5" :decimals="1" :disabled="locked" />
          </FormField>
          <FormField v-if="!editing && !purchase" :label="t('assets.field.opening')" :hint="t('assets.form.openingHint')" optional>
            <MoneyInput v-model="form.opening_accumulated" />
          </FormField>
        </div>
        <p v-if="preview" class="rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-fg" data-testid="asset-preview">
          {{ preview.declining ? t("assets.form.previewDeclining") : t("assets.form.preview") }}
          <span class="font-semibold"><MoneyText :value="preview.monthly" decimals="never" /></span>
          · {{ t("assets.form.previewEnd", { month: fmt.day(preview.end, "monthYear") }) }}
        </p>
        <ToggleSwitch v-model="form.books_depreciation" :disabled="locked" :label="t('assets.field.books')" :description="t('assets.form.booksHint')" />
      </section>
      <InlineAlert v-else tone="info" :title="t('assets.form.lowValueTitle')">{{ t("assets.form.lowValueBody") }}</InlineAlert>

      <section class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("assets.form.who") }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.field.responsible')" :hint="t('assets.form.responsibleHint')" optional>
            <PersonPicker v-model="form.responsible" clearable />
          </FormField>
          <FormField v-if="!editing" :label="t('assets.field.custodian')" :hint="t('assets.form.custodianHint')" optional>
            <PersonPicker v-model="form.custodian" clearable />
          </FormField>
          <FormField :label="t('assets.field.supplier')" optional>
            <TextInput v-model="form.supplier_name" :maxlength="120" />
          </FormField>
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("assets.form.upkeep") }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.field.warranty')" optional>
            <DatePicker v-model="form.warranty_until" clearable />
          </FormField>
          <FormField :label="t('assets.field.insurance')" optional>
            <DatePicker v-model="form.insurance_until" clearable />
          </FormField>
          <FormField :label="t('assets.field.serviceEvery')" :hint="t('assets.form.serviceHint')" optional>
            <NumberInput v-model="form.service_months" :min="1" :max="120" :suffix="t('assets.form.months')" />
          </FormField>
          <FormField :label="t('assets.field.verifyEvery')" :hint="t('assets.form.verifyHint')" optional>
            <NumberInput v-model="form.verify_months" :min="1" :max="120" :suffix="t('assets.form.months')" />
          </FormField>
        </div>
        <FormField :label="t('assets.field.notes')" optional>
          <TextArea v-model="form.notes" :rows="2" autosize :max-rows="6" />
        </FormField>
      </section>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="asset-save" @click="save">{{ editing ? t("common.save") : t("assets.form.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
