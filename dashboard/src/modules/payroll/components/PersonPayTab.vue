<script setup lang="ts">
/**
 * The Person 360 "Pay" tab (plan §15.4): the pay setup in force and its history (with "Change
 * pay"), this month's bonuses and fines, the payslips with their PDF, and the advances with what
 * is still owed. Each part loads and fails on its own; amounts the viewer may not see say so.
 */
import { FileDown, Gift, HandCoins, Pencil, ReceiptText, Scale, WalletCards } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { openPayslipPdf, useAdjustments, useAdvances, useCompensations, useMemberPayslips } from "../api";
import { ADJUSTMENT_TONES, ADVANCE_TONES, isAddition, PAYSLIP_TONES, payHistory, periodOf, signedAmount } from "../lib";
import type { Member, Payslip } from "../types";
import AdvanceDialog from "./AdvanceDialog.vue";
import ChangePayDialog from "./ChangePayDialog.vue";
import PayAmount from "./PayAmount.vue";
import PayHistory from "./PayHistory.vue";
import ProposeDialog from "./ProposeDialog.vue";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const canManage = computed(() => company.can("payroll.manage"));
const canPropose = computed(() => company.can(["payroll.propose", "payroll.manage"]));
const today = computed(() => todayIn(company.timezone));
const period = computed(() => periodOf(today.value));

const compensations = useCompensations(() => ({ member: props.memberId }));
const pay = computed(() => payHistory(compensations.data.value ?? [], today.value));
const member = computed<Member>(() => compensations.data.value?.[0]?.member ?? { id: props.memberId, name: "" });
const adjustments = useAdjustments(() => ({ member: props.memberId, period: period.value, page_size: 50 }));
const payslips = useMemberPayslips(() => props.memberId);
const advances = useAdvances(() => ({ member: props.memberId, page_size: 20 }));

const showHistory = ref(false);
const changing = ref(false);
const proposing = ref(false);
const proposeKind = ref<"bonus" | "fine">("bonus");
const giving = ref(false);
function propose(kind: "bonus" | "fine"): void {
  proposeKind.value = kind;
  proposing.value = true;
}

const downloading = ref<number | null>(null);
async function pdf(slip: Payslip): Promise<void> {
  downloading.value = slip.id;
  try {
    await openPayslipPdf(company.currentId ?? 0, slip.id, `payslip-${slip.period.slice(0, 7)}.pdf`);
  } catch {
    // The HTTP layer said why.
  } finally {
    downloading.value = null;
  }
}
const base = computed(() => `/c/${company.currentId}/payroll`);
</script>

