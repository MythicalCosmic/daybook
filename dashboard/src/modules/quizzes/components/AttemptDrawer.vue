<script setup lang="ts">
/** One attempt with every answer: what the person chose, right or not, the right answer and the
 * explanation (a manager sees the answers whatever the quiz shows the person). */
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useFormat } from "@/lib/useFormat";

import { useAttempt } from "../api";
import QuestionPreview from "./QuestionPreview.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ attemptId: number | null }>();

const { t } = useI18n();
const fmt = useFormat();
const attempt = useAttempt(() => (open.value ? props.attemptId : null));
</script>

<template>
  <UiDrawer v-model:open="open" :title="attempt.data.value ? t('quizzes.attempt.title', { name: attempt.data.value.member.name }) : t('quizzes.attempt.loading')" size="lg">
    <div v-if="attempt.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="96px" radius="12px" /></div>
    <ErrorState v-else-if="attempt.error.value" :error="attempt.error.value" :retry="() => attempt.refetch()" />
    <div v-else-if="attempt.data.value" class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2 text-sm text-muted">
        <StatusPill :tone="attempt.data.value.passed ? 'success' : 'danger'" :label="attempt.data.value.passed ? t('quizzes.results.passed') : t('quizzes.results.failed')" />
        <span class="font-semibold text-fg">{{ attempt.data.value.percent }} %</span>
        <span>· {{ t("quizzes.attempt.score", { score: attempt.data.value.score, max: attempt.data.value.max_score }) }}</span>
        <span>· {{ attempt.data.value.quiz.title }}, {{ t("quizzes.attempt.number", { n: attempt.data.value.number }) }}</span>
        <span v-if="attempt.data.value.finished_at">· {{ fmt.instant(attempt.data.value.finished_at) }}</span>
        <StatusPill v-if="attempt.data.value.state === 'expired'" size="sm" tone="warning" :label="t('quizzes.attemptState.expired')" />
        <StatusPill v-if="attempt.data.value.trial" size="sm" tone="neutral" :label="t('quizzes.attempt.trial')" />
      </div>
      <ol class="flex flex-col gap-3">
        <li v-for="(row, index) in attempt.data.value.review ?? []" :key="index" class="rounded-xl border p-4" :class="row.correct ? 'border-success/40' : 'border-danger/40'">
          <p class="mb-2 text-xs font-semibold uppercase tracking-wide" :class="row.correct ? 'text-success' : 'text-danger'">
            {{ row.correct ? t("quizzes.attempt.right") : row.share > 0 ? t("quizzes.attempt.partly", { n: Math.round(row.share * 100) }) : row.answer ? t("quizzes.attempt.wrong") : t("quizzes.attempt.unanswered") }}
          </p>
          <QuestionPreview :question="row.question" :right="row.right_answer" :answer="row.answer" :explanation="row.explanation" compact />
        </li>
      </ol>
    </div>
  </UiDrawer>
</template>
