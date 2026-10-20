<script setup lang="ts">
/**
 * Finance preferences (plan §6.2 "rates, thresholds, how reimbursements are paid"): where rates
 * come from, which expenses need a receipt, when owners hear about a big expense, which claims wait
 * for approval, and how approved "paid from my own money" claims are paid back.
 */
import { BellRing, Landmark, Paperclip, ReceiptText, Wallet } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";

import { financeApi, useRefresh, useSettings } from "../../api";
import type { FinanceSettings } from "../../types";
import { useCompanyStore } from "@/stores/company";

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const settings = useSettings();
const saving = ref(false);
const form = reactive({
  rate_source: "cbu" as FinanceSettings["rate_source"],
  receipt_required_over: null as string | null,
  large_expense_alert: null as string | null,
  approval_threshold: null as string | null,
  reimburse_via: "payroll" as FinanceSettings["reimburse_via"],
});

function reset(): void {
  const d = settings.data.value;
  if (!d) return;
  Object.assign(form, {
    rate_source: d.rate_source,
    receipt_required_over: d.receipt_required_over,
    large_expense_alert: d.large_expense_alert,
    approval_threshold: d.approval_threshold,
    reimburse_via: d.reimburse_via,
  });
}
watch(() => settings.data.value, reset, { immediate: true });

const dirty = computed(() => {
  const d = settings.data.value;
  if (!d) return false;
  return (["rate_source", "receipt_required_over", "large_expense_alert", "approval_threshold", "reimburse_via"] as const).some((key) => (form[key] ?? null) !== (d[key] ?? null));
});

async function save(): Promise<void> {
  saving.value = true;
  try {
    await financeApi.updateSettings(company.currentId ?? 0, { ...form });
    toast.success(t("finance.prefs.saved"));
    refresh();
  } finally {
    saving.value = false;
  }
}
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

      <section class="ui-card grid grid-cols-1 gap-4 p-5 md:grid-cols-3">
        <FormField :label="t('finance.prefs.receipt')" :hint="t('finance.prefs.receiptHint')" optional>
          <template #label><span class="inline-flex items-center gap-1.5"><Paperclip :size="14" class="text-subtle" />{{ t("finance.prefs.receipt") }}</span></template>
          <MoneyInput v-model="form.receipt_required_over" :placeholder="t('finance.prefs.off')" />
        </FormField>
        <FormField :label="t('finance.prefs.alert')" :hint="t('finance.prefs.alertHint')" optional>
          <template #label><span class="inline-flex items-center gap-1.5"><BellRing :size="14" class="text-subtle" />{{ t("finance.prefs.alert") }}</span></template>
          <MoneyInput v-model="form.large_expense_alert" :placeholder="t('finance.prefs.off')" />
        </FormField>
        <FormField :label="t('finance.prefs.approval')" :hint="t('finance.prefs.approvalHint')" optional>
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
            { value: 'payroll', label: t('finance.prefs.viaPayroll'), description: t('finance.prefs.viaPayrollHint') },
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
