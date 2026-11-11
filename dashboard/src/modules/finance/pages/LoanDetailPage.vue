<script setup lang="ts">
/**
 * One loan (v12): what is owed and how much is repaid, the next payment, the interest paid and
 * still to pay, then the whole schedule (date, payment, principal, interest, what is owed after
 * it, state) with "Pay" on the next one, and the ledger rows the loan booked. "Repay early" plans
 * the rest again; "Change schedule" changes the terms while nothing is paid yet.
 */
import { AlertTriangle, ArrowLeft, CalendarClock, CalendarCog, FastForward, Landmark, Percent, RotateCcw, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId } from "@/stores/company";

import { useRefresh } from "../api";
import LoanEarlyDialog from "../components/loans/LoanEarlyDialog.vue";
import LoanFormDialog from "../components/loans/LoanFormDialog.vue";
import LoanPayDialog from "../components/loans/LoanPayDialog.vue";
import { creditApi, LINE_TONES, repaidShare, useLoan, type LoanLine } from "../credit";
import type { Transaction } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const cid = useCompanyId();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.params.loanId) || null);
const query = useLoan(id);
const detail = computed(() => query.data.value ?? null);
const loan = computed(() => detail.value?.loan ?? null);
const schedule = computed(() => detail.value?.schedule ?? []);
const nextId = computed(() => schedule.value.find((row) => row.status !== "paid")?.id ?? null);
const open = computed(() => loan.value?.status === "open");
const taken = computed(() => loan.value?.direction === "payable");

const kpis = computed(() => {
  const l = loan.value;
  return [
    { id: "owed", label: taken.value ? t("finance.loans.stillOwe") : t("finance.loans.stillOwed"), value: l?.owed ?? null, format: "money" as const, currency: l?.currency, compact: true, icon: Landmark, hint: l ? t("finance.loans.ofAmount", { amount: fmt.money(l.amount, l.currency, { compact: true }) }) : undefined },
    { id: "next", label: t("finance.loans.next"), value: l?.next?.rest ?? null, format: "money" as const, currency: l?.currency, compact: true, icon: CalendarClock, hint: l?.next ? fmt.day(l.next.due_on, "long") : t("finance.loans.allPaid") },
    { id: "paid", label: t("finance.loans.interestPaid"), value: l?.interest_paid ?? null, format: "money" as const, currency: l?.currency, compact: true, icon: Percent },
    { id: "left", label: t("finance.loans.interestLeft"), value: l?.interest_left ?? null, format: "money" as const, currency: l?.currency, compact: true, icon: Wallet, hint: l?.ends_on ? t("finance.loans.endsOn", { date: fmt.day(l.ends_on, "monthYear") }) : undefined },
  ];
});

const payOpen = ref(false);
const paying = ref<LoanLine | null>(null);
function pay(line: LoanLine): void {
  paying.value = line;
  payOpen.value = true;
}
const earlyOpen = ref(false);
const editOpen = ref(false);
const typedRows = computed(() => schedule.value.map((row) => ({ due_on: row.due_on, principal: row.principal, interest: row.interest })));

/** Ledger rows the loan booked, in words: the money in or out, principal, interest or the fee. */
function rowLabel(row: Transaction): string {
  if (row.kind === "debt_open") return taken.value ? t("finance.loans.row.received") : t("finance.loans.row.lent");
  if (row.kind === "debt_payment") return t("finance.loans.row.principal");
  return [row.category?.name, row.description].filter(Boolean).join(" · ") || row.kind_label;
}
const undoable = (row: Transaction) => !!detail.value?.can_undo && row.status === "posted" && row.source?.type === "finance.loan" && row.kind === "debt_payment";

async function undo(row: Transaction): Promise<void> {
  const answer = await confirm({ title: t("finance.loans.undoTitle"), message: t("finance.loans.undoBody"), confirmLabel: t("common.undo"), tone: "danger", reason: "required" });
  if (!answer || !loan.value) return;
  try {
    await creditApi.undo(cid.value, loan.value.id, row.id, answer.reason);
    toast.success(t("finance.loans.undone"));
    refresh();
  } catch {
    // The HTTP layer said why.
  }
}
</script>

