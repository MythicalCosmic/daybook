<script setup lang="ts">
/**
 * Overview card "Attendance, 14 days" (plan §1.2 attendance strip): per day the people on time,
 * late and absent as one stacked bar, from `attendance/summary/`. Plain markup with the chart
 * tokens (no chart library); the bars take whatever height the card has.
 */
import { ArrowRight, CalendarDays } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { addDays, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useSummary } from "../api";
import { weekdayIndex } from "../lib";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const query = useSummary(() => ({ from: addDays(today.value, -13), to: today.value }));

const days = computed(() => query.data.value?.series ?? []);
const peak = computed(() => Math.max(1, ...days.value.map((day) => day.present + day.absent)));
const onTime = computed(() => query.data.value?.totals.on_time_percent ?? null);
const empty = computed(() => days.value.every((day) => !day.present && !day.absent));
const pct = (value: number) => `${(value / peak.value) * 100}%`;
</script>

<template>
  <WidgetCard :title="t('attendance.widget.stripTitle')" :subtitle="t('attendance.widget.stripSubtitle')" :icon="CalendarDays" inset="content">
    <template v-if="onTime !== null" #aside>
      <span class="shrink-0 text-right text-lg font-semibold leading-6 tabular-nums text-fg">{{ t("attendance.widget.onTimeValue", { p: onTime }) }}</span>
    </template>
    <SkeletonBlock v-if="query.isPending.value" class="flex-1" height="150px" radius="10px" />
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="empty" class="my-auto" size="sm" tone="neutral" :icon="CalendarDays" :title="t('attendance.widget.empty')" />
    <template v-else>
      <!-- The bars fill whatever height the card has (absolute, so their percentages have a height to use). -->
      <div class="relative mt-2 min-h-[120px] flex-1">
      <div class="absolute inset-0 flex items-end gap-1.5" role="img" :aria-label="t('attendance.widget.stripSubtitle')">
        <div
          v-for="day in days"
          :key="day.date"
          class="group flex h-full min-w-0 flex-1 flex-col justify-end"
          :title="`${fmt.day(day.date, 'short')} · ${t('attendance.widget.onTime')} ${day.present - day.late} · ${t('attendance.widget.lateLegend')} ${day.late} · ${t('attendance.widget.absentLegend')} ${day.absent}`"
        >
          <span v-if="day.absent" class="w-full rounded-t-[3px] bg-danger/80" :style="{ height: pct(day.absent) }" />
          <span v-if="day.late" :class="['w-full bg-warning/85', !day.absent && 'rounded-t-[3px]']" :style="{ height: pct(day.late) }" />
          <span v-if="day.present - day.late" :class="['w-full bg-success/80', !day.absent && !day.late && 'rounded-t-[3px]']" :style="{ height: pct(day.present - day.late) }" />
          <span v-if="!day.present && !day.absent" class="h-[3px] w-full rounded-full bg-surface-2" />
        </div>
      </div>
      </div>
      <div class="mt-1.5 flex gap-1.5">
        <span v-for="day in days" :key="day.date" :class="['min-w-0 flex-1 text-center text-[10px] tabular-nums', day.date === today ? 'font-semibold text-primary' : 'text-subtle']">
          {{ t(`common.weekday.min.${weekdayIndex(day.date)}`) }}
        </span>
      </div>
    </template>
    <template #footer>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 font-normal">
        <span class="inline-flex items-center gap-1.5"><span class="size-2 rounded-full bg-success" />{{ t("attendance.widget.onTime") }}</span>
        <span class="inline-flex items-center gap-1.5"><span class="size-2 rounded-full bg-warning" />{{ t("attendance.widget.lateLegend") }}</span>
        <span class="inline-flex items-center gap-1.5"><span class="size-2 rounded-full bg-danger" />{{ t("attendance.widget.absentLegend") }}</span>
        <span class="flex-1" />
        <RouterLink :to="`/c/${props.companyId}/attendance/timesheet`" class="group/link inline-flex items-center gap-1 font-semibold hover:text-fg">
          {{ t("attendance.nav.timesheet") }}<ArrowRight :size="12" class="transition-transform duration-150 group-hover/link:translate-x-0.5" aria-hidden="true" />
        </RouterLink>
      </div>
    </template>
  </WidgetCard>
</template>
