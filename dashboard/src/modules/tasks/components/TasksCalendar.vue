<script setup lang="ts">
/**
 * Due dates on a calendar (plan §1.3): a month or a week (`?cal=week`), the month or week in the
 * URL. Each task sits on its deadline, colored by status (late ones red); a day's counts show in
 * the side summary. Click a task to open it.
 */
import { CalendarDays, CalendarRange } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import CalendarMonth from "@/components/CalendarMonth.vue";
import type { CalendarItem } from "@/components/calendarItems";
import CalendarWeek from "@/components/CalendarWeek.vue";
import ErrorState from "@/components/ErrorState.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import { addDays, endOfMonth, startOfMonth, startOfWeek, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useCalendar } from "../api";
import { COLUMN_COLOR } from "../meta";
import type { TaskRow } from "../types";

const props = defineProps<{ params: Record<string, string | string[]> }>();
const emit = defineEmits<{ open: [task: TaskRow] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const mode = useRouteState("cal", rs.enum(["month", "week"] as const, "month"));
const monthParam = useRouteState("month", rs.string(""));
const weekParam = useRouteState("week", rs.string(""));
const month = computed({
  get: () => (/^\d{4}-\d{2}$/.test(monthParam.value) ? monthParam.value : today.value.slice(0, 7)),
  set: (value: string) => (monthParam.value = value === today.value.slice(0, 7) ? "" : value),
});
const week = computed({
  get: () => (/^\d{4}-\d{2}-\d{2}$/.test(weekParam.value) ? weekParam.value : startOfWeek(today.value)),
  set: (value: string) => (weekParam.value = value === startOfWeek(today.value) ? "" : value),
});
const selected = useRouteState("day", rs.day());

const range = computed(() => {
  if (mode.value === "week") return { from: week.value, to: addDays(week.value, 6) };
  // The month grid shows whole weeks around the month.
  const first = startOfMonth(`${month.value}-01`);
  return { from: startOfWeek(first), to: addDays(startOfWeek(endOfMonth(first)), 6) };
});
const query = useCalendar(computed(() => ({ ...props.params, from: range.value.from, to: range.value.to })));

const byId = computed(() => new Map((query.data.value?.items ?? []).map((task) => [String(task.id), task])));
const items = computed<CalendarItem[]>(() =>
  (query.data.value?.items ?? []).map((task) => ({
    id: task.id,
    kind: task.status,
    title: task.title,
    start: task.due_at!,
    end: null,
    all_day: false,
    color: task.is_overdue ? "var(--c-danger)" : task.status === "cancelled" ? "var(--c-subtle)" : COLUMN_COLOR[task.status],
    subtitle: task.assignee.name,
  })),
);

const legend = computed(() => [
  ...(["todo", "in_progress", "review", "done"] as const).map((id) => ({ id, label: t(`tasks.column.${id}`), color: COLUMN_COLOR[id] })),
  // Sent back and late share the danger color.
  { id: "late", label: `${t("tasks.column.returned")} · ${t("tasks.status.late")}`, color: "var(--c-danger)" },
]);

const day = computed(() => (query.data.value?.days ?? []).find((entry) => entry.date === selected.value) ?? null);

function openItem(item: CalendarItem): void {
  const task = byId.value.get(String(item.id));
  if (task) emit("open", task);
}
</script>

<template>
  <div class="min-w-0">
    <ErrorState v-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="flex flex-col gap-3">
      <p v-if="query.data.value?.truncated" class="rounded-[8px] bg-warning-soft px-3 py-2 text-sm text-warning">{{ t("tasks.calendar.truncated") }}</p>
      <CalendarMonth
        v-if="mode === 'month'"
        v-model:month="month"
        v-model:selected="selected"
        :items="items"
        :loading="query.isPending.value"
        :max-per-day="3"
        @item-click="openItem"
      >
        <template #toolbar>
          <div class="flex flex-wrap items-center gap-3">
            <p v-if="day" class="text-sm text-muted">
              <span class="font-semibold text-fg">{{ fmt.day(day.date, "weekday") }}:</span>
              {{ t("tasks.calendar.dayCounts", { total: day.total, done: day.done, late: day.late }) }}
            </p>
            <SegmentedControl
              v-model="mode"
              size="sm"
              :options="[
                { value: 'month', label: t('common.calendar.month'), icon: CalendarDays },
                { value: 'week', label: t('common.calendar.week'), icon: CalendarRange },
              ]"
            />
          </div>
        </template>
      </CalendarMonth>
      <div v-else class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <ul class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <li v-for="entry in legend" :key="entry.id" class="inline-flex items-center gap-1.5">
              <span class="size-2 rounded-full" :style="{ background: entry.color }" />{{ entry.label }}
            </li>
          </ul>
          <SegmentedControl
            v-model="mode"
            size="sm"
            :options="[
              { value: 'month', label: t('common.calendar.month'), icon: CalendarDays },
              { value: 'week', label: t('common.calendar.week'), icon: CalendarRange },
            ]"
          />
        </div>
        <CalendarWeek v-model:week="week" :items="items" :start-hour="7" :end-hour="23" @item-click="openItem" />
      </div>
    </div>
  </div>
</template>
