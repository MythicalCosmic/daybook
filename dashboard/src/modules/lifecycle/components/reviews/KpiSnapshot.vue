<script setup lang="ts">
/**
 * The person's numbers for the review's period, as they were when the reviewer first opened the
 * review (they never change after that): shared work on time, attendance, disciplinary records,
 * the till and training when those modules are on, and how the goals of earlier reviews went.
 */
import { BookOpenCheck, CalendarCheck, ClipboardCheck, Flag, ShieldCheck, Store } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import MoneyText from "@/components/MoneyText.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import { useFormat } from "@/lib/useFormat";

import type { Kpis } from "../../reviews/types";

const props = defineProps<{ kpis: Kpis | null; takenAt?: string | null; compact?: boolean }>();

const { t } = useI18n();
const fmt = useFormat();

const onTime = computed(() => (props.kpis?.tasks.on_time_percent ? Number(props.kpis.tasks.on_time_percent) : null));
const onTimeTone = computed(() => (onTime.value === null ? "neutral" : onTime.value >= 90 ? "success" : onTime.value >= 75 ? "warning" : "danger"));
const records = computed(() => props.kpis?.discipline.records ?? 0);
</script>

<template>
  <section class="ui-card p-4 sm:p-5" data-kpis>
    <div class="mb-3 flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.reviews.kpis.title") }}</h3>
        <p v-if="kpis" class="text-xs text-muted">{{ t("lifecycle.reviews.kpis.period", { from: fmt.day(kpis.start, "medium"), to: fmt.day(kpis.end, "medium") }) }}</p>
      </div>
      <span v-if="takenAt" class="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted" :title="t('lifecycle.reviews.kpis.frozenHint')">
        {{ t("lifecycle.reviews.kpis.frozen", { date: fmt.instant(takenAt, "date") }) }}
      </span>
    </div>

    <p v-if="!kpis" class="rounded-[12px] border border-dashed border-line px-4 py-6 text-center text-sm text-muted">{{ t("lifecycle.reviews.kpis.later") }}</p>

    <ul v-else :class="['grid grid-cols-2 gap-2.5', compact ? '' : 'lg:grid-cols-3']">
      <li class="min-w-0 rounded-[12px] border border-line px-3 py-2.5">
        <div class="flex items-center gap-2 text-xs font-medium text-muted"><ClipboardCheck :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.kpis.tasks") }}</div>
        <template v-if="kpis.tasks.total">
          <p class="mt-1 text-xl font-semibold tabular-nums text-fg">{{ fmt.percent(onTime ?? 0, 1) }}</p>
          <ProgressBar class="mt-1.5" :value="onTime ?? 0" :max="100" size="xs" :tone="onTimeTone" />
          <p class="mt-1.5 text-xs text-muted">{{ t("lifecycle.reviews.kpis.tasksLine", { onTime: kpis.tasks.on_time, total: kpis.tasks.total, late: kpis.tasks.late, missed: kpis.tasks.missed }) }}</p>
        </template>
        <p v-else class="mt-1 text-sm text-muted">{{ t("lifecycle.reviews.kpis.noTasks") }}</p>
      </li>

      <li v-if="kpis.attendance" class="min-w-0 rounded-[12px] border border-line px-3 py-2.5">
        <div class="flex items-center gap-2 text-xs font-medium text-muted"><CalendarCheck :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.kpis.attendance") }}</div>
        <div class="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-0.5">
          <p class="text-xl font-semibold tabular-nums" :class="kpis.attendance.late_arrivals ? 'text-warning' : 'text-fg'">
            {{ kpis.attendance.late_arrivals }}<span class="ml-1 text-xs font-normal text-muted">{{ t("lifecycle.reviews.kpis.lateShort") }}</span>
          </p>
          <p class="text-xl font-semibold tabular-nums" :class="kpis.attendance.absent_days ? 'text-danger' : 'text-fg'">
            {{ kpis.attendance.absent_days }}<span class="ml-1 text-xs font-normal text-muted">{{ t("lifecycle.reviews.kpis.absentShort") }}</span>
          </p>
        </div>
        <p class="mt-1.5 text-xs text-muted">{{ t("lifecycle.reviews.kpis.attendanceLine", { attended: kpis.attendance.attended_days, scheduled: kpis.attendance.scheduled_days, hours: fmt.number(kpis.attendance.worked_hours, 0) }) }}</p>
      </li>

      <li class="min-w-0 rounded-[12px] border border-line px-3 py-2.5">
        <div class="flex items-center gap-2 text-xs font-medium text-muted"><ShieldCheck :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.kpis.discipline") }}</div>
        <p class="mt-1 text-xl font-semibold tabular-nums" :class="records ? 'text-warning' : 'text-success'">{{ records }}</p>
        <p class="mt-1.5 text-xs text-muted">
          <template v-if="records">{{ Object.entries(kpis.discipline.by_kind).map(([kind, count]) => `${t(`lifecycle.kind.${kind}`)}: ${count}`).join(" · ") }}</template>
          <template v-else>{{ t("lifecycle.reviews.kpis.clean") }}</template>
        </p>
      </li>

      <li v-if="kpis.sales" class="min-w-0 rounded-[12px] border border-line px-3 py-2.5">
        <div class="flex items-center gap-2 text-xs font-medium text-muted"><Store :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.kpis.sales") }}</div>
        <p class="mt-1 text-xl font-semibold tabular-nums text-fg"><MoneyText :value="kpis.sales.net" :currency="kpis.sales.currency" compact /></p>
        <p class="mt-1.5 text-xs text-muted">
          {{ t("lifecycle.reviews.kpis.salesLine", { shifts: kpis.sales.shifts, receipts: fmt.number(kpis.sales.receipts) }) }}
          <template v-if="kpis.sales.accuracy"> · {{ t("lifecycle.reviews.kpis.accuracy", { percent: fmt.number(kpis.sales.accuracy, 0) }) }}</template>
          <template v-if="kpis.sales.shortages"> · {{ t("lifecycle.reviews.kpis.shortages", { count: kpis.sales.shortages }, kpis.sales.shortages) }}</template>
        </p>
      </li>

      <li v-if="kpis.learning" class="min-w-0 rounded-[12px] border border-line px-3 py-2.5">
        <div class="flex items-center gap-2 text-xs font-medium text-muted"><BookOpenCheck :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.kpis.learning") }}</div>
        <p class="mt-1 text-xl font-semibold tabular-nums text-fg">{{ kpis.learning.completed }}</p>
        <p class="mt-1.5 text-xs text-muted">
          {{ t("lifecycle.reviews.kpis.learningLine", { open: kpis.learning.open }) }}
          <template v-if="kpis.learning.late"> · <span class="text-warning">{{ t("lifecycle.reviews.kpis.learningLate", { count: kpis.learning.late }, kpis.learning.late) }}</span></template>
        </p>
      </li>

      <li v-if="kpis.goals" class="min-w-0 rounded-[12px] border border-line px-3 py-2.5">
        <div class="flex items-center gap-2 text-xs font-medium text-muted"><Flag :size="14" aria-hidden="true" />{{ t("lifecycle.reviews.kpis.goals") }}</div>
        <p class="mt-1 text-xl font-semibold tabular-nums text-fg">{{ kpis.goals.done }}<span class="text-sm font-normal text-muted"> / {{ kpis.goals.done + kpis.goals.missed + kpis.goals.open }}</span></p>
        <p class="mt-1.5 text-xs text-muted">{{ t("lifecycle.reviews.kpis.goalsLine", { missed: kpis.goals.missed, open: kpis.goals.open }) }}</p>
      </li>
    </ul>
  </section>
</template>
