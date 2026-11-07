<script setup lang="ts">
/**
 * Pay the open occurrence of a recurring bill (contract §2 `recurring/{id}/pay/`): the account the
 * money left (the rule's own first), the real amount (the rule's amount, or empty when it changes
 * each time, as a tax does) and the day. For an income rule it records the money received. The
 * calendar page opens it for a bill in the upcoming list; the recurring page for its Pay button.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId } from "@/stores/company";

import { financeApi, useOptions, useRefresh } from "../api";
import { pickerOrder } from "../lib";
import type { RecurringRule } from "../types";
import AccountChips from "./AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ rule: RecurringRule }>();
const emit = defineEmits<{ paid: [rule: RecurringRule] }>();

const { t } = useI18n();
const fmt = useFormat();
const cid = useCompanyId();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ account: null as number | null, amount: null as string | null, paid_on: null as string | null });

const income = computed(() => props.rule.kind === "income");
/** Accounts in the rule's currency (the amount is in it), the rule's own account first. */
const accounts = computed(() => {
  const all = options.data.value?.accounts ?? [];
  const same = all.filter((account) => account.currency === props.rule.currency);
  return pickerOrder(same.length ? same : all, { id: props.rule.account?.id ?? null, branch: props.rule.branch?.id ?? null });
});

function fillDefaults(): void {
  const data = options.data.value;
  if (!data) return;
  if (!form.paid_on) form.paid_on = data.today;
  if (form.account === null) form.account = accounts.value[0]?.id ?? null;
}
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    const known = !props.rule.amount_varies && dec(props.rule.amount).gt(0);
    Object.assign(form, { account: null, amount: known ? props.rule.amount : null, paid_on: options.data.value?.today ?? null });
    for (const key of Object.keys(errors)) delete errors[key];
    fillDefaults();
  },
  { immediate: true },
);
watch(() => options.data.value, fillDefaults, { immediate: true });

const minDay = computed(() => {
  const locked = options.data.value?.locked_until;
  return locked ? addDays(locked, 1) : null;
});

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (!form.amount || !dec(form.amount).gt(0)) errors.amount = t("finance.quick.errAmount");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const answer = await financeApi.payRecurring(cid.value, props.rule.id, {
      account: form.account!,
      amount: form.amount!,
      ...(form.paid_on ? { paid_on: form.paid_on } : {}),
      // The occurrence this dialog shows: if someone paid it meanwhile, the server says so.
      ...(props.rule.next_due_on ? { occurrence: props.rule.next_due_on } : {}),
    });
    toast.success(income.value ? t("finance.recurring.receivedToast", { name: props.rule.name }) : t("finance.recurring.paidToast", { name: props.rule.name }));
    refresh();
    emit("paid", answer.rule);
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(failure, ["account", "amount", "paid_on"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="income ? t('finance.recurring.receiveTitle') : t('finance.recurring.payTitle')" :description="rule.name" size="md">
    <div class="flex flex-col gap-4" data-pay-rule>
      <div class="flex flex-wrap items-center gap-2 rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm dark:bg-surface-3/60">
        <span class="text-muted">{{ t("finance.recurring.due") }}</span>
        <span class="font-semibold text-fg">{{ rule.next_due_on ? fmt.day(rule.next_due_on, "weekday") : "—" }}</span>
        <StatusPill v-if="rule.overdue" tone="danger" size="sm" :label="t('finance.recurring.overdue')" />
        <span class="flex-1" />
        <span v-if="rule.counterparty" class="truncate text-muted">{{ rule.counterparty.name }}</span>
      </div>
      <FormField :label="income ? t('finance.debts.toAccount') : t('finance.debts.fromAccount')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <FormField :label="t('finance.field.amount')" :error="errors.amount" required :hint="rule.amount_varies ? t('finance.recurring.realAmountHint') : undefined">
        <MoneyInput v-model="form.amount" :currencies="[rule.currency]" :invalid="!!errors.amount" />
      </FormField>
      <FormField :label="income ? t('finance.recurring.receivedOn') : t('finance.debts.paidOn')" :error="errors.paid_on" required>
        <DatePicker v-model="form.paid_on" :min="minDay" :max="options.data.value?.today ?? null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-confirm-pay @click="save">{{ income ? t("finance.recurring.markReceived") : t("finance.recurring.pay") }}</UiButton>
    </template>
  </UiDialog>
</template>
