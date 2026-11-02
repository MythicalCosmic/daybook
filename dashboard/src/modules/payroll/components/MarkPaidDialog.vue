<script setup lang="ts">
/**
 * "Mark paid" on a finalized run: whose pay went out (everyone still waiting, or the rows chosen
 * in the table), how (cash, card, bank transfer) and from which account. The total is the exact
 * sum of the server's net amounts; so‘m and dollars go out as separate payments. Finance books
 * each payment against the person's salary debt.
 */
import { CircleCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import CheckBox from "@/components/CheckBox.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { isPayable, payoutError, paySelection } from "../lib";
import type { Payslip, PayoutMethod, Run } from "../types";
import PayAmount from "./PayAmount.vue";
import PayoutFields from "./PayoutFields.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ run: Run; payslips: Payslip[]; preselected?: number[] | null }>(), { preselected: null });
const emit = defineEmits<{ paid: [ids: number[]] }>();

const { t } = useI18n();
const company = useCompanyStore();
const refresh = useRefresh();

const waiting = computed(() => props.payslips.filter((slip) => isPayable(slip, props.run.status)));
const currencies = computed<Currency[]>(() => [...new Set(waiting.value.map((slip) => slip.currency))].sort((a) => (a === "UZS" ? -1 : 1)));
const currency = ref<Currency>("UZS");
const listed = computed(() => waiting.value.filter((slip) => slip.currency === currency.value));
const chosen = ref<Set<number>>(new Set());
const method = ref<PayoutMethod>("cash");
const account = ref<number | null>(null);
const saving = ref(false);
const accountError = ref<string | null>(null);
const failure = ref<string | null>(null);

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    const wanted = props.preselected?.length ? new Set(props.preselected) : null;
    const first = waiting.value.find((slip) => !wanted || wanted.has(slip.id));
    currency.value = first?.currency ?? currencies.value[0] ?? "UZS";
    chosen.value = new Set(waiting.value.filter((slip) => slip.currency === currency.value && (!wanted || wanted.has(slip.id))).map((slip) => slip.id));
    accountError.value = null;
    failure.value = null;
  },
  { immediate: true },
);
watch(currency, () => {
  chosen.value = new Set(listed.value.map((slip) => slip.id));
});

const selection = computed(() => paySelection(props.payslips, chosen.value, props.run.status));
const total = computed(() => selection.value.totals.find((row) => row.currency === currency.value) ?? null);
const allChosen = computed(() => listed.value.length > 0 && listed.value.every((slip) => chosen.value.has(slip.id)));
const someChosen = computed(() => !allChosen.value && listed.value.some((slip) => chosen.value.has(slip.id)));

function toggle(id: number, value: boolean): void {
  const next = new Set(chosen.value);
  if (value) next.add(id);
  else next.delete(id);
  chosen.value = next;
}

function toggleAll(value: boolean): void {
  chosen.value = value ? new Set(listed.value.map((slip) => slip.id)) : new Set();
}

async function save(): Promise<void> {
  accountError.value = null;
  failure.value = null;
  if (!account.value) {
    accountError.value = t("payroll.payout.chooseAccount");
    return;
  }
  const ids = selection.value.ids;
  if (!ids.length || saving.value) return;
  saving.value = true;
  try {
    await payrollApi.markPaid(company.currentId ?? 0, props.run.id, { payslip_ids: ids, method: method.value, account: account.value });
    toast.success(t("payroll.markPaid.done", { n: ids.length }, ids.length));
    refresh();
    emit("paid", ids);
    open.value = false;
  } catch (error) {
    // Said here, in the dialog: "not enough money in Biznes karta" belongs next to the choice.
    const said = payoutError(error);
    accountError.value = said.account;
    failure.value = said.account ? null : (said.message ?? (said.network ? t("common.error.network") : t("common.error.generic")));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('payroll.markPaid.title')" :description="t('payroll.markPaid.description')" size="md">
    <div class="flex flex-col gap-4">
      <InlineAlert v-if="!waiting.length" tone="success" size="sm" :icon="CircleCheck" :description="t('payroll.markPaid.nothing')" />
      <template v-else>
        <SegmentedControl v-if="currencies.length > 1" v-model="currency" block size="sm" :options="currencies.map((value) => ({ value, label: value === 'UZS' ? t('payroll.currency.uzs') : t('payroll.currency.usd') }))" />
        <div class="rounded-[12px] border border-line">
          <div class="flex items-center gap-3 border-b border-line px-3 py-2">
            <CheckBox :model-value="allChosen" :indeterminate="someChosen" :label="t('payroll.markPaid.everyone', { n: listed.length }, listed.length)" @update:model-value="toggleAll" />
          </div>
          <ul class="max-h-[min(38vh,320px)] overflow-y-auto overscroll-contain">
            <li v-for="slip in listed" :key="slip.id" class="flex min-h-11 items-center gap-3 border-b border-line px-3 py-1.5 last:border-b-0">
              <CheckBox :model-value="chosen.has(slip.id)" :aria-label="slip.member.name" @update:model-value="(value: boolean) => toggle(slip.id, value)" />
              <UserAvatar :name="slip.member.name" :src="slip.member.photo_url" :size="26" />
              <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ slip.member.name }}</span>
              <span class="shrink-0 text-sm font-semibold tabular-nums"><PayAmount :value="slip.net" :currency="slip.currency" /></span>
            </li>
          </ul>
        </div>
        <div class="flex items-baseline justify-between gap-3 rounded-[10px] bg-surface-2 px-3 py-2.5">
          <span class="text-sm text-muted">{{ t("payroll.markPaid.total", { n: selection.ids.length }, selection.ids.length) }}</span>
          <span class="text-lg font-semibold tabular-nums text-fg" data-testid="pay-total"><MoneyText :value="total?.amount ?? '0'" :currency="currency" /></span>
        </div>
        <PayoutFields v-model:method="method" v-model:account="account" :currency="currency" :enabled="open" :error="accountError" />
        <InlineAlert v-if="failure" tone="danger" size="sm" :description="failure" data-testid="pay-failure" />
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" :disabled="!selection.ids.length" data-testid="mark-paid-confirm" @click="save">
        {{ t("payroll.markPaid.confirm", { n: selection.ids.length }, selection.ids.length) }}
      </UiButton>
    </template>
  </UiDialog>
</template>
