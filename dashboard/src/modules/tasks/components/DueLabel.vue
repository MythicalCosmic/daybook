<script setup lang="ts">
/**
 * A deadline in words, in the company's timezone: "today, 18:00", "tomorrow, 09:00", "12 Oct, 18:00".
 * Open work past it turns red and says how late ("late 2 h 10 min"); finished work shows it plainly.
 */
import { AlarmClock, CalendarClock } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { addDays, todayIn, zonedDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { lateness, minutesBetween } from "../meta";

const props = withDefaults(defineProps<{ due: string | null; overdue?: boolean; icon?: boolean; compact?: boolean }>(), {
  overdue: false,
  icon: false,
  compact: false,
});

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const now = useNow();

const text = computed(() => {
  if (!props.due) return t("tasks.due.none");
  const today = todayIn(company.timezone, now.value);
  const day = zonedDay(props.due, company.timezone);
  const time = fmt.instant(props.due, "time");
  if (day === today) return t("tasks.due.today", { time });
  if (day === addDays(today, 1)) return t("tasks.due.tomorrow", { time });
  if (day === addDays(today, -1)) return t("tasks.due.yesterday", { time });
  return props.compact ? fmt.day(day, "short") : `${fmt.day(day, "short")}, ${time}`;
});

const late = computed(() => {
  if (!props.overdue || !props.due) return null;
  const words = { min: t("tasks.unit.min"), h: t("tasks.unit.h"), d: t("tasks.unit.d") };
  return t("tasks.due.lateBy", { time: lateness(minutesBetween(props.due, new Date(now.value)), words) });
});
</script>

<template>
  <span :class="['inline-flex min-w-0 items-center gap-1 tabular-nums', late ? 'font-semibold text-danger' : due ? 'text-fg' : 'text-subtle']" :title="due ? fmt.instant(due, 'datetime') : undefined">
    <component :is="late ? AlarmClock : CalendarClock" v-if="icon" :size="13" class="shrink-0" aria-hidden="true" />
    <span :class="late && !compact ? 'shrink-0' : 'truncate'">{{ text }}</span>
    <span v-if="late && !compact" class="truncate text-xs font-medium">· {{ late }}</span>
  </span>
</template>