<template>
  <div>
    <RouterLink :to="`/c/${cid}/finance/loans`" class="mb-2 inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-fg"><ArrowLeft :size="14" aria-hidden="true" />{{ t("finance.nav.loans") }}</RouterLink>

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="!loan">
      <SkeletonBlock height="64px" radius="12px" class="mb-4" />
      <SkeletonBlock height="96px" radius="14px" class="mb-4" />
      <SkeletonBlock height="360px" radius="14px" />
    </template>
    <div v-else class="flex flex-col gap-4">
      <PageHeader :title="loan.counterparty.name" :description="[loan.direction_label, fmt.percent(Number(loan.annual_rate), 2), loan.method_label, loan.description].filter(Boolean).join(' · ')">
        <template #actions>
          <UiButton v-if="detail?.can_edit_schedule" variant="ghost" :icon="CalendarCog" data-edit-schedule @click="editOpen = true">{{ t("finance.loans.changeSchedule") }}</UiButton>
          <UiButton v-if="detail?.can_pay && open" variant="secondary" :icon="FastForward" data-repay-early @click="earlyOpen = true">{{ t("finance.loans.early.title") }}</UiButton>
          <UiButton
            v-if="detail?.can_pay && open && loan.next"
            variant="primary"
            :icon="Wallet"
            data-pay-next
            @click="pay(schedule.find((row) => row.id === loan!.next!.id) ?? loan.next)"
          >
            {{ t("finance.loans.payNext") }}
          </UiButton>
        </template>
      </PageHeader>

      <InlineAlert
        v-if="loan.overdue_count"
        tone="danger"
        :icon="AlertTriangle"
        :title="t('finance.loans.lateTitle', { n: loan.overdue_count }, loan.overdue_count)"
        :description="t('finance.loans.lateBody', { amount: fmt.money(loan.overdue_amount, loan.currency) })"
      />
      <InlineAlert v-if="loan.status !== 'open'" tone="success" :title="t('finance.loans.closedTitle')" :description="t(`finance.debtStatus.${loan.status}`)" />

      <KpiStrip :items="kpis" :columns="4" phone="grid" />
      <div class="ui-card px-4 py-3">
        <ProgressBar :value="repaidShare(loan)" :max="100" tone="success" :label="t('finance.loans.repaidOf', { paid: fmt.money(loan.paid_principal, loan.currency, { compact: true }), amount: fmt.money(loan.amount, loan.currency, { compact: true }) })" :value-text="fmt.percent(repaidShare(loan))" />
      </div>

      <section class="ui-card overflow-hidden" :aria-label="t('finance.loans.schedule')" data-schedule>
        <header class="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <h2 class="min-w-0 flex-1 text-base font-semibold text-fg">{{ t("finance.loans.schedule") }}</h2>
          <span class="text-xs text-muted">{{ t("finance.loans.paymentsLeft", { n: loan.payments_left, total: loan.payments }, loan.payments_left) }}</span>
        </header>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[44rem] text-sm">
            <thead class="bg-surface-2 text-xs text-muted">
              <tr>
                <th class="w-10 px-3 py-2 text-left font-medium">#</th>
                <th class="px-3 py-2 text-left font-medium">{{ t("finance.loans.col.date") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("finance.loans.col.payment") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("finance.loans.col.principal") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("finance.loans.col.interest") }}</th>
                <th class="px-3 py-2 text-right font-medium">{{ t("finance.loans.col.balance") }}</th>
                <th class="px-3 py-2 text-left font-medium">{{ t("finance.loans.col.status") }}</th>
                <th class="w-24" />
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="row in schedule" :key="row.id" :class="[row.id === nextId && 'bg-accent-soft/30', row.status === 'paid' && 'text-muted']" :data-line="row.id">
                <td class="px-3 py-2 tabular-nums text-subtle">{{ row.position }}</td>
                <td class="px-3 py-2 tabular-nums">
                  {{ fmt.day(row.due_on, "medium") }}
                  <span v-if="row.early" class="ml-1 text-xs font-medium text-accent-fg">{{ t("finance.loans.earlyRow") }}</span>
                </td>
                <td class="px-3 py-2 text-right font-semibold tabular-nums" :class="row.status !== 'paid' && 'text-fg'"><MoneyText :value="row.payment" :currency="loan.currency" decimals="never" /></td>
                <td class="px-3 py-2 text-right tabular-nums"><MoneyText :value="row.principal" :currency="loan.currency" decimals="never" /></td>
                <td class="px-3 py-2 text-right tabular-nums"><MoneyText :value="row.interest" :currency="loan.currency" decimals="never" /></td>
                <td class="px-3 py-2 text-right tabular-nums text-muted"><MoneyText :value="row.balance" :currency="loan.currency" decimals="never" /></td>
                <td class="px-3 py-2"><StatusPill :tone="LINE_TONES[row.status]" size="sm" :label="t(`finance.installment.${row.status}`)" /></td>
                <td class="px-3 py-1.5 text-right">
                  <UiButton v-if="detail?.can_pay && open && row.status !== 'paid' && row.id === nextId" size="sm" :variant="row.status === 'overdue' ? 'primary' : 'secondary'" data-pay-line @click="pay(row)">{{ t("finance.loans.pay") }}</UiButton>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="ui-card overflow-hidden" :aria-label="t('finance.loans.entries')">
        <header class="border-b border-line px-4 py-3"><h2 class="text-base font-semibold text-fg">{{ t("finance.loans.entries") }}</h2></header>
        <EmptyState v-if="!detail?.payments.length" size="sm" :icon="Wallet" :title="t('finance.loans.noEntries')" />
        <ul v-else class="flex flex-col divide-y divide-line">
          <li v-for="row in detail.payments" :key="row.id" :class="['flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5', row.status === 'void' && 'opacity-50']">
            <span class="w-24 shrink-0 text-sm tabular-nums text-muted">{{ fmt.day(row.occurred_on, "medium") }}</span>
            <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ rowLabel(row) }}<span v-if="row.account" class="text-muted"> · {{ row.account.name }}</span></span>
            <StatusPill v-if="row.status === 'void'" tone="neutral" size="sm" :label="row.status_label" />
            <span class="text-sm font-semibold tabular-nums"><MoneyText :value="row.amount" :currency="row.currency" sign="always" colored decimals="never" /></span>
            <UiButton v-if="undoable(row)" size="sm" variant="ghost" :icon="RotateCcw" @click="undo(row)">{{ t("common.undo") }}</UiButton>
          </li>
        </ul>
      </section>
    </div>

    <LoanPayDialog v-if="loan && paying" v-model:open="payOpen" :loan="loan" :line="paying" />
    <LoanEarlyDialog v-if="loan && earlyOpen" v-model:open="earlyOpen" :loan="loan" />
    <LoanFormDialog v-if="loan && editOpen" v-model:open="editOpen" :loan="loan" :rows="typedRows" />
  </div>
</template>
