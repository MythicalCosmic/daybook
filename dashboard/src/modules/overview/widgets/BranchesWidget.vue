<script setup lang="ts">
/**
 * Overview widget "Branches today" (plan §6.2, `GET branches/today/`): one card per branch the
 * person may see, with its status ("Opened 08:57 by Dilnoza", "Not opened · +12 min") and the facts
 * other modules provide (staff in, open tills, sales so far, cash, tasks). A fact is absent when its
 * module is off or the person may not see it.
 */
import { Clock3, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { BranchToday, Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MoneyText from "@/components/MoneyText.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import { zonedNow } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { minutesLate, useBranchesToday } from "../api";

defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const now = useNow();
const query = useBranchesToday();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const branches = computed(() => query.data.value ?? []);
const openCount = computed(() => branches.value.filter((branch) => branch.status === "open").length);

const TONES: Record<BranchToday["status"], StatusTone> = { open: "success", not_opened: "danger", closed: "neutral", day_off: "info" };

function statusLabel(branch: BranchToday): string {
  if (branch.status === "open") {
    const opened = branch.sales?.opened_at ?? branch.attendance?.first_check_in ?? null;
    if (!opened) return t("overview.branches.status.open");
    const time = fmt.instant(opened, "time");
    const by = branch.sales?.opened_at ? branch.sales.opened_by?.name : null;
    return by ? t("overview.branches.status.openedBy", { time, name: by.split(" ")[0] }) : t("overview.branches.status.openedAt", { time });
  }
  if (branch.status === "not_opened") {
    const late = minutesLate(branch.opens_at, zonedNow(company.timezone, now.value));
    // "6h 41m late", not "+401 min".
    return late > 0 ? t("overview.branches.status.late", { late: fmt.duration(late) }) : t("overview.branches.status.not_opened");
  }
  return t(`overview.branches.status.${branch.status}`);
}

function hours(branch: BranchToday): string | null {
  if (!branch.opens_at && !branch.closes_at) return null;
  return t("overview.branches.hours", { from: branch.opens_at ?? "—", to: branch.closes_at ?? "—" });
}

function hasFacts(branch: BranchToday): boolean {
  return !!(branch.sales || branch.attendance || branch.finance || branch.tasks);
}
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('overview.branches.title')">
    <header class="flex min-h-[44px] items-center gap-2 px-4 pb-1 pt-4">
      <Store :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("overview.branches.title") }}</h3>
      <span v-if="branches.length" class="text-xs font-medium text-subtle">{{ t("overview.branches.openOf", { n: openCount, total: branches.length }) }}</span>
    </header>
    <div class="min-h-0 flex-1 p-3 pt-2">
      <div v-if="skeleton" class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] gap-3">
        <div v-for="n in 3" :key="n" class="flex flex-col gap-3 rounded-[12px] border border-line p-3.5">
          <SkeletonBlock width="45%" />
          <SkeletonBlock width="60%" height="20px" radius="999px" />
          <SkeletonBlock height="34px" radius="8px" />
        </div>
      </div>
      <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
      <EmptyState v-else-if="query.data.value && !branches.length" size="sm" tone="neutral" :icon="Store" :title="t('overview.branches.empty')" :description="t('overview.branches.emptyBody')" />
      <ul v-else class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] gap-3">
        <li
          v-for="branch in branches"
          :key="branch.id"
          :class="[
            // A lone branch doesn't stretch its three numbers across the whole page.
            'flex min-w-0 max-w-[40rem] flex-col rounded-[12px] border p-3.5 transition-colors',
            branch.status === 'not_opened' ? 'border-[color-mix(in_srgb,var(--c-danger)_35%,var(--c-border))] bg-danger-soft/40' : 'border-line bg-surface hover:border-line-strong',
          ]"
        >
          <div class="flex items-start gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex min-w-0 items-center gap-2">
                <h4 class="truncate text-base font-semibold text-fg">{{ branch.name }}</h4>
                <span v-if="branch.code" class="shrink-0 rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] font-semibold tracking-wide text-muted">{{ branch.code }}</span>
              </div>
              <StatusPill class="mt-2" size="sm" :tone="TONES[branch.status]" :live="branch.status === 'not_opened'" :label="statusLabel(branch)" />
            </div>
            <ProgressRing
              v-if="branch.tasks && branch.tasks.total > 0"
              :value="branch.tasks.done"
              :max="branch.tasks.total"
              :size="44"
              tone="auto"
              show-value
              :label="t('overview.branches.tasks')"
            />
          </div>
          <p v-if="hours(branch)" class="mt-2.5 flex items-center gap-1.5 text-xs text-muted">
            <Clock3 :size="12" aria-hidden="true" />{{ hours(branch) }}
            <template v-if="branch.tasks?.late"> · <span class="font-medium text-danger">{{ t("overview.branches.tasksLate", { n: branch.tasks.late }) }}</span></template>
          </p>
          <dl v-if="hasFacts(branch)" class="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3">
            <div v-if="branch.attendance" class="min-w-0">
              <dt class="truncate text-[11px] text-muted">{{ t("overview.branches.staff") }}</dt>
              <dd class="mt-0.5 text-sm font-semibold tabular-nums text-fg">{{ branch.attendance.checked_in }}<span class="font-normal text-subtle">/{{ branch.attendance.rostered }}</span></dd>
            </div>
            <div v-if="branch.sales" class="min-w-0">
              <dt class="truncate text-[11px] text-muted">{{ t("overview.branches.sales") }}</dt>
              <dd class="mt-0.5 truncate text-sm font-semibold text-fg"><MoneyText :value="branch.sales.net" compact /></dd>
            </div>
            <div v-if="branch.sales" class="min-w-0">
              <dt class="truncate text-[11px] text-muted">{{ t("overview.branches.tills") }}</dt>
              <dd class="mt-0.5 text-sm font-semibold tabular-nums text-fg">{{ branch.sales.open_tills }}</dd>
            </div>
            <div v-else-if="branch.finance" class="min-w-0">
              <dt class="truncate text-[11px] text-muted">{{ t("overview.branches.cash") }}</dt>
              <dd class="mt-0.5 truncate text-sm font-semibold text-fg"><MoneyText :value="branch.finance.cash" compact /></dd>
            </div>
          </dl>
          <p v-else class="mt-3 border-t border-line pt-3 text-xs text-subtle">{{ t("overview.branches.noFacts") }}</p>
        </li>
      </ul>
    </div>
  </section>
</template>
