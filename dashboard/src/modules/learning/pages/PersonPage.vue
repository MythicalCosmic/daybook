<script setup lang="ts">
/**
 * One person's training: their courses (every cycle, newest first, with the certificate), the
 * lessons they watched with the parts they played, the knowledge base pages they opened, and the
 * panels the quizzes and recognition modules add (`learning.person.panels`: results, skills,
 * points and badges).
 */
import { Award, BookOpen, GraduationCap, PlayCircle } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { learningApi, usePerson } from "../api";
import { STATE_TONES } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const cid = useCompanyId();

const id = computed(() => Number(route.params.memberId));
const person = usePerson(id);
const data = computed(() => person.data.value);
const kpis = computed(() => {
  const summary = data.value?.summary;
  return [
    { id: "open", label: t("learning.person.open"), value: summary?.open ?? null, format: "number" as const },
    { id: "completed", label: t("learning.person.completed"), value: summary?.completed ?? null, format: "number" as const },
    { id: "late", label: t("learning.person.late"), value: summary?.late ?? null, format: "number" as const },
    { id: "watched", label: t("learning.person.watched"), value: summary ? Math.round(summary.watched_seconds / 60) : null, format: "duration" as const },
  ];
});

async function certificate(assignmentId: number): Promise<void> {
  const link = await learningApi.certificate(cid.value, assignmentId);
  window.open(link.url, "_blank", "noopener");
}
</script>

<template>
  <div>
    <ErrorState v-if="person.isError.value" :error="person.error.value" :retry="() => person.refetch()" />
    <template v-else-if="!data">
      <SkeletonBlock height="72px" radius="12px" class="mb-4" />
      <SkeletonBlock v-for="n in 4" :key="n" height="48px" radius="10px" class="mb-2" />
    </template>
    <template v-else>
      <PageHeader :title="data.member.name" :description="[data.member.position, data.member.branch].filter(Boolean).join(' · ')" :back="`/c/${company.currentId}/learning/people`" :back-label="t('learning.nav.people')" />
      <KpiStrip class="mb-4" :items="kpis" :columns="4" phone="grid" />

      <section class="ui-card mb-4 p-4" :aria-label="t('learning.person.courses')">
        <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold text-fg"><GraduationCap :size="16" aria-hidden="true" />{{ t("learning.person.courses") }}</h2>
        <EmptyState v-if="!data.assignments.length" size="sm" :title="t('learning.person.noCourses')" />
        <ul v-else class="flex flex-col divide-y divide-line">
          <li v-for="row in data.assignments" :key="row.id" class="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
            <RouterLink :to="`/c/${company.currentId}/learning/courses/${row.course.id}`" class="min-w-0 flex-1 basis-48 truncate text-sm font-medium text-fg hover:underline">
              {{ row.course.emoji ? `${row.course.emoji} ` : "" }}{{ row.course.title }}
              <span v-if="row.cycle > 1" class="text-xs font-normal text-muted"> · {{ t("learning.person.cycle", { n: row.cycle }) }}</span>
            </RouterLink>
            <div class="flex w-full items-center gap-2 sm:w-44">
              <ProgressBar class="flex-1" size="sm" :value="row.percent" :max="100" tone="auto" :label="row.course.title" />
              <span class="w-12 text-right text-xs text-muted tabular-nums">{{ row.steps_done }}/{{ row.steps_total }}</span>
            </div>
            <StatusPill v-if="row.late" size="sm" tone="danger" :label="t('learning.daysLate', { n: row.days_late }, row.days_late)" />
            <StatusPill v-else size="sm" :tone="STATE_TONES[row.state]" :label="t(`learning.state.${row.state}`)" />
            <UiButton v-if="row.certificate_no" size="sm" variant="ghost" :icon="Award" @click="certificate(row.id)">{{ row.certificate_no }}</UiButton>
          </li>
        </ul>
      </section>

      <div class="mb-4 grid gap-4 xl:grid-cols-2">
        <section class="ui-card p-4" :aria-label="t('learning.person.lessons')">
          <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold text-fg"><PlayCircle :size="16" aria-hidden="true" />{{ t("learning.person.lessons") }}</h2>
          <EmptyState v-if="!data.lessons.length" size="sm" :title="t('learning.person.noLessons')" />
          <ul v-else class="flex flex-col gap-3">
            <li v-for="row in data.lessons" :key="row.lesson.id" class="flex flex-col gap-1">
              <div class="flex items-center gap-2">
                <RouterLink :to="`/c/${company.currentId}/learning/lessons/${row.lesson.id}`" class="min-w-0 flex-1 truncate text-sm text-fg hover:underline">{{ row.lesson.emoji ? `${row.lesson.emoji} ` : "" }}{{ row.lesson.title }}</RouterLink>
                <StatusPill size="sm" :tone="row.completed_at ? 'success' : 'info'" :label="row.completed_at ? t('learning.watched.watched') : `${row.percent}%`" />
              </div>
              <ProgressBar size="xs" :value="row.percent" :max="100" :tone="row.completed_at ? 'success' : 'info'" :label="row.lesson.title" />
              <span class="text-[11px] text-subtle">{{ t("learning.person.spent", { time: fmt.duration(Math.round(row.spent_seconds / 60)), sessions: row.sessions }) }} · <RelativeTime :value="row.last_at" /></span>
            </li>
          </ul>
        </section>
        <section class="ui-card p-4" :aria-label="t('learning.person.pages')">
          <h2 class="mb-3 flex items-center gap-2 text-sm font-semibold text-fg"><BookOpen :size="16" aria-hidden="true" />{{ t("learning.person.pages") }}</h2>
          <EmptyState v-if="!data.pages.length" size="sm" :title="t('learning.person.noPages')" />
          <ul v-else class="flex flex-col divide-y divide-line">
            <li v-for="row in data.pages" :key="row.page.id" class="flex items-center gap-3 py-2">
              <RouterLink :to="`/c/${company.currentId}/knowledge/p/${row.page.id}`" class="min-w-0 flex-1 truncate text-sm text-fg hover:underline">{{ row.page.emoji ? `${row.page.emoji} ` : "" }}{{ row.page.title }}</RouterLink>
              <span class="text-xs text-muted tabular-nums">{{ t("learning.person.read", { visits: row.visits, time: fmt.duration(Math.max(1, Math.round(row.seconds / 60))), scrolled: row.scrolled }) }}</span>
            </li>
          </ul>
        </section>
      </div>

      <ExtensionSlot name="learning.person.panels" :context="{ companyId: company.currentId, memberId: id }" class="grid gap-4 xl:grid-cols-2" />
    </template>
  </div>
</template>
