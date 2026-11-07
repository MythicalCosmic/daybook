<script setup lang="ts">
/**
 * Pharmacist coverage (plan §14.9): "a qualified pharmacist whenever a pharmacy is open". A week
 * per pharmacy: its open hours each day, a bar of the hours covered and the gaps (red), the
 * pharmacists planned (and why one doesn't count, for hr.view), and "Fix in roster" to the
 * roster's week. Above it, any pharmacy open right now without a qualified pharmacist checked in.
 * Week and branch live in the URL (`?week=`, `?branch=`).
 */
import { CalendarRange, ChevronLeft, ChevronRight, CircleCheck, CircleX, PencilRuler, Settings2, ShieldAlert, ShieldCheck, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { addDays, formatRange, startOfWeek } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCoverage, useLiveCoverage } from "../api";
import { coverageTotals, daySegments, hoursOf, rosterLink, weekParams } from "../coverage";
import type { CoverageBranch, CoverageDay, CoverageShift } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const thisWeek = computed(() => startOfWeek(today.value));
const weekParam = useRouteState("week", rs.day());
const week = computed({
  get: () => startOfWeek(weekParam.value ?? thisWeek.value),
  set: (value: string) => (weekParam.value = value === thisWeek.value ? null : value),
});
const branch = useRouteState("branch", rs.optionalNumber());
const weekLabel = computed(() => formatRange({ from: week.value, to: addDays(week.value, 6) }, fmt.lang.value));

const query = useCoverage(() => weekParams(week.value, branch.value));
const live = useLiveCoverage();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const data = computed(() => query.data.value ?? null);
const totals = computed(() => coverageTotals(data.value?.branches ?? []));
const liveGaps = computed(() => (live.data.value?.gaps ?? []).filter((gap) => !branch.value || gap.branch.id === branch.value));
const canManage = computed(() => company.can("hr.manage"));
const canRoster = computed(() => company.can("attendance.view"));

function hoursLabel(row: CoverageBranch): string {
  if (row.open_24h) return t("hr.coverage.allDay");
  if (!row.opens_at) return t("hr.coverage.noHours");
  return `${row.opens_at}–${row.closes_at ?? "24:00"}`;
}

function dayHours(day: CoverageDay, row: CoverageBranch): string {
  if (day.closed) return t(`hr.coverage.closed.${day.closed}`);
  if (row.open_24h) return t("hr.coverage.allDay");
  return `${fmt.instant(day.opens!, "time")}–${fmt.instant(day.closes!, "time")}`;
}

const span = (start: string, end: string) => `${fmt.instant(start, "time")}–${fmt.instant(end, "time")}`;

function why(shift: CoverageShift): string {
  if (!shift.reason) return t("hr.coverage.notCounted");
  const kinds = shift.kinds.map((kind) => t(`hr.kind.${kind}`)).join(", ");
  return kinds ? `${t(`hr.coverage.reason.${shift.reason}`)}: ${kinds}` : t(`hr.coverage.reason.${shift.reason}`);
}

const SEGMENT_CLASS = { covered: "bg-success", gap: "bg-danger", short: "bg-warning" } as const;
</script>

