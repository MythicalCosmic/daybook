<script setup lang="ts">
/**
 * One bonus or fine in a side panel synced with `?adjustment=` (a bottom sheet on phones): the
 * amount with its sign, the reason the person sees, where it came from, who proposed and who
 * decided, the payslip that took it, and the dispute: the person's words and the answer box.
 * Approve, reject or void it from the footer (payroll.manage).
 */
import { Ban, Lock, MessageCircleWarning, Reply } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { payrollApi, useAdjustment, useRefresh } from "../api";
import { ADJUSTMENT_TONES, isAddition, isDecidable, isVoidable, signedAmount } from "../lib";
import type { Adjustment } from "../types";
import PayAmount from "./PayAmount.vue";
import SourceLabel from "./SourceLabel.vue";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const cid = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();
const canManage = computed(() => company.can("payroll.manage"));

const id = computed(() => {
  const raw = route.query.adjustment;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useAdjustment(id);
const row = computed<Adjustment | null>(() => query.data.value ?? null);

const facts = computed<DescriptionItem[]>(() => {
  const r = row.value;
  if (!r) return [];
  const items: DescriptionItem[] = [
    { key: "month", label: t("payroll.adjustments.month"), value: fmt.day(r.period, "monthYear") },
    { key: "kind", label: t("payroll.adjustments.kind"), value: t(`payroll.adjustmentKind.${r.kind}`) },
    { key: "source", label: t("payroll.adjustments.source"), value: "" },
    { key: "proposed", label: t("payroll.adjustments.proposedBy"), value: `${r.proposed_by?.name ?? t("payroll.adjustments.system")} · ${fmt.instant(r.created_at, "date")}` },
  ];
  if (r.decided_at) items.push({ key: "decided", label: t(r.status === "rejected" ? "payroll.adjustments.rejectedBy" : "payroll.adjustments.approvedBy"), value: `${r.decided_by?.name ?? t("payroll.adjustments.system")} · ${fmt.instant(r.decided_at, "date")}` });
  return items;
});

// Dispute answer ----------------------------------------------------------------------------------
const answer = ref("");
const cancelIt = ref(false);
const answering = ref(false);
watch(id, () => {
  answer.value = "";
  cancelIt.value = false;
});
const canAnswer = computed(() => !!row.value?.disputed_at && !row.value.dispute_answer && canManage.value && row.value.status === "approved");

async function sendAnswer(): Promise<void> {
  const r = row.value;
  if (!r || !answer.value.trim() || answering.value) return;
  answering.value = true;
  try {
    await payrollApi.answerDispute(cid.value, r.id, answer.value.trim(), cancelIt.value ? "void" : "keep");
    toast.success(cancelIt.value ? t("payroll.adjustments.answeredVoided") : t("payroll.adjustments.answerSent"));
    refresh();
  } catch {
    // The HTTP layer said why.
  } finally {
    answering.value = false;
  }
}

async function decide(decision: "approve" | "reject", reason = ""): Promise<void> {
  if (!row.value) return;
  await payrollApi.decideAdjustment(cid.value, row.value.id, decision, reason);
  toast.success(decision === "approve" ? t("payroll.adjustments.approved") : t("payroll.adjustments.rejected"));
  refresh();
}

async function voidIt(): Promise<void> {
  const r = row.value;
  if (!r) return;
  const result = await confirm({
    title: t("payroll.adjustments.voidTitle"),
    message: t("payroll.adjustments.voidBody"),
    confirmLabel: t("payroll.adjustments.void"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("common.reason"),
    reasonPlaceholder: t("common.reasonPlaceholder"),
    icon: Ban,
    onConfirm: (reason) => payrollApi.voidAdjustment(cid.value, r.id, reason),
  });
  if (result) {
    toast.success(t("payroll.adjustments.voided"));
    refresh();
  }
}
</script>

<template>
  <UiDrawer query-key="adjustment" size="md" :title="row ? t(`payroll.adjustmentKind.${row.kind}`) : t('payroll.nav.adjustments')">
    <template #default>
      <div class="p-5">
        <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
          <SkeletonBlock height="72px" radius="12px" />
          <SkeletonBlock v-for="n in 4" :key="n" height="18px" />
        </div>
        <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
        <div v-else-if="row" class="flex flex-col gap-5">
          <header class="flex items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="44" shape="rounded" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <p class="mt-0.5 text-[1.625rem] font-semibold leading-8 tracking-[-0.02em] tabular-nums">
                <PayAmount :value="signedAmount(row)" :currency="row.currency" :sign="isAddition(row.kind) ? 'always' : 'auto'" colored />
              </p>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <StatusPill :tone="ADJUSTMENT_TONES[row.status]" size="sm" :label="t(`payroll.adjustmentStatus.${row.status}`)" />
                <StatusPill v-if="row.disputed_at" tone="warning" size="sm" variant="outline" :icon="MessageCircleWarning" :dot="false" :label="t('payroll.adjustments.disputed')" />
                <StatusPill v-if="row.payslip" tone="neutral" size="sm" variant="outline" :icon="Lock" :dot="false" :label="t('payroll.adjustments.onPayslip')" />
              </div>
            </div>
          </header>

          <blockquote class="rounded-[10px] bg-surface-2 px-3.5 py-3 text-base text-fg">{{ row.reason }}</blockquote>

          <DescriptionList :items="facts" :columns="2">
            <template #value-source><SourceLabel :row="row" plain /></template>
          </DescriptionList>

          <section v-if="row.disputed_at" class="flex flex-col gap-3 rounded-[12px] border border-warning/40 p-3.5" data-testid="dispute">
            <div class="flex items-center gap-2">
              <MessageCircleWarning :size="16" class="text-warning" />
              <h3 class="text-sm font-semibold text-fg">{{ t("payroll.adjustments.disputeTitle", { date: fmt.instant(row.disputed_at, "date") }) }}</h3>
            </div>
            <p class="text-base text-fg">{{ row.dispute_text }}</p>
            <div v-if="row.dispute_answer" class="flex gap-2 rounded-[10px] bg-surface-2 px-3 py-2.5">
              <Reply :size="15" class="mt-0.5 shrink-0 text-subtle" />
              <div>
                <p class="text-xs font-semibold text-muted">{{ t("payroll.adjustments.yourAnswer") }}</p>
                <p class="text-sm text-fg">{{ row.dispute_answer }}</p>
              </div>
            </div>
            <template v-else-if="canAnswer">
              <FormField :label="t('payroll.adjustments.answer')" :hint="t('payroll.adjustments.answerHint')">
                <TextArea v-model="answer" :rows="2" :maxlength="500" :placeholder="t('payroll.adjustments.answerPlaceholder')" />
              </FormField>
              <ToggleSwitch v-model="cancelIt" layout="row" :label="t(`payroll.adjustments.cancelToo.${row.kind}`)" :description="t('payroll.adjustments.cancelTooHint')" />
              <UiButton variant="primary" size="sm" class="self-end" :icon="Reply" :loading="answering" :disabled="!answer.trim()" data-testid="send-answer" @click="sendAnswer">{{ t("payroll.adjustments.sendAnswer") }}</UiButton>
            </template>
            <p v-else class="text-sm text-muted">{{ t("payroll.adjustments.waitingAnswer") }}</p>
          </section>
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="row && canManage && (isDecidable(row) || isVoidable(row))" class="flex w-full items-center justify-end gap-2">
        <ApproveRejectButtons v-if="isDecidable(row)" :reject-title="t('payroll.adjustments.rejectTitle', { name: row.member.name })" :on-approve="() => decide('approve')" :on-reject="(reason: string) => decide('reject', reason)" />
        <UiButton v-else variant="danger" size="sm" :icon="Ban" @click="voidIt">{{ t("payroll.adjustments.void") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
