<script setup lang="ts">
/**
 * One employee's month at a glance (attendance's `members/{id}/`): days present, late arrivals with
 * their minutes, absences and hours worked, then the calendar, each day coloured by what happened
 * (on time, late, absent, leave, a day off) with the hours worked. A day is a button: the page
 * shows that day's scans next to it.
 */
import { CalendarClock, ChevronLeft, ChevronRight } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { CELL_CLASSES, CELL_WITH_HOURS, hoursOf, monthOf, shiftMonth, weekdayIndex } from "./team";
import { useMemberMonth, type CellCode, type MonthCell } from "./teamApi";

const props = defineProps<{ memberId: number }>();
const day = defineModel<string>("day", { required: true });

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();
const month = ref(monthOf(day.value));
watch(day, (value) => {
  if (monthOf(value) !== month.value) month.value = monthOf(value);
});

const query = useMemberMonth(() => props.memberId, month);
const data = computed(() => query.data.value);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const blanks = computed(() => (data.value?.days[0] ? weekdayIndex(data.value.days[0]) : 0));
const isFuture = (value: string) => value > today.value;

const stats = computed(() => {
  const totals = data.value?.totals;
  if (!totals) return [];
  // Expected so far: the month's working days up to today (the days still ahead are "planned"),
  // so "6 of 8" mid-month, not "6 of 20".
  const ahead = Object.values(data.value?.cells ?? {}).filter((cell) => cell.code === "planned").length;
  const expected = Math.max(0, totals.scheduled_days - totals.leave_days - ahead);
  return [
    { id: "present", label: t("davomat.employee.month.present"), value: fmt.number(totals.attended_days), hint: totals.has_schedule ? t("davomat.employee.month.ofExpected", { n: fmt.number(expected) }) : "", tone: "text-fg" },
    { id: "late", label: t("davomat.employee.month.late"), value: fmt.number(totals.late_arrivals), hint: totals.late_minutes ? fmt.duration(totals.late_minutes) : "", tone: totals.late_arrivals ? "text-warning" : "text-fg" },
    { id: "absent", label: t("davomat.employee.month.absent"), value: fmt.number(totals.absent_days), hint: "", tone: totals.absent_days ? "text-danger" : "text-fg" },
    { id: "hours", label: t("davomat.employee.month.hours"), value: fmt.number(hoursOf(totals.worked_minutes), 1), hint: totals.approved_overtime_minutes ? t("davomat.employee.month.overtime", { d: fmt.duration(totals.approved_overtime_minutes) }) : "", tone: "text-fg" },
  ];
});

/** The codes this month uses, for the legend (in a fixed order). */
const LEGEND: CellCode[] = ["present", "late", "absent", "leave", "holiday", "open"];
const legend = computed(() => {
  const used = new Set(Object.values(data.value?.cells ?? {}).map((cell) => cell.code));
  return LEGEND.filter((code) => used.has(code));
});

function cellTitle(value: string, cell: MonthCell | undefined): string {
  const parts = [fmt.day(value, "weekday")];
  if (cell) parts.push(t(`davomat.employee.cell.${cell.code}`));
  if (cell?.minutes) parts.push(fmt.duration(cell.minutes));
  if (cell?.late) parts.push(t("davomat.employee.month.lateBy", { d: fmt.duration(cell.late) }));
  const holiday = data.value?.holidays[value];
  if (holiday) parts.push(holiday);
  return parts.join(" · ");
}

function codeOf(value: string): CellCode {
  return data.value?.cells[value]?.code ?? "off";
}
</script>

