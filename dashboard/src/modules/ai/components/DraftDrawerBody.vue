<script setup lang="ts">
/**
 * A voice note in full: who sent it, from where and when, the recording itself, what was heard,
 * and what became of it: the editable tasks while it waits (Create / Discard), the tasks made, or
 * why it didn't work.
 */
import { CalendarClock, Camera, Flag, Trash2, UserRound } from "@lucide/vue";
import { computed, toRef } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { useDiscardDraft, useDraft } from "../api";
import { formatSeconds, isWorking, workingPhase } from "../lib";
import { SOURCE_ICON } from "../meta";
import { failedTitles, useReview } from "../review";
import CreatedTasks from "./CreatedTasks.vue";
import DraftReview from "./DraftReview.vue";
import DraftStatusPill from "./DraftStatusPill.vue";
import WorkingState from "./WorkingState.vue";

const props = defineProps<{ id: number }>();
const emit = defineEmits<{ close: [] }>();

const { t, te } = useI18n();
const fmt = useFormat();
const watched = useDraft(toRef(props, "id"));
const draft = computed(() => watched.data.value ?? null);
const review = useReview(draft);
const discard = useDiscardDraft();
const failedLines = computed(() => failedTitles(review.edits.value, review.result.value));
const created = computed(() => review.result.value?.draft.created_tasks ?? draft.value?.created_tasks ?? []);

async function throwAway(): Promise<void> {
  try {
    await discard.mutateAsync(props.id);
    toast.info(t("ai.review.discarded"));
    emit("close");
  } catch {
    // The reason is a toast.
  }
}
</script>

<template>
  <div v-if="watched.isPending.value" class="flex flex-col gap-3 p-5" aria-hidden="true">
    <SkeletonBlock height="48px" radius="10px" />
    <SkeletonBlock height="54px" radius="27px" />
    <SkeletonBlock height="120px" radius="12px" />
  </div>
  <ErrorState v-else-if="!draft" class="m-5" :error="watched.error.value" :retry="() => watched.refetch()" />
  <div v-else class="flex min-h-full flex-col">
    <div class="flex flex-1 flex-col gap-5 px-5 py-5">
      <div class="flex items-center gap-3">
        <UserAvatar :name="draft.author?.name ?? '?'" :size="40" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-base font-semibold text-fg">{{ draft.author?.name ?? t("ai.voice.unknownAuthor") }}</p>
          <p class="flex flex-wrap items-center gap-x-1.5 text-sm text-muted">
            <component :is="SOURCE_ICON[draft.source]" :size="13" aria-hidden="true" />
            <span>{{ t(`ai.source.${draft.source}`) }}</span>
            <span aria-hidden="true">·</span>
            <time class="num" :datetime="draft.created_at">{{ fmt.instant(draft.created_at, "short") }}</time>
          </p>
        </div>
        <DraftStatusPill :status="draft.status" />
      </div>

      <div v-if="draft.audio" class="flex flex-col gap-1.5 rounded-card border border-line bg-surface-2 p-3 dark:bg-surface-3">
        <audio class="ai-audio h-10 w-full" controls preload="metadata" :src="draft.audio.url" :aria-label="t('ai.voice.recording')" />
        <p class="num px-1 text-xs text-muted">{{ t("ai.voice.length", { time: formatSeconds(draft.audio.seconds) }) }}<template v-if="te(`ai.engine.${draft.engine}`)"> · {{ t(`ai.engine.${draft.engine}`) }}</template></p>
      </div>

      <WorkingState v-if="isWorking(draft.status) && !watched.gaveUp.value" :phase="workingPhase(draft.status, !!draft.audio)" :voice="!!draft.audio" compact />
      <InlineAlert v-else-if="isWorking(draft.status)" tone="warning" :title="t('ai.slow.title')" :description="t('ai.slow.body')">
        <template #actions><UiButton size="sm" @click="watched.retry()">{{ t("ai.slow.retry") }}</UiButton></template>
      </InlineAlert>

      <DraftReview v-else-if="draft.status === 'ready' && !review.result.value" :draft="draft" :review="review" :disabled="review.applying.value" />

      <template v-else>
        <figure v-if="draft.transcript" class="rounded-card bg-surface-2 px-4 py-3 dark:bg-surface-3">
          <figcaption class="mb-1 text-xs font-semibold text-muted">{{ draft.audio ? t("ai.review.heard") : t("ai.review.typed") }}</figcaption>
          <blockquote class="whitespace-pre-line text-base leading-[1.5] text-fg">{{ draft.transcript }}</blockquote>
        </figure>
        <InlineAlert v-if="draft.status === 'failed'" tone="danger" :title="t('ai.error.title')" :description="draft.error || (te(`ai.error.${draft.error_code}`) ? t(`ai.error.${draft.error_code}`) : t('ai.error.generic'))" />
        <InlineAlert v-else-if="draft.status === 'discarded' || draft.status === 'expired'" tone="neutral" :description="t(`ai.voice.${draft.status}`)" />
        <section v-if="draft.status === 'applied' || review.result.value" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("ai.voice.created", { n: created.length }, created.length) }}</h3>
          <CreatedTasks :tasks="created" :failed="failedLines" />
        </section>
        <section v-else-if="draft.drafts.length" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("ai.voice.understood") }}</h3>
          <ul class="ui-card flex flex-col divide-y divide-line">
            <li v-for="(item, index) in draft.drafts" :key="index" class="flex flex-col gap-1 px-4 py-3">
              <span class="text-base font-medium text-fg">{{ item.title }}</span>
              <span class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                <span class="inline-flex items-center gap-1"><UserRound :size="13" aria-hidden="true" />{{ item.assignee?.name ?? t("ai.review.me") }}</span>
                <span v-if="item.due_text" class="inline-flex items-center gap-1"><CalendarClock :size="13" aria-hidden="true" />{{ item.due_text }}</span>
                <UiBadge v-if="item.priority === 'urgent'" tone="danger"><Flag :size="11" class="mr-0.5" aria-hidden="true" />{{ t("ai.review.urgent") }}</UiBadge>
                <UiBadge v-if="item.proof === 'photo'" tone="primary"><Camera :size="11" class="mr-0.5" aria-hidden="true" />{{ t("ai.review.photo") }}</UiBadge>
              </span>
            </li>
          </ul>
        </section>
      </template>
    </div>

    <!-- The decision stays in reach while the drafts scroll. -->
    <div v-if="draft.status === 'ready' && !review.result.value" class="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 border-t border-line bg-surface px-5 py-3">
      <span v-if="review.blockers.value.problems || review.blockers.value.untitled" class="mr-auto text-sm text-warning" role="status">
        {{ review.blockers.value.untitled ? t("ai.review.needTitles") : t("ai.review.fixFirst") }}
      </span>
      <UiButton variant="ghost" :icon="Trash2" :loading="discard.isPending.value" :disabled="review.applying.value" @click="throwAway">{{ t("ai.review.discard") }}</UiButton>
      <UiButton variant="primary" :loading="review.applying.value" :disabled="!review.canApply.value" data-testid="ai-apply" @click="review.create()">
        {{ t("ai.review.create", { n: review.count.value }, review.count.value) }}
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
.ai-audio {
  color-scheme: inherit;
}
</style>
