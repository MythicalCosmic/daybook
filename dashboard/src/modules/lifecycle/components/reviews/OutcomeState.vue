<script setup lang="ts">
/**
 * A published review's outcome and where it stands: the raise or promotion as its job change
 * (waiting for approval, approved for its day, in force, or not approved), the bonus as payroll's
 * adjustment, with a way to it and, for whoever may decide a job change, Approve and Reject here.
 * Nothing changes pay without that approval.
 */
import { ArrowRight, Award, ExternalLink, Gift, Minus, Target, TrendingUp } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import MoneyText from "@/components/MoneyText.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { lifecycleApi } from "../../api";
import { useReviewMutation } from "../../reviews/api";
import { OUTCOME_STATE_TONES } from "../../reviews/lib";
import type { Outcome, Review } from "../../reviews/types";

const props = defineProps<{ review: Review }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const ICONS: Record<Outcome, typeof Minus> = { none: Minus, raise: TrendingUp, bonus: Gift, promotion: Award, improvement_plan: Target };
const change = computed(() => props.review.job_change);
const percent = computed(() => (props.review.raise_percent ? fmt.number(props.review.raise_percent, 2) : null));
const changeLink = computed(() => (change.value ? `/c/${company.currentId}/lifecycle/job-changes?change=${change.value.id}` : null));
const bonusLink = computed(() => `/c/${company.currentId}/payroll/adjustments`);

const approve = useReviewMutation((cid, id: number) => lifecycleApi.approveChange(cid, id));
const reject = useReviewMutation((cid, input: { id: number; reason: string }) => lifecycleApi.rejectChange(cid, input.id, input.reason));
async function runApprove(): Promise<void> {
  if (!change.value) return;
  await approve.mutateAsync(change.value.id);
  toast.success(t("lifecycle.reviews.state.approvedToast", { name: props.review.member.name }));
}
async function runReject(reason: string): Promise<void> {
  if (!change.value) return;
  await reject.mutateAsync({ id: change.value.id, reason });
  toast.success(t("lifecycle.reviews.state.rejectedToast", { name: props.review.member.name }));
}
</script>

<template>
  <div class="flex flex-col gap-3" data-outcome-state>
    <div class="flex items-start gap-3">
      <span class="grid size-10 shrink-0 place-items-center rounded-[12px] bg-surface-2 text-fg dark:bg-surface-3" aria-hidden="true">
        <component :is="ICONS[review.outcome]" :size="18" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <p class="text-base font-semibold text-fg">{{ t(`lifecycle.reviews.outcome.${review.outcome}`) }}</p>
          <StatusPill v-if="review.outcome_state" size="sm" :tone="OUTCOME_STATE_TONES[review.outcome_state]" :label="t(`lifecycle.reviews.state.${review.outcome_state}`)" />
        </div>
        <p class="mt-0.5 text-sm text-muted">
          <template v-if="review.outcome === 'raise' && percent">
            {{ t("lifecycle.reviews.state.raiseLine", { percent, date: review.effective_on ? fmt.day(review.effective_on, "medium") : "—" }) }}
          </template>
          <template v-else-if="review.outcome === 'promotion'">
            {{ t("lifecycle.reviews.state.promotionLine", { position: review.promotion_position?.name ?? "—", date: review.effective_on ? fmt.day(review.effective_on, "medium") : "—" }) }}
            <template v-if="percent"> · {{ t("lifecycle.reviews.state.withRaise", { percent }) }}</template>
          </template>
          <template v-else-if="review.outcome === 'bonus' && review.bonus_amount">
            <MoneyText :value="review.bonus_amount" :currency="review.bonus_currency" />
            <template v-if="review.effective_on"> · {{ t("lifecycle.reviews.state.bonusMonth", { month: fmt.day(review.effective_on, "monthYear") }) }}</template>
          </template>
          <template v-else-if="review.outcome === 'improvement_plan'">{{ t("lifecycle.reviews.state.planLine", { count: review.goals.length }, review.goals.length) }}</template>
          <template v-else>{{ t("lifecycle.reviews.state.noneLine") }}</template>
        </p>
        <p v-if="review.pay && change?.pay_after" class="mt-1 flex flex-wrap items-center gap-1.5 text-sm" data-state-pay>
          <MoneyText class="tabular-nums text-muted" :value="review.pay.amount" :currency="review.pay.currency" />
          <ArrowRight :size="13" class="text-subtle" aria-hidden="true" />
          <MoneyText class="font-semibold tabular-nums text-fg" :value="change.pay_after" :currency="review.pay.currency" />
        </p>
        <p v-if="change?.error" class="mt-1 text-xs text-danger">{{ change.error }}</p>
      </div>
    </div>
    <div v-if="change || review.bonus" class="flex flex-wrap items-center gap-2">
      <ApproveRejectButtons v-if="change?.can_decide" size="sm" :on-approve="runApprove" :on-reject="runReject" :reject-title="t('lifecycle.changes.rejectTitle')" />
      <UiButton v-if="changeLink" size="sm" variant="ghost" :to="changeLink" :icon-right="ExternalLink">{{ t("lifecycle.reviews.state.openChange") }}</UiButton>
      <UiButton v-else-if="review.bonus && company.can(['payroll.view', 'payroll.manage', 'payroll.propose'])" size="sm" variant="ghost" :to="bonusLink" :icon-right="ExternalLink">
        {{ t("lifecycle.reviews.state.openBonus") }}
      </UiButton>
    </div>
    <p v-if="review.outcome_state === 'waiting'" class="text-xs text-muted">{{ t("lifecycle.reviews.state.waitingHint") }}</p>
  </div>
</template>
