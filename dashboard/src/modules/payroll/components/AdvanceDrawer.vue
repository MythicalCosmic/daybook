<script setup lang="ts">
/**
 * One advance in a side panel synced with `?advance=` (a bottom sheet on phones): how much, over
 * how many months, why, who asked and who decided, when it was paid and how; the repayment
 * schedule month by month and the repayments so far. The footer offers what the status allows:
 * approve or reject, pay out, record a repayment made in cash, cancel.
 */
import { Ban, HandCoins, Receipt } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import DatePicker from "@/components/DatePicker.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { isApiError } from "@/api/http";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useAdvance, useRefresh } from "../api";
import { ADVANCE_TONES, repaidShare } from "../lib";
import type { Advance } from "../types";
import AccountField from "./AccountField.vue";
import PayAmount from "./PayAmount.vue";

const emit = defineEmits<{ pay: [advance: Advance] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const canManage = computed(() => company.can("payroll.manage"));
const canPay = computed(() => company.can("payroll.pay"));

const id = computed(() => {
  const raw = route.query.advance;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useAdvance(id);
const advance = computed(() => query.data.value ?? null);
const share = computed(() => (advance.value ? repaidShare(advance.value) : null));

const facts = computed<DescriptionItem[]>(() => {
  const a = advance.value;
  if (!a) return [];
  const items: DescriptionItem[] = [
    {
      key: "plan",
      label: t("payroll.advances.plan"),
      value: a.installments > 1 ? t("payroll.advances.planMany", { n: a.installments, month: fmt.day(a.first_period, "monthYear") }, a.installments) : t("payroll.advances.planOne", { month: fmt.day(a.first_period, "monthYear") }),
      wide: true,
    },
    { key: "requested", label: t("payroll.advances.requested"), value: `${a.requested_by ?? a.member.name} · ${fmt.instant(a.created_at, "date")}` },
  ];
  if (a.decided_at) items.push({ key: "decided", label: a.status === "rejected" ? t("payroll.adjustments.rejectedBy") : t("payroll.adjustments.approvedBy"), value: `${a.decided_by ?? "—"} · ${fmt.instant(a.decided_at, "date")}` });
  if (a.paid_at) items.push({ key: "paid", label: t("payroll.advances.paidAt"), value: `${fmt.instant(a.paid_at, "date")}${a.payout_method ? ` · ${t(`payroll.method.${a.payout_method}`)}` : ""}` });
  if (a.decision_note) items.push({ key: "note", label: t("payroll.advances.decisionNote"), value: a.decision_note, wide: true });
  return items;
});

// Money paid back outside payroll (cash handed back), into an account ---------------------------
const repaying = ref(false);
const repay = reactive({ amount: null as string | null, paid_on: null as string | null, note: "", account: null as number | null });
const repayErrors = reactive<Record<string, string | undefined>>({});
const saving = ref(false);
watch(id, () => (repaying.value = false));
function startRepay(): void {
  Object.assign(repay, { amount: advance.value?.left ?? null, paid_on: todayIn(company.timezone), note: "", account: null });
  for (const key of Object.keys(repayErrors)) delete repayErrors[key];
  repaying.value = true;
}
async function saveRepay(): Promise<void> {
  const a = advance.value;
  if (!a || !repay.amount || !repay.paid_on || saving.value) return;
  if (!repay.account) {
    repayErrors.account = t("payroll.payout.chooseAccount");
    return;
  }
  saving.value = true;
  try {
    await payrollApi.repayAdvance(company.currentId ?? 0, a.id, { amount: repay.amount, account: repay.account, paid_on: repay.paid_on, note: repay.note.trim() });
    toast.success(t("payroll.advances.repaidSaved"));
    repaying.value = false;
    refresh();
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) repayErrors[field] = messages[0];
    // A refusal without a field ("more than is owed") is said in the form: the call shows no toast.
    if (isApiError(error) && !Object.keys(error.fieldErrors).length) repayErrors.form = error.detail ?? t("common.error.generic");
  } finally {
    saving.value = false;
  }
}

async function decide(decision: "approve" | "reject", note = ""): Promise<void> {
  if (!advance.value) return;
  await payrollApi.decideAdvance(company.currentId ?? 0, advance.value.id, decision, note);
  toast.success(decision === "approve" ? t("payroll.advances.approved") : t("payroll.advances.rejected"));
  refresh();
}

async function cancel(): Promise<void> {
  const a = advance.value;
  if (!a) return;
  const answer = await confirm({
    title: t("payroll.advances.cancelTitle"),
    message: t("payroll.advances.cancelBody"),
    confirmLabel: t("payroll.advances.cancel"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("common.reason"),
    icon: Ban,
    onConfirm: (reason) => payrollApi.cancelAdvance(company.currentId ?? 0, a.id, reason),
  });
  if (answer) {
    toast.success(t("payroll.advances.cancelled"));
    refresh();
  }
}
</script>

<template>
  <UiDrawer query-key="advance" size="md" :title="t('payroll.advances.drawerTitle')">
    <template #default>
      <div class="p-5">
        <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
          <SkeletonBlock height="72px" radius="12px" />
          <SkeletonBlock v-for="n in 4" :key="n" height="18px" />
        </div>
        <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
        <div v-else-if="advance" class="flex flex-col gap-5">
          <header class="flex items-start gap-3">
            <UserAvatar :name="advance.member.name" :src="advance.member.photo_url" :size="44" shape="rounded" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ advance.member.name }}</p>
              <p class="mt-0.5 text-[1.625rem] font-semibold leading-8 tracking-[-0.02em] tabular-nums text-fg"><PayAmount :value="advance.amount" :currency="advance.currency" /></p>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <StatusPill :tone="ADVANCE_TONES[advance.status]" size="sm" :label="t(`payroll.advanceStatus.${advance.status}`)" />
              </div>
            </div>
          </header>

          <div v-if="advance.status === 'paid' || advance.status === 'repaid'">
            <ProgressBar :value="share ?? 0" :max="100" size="sm" tone="success" />
            <p class="mt-1.5 text-xs text-muted">
              <template v-if="advance.repaid && advance.amount">{{ t("payroll.advances.repaidOf", { repaid: fmt.money(advance.repaid, advance.currency), amount: fmt.money(advance.amount, advance.currency) }) }}</template>
              <template v-else>{{ t("payroll.hidden") }}</template>
            </p>
          </div>

          <p v-if="advance.reason" class="rounded-[10px] bg-surface-2 px-3 py-2.5 text-base text-fg">{{ advance.reason }}</p>
          <DescriptionList :items="facts" :columns="2" />

          <section class="flex flex-col gap-2">
            <h3 class="flex items-center gap-1.5 text-sm font-semibold text-fg"><Receipt :size="15" class="text-subtle" />{{ t("payroll.advances.repayments") }}</h3>
            <ul v-if="advance.repayments?.length" class="flex flex-col divide-y divide-line rounded-[10px] border border-line" data-testid="repayments">
              <li v-for="row in advance.repayments" :key="row.id" class="flex min-h-11 items-center gap-3 px-3 py-2">
                <span class="w-24 shrink-0 text-sm text-muted">{{ fmt.day(row.paid_on, "short") }}</span>
                <span class="min-w-0 flex-1 truncate text-sm text-fg" :title="row.note">{{ row.how === "payslip" ? t("payroll.advances.fromPayslip") : t("payroll.advances.byHand") }}<template v-if="row.note"> · {{ row.note }}</template></span>
                <span class="shrink-0 text-sm font-semibold tabular-nums"><PayAmount :value="row.amount" :currency="advance.currency" /></span>
              </li>
            </ul>
            <p v-else class="text-sm text-muted">{{ advance.status === "paid" ? t("payroll.advances.repaymentsNone", { month: fmt.day(advance.first_period, "monthYear") }) : t("payroll.advances.repaymentsLater") }}</p>
          </section>

          <div v-if="repaying" class="flex flex-col gap-3 rounded-[12px] border border-line p-3" data-testid="repay-form">
            <p class="text-sm font-semibold text-fg">{{ t("payroll.advances.repayTitle") }}</p>
            <div class="grid gap-3 sm:grid-cols-2">
              <FormField :label="t('payroll.field.amount')" :error="repayErrors.amount" required>
                <MoneyInput v-model="repay.amount" :currencies="[advance.currency]" />
              </FormField>
              <FormField :label="t('payroll.advances.repaidOn')" :error="repayErrors.paid_on" required>
                <DatePicker v-model="repay.paid_on" :max="todayIn(company.timezone)" />
              </FormField>
            </div>
            <AccountField v-model="repay.account" :currency="advance.currency" :label="t('payroll.advances.intoAccount')" :error="repayErrors.account" />
            <InlineAlert v-if="repayErrors.form" tone="danger" size="sm" :description="repayErrors.form" />
            <FormField :label="t('payroll.pay.note')" optional>
              <TextInput v-model="repay.note" :maxlength="200" />
            </FormField>
            <div class="flex justify-end gap-2">
              <UiButton variant="ghost" size="sm" @click="repaying = false">{{ t("common.cancel") }}</UiButton>
              <UiButton variant="primary" size="sm" :loading="saving" :disabled="!repay.amount || !repay.paid_on" @click="saveRepay">{{ t("common.save") }}</UiButton>
            </div>
          </div>
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="advance" class="flex w-full flex-wrap items-center justify-end gap-2">
        <UiButton v-if="canManage && (advance.status === 'requested' || advance.status === 'approved')" variant="ghost" size="sm" :icon="Ban" class="mr-auto text-danger" @click="cancel">{{ t("payroll.advances.cancel") }}</UiButton>
        <ApproveRejectButtons
          v-if="canManage && advance.status === 'requested'"
          reason="optional"
          :reject-title="t('payroll.advances.rejectTitle', { name: advance.member.name })"
          :on-approve="() => decide('approve')"
          :on-reject="(reason: string) => decide('reject', reason)"
        />
        <UiButton v-if="canPay && advance.status === 'approved'" variant="primary" size="sm" :icon="HandCoins" @click="emit('pay', advance)">{{ t("payroll.advances.pay") }}</UiButton>
        <UiButton v-if="canPay && advance.status === 'paid' && !repaying" size="sm" :icon="Receipt" data-testid="start-repay" @click="startRepay">{{ t("payroll.advances.repay") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
