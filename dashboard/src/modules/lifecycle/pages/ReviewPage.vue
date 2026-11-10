<script setup lang="ts">
/**
 * One person's review, as its reviewer writes it (plan §13.4 `Review`): every question with the
 * person's own answer beside the reviewer's, their numbers for the period (taken once, when the
 * reviewer first opens it, so they never change later), the overall rating, a short summary and
 * what follows (none, a raise, a bonus, a promotion, an improvement plan). The draft saves itself
 * as they go; Publish sends it to the person and turns the outcome into proposals that wait for
 * the usual approval. Owners read it; once published it shows where the outcome stands and the
 * plan's goals. With the AI module on, Claude may suggest the summary from the answers and the
 * numbers (an editable draft, never a rating or an outcome).
 */
import { CircleCheck, Eye, EyeOff, Lock, MessageSquareQuote, Send, Sparkles, UserRound, WandSparkles } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import GoalsCard from "../components/reviews/GoalsCard.vue";
import KpiSnapshot from "../components/reviews/KpiSnapshot.vue";
import OutcomeEditor from "../components/reviews/OutcomeEditor.vue";
import OutcomeState from "../components/reviews/OutcomeState.vue";
import RatingPills from "../components/reviews/RatingPills.vue";
import { reviewsApi, useReview, useReviewMutation, useSaveReview } from "../reviews/api";
import { answeredCount, average, managerForm, managerPayload, OUTCOME_TONES, publishProblems, ratingTone, suggestedRating, type ManagerForm } from "../reviews/lib";
import type { Review } from "../reviews/types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();

const roundId = computed(() => Number(route.params.roundId));
const reviewId = computed(() => Number(route.params.reviewId));
const query = useReview(reviewId);
const review = computed<Review | null>(() => query.data.value ?? null);
const writable = computed(() => !!review.value?.can.write);
// An owner reading someone else's review sees "the reviewer's" where its reviewer sees "yours".
const iReview = computed(() => writable.value || (!!review.value?.reviewer && review.value.reviewer.id === company.current?.membership_id));
const published = computed(() => !!review.value?.published_at);
const back = computed(() => ({ path: `/c/${company.currentId}/lifecycle/reviews/${roundId.value}` }));

// The reviewer's draft: kept here, saved a moment after each change. A rating saved earlier counts
// as picked: the overall rating no longer follows their mean.
const form = ref<ManagerForm | null>(null);
const ratingPicked = ref(false);
watch(
  review,
  (value) => {
    if (value && (form.value === null || !writable.value)) {
      form.value = managerForm(value);
      ratingPicked.value = !!value.rating;
    }
  },
  { immediate: true },
);
const save = useSaveReview(reviewId);
const savedAt = ref<string | null>(null);
let timer: ReturnType<typeof setTimeout> | null = null;
function changed(): void {
  if (!writable.value) return;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void flush(), 700);
}
async function flush(): Promise<void> {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (!form.value || !writable.value) return;
  await save.mutateAsync(managerPayload(form.value));
  savedAt.value = new Date().toISOString();
}
onBeforeUnmount(() => {
  if (timer) void flush();
});
watch(
  () => (form.value ? JSON.stringify([form.value.answers, form.value.rating, form.value.summary]) : ""),
  (_value, previous) => {
    if (previous) changed();
  },
);

const questions = computed(() => review.value?.questions ?? []);
const selfAnswers = computed(() => review.value?.self_part.answers ?? null);
const myAverage = computed(() => (form.value ? average(form.value.answers, questions.value) : null));
const suggestion = computed(() => (form.value ? suggestedRating(form.value.answers, questions.value) : null));
function rate(questionId: string, value: number | null): void {
  if (!form.value) return;
  form.value.answers = { ...form.value.answers, [questionId]: { ...form.value.answers[questionId], rating: value } };
}
function comment(questionId: string, value: string): void {
  if (!form.value) return;
  form.value.answers = { ...form.value.answers, [questionId]: { ...form.value.answers[questionId], text: value } };
}
// The overall rating follows the reviewer's own mean until they pick one themselves.
watch(suggestion, (value) => {
  if (form.value && writable.value && value && !ratingPicked.value) form.value.rating = value;
});
function pickRating(value: number | null): void {
  if (!form.value) return;
  ratingPicked.value = value !== null;
  form.value.rating = value;
}

