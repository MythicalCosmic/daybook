<script setup lang="ts">
/**
 * Pay a dividend round: the partners still to pay (all ticked), the business account in so‘m the
 * money leaves and the day. Each partner's part is booked as an owner draw; everything or nothing.
 */
import { Wallet } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import CheckBox from "@/components/CheckBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyText from "@/components/MoneyText.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import type { AccountRef } from "../../types";
import AccountChips from "../AccountChips.vue";
import { ownerMoneyApi, useOwnerMoneyWrite, type Dividend, type DrawAccount } from "../../ownerMoney";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ dividend: Dividend; accounts: DrawAccount[]; today: string }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const form = reactive({ account: null as number | null, paid_on: props.today as string | null, lines: [] as number[] });
const error = ref<string | null>(null);
const unpaid = computed(() => props.dividend.lines.filter((line) => !line.paid));
const chips = computed<AccountRef[]>(() =>
  props.accounts.filter((row) => row.currency === company.currency).map((row) => ({ id: row.id, name: row.name, kind: row.kind as AccountRef["kind"], currency: row.currency as AccountRef["currency"], branch_id: row.branch_id })),
);
const total = computed(() => unpaid.value.filter((line) => form.lines.includes(line.id)).reduce((sum, line) => sum + Number(line.amount), 0));
const account = computed(() => props.accounts.find((row) => row.id === form.account) ?? null);

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    error.value = null;
    const bank = [...props.accounts].filter((row) => row.currency === company.currency).sort((a, b) => Number(b.balance) - Number(a.balance))[0];
    Object.assign(form, { account: bank?.id ?? null, paid_on: props.today, lines: unpaid.value.map((line) => line.id) });
  },
  { immediate: true },
);

function toggle(id: number, on: boolean): void {
  form.lines = on ? [...new Set([...form.lines, id])] : form.lines.filter((line) => line !== id);
}

const pay = useOwnerMoneyWrite((cid: number, input: { account: number; paid_on: string; lines: number[] }) => ownerMoneyApi.payDividend(cid, props.dividend.id, input));
async function save(): Promise<void> {
  error.value = null;
  if (!form.account) {
    error.value = t("finance.quick.errAccount");
    return;
  }
  if (!form.lines.length) {
    error.value = t("finance.dividends.pickLines");
    return;
  }
  try {
    await pay.mutateAsync({ account: form.account, paid_on: form.paid_on ?? props.today, lines: form.lines });
    toast.success(t("finance.dividends.paid", { amount: fmt.money(String(total.value)) }));
    open.value = false;
  } catch (failure) {
    if (!isApiError(failure)) throw failure;
    error.value = failure.detail ?? Object.values(failure.fieldErrors)[0]?.[0] ?? t("finance.myMoney.failed");
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.dividends.payTitle')" :description="`${fmt.day(dividend.period_start, 'medium')} – ${fmt.day(dividend.period_end, 'medium')}`" size="md">
    <div class="flex flex-col gap-4">
      <ul class="flex flex-col divide-y divide-line rounded-[12px] border border-line" data-pay-lines>
        <li v-for="line in unpaid" :key="line.id" class="flex items-center gap-3 px-3 py-2.5">
          <CheckBox :model-value="form.lines.includes(line.id)" :label="line.partner.name" class="min-w-0 flex-1" @update:model-value="toggle(line.id, $event)" />
          <span class="text-xs tabular-nums text-muted">{{ fmt.number(line.share, 2) }}%</span>
          <span class="w-28 text-right text-sm font-semibold tabular-nums text-fg"><MoneyText :value="line.amount" /></span>
        </li>
      </ul>
      <FormField :label="t('finance.myMoney.fromAccount')" :hint="account ? t('finance.myMoney.onAccount', { amount: fmt.money(account.balance) }) : undefined" required>
        <AccountChips v-model="form.account" :accounts="chips" />
      </FormField>
      <FormField :label="t('finance.dividends.paidOn')">
        <DatePicker v-model="form.paid_on" :max="today" />
      </FormField>
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm">
        <span class="text-muted">{{ t("finance.dividends.toPay") }}</span>
        <span class="font-semibold tabular-nums text-fg"><MoneyText :value="String(total)" /></span>
      </div>
      <p class="text-xs text-muted">{{ t("finance.dividends.payFootnote") }}</p>
      <p v-if="error" class="rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{{ error }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Wallet" :loading="pay.isPending.value" data-pay @click="save">{{ t("finance.dividends.pay") }}</UiButton>
    </template>
  </UiDialog>
</template>
