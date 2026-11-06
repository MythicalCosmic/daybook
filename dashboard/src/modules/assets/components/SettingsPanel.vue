<script setup lang="ts">
/**
 * Settings › Assets: the company's asset policy (when depreciation starts, locked once a month
 * is posted; inventory numbers; the low-value threshold; planning inflation; the tax book;
 * warning days) and its categories with their defaults: useful life, method, residual value,
 * the Tax Code group and rate (at most the legal maximum), service and instrument check months.
 */
import { Lock, Pencil, Plus } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { assetsApi, useAssetSettings, useCategories, useRefresh } from "../api";
import { categoryIcon } from "../lib";
import type { Category, CategoryKind, Method, StartRule } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useAssetSettings();
const categories = useCategories();

const policy = reactive({
  start_rule: "next_month" as StartRule,
  number_prefix: "AV",
  capitalization_threshold: null as string | null,
  replacement_inflation: 10,
  tax_book: false,
  remind_days: 30,
});
watch(
  () => settings.data.value,
  (data) => {
    if (!data) return;
    Object.assign(policy, {
      start_rule: data.start_rule,
      number_prefix: data.number_prefix,
      capitalization_threshold: data.capitalization_threshold,
      replacement_inflation: Number(data.replacement_inflation),
      tax_book: data.tax_book,
      remind_days: data.remind_days,
    });
  },
  { immediate: true },
);
const saving = ref(false);
async function savePolicy(): Promise<void> {
  saving.value = true;
  try {
    await assetsApi.updateSettings(company.currentId ?? 0, {
      ...(settings.data.value?.locked_rule ? {} : { start_rule: policy.start_rule }),
      number_prefix: policy.number_prefix,
      capitalization_threshold: policy.capitalization_threshold,
      replacement_inflation: String(policy.replacement_inflation),
      tax_book: policy.tax_book,
      remind_days: policy.remind_days,
    });
    toast.success(t("assets.settings.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}

// Categories ------------------------------------------------------------------------------------

const editing = ref<Category | null>(null);
const dialog = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const draft = reactive({
  name: "",
  kind: "fixed" as CategoryKind,
  life_months: null as number | null,
  method: "straight_line" as Method,
  salvage_percent: 0,
  tax_group: "",
  tax_rate: null as number | null,
  service_months: null as number | null,
  verify_months: null as number | null,
  is_active: true,
});
function edit(row: Category | null): void {
  editing.value = row;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(draft, {
    name: row?.name ?? "",
    kind: row?.kind ?? "fixed",
    life_months: row?.life_months ?? 60,
    method: row?.method ?? "straight_line",
    salvage_percent: Number(row?.salvage_percent ?? 0),
    tax_group: row?.tax_group ?? "",
    tax_rate: row?.tax_rate ? Number(row.tax_rate) : null,
    service_months: row?.service_months ?? null,
    verify_months: row?.verify_months ?? null,
    is_active: row?.is_active ?? true,
  });
  dialog.value = true;
}
const groupOptions = computed(() => (settings.data.value?.tax_groups ?? []).map((group) => ({ value: group.code, label: group.label, description: t("assets.settings.groupRate", { rate: group.rate }) })));
const groupModel = computed({ get: () => draft.tax_group || null, set: (value: string | null) => (draft.tax_group = value ?? "") });
const groupRate = computed(() => settings.data.value?.tax_groups.find((group) => group.code === draft.tax_group)?.rate ?? null);
watch(
  () => draft.tax_group,
  (code, before) => {
    if (code && code !== before && groupRate.value) draft.tax_rate = Number(groupRate.value);
    if (!code) draft.tax_rate = null;
  },
);
const busy = ref(false);
async function saveCategory(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!draft.name.trim()) {
    errors.name = t("assets.form.errName");
    return;
  }
  busy.value = true;
  const cid = company.currentId ?? 0;
  const input = {
    name: draft.name.trim(),
    kind: draft.kind,
    life_months: draft.kind === "low_value" ? null : draft.life_months,
    method: draft.kind === "low_value" ? ("none" as Method) : draft.method,
    salvage_percent: String(draft.salvage_percent ?? 0),
    tax_group: draft.tax_group,
    tax_rate: draft.tax_rate === null ? null : String(draft.tax_rate),
    service_months: draft.service_months,
    verify_months: draft.verify_months,
    is_active: draft.is_active,
  };
  try {
    if (editing.value) await assetsApi.updateCategory(cid, editing.value.id, input);
    else await assetsApi.createCategory(cid, input);
    toast.success(t("assets.settings.categorySaved"));
    refresh();
    dialog.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <section class="flex flex-col gap-4">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("assets.settings.policyTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("assets.settings.policyBody") }}</p>
      </div>
      <FormField :label="t('assets.settings.startRule')" :hint="settings.data.value?.locked_rule ? t('assets.settings.ruleLocked') : t('assets.settings.ruleHint')">
        <SegmentedControl
          v-model="policy.start_rule"
          :disabled="settings.data.value?.locked_rule"
          :options="[
            { value: 'next_month', label: t('assets.rule.next_month') },
            { value: 'daily', label: t('assets.rule.daily') },
          ]"
        />
      </FormField>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('assets.settings.prefix')" :hint="t('assets.settings.prefixHint', { example: `${policy.number_prefix || 'AV'}-0001` })">
          <TextInput v-model="policy.number_prefix" :maxlength="8" mono />
        </FormField>
        <FormField :label="t('assets.settings.threshold')" :hint="t('assets.settings.thresholdHint')" optional>
          <MoneyInput v-model="policy.capitalization_threshold" />
        </FormField>
        <FormField :label="t('assets.settings.inflation')" :hint="t('assets.settings.inflationHint')">
          <NumberInput v-model="policy.replacement_inflation" :min="0" :max="100" :decimals="1" suffix="%" />
        </FormField>
        <FormField :label="t('assets.settings.remind')" :hint="t('assets.settings.remindHint')">
          <NumberInput v-model="policy.remind_days" :min="1" :max="180" :suffix="t('assets.settings.days')" />
        </FormField>
      </div>
      <ToggleSwitch v-model="policy.tax_book" :label="t('assets.settings.taxBook')" :description="t('assets.settings.taxBookHint')" />
      <div><UiButton variant="primary" :loading="saving" @click="savePolicy">{{ t("common.save") }}</UiButton></div>
    </section>

    <section class="flex flex-col gap-3">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h3 class="text-md font-semibold text-fg">{{ t("assets.settings.categoriesTitle") }}</h3>
          <p class="mt-1 text-sm text-muted">{{ t("assets.settings.categoriesBody") }}</p>
        </div>
        <UiButton size="sm" variant="secondary" :icon="Plus" @click="edit(null)">{{ t("assets.settings.addCategory") }}</UiButton>
      </div>
      <InlineAlert tone="neutral">{{ t("assets.settings.legal") }}</InlineAlert>
      <ul class="divide-y divide-line rounded-[12px] border border-line">
        <li v-for="row in categories.data.value ?? []" :key="row.id" class="flex items-center gap-3 px-3 py-2.5" :class="{ 'opacity-60': !row.is_active }">
          <component :is="categoryIcon(row.icon)" :size="16" class="shrink-0 text-muted" aria-hidden="true" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium text-fg">{{ row.name }}</span>
            <span class="block text-xs text-muted">
              <template v-if="row.kind === 'low_value'">{{ t("assets.kind.low_value") }}</template>
              <template v-else>
                {{ row.life_months ? t("assets.form.categoryLife", { years: fmt.number(row.life_months / 12, 1) }) : "—" }} · {{ t(`assets.method.${row.method}`) }}
                <template v-if="row.tax_rate"> · {{ t("assets.settings.taxShort", { rate: row.tax_rate }) }}</template>
              </template>
              · {{ t("assets.settings.assetsN", { n: row.assets }) }}
            </span>
          </span>
          <UiButton size="sm" variant="ghost" :icon="Pencil" :aria-label="t('assets.item.edit')" @click="edit(row)" />
        </li>
      </ul>
    </section>

    <UiDialog v-model:open="dialog" :title="editing ? t('assets.settings.editCategory') : t('assets.settings.addCategory')" size="md">
      <div class="flex flex-col gap-3">
        <FormField :label="t('assets.field.name')" :error="errors.name" required>
          <TextInput v-model="draft.name" :maxlength="100" />
        </FormField>
        <FormField :label="t('assets.settings.kind')">
          <SegmentedControl
            v-model="draft.kind"
            block
            :disabled="!!editing && editing.assets > 0"
            :options="(['fixed', 'intangible', 'low_value'] as const).map((value) => ({ value, label: t(`assets.kind.${value}`) }))"
          />
        </FormField>
        <template v-if="draft.kind !== 'low_value'">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField :label="t('assets.field.life')" :hint="draft.life_months ? t('assets.form.lifeYears', { years: fmt.number(draft.life_months / 12, 1) }) : undefined" :error="errors.life_months">
              <NumberInput v-model="draft.life_months" :min="1" :max="1200" :suffix="t('assets.form.months')" />
            </FormField>
            <FormField :label="t('assets.settings.salvagePercent')">
              <NumberInput v-model="draft.salvage_percent" :min="0" :max="99" :decimals="1" suffix="%" />
            </FormField>
          </div>
          <FormField :label="t('assets.field.method')">
            <SelectBox v-model="draft.method" :options="(['straight_line', 'declining', 'sum_of_years', 'units'] as const).map((value) => ({ value, label: t(`assets.method.${value}`) }))" />
          </FormField>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_140px]">
            <FormField :label="t('assets.settings.taxGroup')">
              <SelectBox v-model="groupModel" :options="groupOptions" clearable :placeholder="t('assets.settings.noGroup')" />
            </FormField>
            <FormField :label="t('assets.settings.taxRate')" :hint="groupRate ? t('assets.settings.atMost', { rate: groupRate }) : undefined" :error="errors.tax_rate">
              <NumberInput v-model="draft.tax_rate" :min="0" :max="groupRate ? Number(groupRate) : 100" :decimals="2" suffix="%" :disabled="!draft.tax_group" />
            </FormField>
          </div>
        </template>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.field.serviceEvery')" optional>
            <NumberInput v-model="draft.service_months" :min="1" :max="120" :suffix="t('assets.form.months')" />
          </FormField>
          <FormField :label="t('assets.field.verifyEvery')" optional>
            <NumberInput v-model="draft.verify_months" :min="1" :max="120" :suffix="t('assets.form.months')" />
          </FormField>
        </div>
        <ToggleSwitch v-model="draft.is_active" :label="t('assets.settings.active')" />
        <p v-if="editing && editing.system_code" class="flex items-center gap-1.5 text-xs text-muted"><Lock :size="12" aria-hidden="true" />{{ t("assets.settings.systemCategory") }}</p>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="dialog = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" @click="saveCategory">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
