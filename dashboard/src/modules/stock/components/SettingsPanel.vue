<script setup lang="ts">
/**
 * Settings › Stock: every stock setting, grouped. Prices and the legal caps (the OTC markup, the
 * prescription and socially significant caps and whether they are enforced, rounding, the cost
 * jump warning); expiry and stock (the warning steps, the shortest shelf life a delivery may have,
 * FEFO, below-zero stock, approval of write-offs, the count tolerance); the legal periods
 * (destruction, the controlled register's close and report days, psychotropic stock); prescriptions
 * (the log, keeping times by kind, validity); and the mini app. Legal defaults are the values the
 * law gave on 21.10.2026; changing one is the company's decision.
 */
import { Pencil, Plus, Trash2 } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useCategories, usePricingRules, useRefresh, useStockSettings } from "../api";
import type { PricingRule, RxKind, StockSettings } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useStockSettings();
const canEdit = computed(() => company.can("stock.manage"));

const RX_KINDS: RxKind[] = ["regular", "benefit", "narcotic", "psychotropic", "listed"];

const form = reactive({
  steps: "90, 60, 30",
  min_shelf_days: 180 as number | null,
  fefo_strict: true,
  allow_negative: true,
  default_markup_percent: 25 as number | null,
  rx_max_markup_percent: 20 as number | null,
  social_max_markup_percent: 10 as number | null,
  cap_enforced: true,
  price_rounding: "100.00" as string | null,
  price_jump_percent: 10 as number | null,
  writeoff_approval: true,
  show_other_branches: true,
  camera_scanning: true,
  rx_log: true,
  count_tolerance: "50000.00" as string | null,
  destroy_within_days: 30 as number | null,
  destroy_commission_min: 5 as number | null,
  rx_keep_months: { regular: 3, benefit: 36, narcotic: 60, psychotropic: 12, listed: 12 } as Record<RxKind, number | null>,
  rx_destroy_commission_min: 3 as number | null,
  narcotic_rx_valid_days: 7 as number | null,
  psychotropic_rx_valid_months: 1 as number | null,
  psychotropic_stock_months: 1 as number | null,
  controlled_close_day: 3 as number | null,
  controlled_report_days: 3 as number | null,
});
const errors = reactive<Record<string, string | undefined>>({});

watch(
  () => settings.data.value,
  (data) => {
    if (!data) return;
    Object.assign(form, {
      steps: data.expiry_steps.join(", "),
      min_shelf_days: data.min_shelf_days,
      fefo_strict: data.fefo_strict,
      allow_negative: data.allow_negative,
      default_markup_percent: Number(data.default_markup_percent),
      rx_max_markup_percent: Number(data.rx_max_markup_percent),
      social_max_markup_percent: Number(data.social_max_markup_percent),
      cap_enforced: data.cap_enforced,
      price_rounding: data.price_rounding,
      price_jump_percent: Number(data.price_jump_percent),
      writeoff_approval: data.writeoff_approval,
      show_other_branches: data.show_other_branches,
      camera_scanning: data.camera_scanning,
      rx_log: data.rx_log,
      count_tolerance: data.count_tolerance,
      destroy_within_days: data.destroy_within_days,
      destroy_commission_min: data.destroy_commission_min,
      rx_keep_months: { ...data.rx_keep_months },
      rx_destroy_commission_min: data.rx_destroy_commission_min,
      narcotic_rx_valid_days: data.narcotic_rx_valid_days,
      psychotropic_rx_valid_months: data.psychotropic_rx_valid_months,
      psychotropic_stock_months: data.psychotropic_stock_months,
      controlled_close_day: data.controlled_close_day,
      controlled_report_days: data.controlled_report_days,
    });
  },
  { immediate: true },
);

/** "90, 60, 30" → [90, 60, 30]; null when something isn't a day count. */
function steps(text: string): number[] | null {
  const parts = text
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const numbers = parts.map(Number);
  if (numbers.some((value) => !Number.isInteger(value) || value < 1 || value > 730)) return null;
  return [...new Set(numbers)].sort((a, b) => b - a);
}

// Pricing rules: markup bands by category and cost, the first match wins ---------------------------

