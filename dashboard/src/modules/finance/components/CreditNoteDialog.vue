<script setup lang="ts">
/**
 * A credit note on a payable (plan §14.8 `credit_debt`; contract `debts/{id}/credit/`): the
 * distributor takes part of the debt back without money changing hands (a return, a price
 * correction, a bonus set off against the invoice). It lowers the debt and the purchase cost of
 * the debt's category by the same amount and moves no account.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { useCompanyId, useCompanyToday } from "@/stores/company";

import { financeApi, useOptions, useRefresh } from "../api";
import { validPayment } from "../lib";
import type { Debt } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ debt: Debt }>();

const { t } = useI18n();
const cid = useCompanyId();
const today = useCompanyToday();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ amount: null as string | null, reason: "", credited_on: null as string | null });

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    Object.assign(form, { amount: null, reason: "", credited_on: today.value });
    for (const key of Object.keys(errors)) delete errors[key];
  },
  { immediate: true },
);

const minDay = computed(() => {
  const locked = options.data.value?.locked_until;
  const after = locked ? addDays(locked, 1) : null;
  return after && after > props.debt.issued_on ? after : props.debt.issued_on;
});

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!validPayment(form.amount, props.debt.outstanding)) errors.amount = t("finance.credit.errAmount");
  if (!form.reason.trim()) errors.reason = t("finance.credit.errReason");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    await financeApi.creditDebt(cid.value, props.debt.id, { amount: form.amount!, reason: form.reason.trim(), credited_on: form.credited_on });
    toast.success(t("finance.credit.saved"));
    refresh();
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(failure, ["amount", "reason", "credited_on"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.credit.title')" :description="debt.party?.name" size="md">
    <div class="flex flex-col gap-4" data-credit-note>
      <p class="text-sm text-muted">{{ t("finance.credit.hint") }}</p>
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm dark:bg-surface-3/60">
        <span class="text-muted">{{ t("finance.debts.left") }}</span>
        <span class="font-semibold tabular-nums text-fg"><MoneyText :value="debt.outstanding" :currency="debt.currency" /></span>
      </div>
      <FormField :label="t('finance.credit.amount')" :error="errors.amount" required>
        <MoneyInput v-model="form.amount" :currencies="[debt.currency]" :invalid="!!errors.amount" />
      </FormField>
      <FormField :label="t('finance.credit.reason')" :error="errors.reason" required>
        <TextInput v-model="form.reason" :maxlength="300" :placeholder="t('finance.credit.reasonPlaceholder')" :invalid="!!errors.reason" />
      </FormField>
      <FormField :label="t('finance.credit.on')" :error="errors.credited_on">
        <DatePicker v-model="form.credited_on" :min="minDay" :max="today" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save-credit @click="save">{{ t("finance.credit.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
