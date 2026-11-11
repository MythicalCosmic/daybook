<script setup lang="ts">
/**
 * Loans (v12): what the company owes on its loans, what is due in the next 30 days and what is
 * late, then a card per loan: the lender, what is still owed and how much is repaid, the next
 * payment, the rate and how it is repaid. A loan given to someone shows the same way, marked.
 * "Record a loan" opens the form with its live schedule; a card opens the loan.
 */
import { AlertTriangle, ArrowUpRight, CalendarClock, CircleCheck, HandCoins, Landmark, Plus, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { isZero } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import LoanFormDialog from "../components/loans/LoanFormDialog.vue";
import { repaidShare, useLoans, type Loan } from "../credit";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const canRecord = computed(() => company.can("finance.record"));

const query = useLoans();
const data = computed(() => query.data.value ?? null);
const open = computed(() => (data.value?.loans ?? []).filter((loan) => loan.status === "open"));
const closed = computed(() => (data.value?.loans ?? []).filter((loan) => loan.status !== "open"));
const showClosed = ref(false);

const kpis = computed(() => {
  const d = data.value;
  const late = !!d && !isZero(d.overdue);
  return [
    { id: "owed", label: t("finance.loans.kpi.owed"), value: d?.owed ?? null, format: "money" as const, compact: true, icon: Landmark },
    { id: "due", label: t("finance.loans.kpi.due30"), value: d?.due_30 ?? null, format: "money" as const, compact: true, icon: CalendarClock },
    { id: "overdue", label: t("finance.loans.kpi.overdue"), value: d?.overdue ?? null, format: "money" as const, compact: true, icon: AlertTriangle, hint: late ? t("finance.loans.kpi.overdueHint") : undefined },
    { id: "ours", label: t("finance.loans.kpi.ours"), value: d?.owed_to_us ?? null, format: "money" as const, compact: true, icon: HandCoins },
  ];
});

const formOpen = ref(false);
function saved(id: number): void {
  void router.push(`/c/${cid.value}/finance/loans/${id}`);
}

function nextLine(loan: Loan): string {
  if (!loan.next) return t("finance.loans.allPaid");
  const when = fmt.day(loan.next.due_on, "medium");
  return loan.next.status === "overdue" ? t("finance.loans.nextLate", { date: when }) : t("finance.loans.nextOn", { date: when });
}
const terms = (loan: Loan) => [fmt.percent(Number(loan.annual_rate), 2), loan.method_label, t("finance.loans.months", { n: loan.payments }, loan.payments)].join(" · ");
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.loans')" :description="t('finance.loans.description')">
      <template #actions>
        <UiButton v-if="canRecord" variant="primary" :icon="Plus" data-new-loan @click="formOpen = true">{{ t("finance.loans.new") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="grid" />

      <div v-if="query.isPending.value" class="grid gap-3 lg:grid-cols-2">
        <SkeletonBlock v-for="n in 2" :key="n" height="188px" radius="14px" />
      </div>
      <div v-else-if="data && !data.loans.length" class="ui-card">
        <EmptyState :icon="Landmark" :title="t('finance.loans.emptyTitle')" :description="t('finance.loans.emptyBody')">
          <UiButton v-if="canRecord" variant="primary" :icon="Plus" @click="formOpen = true">{{ t("finance.loans.new") }}</UiButton>
        </EmptyState>
      </div>

      <div v-if="open.length" class="grid gap-3 lg:grid-cols-2" data-loans>
        <RouterLink
          v-for="loan in open"
          :key="loan.id"
          :to="`/c/${cid}/finance/loans/${loan.id}`"
          :class="['ui-card group flex flex-col gap-4 p-4 transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2', loan.overdue_count && 'ring-1 ring-danger/40']"
          :data-loan="loan.id"
        >
          <header class="flex items-start gap-3">
            <UserAvatar :name="loan.counterparty.name" :size="40" shape="rounded" />
            <div class="min-w-0 flex-1">
              <p class="flex items-center gap-1 text-base font-semibold text-fg">
                <span class="truncate">{{ loan.counterparty.name }}</span>
                <ArrowUpRight :size="14" class="shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
              </p>
              <p class="truncate text-xs text-muted" :title="loan.description || loan.direction_label">{{ loan.description || terms(loan) }}</p>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-1">
              <StatusPill v-if="loan.overdue_count" tone="danger" size="sm" :icon="AlertTriangle" :label="t('finance.loans.lateCount', { n: loan.overdue_count }, loan.overdue_count)" />
              <StatusPill v-if="loan.direction === 'receivable'" tone="info" size="sm" variant="outline" :label="loan.direction_label" />
            </div>
          </header>

          <div class="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
            <div>
              <p class="text-xs text-muted">{{ loan.direction === "payable" ? t("finance.loans.stillOwe") : t("finance.loans.stillOwed") }}</p>
              <p class="text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="loan.owed" :currency="loan.currency" decimals="never" /></p>
            </div>
            <p class="text-xs tabular-nums text-muted">{{ t("finance.loans.ofAmount", { amount: fmt.money(loan.amount, loan.currency, { compact: true }) }) }}</p>
          </div>
          <ProgressBar :value="repaidShare(loan)" :max="100" tone="success" :label="t('finance.loans.repaid')" :value-text="fmt.percent(repaidShare(loan))" />

          <footer class="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-3 text-sm">
            <span :class="['inline-flex items-center gap-1.5', loan.next?.status === 'overdue' ? 'font-semibold text-danger' : 'text-fg']">
              <component :is="loan.next ? CalendarClock : CircleCheck" :size="14" aria-hidden="true" />
              {{ nextLine(loan) }}
            </span>
            <span v-if="loan.next" class="font-semibold tabular-nums text-fg"><MoneyText :value="loan.next.rest" :currency="loan.currency" decimals="never" /></span>
            <span class="flex-1" />
            <span class="text-xs text-subtle">{{ terms(loan) }}</span>
          </footer>
        </RouterLink>
      </div>

      <section v-if="closed.length" class="flex flex-col gap-2">
        <button type="button" class="inline-flex w-fit items-center gap-1.5 text-sm font-semibold text-muted hover:text-fg" :aria-expanded="showClosed" @click="showClosed = !showClosed">
          <Wallet :size="14" aria-hidden="true" />{{ t("finance.loans.closed", { n: closed.length }, closed.length) }}
        </button>
        <ul v-if="showClosed" class="ui-card flex flex-col divide-y divide-line">
          <li v-for="loan in closed" :key="loan.id">
            <RouterLink :to="`/c/${cid}/finance/loans/${loan.id}`" class="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2">
              <UserAvatar :name="loan.counterparty.name" :size="28" shape="rounded" />
              <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ loan.counterparty.name }}</span>
              <span class="text-sm tabular-nums text-muted"><MoneyText :value="loan.amount" :currency="loan.currency" decimals="never" /></span>
              <StatusPill tone="success" size="sm" :label="t(`finance.debtStatus.${loan.status}`)" />
            </RouterLink>
          </li>
        </ul>
      </section>
    </div>

    <LoanFormDialog v-if="formOpen" v-model:open="formOpen" @saved="saved" />
  </div>
</template>
