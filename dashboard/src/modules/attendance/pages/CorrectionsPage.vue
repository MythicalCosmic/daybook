<script setup lang="ts">
/**
 * Corrections and overtime (plan §6.2 "Swaps and corrections inbox"): "I forgot to check in"
 * requests with the times asked for next to what was recorded, and worked time beyond the shift
 * waiting for approval. Both decisions are audited; rejecting needs a reason the person will see.
 */
import { ArrowRight, ClipboardCheck, History, Timer } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useCorrectionDecision, useCorrections, useOvertimeDecision, useRecords } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import RecordDrawer from "../components/RecordDrawer.vue";
import { clockOf } from "../lib";
import type { Correction, RecordRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();

type Tab = "corrections" | "overtime" | "history";
const tab = useRouteState<Tab>("tab", rs.enum(["corrections", "overtime", "history"] as const, "corrections"));
const recordId = useRouteState("record", rs.optionalNumber(), { push: true });

const pending = useCorrections("pending");
const decided = useCorrections("all", () => tab.value === "history");
const overtime = useRecords({ overtime: "pending", page_size: 100, ordering: "-date" });
const decideCorrection = useCorrectionDecision();
const decideOvertime = useOvertimeDecision();

const loading = computed(() => (tab.value === "overtime" ? overtime.isPending.value : tab.value === "history" ? decided.isPending.value : pending.isPending.value));
const skeleton = useDelayedPending(loading);
const failed = computed(() => (tab.value === "overtime" ? overtime : tab.value === "history" ? decided : pending));
const history = computed(() => (decided.data.value?.results ?? []).filter((row) => row.status !== "pending"));

const tabs = computed(() => [
  { value: "corrections" as const, label: t("attendance.corrections.tab"), icon: ClipboardCheck, count: pending.data.value?.count || undefined },
  { value: "overtime" as const, label: t("attendance.corrections.overtimeTab"), icon: Timer, count: overtime.data.value?.count || undefined },
  { value: "history" as const, label: t("attendance.corrections.historyTab"), icon: History },
]);

function recorded(correction: Correction): string {
  const record = correction.record;
  if (!record || !record.check_in_at) return t("attendance.corrections.nothingRecorded");
  const out = record.check_out_at ? clockOf(record.check_out_at) : "—";
  const note = record.status === "auto_closed" ? ` (${t("attendance.status.auto_closed").toLowerCase()})` : "";
  return t("attendance.corrections.recordedTimes", { in: clockOf(record.check_in_at), out }) + note;
}

function asked(correction: Correction): string {
  const parts = [];
  if (correction.check_in_at) parts.push(t("attendance.corrections.came", { time: clockOf(correction.check_in_at) }));
  if (correction.check_out_at) parts.push(t("attendance.corrections.left", { time: clockOf(correction.check_out_at) }));
  return parts.join(" · ");
}

async function runCorrection(correction: Correction, approve: boolean, reason = ""): Promise<void> {
  await decideCorrection.mutateAsync({ correction, approve, reason });
  toast.success(approve ? t("attendance.corrections.approved") : t("attendance.corrections.rejected"));
}

async function runOvertime(record: RecordRow, approve: boolean, reason = ""): Promise<void> {
  await decideOvertime.mutateAsync({ record, approve, reason });
  toast.success(approve ? t("attendance.overtime.approvedToast") : t("attendance.overtime.rejectedToast"));
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <AttendanceHeader :title="t('attendance.corrections.title')" :description="t('attendance.corrections.description')" />

    <SegmentedControl v-model="tab" :options="tabs" class="self-start" />

    <div v-if="skeleton" class="flex flex-col gap-3">
      <SkeletonBlock v-for="n in 3" :key="n" height="112px" radius="12px" />
    </div>
    <ErrorState v-else-if="failed.isError.value" :error="failed.error.value" :retry="() => failed.refetch()" />

    <template v-else-if="tab === 'corrections'">
      <EmptyState v-if="!pending.data.value?.results.length" tone="success" :icon="ClipboardCheck" :title="t('attendance.corrections.emptyTitle')" :description="t('attendance.corrections.emptyBody')" />
      <TransitionGroup v-else tag="ul" name="att-list" class="flex flex-col gap-3">
        <li v-for="correction in pending.data.value!.results" :key="correction.id" class="ui-card flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
          <div class="flex min-w-0 flex-1 gap-3">
            <UserAvatar :name="correction.member.name" :src="correction.member.photo_url" :size="40" />
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-fg">{{ correction.member.name }} <span class="font-normal text-muted">· {{ fmt.day(correction.date, "weekday") }}</span></p>
              <div class="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                <span class="rounded-[6px] bg-surface-2 px-2 py-0.5 text-muted line-through decoration-subtle/60" :title="t('attendance.corrections.wasRecorded')">{{ recorded(correction) }}</span>
                <ArrowRight :size="14" class="text-subtle" aria-hidden="true" />
                <span class="rounded-[6px] bg-accent-soft px-2 py-0.5 font-medium tabular-nums text-accent-fg">{{ asked(correction) }}</span>
              </div>
              <p class="mt-1.5 text-sm text-fg">“{{ correction.reason }}”</p>
              <p class="mt-1 text-xs text-subtle"><RelativeTime :value="correction.created_at" /></p>
            </div>
          </div>
          <ApproveRejectButtons class="shrink-0" :on-approve="() => runCorrection(correction, true)" :on-reject="(reason) => runCorrection(correction, false, reason)" :reject-title="t('attendance.corrections.rejectTitle', { name: correction.member.name })" />
        </li>
      </TransitionGroup>
    </template>

    <template v-else-if="tab === 'overtime'">
      <EmptyState v-if="!overtime.data.value?.results.length" tone="success" :icon="Timer" :title="t('attendance.overtime.emptyTitle')" :description="t('attendance.overtime.emptyBody')" />
      <TransitionGroup v-else tag="ul" name="att-list" class="flex flex-col gap-3">
        <li v-for="record in overtime.data.value!.results" :key="record.id" class="ui-card flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
          <button type="button" class="flex min-w-0 flex-1 gap-3 text-left" @click="recordId = record.id">
            <UserAvatar :name="record.member.name" :src="record.member.photo_url" :size="40" />
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-fg">{{ record.member.name }} <span class="font-normal text-muted">· {{ fmt.day(record.date, "weekday") }}</span></p>
              <p class="mt-1 text-sm tabular-nums text-muted">
                <template v-if="record.shift">{{ t("attendance.overtime.shift", { start: record.shift.start, end: record.shift.end }) }} · </template>{{ t("attendance.overtime.actual", { start: clockOf(record.check_in_at), end: clockOf(record.check_out_at) }) }}
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <StatusPill tone="warning" :label="t('attendance.overtime.extra', { d: fmt.duration(record.overtime_minutes) })" />
                <span class="text-xs text-muted">{{ t("attendance.overtime.worked", { d: fmt.duration(record.worked_minutes) }) }}</span>
              </div>
            </div>
          </button>
          <ApproveRejectButtons class="shrink-0" :on-approve="() => runOvertime(record, true)" :on-reject="(reason) => runOvertime(record, false, reason)" :reject-title="t('attendance.overtime.rejectTitle')" />
        </li>
      </TransitionGroup>
    </template>

    <template v-else>
      <EmptyState v-if="!history.length" tone="neutral" :icon="History" :title="t('attendance.corrections.historyEmpty')" />
      <ul v-else class="ui-card divide-y divide-line">
        <li v-for="correction in history" :key="correction.id" class="flex flex-wrap items-center gap-3 px-4 py-3">
          <UserAvatar :name="correction.member.name" :src="correction.member.photo_url" :size="30" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm text-fg"><span class="font-semibold">{{ correction.member.name }}</span> · {{ fmt.day(correction.date, "short") }} · {{ asked(correction) }}</p>
            <p class="truncate text-xs text-muted">{{ correction.decision_note || correction.reason }}</p>
          </div>
          <StatusPill size="sm" :tone="correction.status === 'approved' ? 'success' : 'danger'" :label="t(`attendance.correctionStatus.${correction.status}`)" />
        </li>
      </ul>
    </template>

    <RecordDrawer />
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
