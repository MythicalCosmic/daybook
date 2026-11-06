<script setup lang="ts">
/**
 * Finance preferences (plan §6.2 "rates, thresholds, how reimbursements are paid"; §14.8 "tax
 * regime"): where rates come from, which tax the company pays (with its rate, the turnover-tax
 * threshold and the base value, each a legal number to confirm with an accountant), which expenses
 * need a receipt, when owners hear about a big expense, which claims wait for approval, and how
 * approved "paid from my own money" claims are paid back (with the payroll only while payroll is
 * on). Saving sends only what changed, so opening the panel never confirms a regime by itself.
 */
import { BellRing, Landmark, Paperclip, Percent, ReceiptText, Wallet } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { dec, toMoney } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useRefresh, useSettings, useTaxSummary } from "../../api";
import type { FinanceSettings, TaxRegime } from "../../types";

/** The rate each regime starts with (the server sets the same when only the regime is sent). */
const DEFAULT_VAT: Record<TaxRegime, number> = { turnover: 0, vat: 12, vat_simplified: 6 };
const DEFAULT_THRESHOLD = 12_000;

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useSettings();
const summary = useTaxSummary(() => company.can("finance.view"));
const saving = ref(false);
const confirming = ref(false);

interface Form {
  rate_source: FinanceSettings["rate_source"];
  receipt_required_over: string | null;
  large_expense_alert: string | null;
  approval_threshold: string | null;
  reimburse_via: FinanceSettings["reimburse_via"];
  tax_regime: TaxRegime;
  vat_percent: number | null;
  turnover_threshold: number | null;
  base_value: string | null;
}

const form = reactive<Form>({
  rate_source: "cbu",
  receipt_required_over: null,
  large_expense_alert: null,
  approval_threshold: null,
  reimburse_via: "payroll",
  tax_regime: "turnover",
  vat_percent: 0,
  turnover_threshold: DEFAULT_THRESHOLD,
  base_value: null,
});

// A server that doesn't say (before package I) keeps today's choice open.
const payrollOn = computed(() => settings.data.value?.payroll_on !== false);

/** What is saved, as the form holds it: with payroll off the server pays claims back in cash. */
const saved = computed<Form | null>(() => {
  const d = settings.data.value;
  if (!d) return null;
  return {
    rate_source: d.rate_source,
    receipt_required_over: d.receipt_required_over,
    large_expense_alert: d.large_expense_alert,
    approval_threshold: d.approval_threshold,
    reimburse_via: d.payroll_on === false ? "cash" : d.reimburse_via,
    tax_regime: d.tax_regime ?? "turnover",
    vat_percent: d.vat_percent === undefined || d.vat_percent === null ? DEFAULT_VAT[d.tax_regime ?? "turnover"] : Number(d.vat_percent),
    turnover_threshold: d.turnover_threshold ?? DEFAULT_THRESHOLD,
    base_value: d.base_value ?? null,
  };
});

function reset(): void {
  if (saved.value) Object.assign(form, saved.value);
}
watch(saved, reset, { immediate: true });

/** Picking a regime brings its usual rate; the rate stays editable. */
const regime = computed({
  get: () => form.tax_regime,
  set: (value: TaxRegime | null) => {
    if (!value) return;
    form.tax_regime = value;
    form.vat_percent = DEFAULT_VAT[value];
  },
});

const MONEY_KEYS = ["receipt_required_over", "large_expense_alert", "approval_threshold", "base_value"] as const;
const PLAIN_KEYS = ["rate_source", "reimburse_via", "tax_regime", "vat_percent", "turnover_threshold"] as const;

function moneyDiffers(a: string | null, b: string | null): boolean {
  const empty = (value: string | null) => value === null || value === "";
  if (empty(a) || empty(b)) return empty(a) !== empty(b);
  return !dec(a).eq(dec(b));
}

/** Only what changed, in the API's shapes. */
const changes = computed<Partial<FinanceSettings>>(() => {
  const before = saved.value;
  if (!before) return {};
  const out: Partial<FinanceSettings> = {};
  for (const key of MONEY_KEYS) {
    if (moneyDiffers(form[key], before[key])) (out as Record<string, unknown>)[key] = form[key] || null;
  }
  for (const key of PLAIN_KEYS) {
    if ((form[key] ?? null) === (before[key] ?? null)) continue;
    if (key === "vat_percent") out.vat_percent = (form.vat_percent ?? 0).toFixed(2);
    else if (key === "turnover_threshold") out.turnover_threshold = form.turnover_threshold ?? 0;
    else (out as Record<string, unknown>)[key] = form[key];
  }
  // A regime saved sends its rate with it, so the server never guesses one.
  if (out.tax_regime && out.vat_percent === undefined) out.vat_percent = (form.vat_percent ?? 0).toFixed(2);
  return out;
});
const dirty = computed(() => Object.keys(changes.value).length > 0);