<template>
  <div>
    <PageHeader :title="t('hr.coverage.title')" :description="t('hr.coverage.description')">
      <template #actions>
        <div class="flex items-center gap-1">
          <IconButton :icon="ChevronLeft" :label="t('hr.coverage.prevWeek')" size="lg" variant="secondary" @click="week = addDays(week, -7)" />
          <span class="min-w-40 text-center text-sm font-semibold tabular-nums text-fg">{{ weekLabel }}</span>
          <IconButton :icon="ChevronRight" :label="t('hr.coverage.nextWeek')" size="lg" variant="secondary" @click="week = addDays(week, 7)" />
        </div>
        <UiButton v-if="week !== thisWeek" variant="ghost" @click="week = thisWeek">{{ t("hr.coverage.thisWeek") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="liveGaps.length" class="mb-4 flex flex-col gap-2" data-live-gaps>
      <InlineAlert
        v-for="gap in liveGaps"
        :key="gap.branch.id"
        tone="danger"
        :icon="ShieldAlert"
        :title="t('hr.coverage.live.title', { branch: gap.branch.name })"
        :description="
          gap.checked_in.length
            ? t('hr.coverage.live.bodyWith', { time: fmt.instant(gap.since, 'time'), names: gap.checked_in.map((p) => p.name).join(', ') })
            : t('hr.coverage.live.body', { time: fmt.instant(gap.since, 'time') })
        "
      />
    </div>

    <ErrorState v-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="skeleton" class="flex flex-col gap-4">
      <SkeletonBlock v-for="n in 2" :key="n" height="220px" radius="12px" />
    </div>

    <div v-else-if="data && data.state === 'off'" class="ui-card">
      <EmptyState :icon="ShieldCheck" tone="neutral" :title="t('hr.coverage.off.title')" :description="t('hr.coverage.off.body')">
        <UiButton v-if="canManage" variant="secondary" :icon="Settings2" :to="`/c/${company.currentId}/settings/hr`">{{ t("hr.settings.open") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else-if="data && data.state === 'setup'" class="ui-card">
      <EmptyState :icon="ShieldCheck" :title="t('hr.coverage.setup.title')" :description="t('hr.coverage.setup.body')">
        <UiButton v-if="canManage" variant="primary" :icon="Settings2" :to="`/c/${company.currentId}/settings/hr`">{{ t("hr.coverage.setup.button") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else-if="data && data.state === 'no_roster'" class="ui-card">
      <EmptyState :icon="CalendarRange" tone="neutral" :title="t('hr.coverage.noRoster.title')" :description="t('hr.coverage.noRoster.body')" />
    </div>

    <template v-else-if="data">
      <div class="mb-3 flex flex-wrap items-center gap-3">
        <div class="w-full sm:w-64">
          <BranchPicker v-model="branch" :placeholder="t('hr.coverage.allPharmacies')" />
        </div>
        <p class="flex-1 text-sm text-muted" data-coverage-summary>
          <template v-if="!totals.branches">{{ t("hr.coverage.summaryNone") }}</template>
          <template v-else-if="totals.gaps">{{ t("hr.coverage.summaryGaps", { n: totals.gaps, h: hoursOf(totals.minutes) }, totals.gaps) }}</template>
          <template v-else>{{ t("hr.coverage.summaryCovered") }}</template>
        </p>
        <p class="flex items-center gap-3 text-xs text-muted" aria-hidden="true">
          <span class="inline-flex items-center gap-1.5"><span class="inline-block h-2 w-4 rounded-full bg-success" />{{ t("hr.coverage.legend.covered") }}</span>
          <span class="inline-flex items-center gap-1.5"><span class="inline-block h-2 w-4 rounded-full bg-danger" />{{ t("hr.coverage.legend.gap") }}</span>
          <span v-if="data.need > 1" class="inline-flex items-center gap-1.5"><span class="inline-block h-2 w-4 rounded-full bg-warning" />{{ t("hr.coverage.legend.short") }}</span>
        </p>
      </div>

      <div v-if="!data.branches.length" class="ui-card">
        <EmptyState :icon="Store" tone="neutral" :title="t('hr.coverage.noPharmacies.title')" :description="t('hr.coverage.noPharmacies.body')" />
      </div>

      <div class="flex flex-col gap-4">
        <section v-for="row in data.branches" :key="row.branch.id" class="ui-card overflow-hidden" :data-coverage-branch="row.branch.id">
          <header class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-3 md:px-5">
            <div class="min-w-0 flex-1">
              <h2 class="truncate text-md font-semibold text-fg">{{ row.branch.name }}</h2>
              <p class="text-xs text-muted">{{ hoursLabel(row) }}</p>
            </div>
            <StatusPill
              v-if="row.gaps.length"
              tone="danger"
              size="sm"
              :label="t('hr.coverage.branchGaps', { n: row.gaps.length, h: hoursOf(row.gap_minutes) }, row.gaps.length)"
            />
            <StatusPill v-else-if="row.days.some((day) => day.opens)" tone="success" size="sm" :label="t('hr.coverage.branchCovered')" />
            <UiButton v-if="canRoster" size="sm" variant="secondary" :icon="PencilRuler" :to="rosterLink(company.currentId!, row.branch.id, week)" data-fix-roster>
              {{ t("hr.coverage.fixInRoster") }}
            </UiButton>
          </header>
          <p v-if="!row.shifts && row.days.some((day) => day.opens)" class="border-b border-line bg-surface-2/60 px-4 py-2 text-xs text-muted md:px-5">
            {{ t("hr.coverage.noShifts") }}
          </p>
          <div class="grid grid-cols-1 divide-y divide-line md:grid-cols-7 md:divide-x md:divide-y-0">
            <div v-for="day in row.days" :key="day.date" :class="['flex min-w-0 flex-col gap-2 px-3 py-3', day.date === today && 'bg-highlight/40']" :data-day="day.date">
              <div class="flex items-baseline justify-between gap-2">
                <p :class="['text-sm font-semibold', day.date === today ? 'text-primary' : 'text-fg']">{{ fmt.day(day.date, "weekdayShort") }}</p>
                <p class="text-xs tabular-nums text-muted">{{ dayHours(day, row) }}</p>
              </div>
              <div v-if="day.opens" class="relative h-2.5 overflow-hidden rounded-full bg-surface-2" role="img" :aria-label="day.gaps.length ? t('hr.coverage.dayGaps', { n: day.gaps.length }, day.gaps.length) : t('hr.coverage.dayCovered')">
                <span
                  v-for="(segment, index) in daySegments(day)"
                  :key="index"
                  :class="['absolute inset-y-0', SEGMENT_CLASS[segment.tone]]"
                  :style="{ left: `${segment.from * 100}%`, width: `${(segment.to - segment.from) * 100}%` }"
                />
              </div>
              <ul v-if="day.gaps.length" class="flex flex-col gap-0.5" data-day-gaps>
                <li v-for="gap in day.gaps" :key="gap.start" class="text-xs font-semibold tabular-nums text-danger">
                  {{ span(gap.start, gap.end) }}<span v-if="gap.need > 1" class="font-normal"> · {{ t("hr.coverage.haveOfNeed", { have: gap.have, need: gap.need }) }}</span>
                </li>
              </ul>
              <ul v-if="day.shifts.length" class="flex flex-col gap-1">
                <li v-for="shift in day.shifts" :key="shift.shift_id" class="flex min-w-0 items-start gap-1.5 text-xs" :title="shift.counts ? undefined : why(shift)">
                  <CircleCheck v-if="shift.counts" :size="13" class="mt-px shrink-0 text-success" aria-hidden="true" />
                  <CircleX v-else :size="13" class="mt-px shrink-0 text-danger" aria-hidden="true" />
                  <span class="min-w-0">
                    <span :class="['block truncate font-medium', shift.counts ? 'text-fg' : 'text-muted line-through decoration-danger/50']">{{ shift.member.name }}</span>
                    <span class="block tabular-nums text-subtle">
                      {{ span(shift.start, shift.end) }}<template v-if="!shift.published"> · {{ t("hr.coverage.draft") }}</template>
                    </span>
                    <span v-if="!shift.counts" class="block text-danger">{{ why(shift) }}</span>
                  </span>
                </li>
              </ul>
              <p v-else-if="day.opens" class="text-xs text-subtle">{{ t("hr.coverage.nobodyPlanned") }}</p>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
