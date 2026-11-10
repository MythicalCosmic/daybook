<script setup lang="ts">
/**
 * A card of "Ask the tutor": what one of its draft tools made, live. A questions card shows each
 * question as the learner will see it, the right answer marked, with Approve (into use), Edit
 * (the bank's editor) and Discard; a quiz card shows the draft test with "Approve and publish"
 * (its draft questions go into use and the test is published) and a link to its page. While the
 * tutor is still writing, it says so. Every decision is the person's own call to the server.
 */
import { Check, CheckCheck, CircleAlert, ClipboardCheck, ExternalLink, ListChecks, PenLine, Sparkles, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { quizzesApi, useRefresh } from "../api";
import type { Question, QuestionState, QuizStatus, TutorDraftCard, TutorDraftItem } from "../types";
import QuestionPreview from "./QuestionPreview.vue";

const props = defineProps<{ card: TutorDraftCard }>();
const emit = defineEmits<{ edit: [question: Question] }>();

const { t } = useI18n();
const cid = useCompanyId();
const refresh = useRefresh();
const confirm = useConfirm();
const busy = ref<string | null>(null);

const STATE_TONE: Record<QuestionState, "warning" | "success" | "neutral"> = { draft: "warning", active: "success", archived: "neutral" };
const QUIZ_TONE: Record<QuizStatus, "warning" | "success" | "neutral"> = { draft: "warning", published: "success", archived: "neutral" };

const live = computed(() => props.card.questions.filter((item) => !item.deleted && item.question));
const drafts = computed(() => live.value.filter((item) => item.question!.state === "draft"));
const inUse = computed(() => live.value.filter((item) => item.question!.state === "active").length);
const quiz = computed(() => props.card.quiz);
const skeletons = computed(() => Math.min(Math.max(props.card.count, 1), 3));
const minutes = computed(() => (quiz.value?.time_limit_seconds ? Math.round(quiz.value.time_limit_seconds / 60) : null));
const quizLink = computed(() => (quiz.value ? `/c/${cid.value}/learning/quizzes/${quiz.value.id}` : ""));

async function act(key: string, run: () => Promise<unknown>, done: string): Promise<void> {
  busy.value = key;
  try {
    await run();
    toast.success(done);
    refresh();
  } catch (error) {
    toast.error(isApiError(error) && error.detail ? error.detail : t("quizzes.chat.error.generic"));
  } finally {
    busy.value = null;
  }
}

const approve = (item: TutorDraftItem) =>
  act(`approve:${item.id}`, () => quizzesApi.approveTutorDraft(cid.value, props.card.id, [item.id]), t("quizzes.tutorDrafts.approved"));
const discard = (item: TutorDraftItem) =>
  act(`discard:${item.id}`, () => quizzesApi.discardTutorDraft(cid.value, props.card.id, [item.id]), t("quizzes.tutorDrafts.discarded"));
const approveAll = () => act("approve", () => quizzesApi.approveTutorDraft(cid.value, props.card.id), t("quizzes.tutorDrafts.approved"));

async function discardRest(): Promise<void> {
  const answer = await confirm({
    title: t("quizzes.tutorDrafts.discardAllTitle"),
    message: t("quizzes.tutorDrafts.discardAllBody"),
    confirmLabel: t("quizzes.tutorDrafts.discard"),
    tone: "danger",
  });
  if (answer) await act("discard", () => quizzesApi.discardTutorDraft(cid.value, props.card.id), t("quizzes.tutorDrafts.discarded"));
}

const publish = () => act("publish", () => quizzesApi.approveTutorDraft(cid.value, props.card.id), t("quizzes.tutorDrafts.published"));

async function discardQuiz(): Promise<void> {
  const answer = await confirm({
    title: t("quizzes.tutorDrafts.discardQuizTitle", { title: quiz.value?.title ?? "" }),
    message: t("quizzes.tutorDrafts.discardQuizBody"),
    confirmLabel: t("quizzes.tutorDrafts.discard"),
    tone: "danger",
  });
  if (answer) await act("discard", () => quizzesApi.discardTutorDraft(cid.value, props.card.id), t("quizzes.tutorDrafts.discarded"));
}
</script>

<template>
  <article
    class="overflow-hidden rounded-[14px] border border-line bg-surface shadow-xs"
    :data-kind="card.kind"
    :data-state="card.state"
    :aria-busy="card.state === 'running'"
    data-testid="tutor-draft"
  >
    <!-- Being written: the tool is still running. -->
    <template v-if="card.state === 'running'">
      <header class="flex items-center gap-3 px-4 py-3">
        <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-fg"><Sparkles :size="17" aria-hidden="true" /></span>
        <div class="min-w-0 flex-1">
          <p class="flex items-center gap-2 text-sm font-semibold text-fg"><UiSpinner :size="13" />{{ t("quizzes.tutorDrafts.writing") }}</p>
          <p class="truncate text-xs text-muted">{{ card.title ? t("quizzes.tutorDrafts.from", { title: card.title }) : t("quizzes.tutorDrafts.writingBody") }}</p>
        </div>
      </header>
      <div class="flex flex-col gap-2 border-t border-line px-4 py-3" aria-hidden="true">
        <div v-for="n in skeletons" :key="n" class="flex flex-col gap-2 rounded-xl border border-dashed border-line p-3">
          <SkeletonBlock height="14px" width="70%" />
          <SkeletonBlock height="32px" radius="8px" />
          <SkeletonBlock height="32px" width="85%" radius="8px" />
        </div>
      </div>
    </template>

    <!-- Nothing was written. -->
    <div v-else-if="card.state === 'failed'" class="flex items-start gap-3 px-4 py-3" role="status">
      <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-danger-soft text-danger"><CircleAlert :size="17" aria-hidden="true" /></span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">{{ t("quizzes.tutorDrafts.failed") }}</p>
        <p class="text-xs text-muted">{{ card.error || t("quizzes.chat.error.generic") }}</p>
      </div>
    </div>

    <!-- Draft questions. -->
    <template v-else-if="card.kind === 'questions'">
      <header class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-fg"><ListChecks :size="17" aria-hidden="true" /></span>
        <div class="min-w-0 flex-1 basis-40">
          <p class="text-sm font-semibold text-fg">{{ t("quizzes.tutorDrafts.questionsTitle", { n: card.questions.length }, card.questions.length) }}</p>
          <p class="truncate text-xs text-muted">
            <span v-if="card.title">{{ t("quizzes.tutorDrafts.from", { title: card.title }) }}</span>
            <span v-if="card.title && (drafts.length || inUse)"> · </span>
            <span v-if="drafts.length">{{ t("quizzes.tutorDrafts.left", { n: drafts.length }) }}</span>
            <span v-if="drafts.length && inUse"> · </span>
            <span v-if="inUse">{{ t("quizzes.tutorDrafts.inUse", { n: inUse }) }}</span>
          </p>
        </div>
        <div v-if="drafts.length > 1" class="flex shrink-0 gap-1 max-sm:w-full">
          <UiButton size="sm" variant="secondary" :icon="CheckCheck" :loading="busy === 'approve'" :disabled="!!busy" data-testid="draft-approve-all" @click="approveAll">{{ t("quizzes.tutorDrafts.approveAll") }}</UiButton>
          <UiButton size="sm" variant="ghost" :icon="Trash2" :disabled="!!busy" :aria-label="t('quizzes.tutorDrafts.discardAll')" :title="t('quizzes.tutorDrafts.discardAll')" data-testid="draft-discard-all" @click="discardRest" />
        </div>
      </header>
      <ol class="divide-y divide-line border-t border-line">
        <li v-for="(item, index) in card.questions" :key="item.id" class="px-4 py-3" data-testid="draft-question" :data-state="item.deleted || !item.question ? 'deleted' : item.question.state">
          <p v-if="item.deleted || !item.question" class="flex items-center gap-2 text-sm text-muted">
            <span class="inline-flex size-5 shrink-0 items-center justify-center rounded-md bg-surface-2 text-xs font-semibold">{{ index + 1 }}</span>{{ t("quizzes.tutorDrafts.deleted") }}
          </p>
          <template v-else>
            <div class="mb-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted">
              <span class="inline-flex size-5 shrink-0 items-center justify-center rounded-md bg-surface-2 font-semibold text-fg dark:bg-surface-3">{{ index + 1 }}</span>
              <span class="font-medium text-fg">{{ t(`quizzes.kind.${item.question.kind}`) }}</span>
              <span>· {{ t(`quizzes.difficulty.${item.question.difficulty}`) }}</span>
              <span v-if="item.question.topic" class="truncate">· {{ item.question.topic.name }}</span>
              <StatusPill class="ml-auto" size="sm" :tone="STATE_TONE[item.question.state]" :label="t(`quizzes.state.${item.question.state}`)" />
            </div>
            <QuestionPreview v-if="item.preview" :question="item.preview.question" :right="item.preview.right_answer" :explanation="item.preview.explanation" compact />
            <div v-if="item.question.state === 'draft'" class="mt-3 flex flex-wrap gap-1.5">
              <UiButton size="sm" variant="primary" :icon="Check" :loading="busy === `approve:${item.id}`" :disabled="!!busy" data-testid="draft-approve" @click="approve(item)">{{ t("quizzes.tutorDrafts.approve") }}</UiButton>
              <UiButton size="sm" variant="secondary" :icon="PenLine" :disabled="!!busy" data-testid="draft-edit" @click="emit('edit', item.question)">{{ t("quizzes.tutorDrafts.edit") }}</UiButton>
              <UiButton size="sm" variant="ghost" :icon="Trash2" :loading="busy === `discard:${item.id}`" :disabled="!!busy" data-testid="draft-discard" @click="discard(item)">{{ t("quizzes.tutorDrafts.discard") }}</UiButton>
            </div>
          </template>
        </li>
      </ol>
    </template>

    <!-- A draft test. -->
    <template v-else>
      <header class="flex items-center gap-3 px-4 py-3">
        <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-fg"><ClipboardCheck :size="17" aria-hidden="true" /></span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-fg">{{ quiz?.title ?? card.title }}</p>
          <p class="text-xs text-muted">{{ t("quizzes.tutorDrafts.quizTitle") }}</p>
        </div>
        <StatusPill v-if="quiz" size="sm" :tone="QUIZ_TONE[quiz.status]" :label="t(`quizzes.status.${quiz.status}`)" />
      </header>
      <p v-if="!quiz" class="border-t border-line px-4 py-3 text-sm text-muted">{{ t("quizzes.tutorDrafts.quizDeleted") }}</p>
      <template v-else>
        <div class="flex flex-wrap gap-1.5 border-t border-line px-4 py-3 text-xs" data-testid="draft-quiz-facts">
          <span class="rounded-full bg-surface-2 px-2.5 py-1 text-fg dark:bg-surface-3">{{ t("quizzes.tutorDrafts.quizQuestions", { n: live.length }, live.length) }}</span>
          <span v-if="drafts.length && quiz.status === 'draft'" class="rounded-full bg-warning-soft px-2.5 py-1 text-warning">{{ t("quizzes.tutorDrafts.quizDrafts", { n: drafts.length }) }}</span>
          <span class="rounded-full bg-surface-2 px-2.5 py-1 text-fg dark:bg-surface-3">{{ t("quizzes.tutorDrafts.passMark", { n: quiz.pass_percent }) }}</span>
          <span class="rounded-full bg-surface-2 px-2.5 py-1 text-fg dark:bg-surface-3">{{ minutes ? t("quizzes.tutorDrafts.timeLimit", { n: minutes }) : t("quizzes.tutorDrafts.noTimeLimit") }}</span>
          <span class="rounded-full bg-surface-2 px-2.5 py-1 text-fg dark:bg-surface-3">{{ quiz.audience_all ? t("quizzes.tutorDrafts.forAll") : t("quizzes.tutorDrafts.forPositions", { names: quiz.positions.join(", ") }) }}</span>
        </div>
        <ol v-if="live.length" class="mx-4 mb-3 flex flex-col gap-1 rounded-xl bg-surface-2/60 p-2.5 text-sm dark:bg-surface-3/60">
          <li v-for="(item, index) in live.slice(0, 6)" :key="item.id" class="flex items-start gap-2">
            <span class="w-5 shrink-0 text-right text-xs font-semibold tabular-nums text-muted">{{ index + 1 }}.</span>
            <span class="min-w-0 flex-1 truncate text-fg">{{ item.question!.text }}</span>
            <span class="mt-1.5 size-2 shrink-0 rounded-full" :class="item.question!.state === 'draft' ? 'bg-warning' : 'bg-success'" :title="t(`quizzes.state.${item.question!.state}`)" />
          </li>
          <li v-if="live.length > 6" class="pl-7 text-xs text-muted">{{ t("quizzes.tutorDrafts.more", { n: live.length - 6 }) }}</li>
        </ol>
        <div class="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-3">
          <UiButton v-if="quiz.status === 'draft'" size="sm" variant="primary" :icon="Check" :loading="busy === 'publish'" :disabled="!!busy" data-testid="draft-publish" @click="publish">{{ t("quizzes.tutorDrafts.publish") }}</UiButton>
          <UiButton size="sm" variant="secondary" :icon="ExternalLink" :to="quizLink" data-testid="draft-open-quiz">{{ t("quizzes.tutorDrafts.openQuiz") }}</UiButton>
          <UiButton v-if="quiz.status === 'draft'" size="sm" variant="ghost" :icon="Trash2" :loading="busy === 'discard'" :disabled="!!busy" data-testid="draft-discard-quiz" @click="discardQuiz">{{ t("quizzes.tutorDrafts.discard") }}</UiButton>
          <p v-if="quiz.status === 'draft' && drafts.length" class="w-full text-xs text-muted">{{ t("quizzes.tutorDrafts.publishHint") }}</p>
        </div>
      </template>
    </template>
  </article>
</template>
