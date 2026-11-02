<script setup lang="ts">
/**
 * Pay out an approved advance: how (cash, card, bank transfer) and from which account. Finance
 * books it as money owed back by the person; the payslips take it back month by month.
 */
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import InlineAlert from "@/components/InlineAlert.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useRefresh } from "../api";
import { payoutError } from "../lib";
import type { Advance, PayoutMethod } from "../types";
import PayAmount from "./PayAmount.vue";
import PayoutFields from "./PayoutFields.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ advance: Advance }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const method = ref<PayoutMethod>("cash");
const account = ref<number | null>(null);
const saving = ref(false);
const error = ref<string | null>(null);
const failure = ref<string | null>(null);
watch(open, (isOpen) => {
  if (isOpen) error.value = failure.value = null;
});

async function save(): Promise<void> {
  error.value = failure.value = null;
  if (!account.value) {
    error.value = t("payroll.payout.chooseAccount");
    return;
  }
  if (saving.value) return;
  saving.value = true;
  try {
    await payrollApi.payAdvance(company.currentId ?? 0, props.advance.id, { method: method.value, account: account.value });
    toast.success(t("payroll.advances.paid"));
    refresh();
    open.value = false;
  } catch (caught) {
    const said = payoutError(caught);
    error.value = said.account;
    failure.value = said.account ? null : (said.message ?? (said.network ? t("common.error.network") : t("common.error.generic")));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('payroll.advances.payTitle')" size="sm">
    <div class="flex flex-col gap-4">
      <div class="flex items-center gap-3 rounded-[12px] bg-surface-2 px-3 py-3">
        <UserAvatar :name="advance.member.name" :src="advance.member.photo_url" :size="34" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ advance.member.name }}</p>
          <p class="truncate text-xs text-muted">
            {{ advance.installments > 1 ? t("payroll.advances.planMany", { n: advance.installments, month: fmt.day(advance.first_period, "monthYear") }, advance.installments) : t("payroll.advances.planOne", { month: fmt.day(advance.first_period, "monthYear") }) }}
          </p>
        </div>
        <span class="shrink-0 text-base font-semibold tabular-nums text-fg"><PayAmount :value="advance.amount" :currency="advance.currency" /></span>
      </div>
      <PayoutFields v-model:method="method" v-model:account="account" :currency="advance.currency" :enabled="open" :error="error" />
      <InlineAlert v-if="failure" tone="danger" size="sm" :description="failure" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="pay-advance" @click="save">{{ t("payroll.advances.paySave") }}</UiButton>
    </template>
  </UiDialog>
</template>
