<script setup lang="ts">
/**
 * One person's attendance month: the Person 360 tab `attendance` (plan §6.1, C hosts it) and the
 * person drawer of the attendance pages. A calendar of coded days, the month's totals, the coming
 * shifts and the latest check-ins (each opens the record drawer).
 */
import "../attendance.css";

import { CalendarClock, ChevronLeft, ChevronRight, LogIn } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useMemberMonth } from "../api";
import { CELL_CLASSES, CELL_WITH_HOURS, clockOf, hours, monthStart, shiftMonth, weekdayIndex } from "../lib";
import type { Cell } from "../types";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const month = ref(todayIn(company.timezone).slice(0, 7));
const query = useMemberMonth(() => props.memberId, month);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const data = computed(() => query.data.value);
const recordId = useRouteState("record", rs.optionalNumber(), { push: true });

/** Leading blanks so the 1st lands on its weekday (Monday first). */
const blanks = computed(() => (data.value?.days[0] ? weekdayIndex(data.value.days[0]) : 0));
const kpis = computed(() => {
  const value = data.value;
  if (!value) return [];
  const totals = value.totals;
  const expected = Math.max(0, totals.scheduled_days - totals.leave_days);
  return [
    { id: "attended", label: t("attendance.person.attended"), value: totals.attended_days, hint: totals.has_schedule ? t("attendance.person.ofScheduled", { n: expected }) : undefined },
    { id: "late", label: t("attendance.person.late"), value: totals.late_arrivals, hint: totals.late_minutes ? fmt.duration(totals.late_minutes) : undefined },
    { id: "absent", label: t("attendance.person.absent"), value: totals.absent_days },
    { id: "hours", label: t("attendance.person.hours"), value: Math.round((totals.worked_minutes / 60) * 10) / 10, hint: totals.approved_overtime_minutes ? t("attendance.person.overtime", { d: fmt.duration(totals.approved_overtime_minutes) }) : undefined },
  ];
});

function cellTitle(day: string, cell: Cell): string {
  const parts = [fmt.day(day, "weekday"), t(`attendance.cell.${cell.code}.label`)];
  if (cell.minutes) parts.push(fmt.duration(cell.minutes));
  if (cell.late) parts.push(t("attendance.record.lateBy", { late: fmt.duration(cell.late) }));
  return parts.join(" · ");
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('common.date.prevMonth')" size="sm" @click="month = shiftMonth(month, -1)" />
        <h3 class="min-w-36 text-center text-base font-semibold text-fg">{{ fmt.day(monthStart(month), "monthYear") }}</h3>
        <IconButton :icon="ChevronRight" :label="t('common.date.nextMonth')" size="sm" @click="month = shiftMonth(month, 1)" />
      </div>
      <StatusPill v-if="data?.schedule" tone="primary" :icon="CalendarClock" :label="data.schedule.name" />
      <StatusPill v-else-if="data" tone="neutral" :label="t('attendance.person.noSchedule')" />
    </div>

    <div v-if="skeleton" class="flex flex-col gap-4">
      <SkeletonBlock height="74px" radius="12px" />
      <SkeletonBlock height="230px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <KpiStrip class="att-kpis" :items="kpis" :columns="4" />

      <section class="ui-card p-3" :aria-label="t('attendance.person.calendar')">
        <div class="grid grid-cols-7 gap-1 text-center">
          <span v-for="index in 7" :key="index" class="pb-1 text-[11px] font-medium uppercase tracking-wide text-subtle">{{ t(`common.weekday.min.${index - 1}`) }}</span>
          <span v-for="n in blanks" :key="`blank-${n}`" />
          <div
            v-for="day in data.days"
            :key="day"
            :class="[
              'flex aspect-[5/4] min-w-0 flex-col items-center justify-center rounded-[8px] text-xs',
              CELL_CLASSES[data.cells[day]?.code ?? 'off'],
              day === data.today && 'outline outline-2 outline-offset-1 outline-[var(--c-primary)]',
            ]"
            :title="data.cells[day] ? cellTitle(day, data.cells[day]) : ''"
          >
            <span class="font-semibold tabular-nums">{{ Number(day.slice(8)) }}</span>
            <span v-if="data.cells[day] && CELL_WITH_HOURS.has(data.cells[day].code)" class="text-[10px] tabular-nums opacity-80">{{ hours(data.cells[day].minutes) }}{{ t("attendance.unit.h") }}</span>
            <span v-else-if="data.cells[day] && data.cells[day].code !== 'off' && data.cells[day].code !== 'planned'" class="text-[10px] opacity-80">{{ t(`attendance.cell.${data.cells[day].code}.short`) }}</span>
          </div>
        </div>
      </section>

      <div class="grid gap-4 md:grid-cols-2">
        <section class="min-w-0">
          <h4 class="mb-2 text-sm font-semibold text-fg">{{ t("attendance.person.nextShifts") }}</h4>
          <ul v-if="data.next_shifts.length" class="flex flex-col divide-y divide-line rounded-[12px] border border-line">
            <li v-for="shift in data.next_shifts" :key="shift.id" class="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span class="text-fg">{{ fmt.day(shift.date, "weekdayShort") }}</span>
              <span class="tabular-nums text-muted">{{ shift.start }}–{{ shift.end }}<template v-if="shift.branch"> · {{ shift.branch.name }}</template></span>
            </li>
          </ul>
          <EmptyState v-else size="sm" tone="neutral" :icon="CalendarClock" :title="t('attendance.person.noShifts')" />
        </section>
        <section class="min-w-0">
          <h4 class="mb-2 text-sm font-semibold text-fg">{{ t("attendance.person.recent") }}</h4>
          <ul v-if="data.records.length" class="flex flex-col divide-y divide-line rounded-[12px] border border-line">
            <li v-for="record in data.records.slice(0, 6)" :key="record.id">
              <button type="button" class="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-highlight" @click="recordId = record.id">
                <span class="text-fg">{{ fmt.day(record.date, "weekdayShort") }}</span>
                <span v-if="record.check_in_at" :class="['inline-flex items-center gap-1 tabular-nums', record.is_late ? 'text-warning' : 'text-muted']">
                  <LogIn :size="12" aria-hidden="true" />{{ clockOf(record.check_in_at) }}<template v-if="record.check_out_at">–{{ clockOf(record.check_out_at) }}</template>
                </span>
                <span v-else class="text-danger">{{ t(`attendance.status.${record.status}`) }}</span>
              </button>
            </li>
          </ul>
          <EmptyState v-else size="sm" tone="neutral" :icon="LogIn" :title="t('attendance.person.noRecords')" />
        </section>
      </div>
    </template>
  </div>
</template>