const rules = usePricingRules();
const categories = useCategories();
const categoryOptions = computed(() => (categories.data.value ?? []).map((row) => ({ value: row.id, label: row.name })));
const ruleDialog = ref(false);
const editingRule = ref<PricingRule | null>(null);
const ruleBusy = ref(false);
const rule = reactive({ category: null as number | null, cost_from: null as string | null, cost_to: null as string | null, markup: 30 as number | null, active: true });
function editRule(row: PricingRule | null): void {
  editingRule.value = row;
  Object.assign(rule, {
    category: row?.category ?? null,
    cost_from: row?.cost_from ?? null,
    cost_to: row?.cost_to ?? null,
    markup: row ? Number(row.markup_percent) : 30,
    active: row?.is_active ?? true,
  });
  ruleDialog.value = true;
}
async function saveRule(): Promise<void> {
  ruleBusy.value = true;
  const input = {
    category: rule.category,
    cost_from: rule.cost_from || null,
    cost_to: rule.cost_to || null,
    markup_percent: String(rule.markup ?? 0),
    is_active: rule.active,
    order: editingRule.value?.order ?? (rules.data.value?.length ?? 0),
  };
  try {
    const cid = company.currentId ?? 0;
    if (editingRule.value) await stockApi.updatePricingRule(cid, editingRule.value.id, input);
    else await stockApi.createPricingRule(cid, input);
    toast.success(t("stock.rules.saved"));
    refresh();
    ruleDialog.value = false;
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    ruleBusy.value = false;
  }
}
async function removeRule(row: PricingRule): Promise<void> {
  await stockApi.deletePricingRule(company.currentId ?? 0, row.id);
  refresh();
}