const problems = computed(() => (form.value ? publishProblems(form.value, questions.value, today.value) : []));
const publish = useReviewMutation((cid, id: number) => reviewsApi.publish(cid, id));
async function runPublish(): Promise<void> {
  if (!review.value || !form.value || problems.value.length) return;
  const outcome = form.value.outcome;
  const answer = await confirm({
    title: t("lifecycle.reviews.publishTitle", { name: review.value.member.name }),
    message: t(`lifecycle.reviews.publishBody.${outcome}`),
    confirmLabel: t("lifecycle.reviews.publish"),
    icon: Send,
  });
  if (!answer) return;
  await flush();
  await publish.mutateAsync(review.value.id);
  toast.success(t("lifecycle.reviews.published", { name: review.value.member.name }));
}

// "Draft with AI": Claude's suggestion goes into the summary box as the reviewer's own draft (it
// saves like their words and changes freely); it follows the answers as saved, so they go first.
const drafting = useReviewMutation((cid, id: number) => reviewsApi.draftSummary(cid, id), { refresh: false });
const drafted = ref(false);
const mayDraft = computed(() => writable.value && !!review.value?.can.draft_summary);
const hasAnswers = computed(() => !!form.value && answeredCount(form.value.answers, questions.value) > 0);
async function runDraft(): Promise<void> {
  if (!review.value || !form.value || !hasAnswers.value) return;
  if (form.value.summary.trim()) {
    const answer = await confirm({
      title: t("lifecycle.reviews.draftReplaceTitle"),
      message: t("lifecycle.reviews.draftReplaceBody"),
      confirmLabel: t("lifecycle.reviews.draftReplace"),
      icon: WandSparkles,
    });
    if (!answer) return;
  }
  try {
    await flush();
    const result = await drafting.mutateAsync(review.value.id);
    if (!form.value) return;
    form.value.summary = result.summary;
    drafted.value = true;
  } catch {
    // The request's own toast says what went wrong; the summary stays as it was.
  }
}

const selfHidden = computed(() => review.value && !review.value.self_part.visible);
const stageNote = computed(() => {
  const value = review.value;
  if (!value || published.value) return null;
  if (value.round.status === "self") return t("lifecycle.reviews.partLater", { date: fmt.day(value.round.self_due_on, "medium") });
  if (value.round.status === "closed") return t("lifecycle.reviews.roundClosed");
  if (!writable.value) return t("lifecycle.reviews.readOnly", { name: value.reviewer?.name ?? "—" });
  return null;
});
</script>

