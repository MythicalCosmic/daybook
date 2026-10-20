<script setup lang="ts">
/**
 * Person 360 › Overview: how their work went week by week, the last 30 days split into on time,
 * late and missed, their details, and the time off coming up.
 */
import { CalendarDays, CalendarPlus, Flame } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import ChartCard from "@/components/ChartCard.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import EmptyState from "@/components/EmptyState.vue";
import LineChart from "@/components/LineChart.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import { formatPhone } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import type { PersonDetail } from "../types";

const props = defineProps<{ person: PersonDetail; rateTone: "success" | "warning" | "danger" | "neutral" }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const trend = computed(() => props.person.overview.trend);
const hasTrend = computed(() => trend.value.some((point) => point.total > 0));
const categories = computed(() => trend.value.map((point) => point.date));
const series = computed(() => [
  { name: t("people.overview.onTimeSeries"), data: trend.value.map((point) => point.on_time_percent) },
]);
const csv = computed(() => ({
  filename: `on-time-${props.person.name}`,
  columns: [
    { key: "date", label: t("people.overview.week") },
    { key: "on_time_percent", label: t("people.overview.onTimeSeries") },
    { key: "done", label: t("people.overview.onTime") },
    { key: "total", label: t("people.overview.total") },
  ],
  rows: trend.value as never[],
}));

const o = computed(() => props.person.overview);
const split = computed(() => [
  { value: o.value.on_time, color: "var(--c-success)", label: t("people.overview.onTime") },
  { value: o.value.late, color: "var(--c-warning)", label: t("people.overview.late") },
  { value: o.value.missed, color: "var(--c-danger)", label: t("people.overview.missed") },
]);

const LANGUAGES: Record<string, string> = { uz: "O‘zbekcha", ru: "Русский", en: "English" };
const details = computed<DescriptionItem[]>(() => [
  { key: "position", label: t("people.col.position"), value: props.person.position?.name ?? null },
  { key: "role", label: t("people.col.role"), value: props.person.role?.name ?? null },
  { key: "home", label: t("people.field.homeBranch"), value: props.person.home_branch?.name ?? null },
  { key: "branches", label: t("people.field.branches"), value: props.person.branches.map((b) => b.name).join(", ") || null },
  { key: "phone", label: t("people.col.phone"), value: props.person.phone ? formatPhone(props.person.phone) : null, copy: true },
  { key: "telegram", label: "Telegram", value: props.person.username ? `@${props.person.username}` : null, copy: true },
  { key: "language", label: t("people.field.language"), value: LANGUAGES[props.person.language] ?? props.person.language },
  { key: "joined", label: t("people.col.joined"), value: o.value.joined_on ? fmt.day(o.value.joined_on, "long") : null },
]);

function span(first: string, last: string): string {
  return first === last ? fmt.day(first, "medium") : fmt.range({ from: first, to: last });
}
</script>

<template>
  <div class="grid grid-cols-1 gap-5 lg:grid-cols-3">
    <div class="flex min-w-0 flex-col gap-5 lg:col-span-2">
      <ChartCard
        :title="t('people.overview.trendTitle')"
        :subtitle="t('people.overview.trendSubtitle')"
        :value="o.on_time_percent !== null ? fmt.percent(o.on_time_percent, 1) : undefined"
        :empty="!hasTrend"
        :empty-text="t('people.overview.trendEmpty')"
        :csv="csv"
      >
        <LineChart :categories="categories" :series="series" value-format="percent" x-format="day" height="220px" :target="{ value: 90, label: t('people.overview.goal') }" smooth />
      </ChartCard>

      <section class="ui-card p-5">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="text-md font-semibold text-fg">{{ t("people.overview.monthTitle") }}</h2>
          <span class="text-sm text-muted">{{ fmt.range(o.range) }}</span>
        </div>
        <template v-if="o.total">
          <ProgressBar class="mt-4" size="lg" :segments="split" :max="o.total" :label="t('people.overview.monthTitle')" />
          <dl class="mt-4 grid grid-cols-3 gap-3">
            <div v-for="part in split" :key="part.label" class="min-w-0">
              <dt class="flex items-center gap-1.5 text-xs font-medium text-muted"><span class="size-2 rounded-full" :style="{ background: part.color }" />{{ part.label }}</dt>
              <dd class="mt-0.5 text-lg font-semibold tabular-nums text-fg">{{ part.value }}</dd>
            </div>
          </dl>
          <p v-if="o.streak" class="mt-4 inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-sm font-medium text-accent-fg">
            <Flame :size="14" aria-hidden="true" />{{ t("people.overview.streak", { n: o.streak }, o.streak) }}
          </p>
        </template>
        <EmptyState v-else size="sm" tone="neutral" :icon="CalendarDays" :title="t('people.overview.noWorkTitle')" :description="t('people.overview.noWorkBody')" />
      </section>
    </div>

    <div class="flex min-w-0 flex-col gap-5">
      <section class="ui-card p-5">
        <h2 class="mb-1 text-md font-semibold text-fg">{{ t("people.overview.details") }}</h2>
        <DescriptionList :items="details" layout="rows" />
      </section>

      <section class="ui-card p-5">
        <div class="mb-3 flex items-center justify-between gap-2">
          <h2 class="text-md font-semibold text-fg">{{ t("people.overview.timeOff") }}</h2>
          <RouterLink
            v-if="person.can.record_time_off"
            :to="{ path: `/c/${company.currentId}/time-off`, query: { record: String(person.id) } }"
            class="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            <CalendarPlus :size="14" aria-hidden="true" />{{ t("people.action.recordTimeOff") }}
          </RouterLink>
        </div>
        <ul v-if="o.upcoming_time_off.length" class="flex flex-col divide-y divide-[var(--c-border)]">
          <li v-for="item in o.upcoming_time_off" :key="item.id" class="flex items-center gap-3 py-2.5">
            <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-info-soft text-info"><CalendarDays :size="16" aria-hidden="true" /></span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-medium text-fg">{{ span(item.first_day, item.last_day) }}</p>
              <p v-if="item.reason" class="truncate text-xs text-muted">{{ item.reason }}</p>
            </div>
            <StatusPill size="sm" :tone="item.status === 'approved' ? 'success' : 'warning'" :label="t(`people.timeOff.${item.status}`)" />
          </li>
        </ul>
        <p v-else class="text-sm text-muted">{{ t("people.overview.noTimeOff") }}</p>
        <p class="mt-3 text-xs text-subtle">{{ t("people.overview.daysOffThisYear", { n: o.days_off_this_year }, o.days_off_this_year) }}</p>
      </section>
    </div>
  </div>
</template>
