<script setup lang="ts">
/**
 * Repay part of a loan early (v12): how much principal, the interest the bank charged up to today,
 * and what to do with what is left: the same months with smaller payments, or the same payment
 * and done sooner. Everything left settles the loan. The new schedule shows on the loan's page.
 */
import { CalendarMinus, TrendingDown } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import RadioCards from "@/components/RadioCards.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useOptions, useRefresh } from "../../api";
import { creditApi, type EarlyMode, type Loan } from "../../credit";
import { pickerOrder } from "../../lib";
import AccountChips from "../AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ loan: Loan }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ account: null as number | null, amount: null as string | null, interest: null as string | null, paid_on: null as string | null, mode: "payment" as EarlyMode });

const accounts = computed(() => pickerOrder((options.data.value?.accounts ?? []).filter((a) => a.currency === props.loan.currency), { id: props.loan.account?.id ?? null }));
const everything = computed(() => !!form.amount && dec(form.amount).greaterThanOrEqualTo(dec(props.loan.owed)));
const modeOptions = computed(() => [
  { value: "payment" as const, label: t("finance.loans.early.payment"), description: t("finance.loans.early.paymentHint"), icon: TrendingDown },
  { value: "term" as const, label: t("finance.loans.early.term"), description: t("finance.loans.early.termHint"), icon: CalendarMinus },
]);

function fill(): void {
  if (!form.paid_on && options.data.value) form.paid_on = options.data.value.today;
  if (form.account === null) form.account = accounts.value[0]?.id ?? null;
}
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, { account: null, amount: null, interest: null, paid_on: options.data.value?.today ?? null, mode: "payment" });
    fill();
  },
  { immediate: true },
);
watch(() => options.data.value, fill);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (!form.amount) errors.amount = t("finance.quick.errAmount");
  else if (dec(form.amount).greaterThan(dec(props.loan.owed))) errors.amount = t("finance.loans.errEarly", { amount: fmt.money(props.loan.owed, props.loan.currency) });
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await creditApi.repayEarly(company.currentId ?? 0, props.loan.id, {
      account: form.account!,
      paid_on: form.paid_on!,
      amount: form.amount!,
      interest: form.interest || "0",
      mode: form.mode,
    });
    toast.success(everything.value ? t("finance.loans.early.settled") : t("finance.loans.early.done"));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.loans.early.title')" :description="loan.counterparty.name" size="md">
    <div class="flex flex-col gap-4">
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm">
        <span class="text-muted">{{ t("finance.loans.owedNow") }}</span>
        <span class="font-semibold tabular-nums text-fg"><MoneyText :value="loan.owed" :currency="loan.currency" /></span>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('finance.loans.early.amount')" :error="errors.amount" required>
          <div class="flex items-center gap-2">
            <MoneyInput v-model="form.amount" :currencies="[loan.currency]" class="min-w-0 flex-1" :invalid="!!errors.amount" />
            <UiButton variant="ghost" size="sm" @click="form.amount = loan.owed">{{ t("finance.debts.all") }}</UiButton>
          </div>
        </FormField>
        <FormField :label="t('finance.loans.early.interest')" :hint="t('finance.loans.early.interestHint')" optional>
          <MoneyInput v-model="form.interest" :currencies="[loan.currency]" />
        </FormField>
      </div>
      <FormField v-if="!everything" :label="t('finance.loans.early.then')">
        <RadioCards v-model="form.mode" :options="modeOptions" :columns="2" />
      </FormField>
      <InlineAlert v-else tone="success" size="sm" :description="t('finance.loans.early.everything')" />
      <FormField :label="t('finance.debts.fromAccount')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <FormField :label="t('finance.debts.paidOn')" required>
        <DatePicker v-model="form.paid_on" :min="loan.issued_on" :max="options.data.value?.today ?? null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-repay-early @click="save">{{ t("finance.loans.early.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
