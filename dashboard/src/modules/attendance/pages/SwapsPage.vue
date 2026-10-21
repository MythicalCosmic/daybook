<script setup lang="ts">
/**
 * Swaps and open shifts (plan §6.2 "Swaps and corrections inbox"): covers, swaps and open-shift
 * claims a colleague already agreed to wait for a decision here (also in "Needs you"); requests
 * still waiting for a colleague and the decided history are a tab away. Decisions leave the list at
 * once and come back if the server refuses.
 */
import { ArrowLeftRight, CalendarCheck2, Hand, History, Inbox, Repeat2, UserRoundCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useSwapDecision, useSwaps } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import type { Shift, Swap, SwapStatus } from "../types";

const { t } = useI18n();
const fmt = useFormat();

type Tab = "waiting" | "asked" | "history";
const tab = useRouteState<Tab>("tab", rs.enum(["waiting", "asked", "history"] as const, "waiting"));
const status = computed(() => (tab.value === "waiting" ? "accepted" : tab.value === "asked" ? "requested" : "all"));
const query = useSwaps(status);
const waiting = useSwaps("accepted");
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const decide = useSwapDecision();

const CLOSED: SwapStatus[] = ["approved", "rejected", "cancelled", "expired"];
const rows = computed(() => {
  const list = query.data.value?.results ?? [];
  return tab.value === "history" ? list.filter((swap) => CLOSED.includes(swap.status)) : list;
});

const tabs = computed(() => [
  { value: "waiting" as const, label: t("attendance.swaps.waiting"), icon: Inbox, count: waiting.data.value?.count || undefined },
  { value: "asked" as const, label: t("attendance.swaps.asked"), icon: Hand },
  { value: "history" as const, label: t("attendance.swaps.history"), icon: History },
]);

const STATUS_TONES: Record<SwapStatus, StatusTone> = {
  requested: "info",
  accepted: "warning",
  approved: "success",
  rejected: "danger",
  cancelled: "neutral",
  expired: "neutral",
};

function title(swap: Swap): string {
  const asker = swap.requested_by.name;
  const taker = swap.accepted_by?.name ?? swap.target?.name ?? "";
  if (swap.kind === "claim") return t("attendance.swaps.claimTitle", { name: asker });
  if (swap.kind === "swap") return t("attendance.swaps.swapTitle", { a: asker, b: taker });
  if (!taker) return t("attendance.swaps.coverAnyone", { name: asker });
  return t("attendance.swaps.coverTitle", { a: asker, b: taker });
}

function shiftLine(shift: Shift): string {
  return [fmt.day(shift.date, "weekdayShort"), `${shift.start}–${shift.end}`, shift.branch?.name].filter(Boolean).join(" · ");
}

function waitingFor(swap: Swap): string {
  if (swap.target) return t("attendance.swaps.waitingFor", { name: swap.target.name });
  return t("attendance.swaps.offeredToAll");
}

async function run(swap: Swap, approve: boolean, reason = ""): Promise<void> {
  await decide.mutateAsync({ swap, approve, reason });
  toast.success(approve ? t("attendance.swaps.approved") : t("attendance.swaps.rejected"));
}

const kindIcon = (swap: Swap) => (swap.kind === "claim" ? Hand : swap.kind === "swap" ? ArrowLeftRight : UserRoundCheck);
</script>

<template>
  <div class="flex flex-col gap-5">
    <AttendanceHeader :title="t('attendance.swaps.title')" :description="t('attendance.swaps.description')" />

    <SegmentedControl v-model="tab" :options="tabs" class="self-start" />

    <div v-if="skeleton" class="flex flex-col gap-3">
      <SkeletonBlock v-for="n in 3" :key="n" height="104px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState
      v-else-if="!rows.length"
      :icon="tab === 'history' ? History : tab === 'asked' ? Repeat2 : CalendarCheck2"
      :tone="tab === 'waiting' ? 'success' : 'neutral'"
      :title="t(`attendance.swaps.empty.${tab}`)"
      :description="t(`attendance.swaps.emptyBody.${tab}`)"
    />
    <TransitionGroup v-else tag="ul" name="att-list" class="flex flex-col gap-3">
      <li v-for="swap in rows" :key="swap.id" class="ui-card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <span class="grid size-10 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg" aria-hidden="true">
          <component :is="kindIcon(swap)" :size="18" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <p class="text-sm font-semibold text-fg">{{ title(swap) }}</p>
            <StatusPill size="sm" :tone="STATUS_TONES[swap.status]" :label="tab === 'asked' ? waitingFor(swap) : t(`attendance.swapStatus.${swap.status}`)" />
          </div>
          <p class="mt-1 text-sm tabular-nums text-muted">
            {{ shiftLine(swap.shift) }}<template v-if="swap.other_shift"> <ArrowLeftRight :size="12" class="mx-1 inline" /> {{ shiftLine(swap.other_shift) }}</template>
          </p>
          <p v-if="swap.note" class="mt-1.5 text-sm text-fg">“{{ swap.note }}”</p>
          <p v-if="swap.decision_note && tab === 'history'" class="mt-1 text-xs text-muted">{{ swap.decision_note }}</p>
          <p class="mt-1.5 text-xs text-subtle">
            <RelativeTime :value="swap.created_at" />
            <template v-if="swap.status === 'accepted' || swap.status === 'requested'"> · {{ t("attendance.swaps.lapses") }} <RelativeTime :value="swap.expires_at" /></template>
          </p>
        </div>
        <ApproveRejectButtons
          v-if="tab === 'waiting'"
          class="shrink-0"
          :on-approve="() => run(swap, true)"
          :on-reject="(reason) => run(swap, false, reason)"
          :reject-title="t('attendance.swaps.rejectTitle')"
        />
      </li>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.att-list-move,
.att-list-leave-active {
  transition:
    transform 240ms var(--ease-out),
    opacity 180ms var(--ease-out);
}
.att-list-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>
