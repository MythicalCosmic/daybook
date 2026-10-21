<script setup lang="ts">
/**
 * The monthly timesheet (plan §6.2): people × days, a coloured cell per day with the hours worked
 * (late days in ochre, absences in brick, leave in slate, holidays shaded), each person's totals
 * pinned on the right, and the month's numbers on top. Click a day to open its record and correct
 * it (audited, reason required), or to record a day nobody checked in for.
 */
import { CalendarDays, ChevronLeft, ChevronRight, Users } from "@lucide/vue";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { createRecord, useCompanyId, useRefresh, useSummary, useTimesheet } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import BranchSwitch from "../components/BranchSwitch.vue";
import RecordDrawer from "../components/RecordDrawer.vue";
import { CELL_CLASSES, CELL_WITH_HOURS, hours, isWeekend, localDateTime, monthStart, shiftMonth } from "../lib";
import type { Cell, CellCode, TimesheetRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefresh();

const thisMonth = computed(() => todayIn(company.timezone).slice(0, 7));
const monthParam = useRouteState("month", rs.string(""));
const month = computed({
  get: () => (/^\d{4}-\d{2}$/.test(monthParam.value) ? monthParam.value : thisMonth.value),
  set: (value: string) => (monthParam.value = value === thisMonth.value ? "" : value),
});
const branch = useRouteState("branch", rs.optionalNumber());
const recordId = useRouteState("record", rs.optionalNumber(), { push: true });

const sheet = useTimesheet(() => ({ month: month.value, branch: branch.value }));
const skeleton = useDelayedPending(computed(() => sheet.isPending.value));
const data = computed(() => sheet.data.value);
const lastDay = computed(() => data.value?.days.at(-1) ?? `${month.value}-28`);
const summary = useSummary(() => ({ from: monthStart(month.value), to: lastDay.value, branch: branch.value ? [branch.value] : [] }));

const kpis = computed(() => {
  const totals = summary.data.value?.totals;
  const people = data.value?.people ?? [];
  const overtime = people.reduce((sum, row) => sum + row.totals.approved_overtime_minutes, 0);
  return [
    { id: "attendance", label: t("attendance.sheet.attendanceRate"), value: totals?.attendance_percent ? Number(totals.attendance_percent) : null, format: "percent" as const, loading: summary.isPending.value },
    { id: "ontime", label: t("attendance.sheet.onTime"), value: totals?.on_time_percent ? Number(totals.on_time_percent) : null, format: "percent" as const, loading: summary.isPending.value },
    { id: "late", label: t("attendance.sheet.lateArrivals"), value: totals?.late ?? null, loading: summary.isPending.value },
    { id: "absent", label: t("attendance.sheet.absences"), value: totals?.absent ?? null, loading: summary.isPending.value },
    { id: "hours", label: t("attendance.sheet.hours"), value: totals ? Number(totals.worked_hours) : null, hint: overtime ? t("attendance.sheet.overtimeApproved", { d: fmt.duration(overtime) }) : undefined, loading: summary.isPending.value },
  ];
});

const LEGEND: CellCode[] = ["present", "late", "absent", "leave", "holiday", "excused", "auto", "unscheduled", "planned"];

function cellText(cell: Cell): string {
  if (CELL_WITH_HOURS.has(cell.code)) return cell.minutes ? hours(cell.minutes) : "·";
  if (cell.code === "off" || cell.code === "planned") return "";
  if (cell.code === "open") return "●";
  return t(`attendance.cell.${cell.code}.short`);
}

function cellTitle(row: TimesheetRow, day: string, cell: Cell): string {
  const parts = [row.member.name, fmt.day(day, "weekday"), t(`attendance.cell.${cell.code}.label`)];
  if (cell.minutes && CELL_WITH_HOURS.has(cell.code)) parts.push(fmt.duration(cell.minutes));
  if (cell.late) parts.push(t("attendance.record.lateBy", { late: fmt.duration(cell.late) }));
  return parts.join(" · ");
}

// Recording a day nobody checked in for -------------------------------------------------------

const draft = ref<{ row: TimesheetRow; day: string } | null>(null);
const form = ref({ in: "09:00", out: "18:00", reason: "" });
const saving = ref(false);
const formError = ref<string | null>(null);
const canManage = computed(() => company.can("attendance.manage"));

function openCell(row: TimesheetRow, day: string, cell: Cell): void {
  if (cell.record_id) {
    recordId.value = cell.record_id;
    return;
  }
  if (!canManage.value || !data.value || day > data.value.today || cell.code === "leave" || cell.code === "holiday") return;
  draft.value = { row, day };
  form.value = { in: "09:00", out: "18:00", reason: "" };
  formError.value = null;
}

async function saveDraft(): Promise<void> {
  const target = draft.value;
  if (!target) return;
  if (!form.value.reason.trim()) {
    formError.value = t("attendance.record.reasonNeeded");
    return;
  }
  saving.value = true;
  try {
    await createRecord(companyId.value, {
      member_id: target.row.member.id,
      date: target.day,
      check_in_at: localDateTime(target.day, form.value.in),
      check_out_at: localDateTime(target.day, form.value.out, form.value.in),
      reason: form.value.reason.trim(),
    });
    toast.success(t("attendance.sheet.recorded"));
    draft.value = null;
    refresh();
  } catch {
    // The HTTP client shows the server's message.
  } finally {
    saving.value = false;
  }
}

const dayHeader = (day: string) => t(`common.weekday.min.${(new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7}`);

// This month opens scrolled so today's column is in view, next to the pinned totals.
const scroller = ref<HTMLElement | null>(null);
watch(
  () => [data.value?.month, data.value?.people.length],
  async () => {
    await nextTick();
    const el = scroller.value;
    const today = data.value?.today;
    if (!el || !today || !data.value?.days.includes(today)) return;
    const cell = el.querySelector<HTMLElement>(`th[data-day="${today}"]`);
    if (!cell) return;
    const pinned = el.querySelector<HTMLElement>("thead .att-sticky-right")?.offsetWidth ?? 0;
    const target = cell.offsetLeft + cell.offsetWidth + 3 * cell.offsetWidth - (el.clientWidth - pinned);
    el.scrollLeft = Math.max(0, target);
  },
  { immediate: true },
);
</script>

<template>
  <div class="flex flex-col gap-5">
    <AttendanceHeader :title="t('attendance.sheet.title')" :description="t('attendance.sheet.description')">
      <template #actions>
        <ExportButton kind="attendance.timesheet" :params="{ month, branch: branch ?? undefined }" />
      </template>
    </AttendanceHeader>

    <div class="flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('common.date.prevMonth')" size="sm" variant="secondary" @click="month = shiftMonth(month, -1)" />
        <span class="inline-flex min-w-40 items-center justify-center gap-1.5 text-base font-semibold text-fg">
          <CalendarDays :size="15" class="text-subtle" aria-hidden="true" />{{ fmt.day(monthStart(month), "monthYear") }}
        </span>
        <IconButton :icon="ChevronRight" :label="t('common.date.nextMonth')" size="sm" variant="secondary" :disabled="month >= thisMonth" @click="month = shiftMonth(month, 1)" />
        <UiButton v-if="month !== thisMonth" size="sm" variant="ghost" @click="month = thisMonth">{{ t("attendance.sheet.thisMonth") }}</UiButton>
      </div>
      <span class="flex-1" />
      <BranchSwitch v-model="branch" />
    </div>

    <KpiStrip class="att-kpis" :items="kpis" :columns="5" />

    <div v-if="skeleton" class="ui-card flex flex-col gap-2 p-4">
      <SkeletonBlock v-for="n in 7" :key="n" height="34px" radius="8px" />
    </div>
    <ErrorState v-else-if="sheet.isError.value" :error="sheet.error.value" :retry="() => sheet.refetch()" />
    <EmptyState v-else-if="data && !data.people.length" :icon="Users" :title="t('attendance.sheet.emptyTitle')" :description="t('attendance.sheet.emptyBody')" />
    <section v-else-if="data" class="ui-card overflow-hidden" :aria-label="t('attendance.sheet.title')">
      <div ref="scroller" class="att-sheet">
        <table class="w-max min-w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th class="att-sticky-left z-20 min-w-[200px] border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold text-muted" scope="col">{{ t("attendance.sheet.person") }}</th>
              <th
                v-for="day in data.days"
                :key="day"
                :data-day="day"
                scope="col"
                :class="[
                  'border-b border-line px-0.5 py-1.5 text-center font-normal',
                  day === data.today ? 'text-primary' : isWeekend(day) || data.holidays[day] ? 'text-subtle' : 'text-muted',
                ]"
                :title="data.holidays[day] ?? fmt.day(day, 'weekday')"
              >
                <span class="block text-[10px] uppercase leading-tight tracking-wide">{{ dayHeader(day) }}</span>
                <span :class="['mx-auto mt-0.5 grid size-6 place-items-center rounded-full text-xs font-semibold tabular-nums', day === data.today && 'bg-primary text-on-primary']">{{ Number(day.slice(8)) }}</span>
                <span v-if="data.holidays[day]" class="mx-auto mt-0.5 block size-1 rounded-full bg-info" aria-hidden="true" />
              </th>
              <th class="att-sticky-right z-20 border-b border-l border-line bg-surface px-2 py-2 text-right text-xs font-semibold text-muted" scope="col">
                <span class="inline-flex gap-3">
                  <span class="w-10" :title="t('attendance.sheet.daysHint')">{{ t("attendance.sheet.days") }}</span>
                  <span class="w-8">{{ t("attendance.sheet.lateShort") }}</span>
                  <span class="w-8">{{ t("attendance.sheet.absentShort") }}</span>
                  <span class="w-12">{{ t("attendance.sheet.hoursShort") }}</span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in data.people" :key="row.member.id" class="group">
              <th scope="row" class="att-sticky-left z-10 border-b border-line bg-surface px-3 py-1.5 text-left font-normal group-hover:bg-surface-2">
                <div class="flex min-w-0 items-center gap-2">
                  <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="26" />
                  <div class="min-w-0">
                    <p class="truncate text-sm font-medium text-fg">{{ row.member.name }}</p>
                    <p class="truncate text-[11px] text-muted">{{ row.member.position?.name ?? "" }}</p>
                  </div>
                </div>
              </th>
              <td v-for="day in data.days" :key="day" class="border-b border-line p-[3px] group-hover:bg-surface-2/60">
                <button
                  type="button"
                  :class="[
                    'grid size-[30px] place-items-center rounded-[6px] text-[11px] font-semibold tabular-nums transition-transform duration-[120ms] hover:scale-110 focus-visible:outline-2 focus-visible:outline-[var(--c-ring)]',
                    CELL_CLASSES[row.cells[day]?.code ?? 'off'],
                    !row.cells[day]?.record_id && (row.cells[day]?.code === 'off' || row.cells[day]?.code === 'planned') && 'cursor-default hover:scale-100',
                  ]"
                  :title="row.cells[day] ? cellTitle(row, day, row.cells[day]) : ''"
                  :aria-label="row.cells[day] ? cellTitle(row, day, row.cells[day]) : day"
                  @click="row.cells[day] && openCell(row, day, row.cells[day])"
                >
                  {{ row.cells[day] ? cellText(row.cells[day]) : "" }}
                </button>
              </td>
              <td class="att-sticky-right z-10 border-b border-l border-line bg-surface px-2 py-1.5 text-right tabular-nums group-hover:bg-surface-2">
                <span class="inline-flex gap-3 text-sm">
                  <span class="w-10 font-semibold text-fg">{{ row.totals.attended_days }}<span v-if="row.totals.has_schedule" class="font-normal text-subtle">/{{ Math.max(0, row.totals.scheduled_days - row.totals.leave_days) }}</span></span>
                  <span :class="['w-8', row.totals.late_arrivals ? 'font-semibold text-warning' : 'text-subtle']">{{ row.totals.late_arrivals }}</span>
                  <span :class="['w-8', row.totals.absent_days ? 'font-semibold text-danger' : 'text-subtle']">{{ row.totals.absent_days }}</span>
                  <span class="w-12 text-fg">{{ hours(row.totals.worked_minutes) }}</span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line px-4 py-3">
        <span v-for="code in LEGEND" :key="code" class="inline-flex items-center gap-1.5 text-xs text-muted">
          <span :class="['grid size-4 place-items-center rounded-[4px] text-[9px] font-bold', CELL_CLASSES[code]]">{{ code === "present" || code === "late" || code === "auto" || code === "unscheduled" ? "8" : code === "planned" ? "" : t(`attendance.cell.${code}.short`) }}</span>
          {{ t(`attendance.cell.${code}.label`) }}
        </span>
      </footer>
    </section>

    <RecordDrawer />

    <UiDialog
      :open="draft !== null"
      :title="t('attendance.sheet.recordTitle')"
      :description="draft ? `${draft.row.member.name} · ${fmt.day(draft.day, 'weekday')}` : undefined"
      size="sm"
      @update:open="(open: boolean) => !open && (draft = null)"
    >
      <form class="flex flex-col gap-3" @submit.prevent="saveDraft">
        <div class="grid grid-cols-2 gap-3">
          <FormField :label="t('attendance.record.came')"><TimePicker v-model="form.in" :step="5" /></FormField>
          <FormField :label="t('attendance.record.left')"><TimePicker v-model="form.out" :step="5" /></FormField>
        </div>
        <FormField :label="t('common.reason')" :error="formError" required :hint="t('attendance.record.reasonHint')">
          <TextArea v-model="form.reason" :rows="2" :maxlength="300" :placeholder="t('attendance.record.reasonPlaceholder')" />
        </FormField>
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="draft = null">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="saveDraft">{{ t("attendance.sheet.recordSave") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<style scoped>
.att-sheet {
  overflow: auto;
  max-height: calc(100dvh - 300px);
}
.att-sheet thead th {
  position: sticky;
  top: 0;
  z-index: 15;
  background: var(--c-surface);
}
.att-sticky-left {
  position: sticky;
  left: 0;
}
.att-sticky-right {
  position: sticky;
  right: 0;
  box-shadow: -8px 0 12px -10px color-mix(in srgb, var(--c-text) 22%, transparent);
}
.att-sheet thead th.att-sticky-left,
.att-sheet thead th.att-sticky-right {
  z-index: 25;
}
</style>
