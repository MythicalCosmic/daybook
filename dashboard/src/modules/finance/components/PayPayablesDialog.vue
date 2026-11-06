<script setup lang="ts">
/**
 * Pay several payables at once (plan §14.8 "Pay distributors": `payables/pay/`, one ledger row
 * and one audit row per debt, all or nothing): one account and one day for every debt picked, what
 * each debt gets, and the total. Goods-receipt payables are wholesale of marked medicines, paid by
 * bank transfer: picking a cash desk, a safe or someone's own money for one shows a warning first.
 * Debts in different currencies are paid apart (one account has one currency).
 */
import { TriangleAlert } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { dec, toMoney } from "@/lib/decimal";
import { useCompanyId } from "@/stores/company";

import { financeApi, useOptions, useRefresh } from "../api";
import { bankTransferWarning, CASH_ACCOUNT_KINDS, pickerOrder } from "../lib";
import type { PayableDebt } from "../types";
import AccountChips from "./AccountChips.vue";

export interface PayablePick {
  debt: PayableDebt;
  amount: string;
}

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ picks: PayablePick[] }>();
const emit = defineEmits<{ paid: [ids: number[]] }>();

const { t } = useI18n();
const cid = useCompanyId();
const refresh = useRefresh();
const options = useOptions(open);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ account: null as number | null, paid_on: null as string | null });

const currencies = computed(() => [...new Set(props.picks.map((pick) => pick.debt.currency))]);
const currency = computed(() => currencies.value[0] ?? null);
const mixed = computed(() => currencies.value.length > 1);
const bankOnly = computed(() => props.picks.filter((pick) => pick.debt.bank_only));
/** Accounts in the debts' currency; with a goods-receipt payable among them, banks and cards first. */
const accounts = computed(() => {
  const all = (options.data.value?.accounts ?? []).filter((account) => account.currency === currency.value);
  const ordered = pickerOrder(all);
  if (!bankOnly.value.length) return ordered;
  return [...ordered.filter((account) => !CASH_ACCOUNT_KINDS.includes(account.kind)), ...ordered.filter((account) => CASH_ACCOUNT_KINDS.includes(account.kind))];
});
const account = computed(() => accounts.value.find((row) => row.id === form.account) ?? null);
const warn = computed(() => bankTransferWarning(props.picks.map((pick) => pick.debt), account.value));
const total = computed(() => toMoney(props.picks.reduce((sum, pick) => sum.plus(dec(pick.amount)), dec(0))));
/** Each distributor once, with what it gets in all. */
const parties = computed(() => {
  const byParty = new Map<string, { name: string; amount: ReturnType<typeof dec>; count: number }>();
  for (const pick of props.picks) {
    const name = pick.debt.party?.name ?? t("finance.debts.hidden");
    const key = `${pick.debt.party?.type ?? "x"}:${pick.debt.party?.id ?? name}`;
    const entry = byParty.get(key) ?? { name, amount: dec(0), count: 0 };
    entry.amount = entry.amount.plus(dec(pick.amount));
    entry.count += 1;
    byParty.set(key, entry);
  }
  return [...byParty.entries()].map(([key, entry]) => ({ key, name: entry.name, amount: toMoney(entry.amount), count: entry.count }));
});

function fillDefaults(): void {
  const data = options.data.value;
  if (!data) return;
  if (!form.paid_on) form.paid_on = data.today;
  if (form.account === null || !accounts.value.some((row) => row.id === form.account)) form.account = accounts.value[0]?.id ?? null;
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
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (!form.paid_on) errors.paid_on = t("finance.quick.errDay");
  if (Object.keys(errors).length || mixed.value || !props.picks.length) return;
  saving.value = true;
  try {
    const answer = await financeApi.payPayables(cid.value, {
      account: form.account!,
      paid_on: form.paid_on!,
      debts: props.picks.map((pick) => ({ id: pick.debt.id, amount: pick.amount })),
    });
    const n = answer.paid.length;
    toast.success(t("finance.payables.paidToast", { n }, n));
    for (const warning of answer.warnings ?? []) toast.warning(warning);
    refresh();
    emit(
      "paid",
      answer.paid.map((row) => row.debt_id),
    );
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
  <UiDialog v-model:open="open" :title="t('finance.payables.payTitle', { n: picks.length }, picks.length)" :description="t('finance.payables.payHint')" size="md">
    <div class="flex flex-col gap-4" data-pay-payables>
      <InlineAlert v-if="mixed" tone="danger" size="sm" :title="t('finance.payables.mixedTitle')" :description="t('finance.payables.mixedBody', { currencies: currencies.join(', ') })" />
      <ul class="flex max-h-48 flex-col divide-y divide-line overflow-y-auto rounded-[10px] border border-line">
        <li v-for="party in parties" :key="party.key" class="flex items-center gap-3 px-3 py-2 text-sm">
          <span class="min-w-0 flex-1 truncate text-fg" :title="party.name">{{ party.name }}</span>
          <span class="shrink-0 text-xs text-muted">{{ t("finance.overview.debtCount", { n: party.count }, party.count) }}</span>
          <span class="shrink-0 font-semibold tabular-nums text-fg"><MoneyText :value="party.amount" :currency="currency ?? undefined" decimals="never" /></span>
        </li>
      </ul>
      <div class="flex items-center justify-between rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm dark:bg-surface-3/60">
        <span class="text-muted">{{ t("finance.payables.total") }}</span>
        <span class="text-base font-semibold tabular-nums text-fg" data-total><MoneyText :value="total" :currency="currency ?? undefined" /></span>
      </div>
      <FormField :label="t('finance.debts.fromAccount')" :error="errors.account" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <InlineAlert
        v-if="warn"
        tone="warning"
        size="sm"
        :icon="TriangleAlert"
        :title="t('finance.payables.bankTitle')"
        :description="t('finance.payables.bankBody', { n: bankOnly.length, account: account?.name ?? '' }, bankOnly.length)"
        data-bank-warning
      />
      <FormField :label="t('finance.debts.paidOn')" :error="errors.paid_on" required>
        <DatePicker v-model="form.paid_on" :min="minDay" :max="options.data.value?.today ?? null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton :variant="warn ? 'secondary' : 'primary'" :loading="saving" :disabled="mixed || !picks.length" data-confirm-pay @click="pay">
        {{ warn ? t("finance.payables.payAnyway") : t("finance.payables.pay", { n: picks.length }, picks.length) }}
      </UiButton>
    </template>
  </UiDialog>
</template>