<template>
  <div class="flex flex-col gap-5">
    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock height="64px" radius="14px" />
      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <SkeletonBlock height="520px" radius="16px" />
        <SkeletonBlock height="360px" radius="16px" />
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value || !review || !form" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <PageHeader :title="review.member.name" :description="`${review.round.name} · ${fmt.day(review.round.period_start, 'medium')} – ${fmt.day(review.round.period_end, 'medium')}`" :back="back" :back-label="review.round.name">
        <template #meta>
          <StatusPill v-if="published" size="sm" tone="success" :icon="CircleCheck" :label="t('lifecycle.reviews.managerState.published')" />
          <StatusPill v-else size="sm" :tone="review.manager_state === 'draft' ? 'info' : 'neutral'" :label="t(`lifecycle.reviews.managerState.${review.manager_state}`)" />
        </template>
        <template #actions>
          <span v-if="writable" class="text-xs text-muted" aria-live="polite" data-save-state>
            {{ save.isPending.value ? t("lifecycle.reviews.saving") : savedAt || review.manager_saved_at ? t("lifecycle.reviews.saved") : "" }}
          </span>
          <UiButton v-if="writable" variant="primary" :icon="Send" :loading="publish.isPending.value" :disabled="problems.length > 0" @click="runPublish">{{ t("lifecycle.reviews.publish") }}</UiButton>
        </template>
      </PageHeader>

      <InlineAlert v-if="stageNote" tone="info" size="sm" :icon="Lock" :description="stageNote" />

      <div class="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:grid-rows-[auto_1fr]">
        <!-- Who, and their numbers: first on a phone, beside the answers on a wide screen -->
        <div class="flex flex-col gap-4 lg:col-start-2 lg:row-start-1">
          <!-- Who: the two averages beside them on a wide card, under them in the narrow column -->
          <section class="@container ui-card p-4" data-person>
            <div class="flex flex-col gap-3 @[26rem]:flex-row @[26rem]:items-center">
              <div class="flex min-w-0 flex-1 items-center gap-3">
                <UserAvatar :name="review.member.name" :src="review.member.photo_url" :size="44" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-fg">{{ review.member.name }}</p>
                  <p class="truncate text-xs text-muted">{{ [review.position, review.home_branch?.name].filter(Boolean).join(" · ") }}</p>
                  <p class="mt-0.5 flex items-start gap-1 text-xs text-subtle">
                    <UserRound :size="12" class="mt-0.5 shrink-0" aria-hidden="true" /><span class="min-w-0 break-words">{{ t("lifecycle.reviews.reviewerLine", { name: review.reviewer?.name ?? "—" }) }}</span>
                  </p>
                </div>
              </div>
              <div class="grid shrink-0 grid-cols-2 gap-2 text-center">
                <div class="rounded-[10px] bg-surface-2 px-2.5 py-1.5 dark:bg-surface-3">
                  <p class="text-[11px] text-muted">{{ t("lifecycle.reviews.theirs") }}</p>
                  <p class="text-sm font-semibold tabular-nums text-fg">{{ review.self_part.average ? fmt.number(review.self_part.average, 1) : "—" }}</p>
                </div>
                <div class="rounded-[10px] bg-surface-2 px-2.5 py-1.5 dark:bg-surface-3">
                  <p class="text-[11px] text-muted">{{ iReview ? t("lifecycle.reviews.yours") : t("lifecycle.reviews.reviewerShort") }}</p>
                  <p class="text-sm font-semibold tabular-nums text-fg">{{ myAverage === null ? "—" : fmt.number(myAverage, 1) }}</p>
                </div>
              </div>
            </div>
          </section>
          <KpiSnapshot :kpis="review.kpis" :taken-at="review.kpis_at" compact />
          <section v-if="review.earlier.length" class="ui-card p-4" data-earlier>
            <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("lifecycle.reviews.earlier") }}</h3>
            <ul class="flex flex-col gap-1.5">
              <li v-for="item in review.earlier" :key="item.id" class="flex items-center justify-between gap-2 text-sm">
                <span class="min-w-0 truncate text-muted">{{ item.round }}</span>
                <span class="flex shrink-0 items-center gap-1.5">
                  <StatusPill size="sm" variant="outline" :tone="OUTCOME_TONES[item.outcome]" :label="t(`lifecycle.reviews.outcome.${item.outcome}`)" />
                  <StatusPill size="sm" :tone="ratingTone(item.rating)" :label="item.rating ? `${item.rating}/5` : '—'" />
                </span>
              </li>
            </ul>
          </section>
        </div>

        <!-- The answers, side by side -->
        <section class="ui-card p-4 sm:p-5 lg:col-start-1 lg:row-span-2 lg:row-start-1" data-answers>
          <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-base font-semibold text-fg">{{ t("lifecycle.reviews.answers") }}</h2>
            <p class="flex items-center gap-1.5 text-xs text-muted">
              <component :is="selfHidden ? EyeOff : Eye" :size="14" aria-hidden="true" />
              <template v-if="selfHidden">{{ t("lifecycle.reviews.selfHidden") }}</template>
              <template v-else-if="review.self_part.state === 'sent' && review.self_part.sent_at">{{ t("lifecycle.reviews.selfSentAt", { date: fmt.instant(review.self_part.sent_at, "short") }) }}</template>
              <template v-else>{{ t("lifecycle.reviews.selfNotSent") }}</template>
            </p>
          </div>
          <ol class="flex flex-col divide-y divide-line">
            <li v-for="(question, index) in questions" :key="question.id" class="py-4 first:pt-0 last:pb-0" :data-question="question.id">
              <p class="mb-3 flex gap-2 text-sm font-medium text-fg">
                <span class="grid size-6 shrink-0 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary">{{ index + 1 }}</span>
                <span class="pt-0.5">{{ question.text }}</span>
              </p>
              <div class="grid gap-3 pl-8 sm:grid-cols-2">
                <div class="rounded-[12px] bg-surface-2/60 p-3 dark:bg-surface-3/40" data-their-answer>
                  <p class="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-subtle"><MessageSquareQuote :size="12" aria-hidden="true" />{{ t("lifecycle.reviews.theirAnswer") }}</p>
                  <template v-if="selfHidden || !selfAnswers">
                    <p class="text-sm text-subtle">{{ selfHidden ? t("lifecycle.reviews.hiddenShort") : t("lifecycle.reviews.notAnswered") }}</p>
                  </template>
                  <template v-else>
                    <RatingPills v-if="question.kind === 'rating'" :model-value="selfAnswers[question.id]?.rating ?? null" readonly size="sm" />
                    <p v-if="selfAnswers[question.id]?.text" class="mt-1 whitespace-pre-line text-sm text-fg">{{ selfAnswers[question.id]?.text }}</p>
                    <p v-else-if="question.kind === 'text'" class="text-sm text-subtle">{{ t("lifecycle.reviews.notAnswered") }}</p>
                  </template>
                </div>
                <div class="rounded-[12px] border border-line p-3" data-my-answer>
                  <p class="mb-2 text-[11px] font-medium uppercase tracking-wide text-subtle">{{ iReview ? t("lifecycle.reviews.yourAnswer") : t("lifecycle.reviews.reviewerAnswer") }}</p>
                  <RatingPills
                    v-if="question.kind === 'rating'"
                    :model-value="form.answers[question.id]?.rating ?? null"
                    :readonly="!writable"
                    size="sm"
                    :mark="selfAnswers?.[question.id]?.rating ?? null"
                    @update:model-value="(value) => rate(question.id, value)"
                  />
                  <TextArea
                    v-if="writable"
                    :model-value="form.answers[question.id]?.text ?? ''"
                    :rows="question.kind === 'text' ? 3 : 1"
                    autosize
                    :max-rows="8"
                    :maxlength="2000"
                    :placeholder="question.kind === 'text' ? t('lifecycle.reviews.answerPlaceholder') : t('lifecycle.reviews.commentPlaceholder')"
                    class="mt-1"
                    @update:model-value="(value: string | null) => comment(question.id, value ?? '')"
                  />
                  <p v-else-if="form.answers[question.id]?.text" class="mt-1 whitespace-pre-line text-sm text-fg">{{ form.answers[question.id]?.text }}</p>
                  <p v-else-if="question.kind === 'text'" class="text-sm text-subtle">—</p>
                </div>
              </div>
            </li>
          </ol>
        </section>

        <!-- The overall rating, the summary, what follows -->
        <div class="flex flex-col gap-4 lg:sticky lg:top-4 lg:col-start-2 lg:row-start-2">
          <section class="ui-card p-4 sm:p-5" data-overall>
            <h2 class="mb-3 text-base font-semibold text-fg">{{ t("lifecycle.reviews.overall") }}</h2>
            <RatingPills :model-value="form.rating" :readonly="!writable" :label="t('lifecycle.reviews.overall')" @update:model-value="pickRating" />
            <p v-if="writable && suggestion" class="mt-1 text-xs text-subtle">{{ t("lifecycle.reviews.suggestion", { value: fmt.number(myAverage ?? 0, 1) }) }}</p>
            <div class="mt-4">
              <div class="mb-1.5 flex min-h-8 items-center justify-between gap-2">
                <label class="block text-sm font-medium text-fg" for="review-summary">{{ t("lifecycle.reviews.summary") }}</label>
                <UiButton v-if="mayDraft" size="sm" variant="ghost" :icon="WandSparkles" :loading="drafting.isPending.value" :disabled="!hasAnswers" data-draft-summary @click="runDraft">{{ t("lifecycle.reviews.draftSummary") }}</UiButton>
              </div>
              <TextArea v-if="writable" id="review-summary" v-model="form.summary" :rows="3" autosize :max-rows="10" :maxlength="2000" :placeholder="t('lifecycle.reviews.summaryPlaceholder')" />
              <p v-else class="whitespace-pre-line text-sm text-fg">{{ form.summary || "—" }}</p>
              <p v-if="mayDraft && drafted" class="mt-1.5 flex items-start gap-1.5 text-xs text-muted" data-drafted>
                <Sparkles :size="12" class="mt-0.5 shrink-0 text-primary" aria-hidden="true" />{{ t("lifecycle.reviews.draftedHint") }}
              </p>
              <p v-else-if="mayDraft && !hasAnswers" class="mt-1.5 text-xs text-subtle">{{ t("lifecycle.reviews.draftNeedsAnswers") }}</p>
            </div>
          </section>

          <section class="ui-card p-4 sm:p-5" data-outcome-card>
            <h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg"><Sparkles :size="16" class="text-primary" aria-hidden="true" />{{ t("lifecycle.reviews.whatFollows") }}</h2>
            <OutcomeEditor v-if="writable" v-model="form" :review="review" :today="today" @change="changed" />
            <OutcomeState v-else-if="published" :review="review" />
            <p v-else class="text-sm text-muted">{{ t("lifecycle.reviews.notYet") }}</p>
            <div v-if="published && review.goals.length" class="mt-4">
              <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("lifecycle.reviews.goals") }}</h3>
              <GoalsCard :goals="review.goals" :editable="review.can.goals" />
            </div>
            <p v-if="published" class="mt-4 text-xs text-muted">
              {{ t("lifecycle.reviews.publishedLine", { date: fmt.instant(review.published_at!, "short"), name: review.published_by?.name ?? "—" }) }}
              ·
              <template v-if="review.acknowledged_at">{{ t("lifecycle.reviews.readOn", { date: fmt.instant(review.acknowledged_at, "short") }) }}</template>
              <template v-else>{{ t("lifecycle.reviews.notReadYet") }}</template>
            </p>
          </section>

          <section v-if="writable && problems.length" class="rounded-[14px] border border-dashed border-line-strong p-4" data-publish-needs>
            <p class="mb-2 text-sm font-medium text-fg">{{ t("lifecycle.reviews.beforePublish") }}</p>
            <ul class="flex flex-col gap-1 text-sm text-muted">
              <li v-for="problem in problems" :key="problem" class="flex items-center gap-2"><span class="size-1.5 rounded-full bg-warning" aria-hidden="true" />{{ t(`lifecycle.reviews.publishNeeds.${problem}`) }}</li>
            </ul>
          </section>
          <UiButton v-if="writable" class="lg:hidden" variant="primary" block :icon="Send" :loading="publish.isPending.value" :disabled="problems.length > 0" @click="runPublish">{{ t("lifecycle.reviews.publish") }}</UiButton>
        </div>
      </div>
    </template>
  </div>
</template>