<template>
  <section class="ui-card flex flex-col gap-4 p-4 sm:p-5" :aria-label="t('davomat.employee.month.title')" data-employee-month>
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('common.date.prevMonth')" size="sm" @click="month = shiftMonth(month, -1)" />
        <h2 class="min-w-36 text-center text-base font-semibold capitalize text-fg">{{ fmt.day(`${month}-01`, "monthYear") }}</h2>
        <IconButton :icon="ChevronRight" :label="t('common.date.nextMonth')" size="sm" :disabled="month >= monthOf(today)" @click="month = shiftMonth(month, 1)" />
      </div>
      <StatusPill v-if="data?.schedule" tone="primary" :icon="CalendarClock" :label="data.schedule.name" size="sm" />
      <StatusPill v-else-if="data" tone="neutral" :label="t('davomat.employee.month.noSchedule')" size="sm" />
    </div>

    <div v-if="skeleton" class="flex flex-col gap-3" aria-hidden="true">
      <div class="grid grid-cols-2 gap-2 sm:grid-cols-4"><SkeletonBlock v-for="n in 4" :key="n" height="64px" radius="12px" /></div>
      <SkeletonBlock height="260px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <dl class="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div v-for="stat in stats" :key="stat.id" class="rounded-[12px] bg-surface-2/70 px-3 py-2.5" :data-stat="stat.id">
          <dt class="text-xs font-medium text-muted">{{ stat.label }}</dt>
          <dd :class="['mt-0.5 text-xl font-semibold leading-7 tabular-nums', stat.tone]">{{ stat.value }}</dd>
          <dd class="min-h-4 text-xs leading-4 tabular-nums text-muted line-clamp-2">{{ stat.hint }}</dd>
        </div>
      </dl>

      <div class="grid grid-cols-7 gap-1 text-center" role="grid" :aria-label="t('davomat.employee.month.title')">
        <span v-for="index in 7" :key="`h-${index}`" class="pb-1 text-[11px] font-medium uppercase tracking-wide text-subtle" role="columnheader">{{ t(`common.weekday.min.${index - 1}`) }}</span>
        <span v-for="n in blanks" :key="`b-${n}`" aria-hidden="true" />
        <button
          v-for="value in data.days"
          :key="value"
          type="button"
          :disabled="isFuture(value)"
          :class="[
            'calendar-day relative flex aspect-square min-w-0 flex-col items-center justify-center rounded-[10px] text-xs transition-[box-shadow,transform] duration-150 sm:aspect-[6/5]',
            CELL_CLASSES[codeOf(value)],
            isFuture(value) ? 'cursor-default opacity-60' : 'hover:-translate-y-px hover:shadow-[var(--sh-raised)]',
            value === day && 'ring-2 ring-[var(--c-primary)] ring-offset-2 ring-offset-[var(--c-surface)]',
          ]"
          :title="cellTitle(value, data.cells[value])"
          :aria-pressed="value === day"
          :aria-label="cellTitle(value, data.cells[value])"
          :data-day="value"
          @click="day = value"
        >
          <span :class="['font-semibold tabular-nums', value === data.today && 'underline decoration-2 underline-offset-4']">{{ Number(value.slice(8)) }}</span>
          <span v-if="data.cells[value] && CELL_WITH_HOURS.has(codeOf(value))" class="text-[10px] tabular-nums opacity-80"
            >{{ fmt.number(hoursOf(data.cells[value]!.minutes), 1) }}<span class="max-sm:hidden">&#8239;{{ t("davomat.employee.month.h") }}</span></span
          >
          <span v-else-if="data.cells[value] && codeOf(value) !== 'off' && codeOf(value) !== 'planned'" class="max-w-full truncate px-0.5 text-[10px] opacity-80">{{ t(`davomat.employee.cellShort.${codeOf(value)}`) }}</span>
        </button>
      </div>

      <ul v-if="legend.length" class="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted" :aria-label="t('davomat.employee.month.legend')">
        <li v-for="code in legend" :key="code" class="inline-flex items-center gap-1.5">
          <span :class="['size-3 rounded-[4px]', CELL_CLASSES[code]]" aria-hidden="true" />{{ t(`davomat.employee.cell.${code}`) }}
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
@media (prefers-reduced-motion: reduce) {
  .calendar-day:hover {
    transform: none;
  }
}
</style>
