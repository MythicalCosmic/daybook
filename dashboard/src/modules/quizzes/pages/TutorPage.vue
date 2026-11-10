<script setup lang="ts">
/**
 * The tutor (Ustoz): its suggestions to act on in one tap (assign a course, add a missing lesson,
 * open someone's page, ask a strong person to coach, say thanks), the last weekly report (or the
 * one it would send now), the weakest topics, what it did lately, and "Ask the tutor".
 * The tutor runs where AI is on; its settings and its room are on its agent page.
 */
import { BookOpen, Check, GraduationCap, HandHeart, Lightbulb, Settings2, Sparkles, UserRound, X } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { quizzesApi, useRefresh, useSuggestions, useTutor } from "../api";
import TutorChat from "../components/TutorChat.vue";
import { BAND_CELL, band } from "../lib";
import type { Suggestion, SuggestionKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const refresh = useRefresh();
const canManage = computed(() => company.can("learning.manage"));
const tutor = useTutor();
const suggestions = useSuggestions();

const ICONS: Record<SuggestionKind, typeof Sparkles> = {
  assign: BookOpen,
  practice: Lightbulb,
  lesson_needed: Lightbulb,
  mentor: GraduationCap,
  praise: HandHeart,
  overdue: UserRound,
};
const deciding = ref<number | null>(null);

/** What accepting does for each kind, and where it leads. */
function acceptLabel(row: Suggestion): string {
  return t(`quizzes.tutor.accept.${row.kind}`);
}
async function decide(row: Suggestion, action: "accept" | "dismiss"): Promise<void> {
  deciding.value = row.id;
  try {
    await quizzesApi.decide(company.currentId ?? 0, row.id, action);
    toast.success(action === "accept" ? t("quizzes.tutor.accepted") : t("quizzes.tutor.dismissed"));
    refresh();
    if (action === "accept") {
      const base = `/c/${company.currentId}`;
      if (row.kind === "lesson_needed") void router.push(`${base}/learning/lessons?new=1${row.topic ? `&topic=${row.topic.id}` : ""}`);
      if (row.kind === "overdue" && row.member) void router.push(`${base}/learning/people/${row.member.id}`);
    }
  } catch (error) {
    if (isApiError(error) && error.detail) toast.error(error.detail);
  } finally {
    deciding.value = null;
  }
}

const report = computed(() => tutor.data.value?.report ?? null);
const agent = computed(() => tutor.data.value?.agent ?? null);
</script>

<template>
  <!-- On wide screens the page is two panes that fill the window below the header: the tutor's
       findings scroll on the left, the chat is a window of its own on the right. Narrower, the
       chat is a panel as tall as the screen under the findings. Either way a long conversation
       scrolls inside the chat and never makes the page longer. -->
  <div class="flex flex-col xl:h-[calc(100dvh-var(--topbar-h)-86px)]" data-testid="tutor-page">
    <PageHeader :title="t('quizzes.nav.tutor')" :description="t('quizzes.tutor.description')">
      <template #actions>
        <UiButton v-if="agent?.listed" variant="secondary" :icon="Settings2" :to="`/c/${company.currentId}/ai/agents/tutor`">{{ t("quizzes.tutor.settings") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="tutor.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="120px" radius="12px" /></div>
    <ErrorState v-else-if="tutor.error.value" :error="tutor.error.value" :retry="() => tutor.refetch()" />
    <template v-else-if="tutor.data.value">
      <InlineAlert v-if="!agent?.ai_on" class="mb-4" tone="info" :title="t('quizzes.tutor.aiOffTitle')" :description="t('quizzes.tutor.aiOffBody')" />
      <InlineAlert v-else-if="!agent?.enabled" class="mb-4" tone="warning" :title="t('quizzes.tutor.offTitle')" :description="t('quizzes.tutor.offBody')" />
      <p v-else-if="agent.next_report_at" class="mb-4 flex items-center gap-2 text-sm text-muted">
        <Sparkles :size="14" aria-hidden="true" />{{ t("quizzes.tutor.nextReport", { when: fmt.instant(agent.next_report_at) }) }}
      </p>

      <div class="grid gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[minmax(0,1fr)_460px] 2xl:grid-cols-[minmax(0,1fr)_540px]">
        <div class="flex min-w-0 flex-col gap-4 xl:min-h-0 xl:overflow-y-auto xl:overscroll-contain xl:pr-1" data-testid="tutor-findings">
          <PageSection variant="card" :title="t('quizzes.tutor.suggestions')" :count="suggestions.data.value?.length" flush>
            <div v-if="suggestions.isPending.value" class="p-4"><SkeletonBlock height="64px" /></div>
            <ul v-else-if="suggestions.data.value?.length" class="divide-y divide-line" data-testid="suggestions">
              <li v-for="row in suggestions.data.value" :key="row.id" class="flex flex-wrap items-start gap-3 px-4 py-3">
                <UserAvatar v-if="row.member" :name="row.member.name" :src="row.member.photo_url" :size="32" />
                <span v-else class="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg"><component :is="ICONS[row.kind]" :size="16" aria-hidden="true" /></span>
                <div class="min-w-0 flex-1 basis-48">
                  <p class="text-sm text-fg">{{ row.text }}</p>
                  <p class="mt-0.5 flex flex-wrap items-center gap-1 text-xs text-muted">
                    <StatusPill size="sm" variant="plain" tone="primary" :icon="ICONS[row.kind]" :label="t(`quizzes.suggestionKind.${row.kind}`)" />
                    <span>· {{ fmt.relative(row.created_at) }}</span>
                  </p>
                </div>
                <!-- On a phone the buttons go under the text, lined up with it. -->
                <div v-if="canManage" class="flex gap-1 max-sm:w-full max-sm:pl-11">
                  <UiButton size="sm" variant="primary" :icon="Check" :loading="deciding === row.id" @click="decide(row, 'accept')">{{ acceptLabel(row) }}</UiButton>
                  <UiButton size="sm" variant="ghost" :icon="X" :aria-label="t('quizzes.tutor.dismiss')" @click="decide(row, 'dismiss')" />
                </div>
              </li>
            </ul>
            <EmptyState v-else size="sm" :icon="Sparkles" :title="t('quizzes.tutor.noSuggestions')" :description="t('quizzes.tutor.noSuggestionsBody')" />
          </PageSection>

          <PageSection variant="card" :title="t('quizzes.tutor.report')" :description="report?.sent_at ? t('quizzes.tutor.reportSent', { when: fmt.instant(report.sent_at) }) : t('quizzes.tutor.reportNow')">
            <div v-if="report" class="flex flex-col gap-2 text-sm" data-testid="tutor-report">
              <p v-if="report.opening" class="font-medium text-fg">{{ report.opening }}</p>
              <p v-for="(line, index) in report.lines" :key="index" class="text-fg">{{ line }}</p>
            </div>
            <p v-else class="text-sm text-muted">{{ t("quizzes.tutor.noReport") }}</p>
          </PageSection>

          <div class="grid gap-4 lg:grid-cols-2">
            <PageSection variant="card" :title="t('quizzes.tutor.weakest')" flush>
              <ul v-if="tutor.data.value.weakest.length" class="divide-y divide-line">
                <li v-for="topic in tutor.data.value.weakest" :key="topic.id" class="flex items-center gap-3 px-4 py-2.5 text-sm">
                  <span class="min-w-0 flex-1 truncate text-fg">{{ topic.name }}</span>
                  <ProgressBar :value="topic.average ?? 0" :max="100" size="sm" tone="auto" class="w-20" />
                  <span class="w-10 text-right font-semibold tabular-nums" :class="BAND_CELL[band(topic.average)].split(' ')[1]">{{ topic.average }}</span>
                </li>
              </ul>
              <p v-else class="px-4 py-6 text-center text-sm text-muted">{{ t("quizzes.tutor.noWeakest") }}</p>
            </PageSection>
            <PageSection variant="card" :title="t('quizzes.tutor.lately')" flush>
              <ul v-if="tutor.data.value.events.length" class="divide-y divide-line">
                <li v-for="(event, index) in tutor.data.value.events" :key="index" class="flex items-start gap-3 px-4 py-2.5 text-sm">
                  <span class="min-w-0 flex-1 text-fg">{{ event.text }}</span>
                  <span class="shrink-0 text-xs text-muted">{{ fmt.relative(event.at) }}</span>
                </li>
              </ul>
              <p v-else class="px-4 py-6 text-center text-sm text-muted">{{ t("quizzes.tutor.nothingYet") }}</p>
            </PageSection>
          </div>
        </div>

        <div
          class="ui-card flex h-[calc(100dvh-var(--topbar-h)-var(--safe-top)-var(--tabbar-h)-var(--safe-bottom)-2rem)] max-h-[820px] min-h-[440px] flex-col overflow-hidden xl:h-auto xl:max-h-none xl:min-h-0"
          data-testid="tutor-chat-panel"
        >
          <TutorChat v-if="agent?.chat" />
          <div v-else class="flex flex-col gap-3 p-4">
            <h2 class="text-sm font-semibold text-fg">{{ t("quizzes.tutor.ask") }}</h2>
            <InlineAlert tone="info" :description="t('quizzes.tutor.askOff')" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
