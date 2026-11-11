<script setup lang="ts">
/**
 * Pay one payment of a loan (v12): what is left of it, split into the principal (the loan gets
 * smaller; not an expense) and the interest (an expense), the account and the day. Both parts can
 * be changed: a part payment, or a late fee the bank added to the interest. One tap books both.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { add, dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useOptions, useRefresh } from "../../api";
import { creditApi, type Loan, type LoanLine } from "../../credit";
import { pickerOrder } from "../../lib";
import AccountChips from "../AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ loan: Loan; line: LoanLine }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ account: null as number | null, principal: null as string | null, interest: null as string | null, paid_on: null as string | null });

const principalLeft = computed(() => dec(props.line.principal).minus(dec(props.line.principal_paid)).toFixed(2));
const interestLeft = computed(() => {
  const left = dec(props.line.interest).minus(dec(props.line.interest_paid));
  return (left.isNegative() ? dec(0) : left).toFixed(2);
});
const accounts = computed(() => pickerOrder((options.data.value?.accounts ?? []).filter((a) => a.currency === props.loan.currency), { id: props.loan.account?.id ?? null }));
const total = computed(() => add(form.principal || "0", form.interest || "0"));
const receivable = computed(() => props.loan.direction === "receivable");

function fill(): void {
  const data = options.data.value;
  if (!form.paid_on && data) form.paid_on = data.today;
  if (form.account === null) form.account = accounts.value[0]?.id ?? null;
}
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    Object.assign(form, { account: null, principal: principalLeft.value, interest: interestLeft.value, paid_on: options.data.value?.today ?? null });
    fill();
  },
  { immediate: true },
);
watch(() => options.data.value, fill);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (dec(total.value).isZero()) errors.principal = t("finance.quick.errAmount");
  if (dec(form.principal || "0").greaterThan(dec(principalLeft.value))) errors.principal = t("finance.loans.errPrincipal", { amount: fmt.money(principalLeft.value, props.loan.currency) });
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await creditApi.pay(company.currentId ?? 0, props.loan.id, {
      installment: props.line.id,
      account: form.account!,
      paid_on: form.paid_on!,
      principal: form.principal || "0",
      interest: form.interest || "0",
    });
    toast.success(t("finance.loans.paid", { amount: fmt.money(total.value, props.loan.currency) }));
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
  <UiDialog
    v-model:open="open"
    :title="t('finance.loans.payTitle', { n: line.position })"
    :description="`${loan.counterparty.name} · ${fmt.day(line.due_on, 'long')}`"
    size="md"
  >
    <div class="flex flex-col gap-4">
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('finance.loans.col.principal')" :hint="t('finance.loans.principalHint')" :error="errors.principal">
          <MoneyInput v-model="form.principal" :currencies="[loan.currency]" :invalid="!!errors.principal" />
        </FormField>
        <FormField :label="t('finance.loans.col.interest')" :hint="receivable ? t('finance.loans.interestInHint') : t('finance.loans.interestHint')">
          <MoneyInput v-model="form.interest" :currencies="[loan.currency]" />
        </FormField>
      </div>
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm">
        <span class="text-muted">{{ receivable ? t("finance.loans.receivedTotal") : t("finance.loans.payTotal") }}</span>
        <span class="text-base font-semibold tabular-nums text-fg"><MoneyText :value="total" :currency="loan.currency" /></span>
      </div>
      <FormField :label="receivable ? t('finance.debts.toAccount') : t('finance.debts.fromAccount')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <FormField :label="t('finance.debts.paidOn')" required>
        <DatePicker v-model="form.paid_on" :min="loan.issued_on" :max="options.data.value?.today ?? null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-pay-loan @click="save">{{ t("finance.debts.savePayment") }}</UiButton>
    </template>
  </UiDialog>
</template>