<template>
  <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="person-pay">
    <div class="flex min-w-0 flex-col gap-5">
      <PageSection variant="card" :heading-level="3" :title="t('payroll.person.payNow')">
        <template v-if="canManage" #actions>
          <UiButton size="sm" :icon="Pencil" data-testid="person-change-pay" @click="changing = true">{{ pay.current ? t("payroll.pay.change") : t("payroll.pay.set") }}</UiButton>
        </template>
        <div v-if="compensations.isPending.value" class="flex flex-col gap-2"><SkeletonBlock height="28px" width="60%" /><SkeletonBlock height="16px" width="40%" /></div>
        <ErrorState v-else-if="compensations.isError.value" compact :error="compensations.error.value" :retry="() => compensations.refetch()" />
        <EmptyState v-else-if="!pay.current && !pay.upcoming" size="sm" :icon="WalletCards" tone="neutral" :title="t('payroll.pay.none')" :description="t('payroll.person.noPayBody')" />
        <div v-else class="flex flex-col gap-3">
          <div v-if="pay.current">
            <p class="text-2xl font-semibold tabular-nums text-fg">
              <PayAmount :value="pay.current.amount" :currency="pay.current.currency" /><span class="ml-1.5 text-base font-normal text-muted">{{ t(`payroll.pay.per.${pay.current.pay_type}`) }}</span>
            </p>
            <p class="mt-0.5 text-sm text-muted">
              {{ t(`payroll.payType.${pay.current.pay_type}`) }}<template v-if="pay.current.pay_type === 'monthly'"> · {{ t(`payroll.proration.${pay.current.proration}`) }}</template> ·
              {{ t("payroll.pay.from", { date: fmt.day(pay.current.effective_from, "long") }) }}
            </p>
          </div>
          <p v-if="pay.upcoming" class="rounded-[10px] bg-info-soft px-3 py-2 text-sm text-info">
            {{ t("payroll.person.upcoming", { date: fmt.day(pay.upcoming.effective_from, "long"), amount: pay.upcoming.amount ? fmt.money(pay.upcoming.amount, pay.upcoming.currency) : t("payroll.hidden") }) }}
          </p>
          <button v-if="pay.history.length" type="button" class="self-start text-sm font-semibold text-accent-fg hover:underline" @click="showHistory = !showHistory">
            {{ showHistory ? t("payroll.person.hideHistory") : t("payroll.person.showHistory", { n: pay.history.length }, pay.history.length) }}
          </button>
          <PayHistory v-if="showHistory" :history="pay.history" :current="pay.current" :editable="false" />
        </div>
      </PageSection>

      <PageSection variant="card" :heading-level="3" :title="t('payroll.person.thisMonth', { month: fmt.day(period, 'monthYear') })">
        <template v-if="canPropose" #actions>
          <div class="flex gap-1">
            <IconButton :icon="Scale" size="sm" variant="secondary" :label="t('payroll.adjustments.newFine')" @click="propose('fine')" />
            <IconButton :icon="Gift" size="sm" variant="secondary" :label="t('payroll.adjustments.newBonus')" @click="propose('bonus')" />
          </div>
        </template>
        <div v-if="adjustments.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="40px" radius="8px" /></div>
        <ErrorState v-else-if="adjustments.isError.value" compact :error="adjustments.error.value" :retry="() => adjustments.refetch()" />
        <p v-else-if="!adjustments.data.value?.results.length" class="text-sm text-muted">{{ t("payroll.person.noAdjustments") }}</p>
        <ul v-else class="-mx-1 flex flex-col">
          <li v-for="row in adjustments.data.value.results" :key="row.id">
            <RouterLink :to="`${base}/adjustments?tab=${row.disputed_at ? 'disputed' : row.status === 'void' ? 'rejected' : row.status}&adjustment=${row.id}`" class="flex min-h-11 items-center gap-3 rounded-[8px] px-1 py-1.5 hover:bg-surface-2">
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-fg">{{ row.reason }}</p>
                <p class="truncate text-xs text-muted">{{ t(`payroll.adjustmentKind.${row.kind}`) }} · {{ t(`payroll.source.${row.source}`) }}</p>
              </div>
              <StatusPill :tone="ADJUSTMENT_TONES[row.status]" size="sm" :label="t(`payroll.adjustmentStatus.${row.status}`)" />
              <span class="w-28 shrink-0 text-right text-sm font-semibold tabular-nums"><PayAmount :value="signedAmount(row)" :currency="row.currency" :sign="isAddition(row.kind) ? 'always' : 'auto'" colored /></span>
            </RouterLink>
          </li>
        </ul>
      </PageSection>
    </div>

    <div class="flex min-w-0 flex-col gap-5">
      <PageSection variant="card" :heading-level="3" :title="t('payroll.person.payslips')">
        <div v-if="payslips.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="40px" radius="8px" /></div>
        <ErrorState v-else-if="payslips.isError.value" compact :error="payslips.error.value" :retry="() => payslips.refetch()" />
        <p v-else-if="!payslips.data.value?.length" class="flex items-center gap-2 text-sm text-muted"><ReceiptText :size="15" class="text-subtle" />{{ t("payroll.person.noPayslips") }}</p>
        <ul v-else class="-mx-1 flex flex-col">
          <li v-for="slip in payslips.data.value" :key="slip.id" class="flex min-h-11 items-center gap-3 rounded-[8px] px-1 py-1.5 hover:bg-surface-2">
            <RouterLink :to="`${base}/runs/${slip.run}?payslip=${slip.id}`" class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-fg">{{ fmt.day(slip.period, "monthYear") }}</p>
              <p v-if="slip.received_at || slip.paid_at" class="truncate text-xs text-muted">
                {{ slip.received_at ? t("payroll.person.received", { date: fmt.instant(slip.received_at, "date") }) : t("payroll.runs.paidOn", { date: fmt.instant(slip.paid_at!, "date") }) }}
              </p>
            </RouterLink>
            <StatusPill :tone="PAYSLIP_TONES[slip.status]" size="sm" :label="t(`payroll.payslipStatus.${slip.status}`)" />
            <span class="w-28 shrink-0 text-right text-sm font-semibold tabular-nums text-fg"><PayAmount :value="slip.net" :currency="slip.currency" /></span>
            <IconButton :icon="FileDown" size="sm" :label="t('payroll.payslip.pdf')" :loading="downloading === slip.id" @click="pdf(slip)" />
          </li>
        </ul>
      </PageSection>

      <PageSection variant="card" :heading-level="3" :title="t('payroll.nav.advances')">
        <template v-if="canManage" #actions>
          <IconButton :icon="HandCoins" size="sm" variant="secondary" :label="t('payroll.advances.give')" @click="giving = true" />
        </template>
        <div v-if="advances.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="40px" radius="8px" /></div>
        <ErrorState v-else-if="advances.isError.value" compact :error="advances.error.value" :retry="() => advances.refetch()" />
        <p v-else-if="!advances.data.value?.results.length" class="text-sm text-muted">{{ t("payroll.person.noAdvances") }}</p>
        <ul v-else class="-mx-1 flex flex-col">
          <li v-for="row in advances.data.value.results" :key="row.id">
            <RouterLink :to="`${base}/advances?advance=${row.id}`" class="flex min-h-11 items-center gap-3 rounded-[8px] px-1 py-1.5 hover:bg-surface-2">
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-fg">{{ fmt.instant(row.created_at, "date") }}<template v-if="row.reason"> · {{ row.reason }}</template></p>
                <p v-if="row.status === 'paid' && row.left" class="truncate text-xs text-muted">{{ t("payroll.person.owes", { amount: fmt.money(row.left, row.currency) }) }}</p>
              </div>
              <StatusPill :tone="ADVANCE_TONES[row.status]" size="sm" :label="t(`payroll.advanceStatus.${row.status}`)" />
              <span class="w-28 shrink-0 text-right text-sm font-semibold tabular-nums text-fg"><PayAmount :value="row.amount" :currency="row.currency" /></span>
            </RouterLink>
          </li>
        </ul>
      </PageSection>
    </div>

    <ChangePayDialog v-if="canManage" v-model:open="changing" :member="member" :history="pay.history" />
    <ProposeDialog v-if="canPropose" v-model:open="proposing" :kind="proposeKind" :member="memberId" />
    <AdvanceDialog v-if="canManage" v-model:open="giving" :member="memberId" />
  </div>
</template>
