<script setup lang="ts">
/**
 * Training at a glance (docs/PLAN-LEARNING.md §11): how much of the mandatory training is done,
 * who is late, time watched this week and day by day, every live course's completion, and the
 * cards the quizzes and recognition modules add (`learning.overview.cards`). Branch-scoped.
 */
import { AlarmClock, GraduationCap, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

import { useOverview } from "../api";

const { t } = useI18n();
const company = useCompanyStore();
const router = useRouter();

const params = computed(() => ({ branch: company.branchFilter.length === 1 ? company.branchFilter[0] : undefined }));
const overview = useOverview(params);
const data = computed(() => overview.data.value);
const canManage = computed(() => company.can("learning.manage"));
const base = computed(() => `/c/${company.currentId}/learning`);

const kpis = computed(() => {
  const value = data.value;
  return [
    { id: "people", label: t("learning.kpi.people"), value: value?.compliance.people ?? null, format: "number" as const, hint: t("learning.kpi.peopleHint") },
    { id: "done", label: t("learning.kpi.done"), value: value?.compliance.completed ?? null, format: "number" as const },
    { id: "late", label: t("learning.kpi.late"), value: value?.compliance.overdue_people ?? null, format: "number" as const, to: `${base.value}/people?late=1` },
    { id: "watched", label: t("learning.kpi.watched"), value: value ? Math.round(value.watched_week_seconds / 60) : null, format: "duration" as const, hint: t("learning.kpi.watchedHint") },
  ];
});

const days = computed(() => (data.value?.activity ?? []).map((row) => row.day));
const series = computed(() => [
  { name: t("learning.chart.minutes"), data: (data.value?.activity ?? []).map((row) => Math.round(row.seconds / 60)) },
]);
const quiet = computed(() => (data.value?.activity ?? []).every((row) => !row.seconds));

function openCourse(id: number): void {
  void router.push(`${base.value}/courses/${id}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('learning.nav.overview')" :description="t('learning.overview.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" :to="`${base}/courses?new=1`">{{ t("learning.courses.new") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="overview.isError.value" :error="overview.error.value" :retry="() => overview.refetch()" />
    <template v-else>
      <div class="mb-4 grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <section class="ui-card flex items-center gap-4 p-5" :aria-label="t('learning.overview.compliance')">
          <SkeletonBlock v-if="!data" width="88px" height="88px" radius="999px" />
          <ProgressRing v-else :value="data.compliance.percent" :max="100" :size="88" :stroke="9" tone="auto" show-value :label="t('learning.overview.compliance')" />
          <div class="min-w-0">
            <h2 class="text-base font-semibold text-fg">{{ t("learning.overview.compliance") }}</h2>
            <p class="text-sm text-muted">
              {{ data ? t("learning.overview.complianceBody", { done: data.compliance.completed, people: data.compliance.people }) : "" }}
            </p>
          </div>
        </section>
        <KpiStrip :items="kpis" :loading="!data" :columns="4" phone="grid" />
      </div>

      <div class="mb-4 grid gap-4 xl:grid-cols-2">
        <ChartCard :title="t('learning.chart.title')" :subtitle="t('learning.chart.subtitle')" :loading="!data" :empty="quiet" :empty-text="t('learning.chart.empty')" height="220px">
          <BarChart :categories="days" :series="series" x-format="day" height="220px" integer :label="t('learning.chart.title')" />
        </ChartCard>

        <section class="ui-card flex flex-col p-4" :aria-label="t('learning.overview.late')">
          <div class="mb-3 flex items-center gap-2">
            <AlarmClock :size="18" class="text-warning" aria-hidden="true" />
            <h2 class="text-sm font-semibold text-fg">{{ t("learning.overview.late") }}</h2>
          </div>
          <template v-if="!data">
            <SkeletonBlock v-for="n in 4" :key="n" height="40px" radius="8px" class="mb-2" />
          </template>
          <EmptyState v-else-if="!data.late.length" size="sm" tone="success" :title="t('learning.overview.nobodyLate')" />
          <ul v-else class="flex flex-col">
            <li v-for="row in data.late" :key="`${row.member.id}-${row.course.id}`" class="flex items-center gap-3 border-b border-line py-2 last:border-0">
              <PersonCell :person="row.member" :subtitle="row.course.title" class="min-w-0 flex-1" />
              <StatusPill size="sm" tone="danger" :label="t('learning.daysLate', { n: row.days_late }, row.days_late)" />
            </li>
          </ul>
        </section>
      </div>

      <section class="ui-card mb-4 p-4" :aria-label="t('learning.overview.courses')">
        <h2 class="mb-3 text-sm font-semibold text-fg">{{ t("learning.overview.courses") }}</h2>
        <template v-if="!data">
          <SkeletonBlock v-for="n in 3" :key="n" height="44px" radius="8px" class="mb-2" />
        </template>
        <EmptyState v-else-if="!data.courses.length" size="sm" :icon="GraduationCap" :title="t('learning.overview.noCourses')" :description="t('learning.overview.noCoursesBody')">
          <UiButton v-if="canManage" size="sm" variant="primary" :icon="Plus" :to="`${base}/courses?new=1`">{{ t("learning.courses.new") }}</UiButton>
        </EmptyState>
        <ul v-else class="flex flex-col gap-1">
          <li v-for="course in data.courses" :key="course.id">
            <button type="button" class="flex w-full flex-wrap items-center gap-x-4 gap-y-1 rounded-[10px] px-2 py-2 text-left hover:bg-surface-2" @click="openCourse(course.id)">
              <span class="flex min-w-0 flex-1 items-center gap-2">
                <span aria-hidden="true">{{ course.emoji || "📘" }}</span>
                <span class="truncate text-sm font-medium text-fg">{{ course.title }}</span>
                <StatusPill v-if="course.mandatory" size="sm" variant="outline" tone="primary" :label="t('learning.mandatory')" />
              </span>
              <span class="flex w-full items-center gap-3 sm:w-72">
                <ProgressBar class="flex-1" size="sm" :value="course.completed" :max="course.people || 1" tone="auto" />
                <span class="w-24 text-right text-xs text-muted tabular-nums">{{ t("learning.ofPeople", { done: course.completed, people: course.people }) }}</span>
              </span>
              <!-- The late count has a place of its own on every row, so all the bars line up. -->
              <span class="flex justify-end sm:w-32">
                <StatusPill v-if="course.overdue" size="sm" tone="danger" variant="plain" :label="t('learning.lateCount', { n: course.overdue }, course.overdue)" />
              </span>
            </button>
          </li>
        </ul>
      </section>

      <ExtensionSlot name="learning.overview.cards" :context="{ companyId: company.currentId }" class="grid gap-4 xl:grid-cols-2" />
    </template>
    <p v-if="data && data.counts.processing_videos" class="mt-4 text-xs text-muted">
      {{ t("learning.overview.processing", { n: data.counts.processing_videos }, data.counts.processing_videos) }}
    </p>
  </div>
</template>