async function save(): Promise<void> {
  saving.value = true;
  try {
    await financeApi.updateSettings(company.currentId ?? 0, changes.value);
    toast.success(t("finance.prefs.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}

/** The Get started step's question, answered here: the regime on screen is the one paid. */
async function confirmRegime(): Promise<void> {
  confirming.value = true;
  try {
    await financeApi.updateSettings(company.currentId ?? 0, { tax_regime: form.tax_regime, vat_percent: (form.vat_percent ?? 0).toFixed(2) });
    toast.success(t("finance.prefs.taxConfirmed"));
    refresh();
  } finally {
    confirming.value = false;
  }
}

const regimes = computed(() => [
  { value: "turnover" as const, label: t("finance.taxRegime.turnover"), description: t("finance.taxRegime.turnoverHint") },
  { value: "vat" as const, label: t("finance.taxRegime.vat"), description: t("finance.taxRegime.vatHint") },
  { value: "vat_simplified" as const, label: t("finance.taxRegime.vat_simplified"), description: t("finance.taxRegime.vat_simplifiedHint") },
]);

/** The threshold in money as typed: base values × one base value. */
const thresholdMoney = computed(() => (form.turnover_threshold && form.base_value ? toMoney(dec(form.base_value).times(form.turnover_threshold)) : null));
const thresholdHint = computed(() =>
  thresholdMoney.value ? t("finance.prefs.thresholdHint", { amount: fmt.money(thresholdMoney.value, undefined, { compact: true }) }) : t("finance.prefs.thresholdHintEmpty"),
);
const turnoverShare = computed(() => {
  const share = summary.data.value?.share;
  return share === null || share === undefined ? null : Number(share) * 100;
});
</script>

<template>
  <div class="flex flex-col gap-4">
    <ErrorState v-if="settings.isError.value" :error="settings.error.value" :retry="() => settings.refetch()" />
    <SkeletonBlock v-else-if="settings.isPending.value" height="420px" radius="12px" />
    <template v-else>
      <section class="ui-card flex flex-col gap-4 p-5">
        <header class="flex items-start gap-3">
          <Landmark :size="18" class="mt-0.5 shrink-0 text-subtle" />
          <div>
            <h3 class="text-sm font-semibold text-fg">{{ t("finance.prefs.rates") }}</h3>
            <p class="text-sm text-muted">{{ t("finance.prefs.ratesHint") }}</p>
          </div>
        </header>
        <RadioCards
          v-model="form.rate_source"
          :columns="2"
          :options="[
            { value: 'cbu', label: t('finance.prefs.rateCbu'), description: t('finance.prefs.rateCbuHint') },
            { value: 'manual', label: t('finance.prefs.rateManual'), description: t('finance.prefs.rateManualHint') },
          ]"
        />
      </section>

      <section class="ui-card flex flex-col gap-4 p-5" data-tax-regime>
        <header class="flex items-start gap-3">
          <Percent :size="18" class="mt-0.5 shrink-0 text-subtle" />
          <div>
            <h3 class="text-sm font-semibold text-fg">{{ t("finance.prefs.tax") }}</h3>
            <p class="text-sm text-muted">{{ t("finance.prefs.taxHint") }}</p>
          </div>
        </header>
        <InlineAlert v-if="settings.data.value && settings.data.value.tax_regime_set === false" tone="info" size="sm" :title="t('finance.prefs.taxUnset')" :description="t('finance.prefs.taxUnsetBody')">
          <template #actions>
            <UiButton size="sm" variant="secondary" :loading="confirming" data-confirm-regime @click="confirmRegime">{{ t("finance.prefs.taxConfirm") }}</UiButton>
          </template>
        </InlineAlert>
        <RadioCards v-model="regime" :columns="3" :options="regimes" />
        <div class="grid grid-cols-1 gap-4 md:grid-cols-3 md:grid-rows-[auto_auto] md:gap-y-1.5">
          <FormField v-if="form.tax_regime !== 'turnover'" class="md:row-span-2 md:grid md:grid-rows-subgrid" :label="t('finance.prefs.vatPercent')" :hint="t('finance.prefs.vatPercentHint')">
            <template #label>
              <span>{{ t("finance.prefs.vatPercent") }} <span class="font-normal text-subtle">{{ t("finance.prefs.confirm") }}</span></span>
            </template>
            <NumberInput v-model="form.vat_percent" :min="0" :max="100" :decimals="2" suffix="%" />
          </FormField>
          <FormField class="md:row-span-2 md:grid md:grid-rows-subgrid" :label="t('finance.prefs.threshold')" :hint="thresholdHint">
            <template #label>
              <span>{{ t("finance.prefs.threshold") }} <span class="font-normal text-subtle">{{ t("finance.prefs.confirm") }}</span></span>
            </template>
            <NumberInput v-model="form.turnover_threshold" :min="0" :max="1000000" grouping :suffix="t('finance.prefs.bhm')" />
          </FormField>
          <FormField class="md:row-span-2 md:grid md:grid-rows-subgrid" :label="t('finance.prefs.baseValue')" :hint="t('finance.prefs.baseValueHint')">
            <template #label>
              <span>{{ t("finance.prefs.baseValue") }} <span class="font-normal text-subtle">{{ t("finance.prefs.confirm") }}</span></span>
            </template>
            <MoneyInput v-model="form.base_value" />
          </FormField>
        </div>
        <!-- This year's turnover against the threshold (the saved one), for a turnover-tax payer. -->
        <div v-if="summary.data.value && saved?.tax_regime === 'turnover' && summary.data.value.share !== null" class="flex flex-col gap-2 rounded-[10px] bg-surface-2 px-3 py-3 dark:bg-surface-3/60" data-turnover>
          <ProgressBar
            :value="turnoverShare ?? 0"
            :max="100"
            size="sm"
            tone="auto"
            :label="t('finance.prefs.turnoverYear', { year: summary.data.value.year })"
            :value-text="t('finance.prefs.turnoverOf', { amount: fmt.money(summary.data.value.turnover, undefined, { compact: true }), threshold: fmt.money(summary.data.value.threshold, undefined, { compact: true }) })"
          />
          <p v-if="summary.data.value.over" class="text-sm font-medium text-danger">{{ t("finance.prefs.turnoverOver") }}</p>
        </div>
      </section>

      <!-- The labels share one row (a subgrid), so the three amounts line up even when a label wraps. -->
      <section class="ui-card grid grid-cols-1 gap-4 p-5 md:grid-cols-3 md:grid-rows-[auto_auto] md:gap-y-1.5">
        <FormField class="md:row-span-2 md:grid md:grid-rows-subgrid" :label="t('finance.prefs.receipt')" :hint="t('finance.prefs.receiptHint')" optional>
          <template #label><span class="inline-flex items-center gap-1.5"><Paperclip :size="14" class="text-subtle" />{{ t("finance.prefs.receipt") }}</span></template>
          <MoneyInput v-model="form.receipt_required_over" :placeholder="t('finance.prefs.off')" />
        </FormField>
        <FormField class="md:row-span-2 md:grid md:grid-rows-subgrid" :label="t('finance.prefs.alert')" :hint="t('finance.prefs.alertHint')" optional>
          <template #label><span class="inline-flex items-center gap-1.5"><BellRing :size="14" class="text-subtle" />{{ t("finance.prefs.alert") }}</span></template>
          <MoneyInput v-model="form.large_expense_alert" :placeholder="t('finance.prefs.off')" />
        </FormField>
        <FormField class="md:row-span-2 md:grid md:grid-rows-subgrid" :label="t('finance.prefs.approval')" :hint="t('finance.prefs.approvalHint')" optional>
          <template #label><span class="inline-flex items-center gap-1.5"><ReceiptText :size="14" class="text-subtle" />{{ t("finance.prefs.approval") }}</span></template>
          <MoneyInput v-model="form.approval_threshold" :placeholder="t('finance.prefs.everyClaim')" />
        </FormField>
      </section>

      <section class="ui-card flex flex-col gap-4 p-5">
        <header class="flex items-start gap-3">
          <Wallet :size="18" class="mt-0.5 shrink-0 text-subtle" />
          <div>
            <h3 class="text-sm font-semibold text-fg">{{ t("finance.prefs.reimburse") }}</h3>
            <p class="text-sm text-muted">{{ t("finance.prefs.reimburseHint") }}</p>
          </div>
        </header>
        <RadioCards
          v-model="form.reimburse_via"
          :columns="2"
          :options="[
            { value: 'payroll', label: t('finance.prefs.viaPayroll'), description: payrollOn ? t('finance.prefs.viaPayrollHint') : t('finance.prefs.viaPayrollOff'), disabled: !payrollOn },
            { value: 'cash', label: t('finance.prefs.viaCash'), description: t('finance.prefs.viaCashHint') },
          ]"
        />
      </section>

      <StickyActionBar :show="dirty" :message="t('common.unsaved')">
        <UiButton variant="ghost" @click="reset">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>
  </div>
</template>
