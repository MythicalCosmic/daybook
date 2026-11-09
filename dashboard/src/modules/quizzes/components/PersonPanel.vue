<script setup lang="ts">
/**
 * On learning's person page (the slot `learning.person.panels`): the person's mastery of each
 * topic they answered in, weakest first, their latest quizzes and checks, and the question of the
 * day over the last 30 days.
 */
import { GraduationCap } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { usePersonSkills } from "../api";
import { BAND_CELL, BAND_TONE } from "../lib";

const props = defineProps<{ context: { companyId: number; memberId: number } }>();
const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const allowed = computed(() => company.can(["learning.view", "learning.manage"]));
const skills = usePersonSkills(() => (allowed.value ? props.context.memberId : 0));
</script>

<template>
  <section v-if="allowed" class="ui-card flex flex-col gap-4 p-4" data-testid="quizzes-person-panel">
    <div class="flex items-center gap-2">
      <GraduationCap :size="18" class="text-muted" aria-hidden="true" />
      <h3 class="text-md font-semibold text-fg">{{ t("quizzes.person.title") }}</h3>
    </div>
    <SkeletonBlock v-if="skills.isPending.value" height="96px" />
    <template v-else-if="skills.data.value">
      <div v-if="skills.data.value.topics.length" class="flex flex-col gap-2">
        <div v-for="row in skills.data.value.topics" :key="row.topic.id" class="flex items-center gap-3 text-sm">
          <span class="w-40 shrink-0 truncate text-fg">{{ row.topic.name }}</span>
          <ProgressBar :value="row.score ?? 0" :max="100" size="sm" :tone="BAND_TONE[row.band] === 'neutral' ? 'neutral' : BAND_TONE[row.band]" class="flex-1" />
          <span class="w-12 text-right font-semibold tabular-nums" :class="BAND_CELL[row.band].split(' ')[1]">{{ row.score ?? "—" }}</span>
          <span class="w-20 text-right text-xs text-muted">{{ t("quizzes.person.answers", { n: row.answers }, row.answers) }}</span>
        </div>
      </div>
      <p v-else class="text-sm text-muted">{{ t("quizzes.person.noAnswers") }}</p>

      <div v-if="skills.data.value.attempts.length">
        <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{{ t("quizzes.person.recent") }}</p>
        <ul class="divide-y divide-line rounded-lg border border-line">
          <li v-for="attempt in skills.data.value.attempts.slice(0, 8)" :key="attempt.id" class="flex items-center gap-3 px-3 py-2 text-sm">
            <span class="min-w-0 flex-1 truncate text-fg">{{ attempt.quiz.title }}</span>
            <StatusPill v-if="attempt.check" size="sm" variant="plain" tone="neutral" :label="t('quizzes.results.check')" />
            <span class="tabular-nums text-fg">{{ attempt.percent ?? "—" }} %</span>
            <StatusPill size="sm" :tone="attempt.passed ? 'success' : 'danger'" :label="attempt.passed ? t('quizzes.results.passed') : t('quizzes.results.failed')" />
            <span class="hidden w-28 text-right text-xs text-muted sm:inline">{{ attempt.finished_at ? fmt.instant(attempt.finished_at, "short") : "" }}</span>
          </li>
        </ul>
      </div>
      <p class="text-sm text-muted">{{ t("quizzes.person.daily", { asked: skills.data.value.daily.asked, answered: skills.data.value.daily.answered, right: skills.data.value.daily.right }) }}</p>
    </template>
  </section>
</template>
