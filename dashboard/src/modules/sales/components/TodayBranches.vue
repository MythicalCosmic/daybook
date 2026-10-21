<script setup lang="ts">
/**
 * Today, live, per branch (`GET sales/today/`): opened at and by whom (or "not opened +12 min"),
 * the tills open right now with their cashier, sales so far, cash in the branch against its limit,
 * this month's pacing and the alerts (a difference, a handover in transit). A card opens the
 * branch's shifts of today.
 */
import { AlertTriangle, ArrowRight, HandCoins, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MoneyText from "@/components/MoneyText.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { dec, percent } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useOptions, useToday } from "../api";
import type { BranchTodaySales } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = useToday();
const options = useOptions();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const branches = computed(() => query.data.value?.branches ?? []);
/** Tills open and nothing closed yet in shift-totals mode: today's sales come with the Z-reports. */
function awaitingTotals(branch: BranchTodaySales): boolean {
  return options.data.value?.settings.mode === "shift_totals" && branch.open_tills.length > 0 && branch.receipts === 0 && dec(branch.net).isZero();
}

const TONES: Record<BranchTodaySales["status"], StatusTone> = { open: "success", not_opened: "danger", closed: "neutral", day_off: "info" };

function status(branch: BranchTodaySales): string {
  if (branch.status === "open" && branch.opened_at) {
    return t("sales.today.openedBy", { time: fmt.instant(branch.opened_at, "time"), name: branch.opened_by?.name.split(" ")[0] ?? "" });
  }
  return t(`sales.today.status.${branch.status}`);
}
function limitUse(branch: BranchTodaySales): number | null {
  return branch.cash_limit ? percent(branch.cash_in_branch, branch.cash_limit, 0) : null;
}
const link = (branch: BranchTodaySales) => ({ path: `/c/${company.currentId}/sales/shifts`, query: { branch: String(branch.id), from: undefined } });
</script>

<template>
  <div>
    <div v-if="skeleton" class="grid gap-3 md:grid-cols-2">
      <!-- Shaped like a loaded card (name, status, till, cash and month bars) so nothing jumps. -->
      <div v-for="n in 2" :key="n" class="ui-card flex flex-col gap-3 p-4">
        <SkeletonBlock width="40%" height="16px" />
        <SkeletonBlock width="55%" height="22px" radius="999px" />
        <SkeletonBlock height="50px" radius="10px" />
        <div class="mt-1 grid grid-cols-2 gap-4 border-t border-line pt-3">
          <SkeletonBlock height="38px" />
          <SkeletonBlock height="38px" />
        </div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !branches.length" class="ui-card">
      <EmptyState size="sm" tone="neutral" :icon="Store" :title="t('sales.today.empty')" :description="t('sales.today.emptyBody')" />
    </div>
    <ul v-else class="grid gap-3 md:grid-cols-2">
      <li
        v-for="branch in branches"
        :key="branch.id"
        :class="[
          'ui-card flex min-w-0 flex-col gap-3 p-4 transition-colors',
          branch.status === 'not_opened' && 'border-[color-mix(in_srgb,var(--c-danger)_35%,var(--c-border))] bg-danger-soft/30',
        ]"
      >
        <div class="flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex min-w-0 items-center gap-2">
              <h3 class="truncate text-base font-semibold text-fg">{{ branch.name }}</h3>
              <span v-if="branch.code" class="shrink-0 rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] font-semibold tracking-wide text-muted">{{ branch.code }}</span>
            </div>
            <StatusPill class="mt-1.5" size="sm" :tone="TONES[branch.status]" :live="branch.status === 'not_opened' || branch.open_tills.length > 0" :label="status(branch)" />
          </div>
          <div class="text-right">
            <p class="text-[11px] font-medium uppercase tracking-wide text-subtle">{{ t("sales.today.soFar") }}</p>
            <template v-if="awaitingTotals(branch)">
              <p class="text-lg font-semibold text-subtle" data-testid="today-awaiting">—</p>
              <p class="text-xs text-muted">{{ t("sales.shift.movedOutHint") }}</p>
            </template>
            <template v-else>
              <p class="text-lg font-semibold tabular-nums text-fg"><MoneyText :value="branch.net" compact /></p>
              <p class="text-xs text-muted">{{ t("sales.today.receipts", { n: branch.receipts }, branch.receipts) }}</p>
            </template>
          </div>
        </div>

        <ul v-if="branch.open_tills.length" class="flex flex-col gap-1.5">
          <li v-for="till in branch.open_tills" :key="till.shift.id">
            <RouterLink
              :to="{ path: `/c/${company.currentId}/sales/shifts`, query: { shift: String(till.shift.id) } }"
              class="flex items-center gap-2.5 rounded-[10px] bg-surface-2/70 px-2.5 py-2 transition-colors hover:bg-highlight"
            >
              <UserAvatar :name="till.cashier.name" :size="28" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium text-fg">{{ till.cashier.name }}</span>
                <span class="block truncate text-xs text-muted">{{ till.register.name }} · {{ till.shift.code }} · {{ t("sales.today.since", { time: fmt.instant(till.shift.since, "time") }) }}</span>
              </span>
              <ArrowRight :size="14" class="shrink-0 text-subtle" />
            </RouterLink>
          </li>
        </ul>

        <div class="grid grid-cols-2 gap-3 border-t border-line pt-3">
          <div class="min-w-0" role="group" :aria-label="t('sales.today.cash')">
            <p class="flex items-baseline justify-between gap-2 text-[11px] text-muted">
              <span class="truncate">{{ t("sales.today.cash") }}</span>
              <span v-if="branch.cash_limit" class="shrink-0 tabular-nums text-subtle">{{ t("sales.today.limit", { amount: fmt.money(branch.cash_limit, undefined, { compact: true }) }) }}</span>
            </p>
            <p class="truncate text-sm font-semibold text-fg"><MoneyText :value="branch.cash_in_branch" compact /></p>
            <ProgressBar v-if="limitUse(branch) !== null" class="mt-2" size="xs" :value="Math.min(limitUse(branch)!, 100)" :tone="limitUse(branch)! >= 100 ? 'danger' : limitUse(branch)! >= 80 ? 'warning' : 'primary'" />
          </div>
          <div v-if="branch.target" class="min-w-0" role="group" :aria-label="t('sales.today.pace')">
            <p class="truncate text-[11px] text-muted">{{ t("sales.today.month", { percent: fmt.percent(Number(branch.target.percent), 1) }) }}</p>
            <p class="truncate text-sm font-semibold text-fg"><MoneyText :value="branch.target.actual" compact /> <span class="font-normal text-subtle">/ <MoneyText :value="branch.target.amount" compact /></span></p>
            <ProgressBar class="mt-2" size="xs" :value="Number(branch.target.percent)" :target="(branch.target.elapsed / branch.target.days) * 100" :tone="branch.target.ahead ? 'success' : 'warning'" />
          </div>
          <div v-else class="min-w-0">
            <p class="text-[11px] text-muted">{{ t("sales.today.tills") }}</p>
            <p class="text-sm font-semibold tabular-nums text-fg">{{ branch.open_tills.length }}<span class="font-normal text-subtle"> / {{ branch.tills }}</span></p>
          </div>
        </div>

        <ul v-if="branch.alerts.filter((a) => a.kind !== 'not_opened').length" class="flex flex-col gap-1">
          <li v-for="(alert, index) in branch.alerts.filter((a) => a.kind !== 'not_opened')" :key="index" class="flex items-center gap-2 text-xs">
            <component :is="alert.kind === 'in_transit' ? HandCoins : AlertTriangle" :size="13" :class="alert.severity === 'critical' ? 'text-danger' : 'text-warning'" aria-hidden="true" />
            <span class="text-muted">
              <template v-if="alert.kind === 'difference'">{{ t("sales.today.alert.difference", { code: alert.shift?.code ?? "", amount: fmt.money(alert.amount) }) }}</template>
              <template v-else-if="alert.kind === 'in_transit'">{{ t("sales.today.alert.transit", { n: alert.count ?? 0, amount: fmt.money(alert.amount) }, alert.count ?? 0) }}</template>
              <template v-else>{{ t("sales.today.alert.limit") }}</template>
            </span>
          </li>
        </ul>
        <RouterLink :to="link(branch)" class="sr-only">{{ t("sales.today.open", { name: branch.name }) }}</RouterLink>
      </li>
    </ul>
  </div>
</template>
