<script setup lang="ts">
/**
 * "Pul olish" (take money out) and "Pul qo‘yish" (put money in): the amount, the business account
 * it leaves or reaches, the day and a note. Taking more than is safe shows what it puts at risk
 * and needs a tick before it books; the server checks the same and refuses without it.
 */
import { ArrowDownToLine, ArrowUpFromLine, TriangleAlert } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import CheckBox from "@/components/CheckBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import type { AccountRef } from "../../types";
import AccountChips from "../AccountChips.vue";
import { ownerMoneyApi, useOwnerMoneyWrite, type OwnerMoney } from "../../ownerMoney";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ mode: "take" | "put"; data: OwnerMoney }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({ amount: null as string | null, account: null as number | null, occurred_on: null as string | null, description: "", confirmed: false });

const taking = computed(() => props.mode === "take");
const accounts = computed<AccountRef[]>(() =>
  props.data.accounts.filter((account) => account.currency === company.currency).map((account) => ({ id: account.id, name: account.name, kind: account.kind as AccountRef["kind"], currency: account.currency as AccountRef["currency"], branch_id: account.branch_id })),
);
const account = computed(() => props.data.accounts.find((row) => row.id === form.account) ?? null);
const over = computed(() => taking.value && !!form.amount && Number(form.amount) > Number(props.data.safe));
const overBy = computed(() => (over.value ? Number(form.amount) - Number(props.data.safe) : 0));
const tooMuch = computed(() => taking.value && !!form.amount && !!account.value && Number(form.amount) > Number(account.value.balance));

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    Object.assign(form, { amount: null, account: biggestAccount(), occurred_on: props.data.today, description: "", confirmed: false });
    for (const key of Object.keys(errors)) delete errors[key];
  },
  { immediate: true },
);
watch(over, (isOver) => {
  if (!isOver) form.confirmed = false;
});

function biggestAccount(): number | null {
  const list = [...props.data.accounts].filter((row) => row.currency === company.currency);
  list.sort((a, b) => Number(b.balance) - Number(a.balance));
  return list[0]?.id ?? null;
}

const take = useOwnerMoneyWrite(ownerMoneyApi.take);
const put = useOwnerMoneyWrite(ownerMoneyApi.put);
const saving = computed(() => take.isPending.value || put.isPending.value);
const lastSafe = ref<string | null>(null);

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.amount || Number(form.amount) <= 0) errors.amount = t("finance.quick.errAmount");
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (over.value && !form.confirmed) errors.confirmed = t("finance.myMoney.confirmNeeded");
  if (Object.keys(errors).length) return;
  const input = { account: form.account!, amount: form.amount!, occurred_on: form.occurred_on ?? undefined, description: form.description.trim(), confirmed: form.confirmed };
  try {
    const result = taking.value ? await take.mutateAsync(input) : await put.mutateAsync(input);
    lastSafe.value = result.safe;
    toast.success(taking.value ? t("finance.myMoney.taken", { amount: fmt.money(result.amount) }) : t("finance.myMoney.putDone", { amount: fmt.money(result.amount) }));
    open.value = false;
  } catch (error) {
    if (!isApiError(error)) throw error;
    if (error.code === "over_safe") {
      errors.confirmed = t("finance.myMoney.confirmNeeded");
      return;
    }
    for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    if (error.detail) toast.error(error.detail);
    else if (!Object.keys(error.fieldErrors).length) toast.error(t("finance.myMoney.failed"));
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    :title="taking ? t('finance.myMoney.takeTitle') : t('finance.myMoney.putTitle')"
    :description="taking ? t('finance.myMoney.takeDescription') : t('finance.myMoney.putDescription')"
    size="md"
  >
    <div class="flex flex-col gap-4">
      <div v-if="taking" class="flex items-center justify-between gap-3 rounded-[10px] bg-success-soft px-3 py-2.5 text-sm" data-safe-line>
        <span class="text-success">{{ t("finance.myMoney.safeLabel") }}</span>
        <button type="button" class="font-semibold tabular-nums text-success underline-offset-2 hover:underline" :title="t('finance.myMoney.useSafe')" data-use-safe @click="form.amount = data.safe">
          <MoneyText :value="data.safe" />
        </button>
      </div>

      <FormField :label="t('finance.field.amount')" :error="errors.amount" required>
        <MoneyInput v-model="form.amount" :currencies="[company.currency]" :invalid="!!errors.amount" data-amount />
      </FormField>

      <div v-if="over" class="flex gap-2.5 rounded-[10px] border border-[color-mix(in_srgb,var(--c-warning)_30%,transparent)] bg-warning-soft/70 p-3" role="alert" data-over>
        <TriangleAlert :size="16" class="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
        <div class="min-w-0 flex-1 text-sm">
          <p class="font-semibold text-fg">{{ t("finance.myMoney.overTitle", { amount: fmt.money(String(overBy), undefined, { compact: true }) }) }}</p>
          <p class="mt-0.5 text-muted">{{ t("finance.myMoney.overBody", { days: data.horizon_days }) }}</p>
          <CheckBox v-model="form.confirmed" class="mt-2" :label="t('finance.myMoney.overConfirm')" data-confirm />
          <p v-if="errors.confirmed" class="mt-1 text-xs text-danger">{{ errors.confirmed }}</p>
        </div>
      </div>

      <FormField :label="taking ? t('finance.myMoney.fromAccount') : t('finance.myMoney.toAccount')" :error="errors.account" :hint="account ? t('finance.myMoney.onAccount', { amount: fmt.money(account.balance, account.currency as never) }) : undefined" required>
        <AccountChips v-model="form.account" :accounts="accounts" :invalid="!!errors.account" />
      </FormField>
      <p v-if="tooMuch" class="-mt-2 text-xs text-danger">{{ t("finance.myMoney.notEnough") }}</p>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('finance.field.date')" :error="errors.occurred_on">
          <DatePicker v-model="form.occurred_on" :max="data.today" />
        </FormField>
        <FormField :label="t('finance.myMoney.note')" optional :error="errors.description">
          <TextInput v-model="form.description" :maxlength="300" :placeholder="taking ? t('finance.myMoney.notePlaceholderTake') : t('finance.myMoney.notePlaceholderPut')" />
        </FormField>
      </div>
      <p class="text-xs text-muted">{{ taking ? t("finance.myMoney.takeFootnote") : t("finance.myMoney.putFootnote") }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton :variant="over ? 'danger' : 'primary'" :icon="taking ? ArrowUpFromLine : ArrowDownToLine" :loading="saving" :disabled="over && !form.confirmed" data-save @click="save">
        {{ taking ? (over ? t("finance.myMoney.takeAnyway") : t("finance.myMoney.take")) : t("finance.myMoney.put") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
