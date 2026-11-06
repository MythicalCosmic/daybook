<script setup lang="ts">
/**
 * Pay back an approved "paid from my own money" claim in cash (contract §7 `claims/{id}/pay/`,
 * finance.record): the account the money leaves, in the claim's currency, the branch's own first,
 * and the day.
 */
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyText from "@/components/MoneyText.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { useCompanyId } from "@/stores/company";

import { financeApi, useOptions, useRefresh } from "../api";
import { pickerOrder } from "../lib";
import type { Claim } from "../types";
import AccountChips from "./AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ claim: Claim }>();
const emit = defineEmits<{ paid: [claim: Claim] }>();

const { t } = useI18n();
const cid = useCompanyId();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ account: null as number | null, paid_on: null as string | null });

const accounts = computed(() =>
  pickerOrder(
    (options.data.value?.accounts ?? []).filter((account) => account.currency === props.claim.currency),
    { branch: props.claim.branch?.id ?? null },
  ),
);

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
    Object.assign(form, { account: null, paid_on: options.data.value?.today ?? null });
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

async function pay(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.account) {
    errors.account = t("finance.quick.errAccount");
    return;
  }
  saving.value = true;
  try {
    const answer = await financeApi.payClaim(cid.value, props.claim.id, { account: form.account, ...(form.paid_on ? { paid_on: form.paid_on } : {}) });
    toast.success(t("finance.claims.paidToast", { name: props.claim.member.name }));
    refresh();
    emit("paid", answer);
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(failure, ["account", "paid_on"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.claims.payTitle')" :description="claim.member.name" size="md">
    <div class="flex flex-col gap-4" data-pay-claim>
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm dark:bg-surface-3/60">
        <span class="text-muted">{{ t("finance.claims.toPayBack") }}</span>
        <span class="text-base font-semibold tabular-nums text-fg"><MoneyText :value="claim.amount" :currency="claim.currency" /></span>
      </div>
      <FormField :label="t('finance.debts.fromAccount')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <FormField :label="t('finance.debts.paidOn')" :error="errors.paid_on" required>
        <DatePicker v-model="form.paid_on" :min="minDay" :max="options.data.value?.today ?? null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-confirm-pay @click="pay">{{ t("finance.claims.pay") }}</UiButton>
    </template>
  </UiDialog>
</template>
