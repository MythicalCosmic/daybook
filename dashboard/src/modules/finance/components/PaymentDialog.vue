<script setup lang="ts">
/**
 * Record a payment on a debt (plan §6.2 "record-payment modal"): the account the money reached
 * (or left), the amount in that account's currency, how much of the debt it settles when the
 * currencies differ (a dollar debt paid in so‘m), the day, and "the whole rest" in one tap.
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
import { addDays } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useOptions, useRefresh } from "../api";
import { pickerOrder } from "../lib";
import type { Debt } from "../types";
import AccountChips from "./AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ debt: Debt }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ account: null as number | null, amount: null as string | null, debt_amount: null as string | null, paid_on: null as string | null });

const chipAccounts = computed(() => pickerOrder(options.data.value?.accounts ?? [], { branch: props.debt.branch?.id ?? null }));
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    Object.assign(form, { account: null, amount: props.debt.outstanding, debt_amount: null, paid_on: options.data.value?.today ?? null });
    for (const key of Object.keys(errors)) delete errors[key];
  },
  { immediate: true },
);
watch(
  () => options.data.value,
  (data) => {
    if (!data) return;
    if (!form.paid_on) form.paid_on = data.today;
    if (form.account === null) form.account = chipAccounts.value.find((a) => a.currency === props.debt.currency)?.id ?? chipAccounts.value[0]?.id ?? null;
  },
  { immediate: true },
);

const account = computed(() => options.data.value?.accounts.find((a) => a.id === form.account) ?? null);
const crossCurrency = computed(() => !!account.value && account.value.currency !== props.debt.currency);
const receivable = computed(() => props.debt.direction === "receivable");
const minDay = computed(() => {
  const locked = options.data.value?.locked_until;
  const after = locked ? addDays(locked, 1) : null;
  return after && after > props.debt.issued_on ? after : props.debt.issued_on;
});

watch(crossCurrency, (cross) => {
  if (cross) {
    form.amount = null;
    form.debt_amount = props.debt.outstanding;
  } else {
    form.amount = props.debt.outstanding;
    form.debt_amount = null;
  }
});

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (!form.amount) errors.amount = t("finance.quick.errAmount");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await financeApi.payDebt(company.currentId ?? 0, props.debt.id, {
      account: form.account!,
      amount: form.amount!,
      debt_amount: crossCurrency.value ? form.debt_amount : null,
      paid_on: form.paid_on!,
    });
    toast.success(receivable.value ? t("finance.debts.paymentIn") : t("finance.debts.paymentOut"));
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
  <UiDialog v-model:open="open" :title="receivable ? t('finance.debts.recordIn') : t('finance.debts.recordOut')" :description="debt.party?.name" size="md">
    <div class="flex flex-col gap-4">
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm">
        <span class="text-muted">{{ t("finance.debts.left") }}</span>
        <span class="font-semibold tabular-nums text-fg"><MoneyText :value="debt.outstanding" :currency="debt.currency" /></span>
      </div>
      <FormField :label="receivable ? t('finance.debts.toAccount') : t('finance.debts.fromAccount')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="chipAccounts" :invalid="!!errors.account" />
      </FormField>
      <FormField :label="t('finance.field.amount')" :error="errors.amount" required>
        <div class="flex items-center gap-2">
          <MoneyInput v-model="form.amount" :currencies="[account?.currency ?? debt.currency]" class="min-w-0 flex-1" :invalid="!!errors.amount" />
          <UiButton v-if="!crossCurrency" variant="ghost" size="sm" @click="form.amount = debt.outstanding">{{ t("finance.debts.all") }}</UiButton>
        </div>
      </FormField>
      <FormField v-if="crossCurrency" :label="t('finance.debts.settles', { currency: debt.currency })" :error="errors.debt_amount" :hint="t('finance.debts.settlesHint')">
        <MoneyInput v-model="form.debt_amount" :currencies="[debt.currency]" />
      </FormField>
      <FormField :label="t('finance.debts.paidOn')" required>
        <DatePicker v-model="form.paid_on" :min="minDay" :max="options.data.value?.today ?? null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" @click="save">{{ t("finance.debts.savePayment") }}</UiButton>
    </template>
  </UiDialog>
</template>