const saving = ref(false);
async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  const parsed = steps(form.steps);
  if (!parsed || parsed.length > 6) {
    errors.expiry_steps = t("stock.settings.errSteps");
    return;
  }
  saving.value = true;
  const n = (value: number | null, fallback: number) => (value === null ? fallback : value);
  const input: Partial<StockSettings> = {
    expiry_steps: parsed,
    min_shelf_days: n(form.min_shelf_days, 0),
    fefo_strict: form.fefo_strict,
    allow_negative: form.allow_negative,
    default_markup_percent: String(n(form.default_markup_percent, 0)),
    rx_max_markup_percent: String(n(form.rx_max_markup_percent, 0)),
    social_max_markup_percent: String(n(form.social_max_markup_percent, 0)),
    cap_enforced: form.cap_enforced,
    price_rounding: form.price_rounding || "0",
    price_jump_percent: String(n(form.price_jump_percent, 0)),
    writeoff_approval: form.writeoff_approval,
    show_other_branches: form.show_other_branches,
    camera_scanning: form.camera_scanning,
    rx_log: form.rx_log,
    count_tolerance: form.count_tolerance || "0",
    destroy_within_days: n(form.destroy_within_days, 30),
    destroy_commission_min: n(form.destroy_commission_min, 5),
    rx_keep_months: Object.fromEntries(RX_KINDS.map((kind) => [kind, n(form.rx_keep_months[kind], 0)])) as Record<RxKind, number>,
    rx_destroy_commission_min: n(form.rx_destroy_commission_min, 3),
    narcotic_rx_valid_days: n(form.narcotic_rx_valid_days, 7),
    psychotropic_rx_valid_months: n(form.psychotropic_rx_valid_months, 1),
    psychotropic_stock_months: n(form.psychotropic_stock_months, 1),
    controlled_close_day: n(form.controlled_close_day, 3),
    controlled_report_days: n(form.controlled_report_days, 3),
  };
  try {
    await stockApi.updateSettings(company.currentId ?? 0, input);
    toast.success(t("stock.settings.saved"));
    refresh();
  } catch (error) {
    if (isApiError(error)) {
      for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
      if (!Object.keys(error.fieldErrors).length) toast.error(error.message);
    }
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-6" data-testid="stock-settings">
    <InlineAlert tone="neutral" size="sm">{{ t("stock.settings.legalNote") }}</InlineAlert>

    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("stock.settings.pricesTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("stock.settings.pricesBody") }}</p>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('stock.settings.markup')" :hint="t('stock.settings.markupHint')" :error="errors.default_markup_percent">
          <NumberInput v-model="form.default_markup_percent" :min="0" :max="500" :decimals="2" suffix="%" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.rxCap')" :hint="t('stock.settings.rxCapHint')" :error="errors.rx_max_markup_percent">
          <NumberInput v-model="form.rx_max_markup_percent" :min="0" :max="500" :decimals="2" suffix="%" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.socialCap')" :hint="t('stock.settings.socialCapHint')" :error="errors.social_max_markup_percent">
          <NumberInput v-model="form.social_max_markup_percent" :min="0" :max="500" :decimals="2" suffix="%" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.rounding')" :hint="t('stock.settings.roundingHint')" :error="errors.price_rounding">
          <MoneyInput v-model="form.price_rounding" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.jump')" :hint="t('stock.settings.jumpHint')" :error="errors.price_jump_percent">
          <NumberInput v-model="form.price_jump_percent" :min="0" :max="500" :decimals="2" suffix="%" :disabled="!canEdit" />
        </FormField>
      </div>
      <ToggleSwitch v-model="form.cap_enforced" :label="t('stock.settings.capEnforced')" :description="t('stock.settings.capEnforcedHint')" :disabled="!canEdit" />
    </section>

    <section class="flex flex-col gap-3" data-testid="pricing-rules">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h3 class="text-md font-semibold text-fg">{{ t("stock.rules.title") }}</h3>
          <p class="mt-1 text-sm text-muted">{{ t("stock.rules.body") }}</p>
        </div>
        <UiButton v-if="canEdit" size="sm" variant="secondary" :icon="Plus" @click="editRule(null)">{{ t("stock.rules.add") }}</UiButton>
      </div>
      <ul v-if="rules.data.value?.length" class="divide-y divide-line rounded-[12px] border border-line">
        <li v-for="row in rules.data.value" :key="row.id" class="flex items-center gap-3 px-3 py-2.5 text-sm" :class="{ 'opacity-60': !row.is_active }">
          <span class="min-w-0 flex-1">
            <span class="block truncate text-fg">{{ row.category_name ?? t("stock.rules.anyCategory") }}</span>
            <span class="block text-xs text-muted">
              <template v-if="row.cost_from || row.cost_to">
                <MoneyText v-if="row.cost_from" :value="row.cost_from" decimals="never" /><template v-else>0</template> – <MoneyText v-if="row.cost_to" :value="row.cost_to" decimals="never" /><template v-else>∞</template>
              </template>
              <template v-else>{{ t("stock.rules.anyCost") }}</template>
            </span>
          </span>
          <span class="font-semibold tabular-nums text-fg">{{ row.markup_percent }} %</span>
          <template v-if="canEdit">
            <IconButton :icon="Pencil" size="sm" :label="t('common.edit')" @click="editRule(row)" />
            <IconButton :icon="Trash2" size="sm" :label="t('common.delete')" @click="removeRule(row)" />
          </template>
        </li>
      </ul>
      <p v-else class="text-sm text-muted">{{ t("stock.rules.none") }}</p>
    </section>

    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("stock.settings.expiryTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("stock.settings.expiryBody") }}</p>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('stock.settings.steps')" :hint="t('stock.settings.stepsHint')" :error="errors.expiry_steps">
          <TextInput v-model="form.steps" :maxlength="40" :disabled="!canEdit" data-testid="expiry-steps" />
        </FormField>
        <FormField :label="t('stock.settings.minShelf')" :hint="t('stock.settings.minShelfHint')" :error="errors.min_shelf_days">
          <NumberInput v-model="form.min_shelf_days" :min="0" :max="3650" :suffix="t('stock.settings.days')" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.tolerance')" :hint="t('stock.settings.toleranceHint')" :error="errors.count_tolerance">
          <MoneyInput v-model="form.count_tolerance" :disabled="!canEdit" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ToggleSwitch v-model="form.fefo_strict" :label="t('stock.settings.fefo')" :description="t('stock.settings.fefoHint')" :disabled="!canEdit" />
        <ToggleSwitch v-model="form.allow_negative" :label="t('stock.settings.negative')" :description="t('stock.settings.negativeHint')" :disabled="!canEdit" />
        <ToggleSwitch v-model="form.writeoff_approval" :label="t('stock.settings.approval')" :description="t('stock.settings.approvalHint')" :disabled="!canEdit" />
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("stock.settings.legalTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("stock.settings.legalBody") }}</p>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('stock.settings.destroyWithin')" :hint="t('stock.settings.destroyWithinHint')" :error="errors.destroy_within_days">
          <NumberInput v-model="form.destroy_within_days" :min="1" :max="365" :suffix="t('stock.settings.days')" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.commission')" :hint="t('stock.settings.commissionHint')" :error="errors.destroy_commission_min">
          <NumberInput v-model="form.destroy_commission_min" :min="1" :max="20" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.closeDay')" :hint="t('stock.settings.closeDayHint')" :error="errors.controlled_close_day">
          <NumberInput v-model="form.controlled_close_day" :min="1" :max="28" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.reportDays')" :hint="t('stock.settings.reportDaysHint')" :error="errors.controlled_report_days">
          <NumberInput v-model="form.controlled_report_days" :min="1" :max="60" :suffix="t('stock.settings.days')" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.psychoStock')" :hint="t('stock.settings.psychoStockHint')" :error="errors.psychotropic_stock_months">
          <NumberInput v-model="form.psychotropic_stock_months" :min="1" :max="24" :suffix="t('stock.settings.months')" :disabled="!canEdit" />
        </FormField>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("stock.settings.rxTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("stock.settings.rxBody") }}</p>
      </div>
      <ToggleSwitch v-model="form.rx_log" :label="t('stock.settings.rxLog')" :description="t('stock.settings.rxLogHint')" :disabled="!canEdit" />
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <FormField v-for="kind in RX_KINDS" :key="kind" :label="t(`stock.rxKind.${kind}`)" :hint="t('stock.settings.keepMonths')">
          <NumberInput v-model="form.rx_keep_months[kind]" :min="0" :max="240" :disabled="!canEdit" />
        </FormField>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <FormField :label="t('stock.settings.narcoticValid')" :error="errors.narcotic_rx_valid_days">
          <NumberInput v-model="form.narcotic_rx_valid_days" :min="1" :max="365" :suffix="t('stock.settings.days')" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.psychoValid')" :error="errors.psychotropic_rx_valid_months">
          <NumberInput v-model="form.psychotropic_rx_valid_months" :min="1" :max="24" :suffix="t('stock.settings.months')" :disabled="!canEdit" />
        </FormField>
        <FormField :label="t('stock.settings.rxCommission')" :hint="t('stock.settings.rxCommissionHint')" :error="errors.rx_destroy_commission_min">
          <NumberInput v-model="form.rx_destroy_commission_min" :min="1" :max="20" :disabled="!canEdit" />
        </FormField>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <div>
        <h3 class="text-md font-semibold text-fg">{{ t("stock.settings.appTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("stock.settings.appBody") }}</p>
      </div>
      <ToggleSwitch v-model="form.show_other_branches" :label="t('stock.settings.otherBranches')" :description="t('stock.settings.otherBranchesHint')" :disabled="!canEdit" />
      <ToggleSwitch v-model="form.camera_scanning" :label="t('stock.settings.camera')" :description="t('stock.settings.cameraHint')" :disabled="!canEdit" />
    </section>

    <div v-if="canEdit"><UiButton variant="primary" :loading="saving" data-testid="stock-settings-save" @click="save">{{ t("common.save") }}</UiButton></div>

    <UiDialog v-model:open="ruleDialog" :title="editingRule ? t('stock.rules.editTitle') : t('stock.rules.add')" :description="t('stock.rules.dialogBody')" size="sm">
      <div class="flex flex-col gap-3">
        <FormField :label="t('stock.field.category')">
          <SelectBox v-model="rule.category" :options="categoryOptions" clearable :placeholder="t('stock.rules.anyCategory')" />
        </FormField>
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('stock.rules.costFrom')" optional>
            <MoneyInput v-model="rule.cost_from" />
          </FormField>
          <FormField :label="t('stock.rules.costTo')" optional>
            <MoneyInput v-model="rule.cost_to" />
          </FormField>
        </div>
        <FormField :label="t('stock.rules.markup')" :hint="t('stock.rules.markupHint')">
          <NumberInput v-model="rule.markup" :min="0" :max="500" :decimals="2" suffix="%" />
        </FormField>
        <ToggleSwitch v-model="rule.active" :label="t('stock.rules.active')" />
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="ruleDialog = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="ruleBusy" @click="saveRule">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
