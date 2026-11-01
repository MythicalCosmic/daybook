<script setup lang="ts">
/**
 * AI › Voice notes: every instruction given to the AI, spoken or typed, from the bots, the mini
 * app and here: who, from where, when, how long, and what became of it. One opens in a drawer
 * (`?draft=41`, also the owner bot's "Edit" link) with the recording, the transcript and the tasks.
 */
import { AudioLines, Keyboard, Mic, Sparkles } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { closeQueryKey, patchQuery, rs, useRouteState } from "@/lib/useRouteState";

import { useAiStatus, useDrafts } from "../api";
import AiHeader from "../components/AiHeader.vue";
import DraftDrawerBody from "../components/DraftDrawerBody.vue";
import DraftStatusPill from "../components/DraftStatusPill.vue";
import { openDictation } from "../dictation";
import { aiVisibility, formatSeconds } from "../lib";
import { SOURCE_ICON } from "../meta";
import type { AiDraft, DraftSource } from "../types";

const { t } = useI18n();
const router = useRouter();
const fmt = useFormat();
const now = useNow();
const { isPhone } = useBreakpoints();
const status = useAiStatus();
const show = computed(() => aiVisibility(status.data.value));

const STATUS_FILTERS = ["", "ready", "applied", "failed"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];
const SOURCES: DraftSource[] = ["bot", "owner_bot", "miniapp", "dashboard"];
const statusFilter = useRouteState("status", rs.enum<StatusFilter>(STATUS_FILTERS, ""));
const source = useRouteState("source", rs.string(""));
const pageSize = ref(20);
watch([statusFilter, source], () => (pageSize.value = 20));
const drafts = useDrafts(() => ({ status: statusFilter.value, source: (source.value as DraftSource) || "", page_size: pageSize.value }));
const rows = computed(() => drafts.data.value?.results ?? []);
const total = computed(() => drafts.data.value?.count ?? 0);

const sourceOptions = computed(() => [{ value: "", label: t("ai.voice.allSources") }, ...SOURCES.map((value) => ({ value, label: t(`ai.source.${value}`) }))]);

function open(draft: AiDraft): void {
  patchQuery(router, { draft: String(draft.id) }, true);
}

/** "2 tasks" once made, else how many the AI found. */
function taskCount(draft: AiDraft): string {
  const n = draft.created_tasks.length || draft.drafts.length;
  return n ? t(draft.created_tasks.length ? "ai.voice.tasksMade" : "ai.voice.tasksFound", { n }, n) : "";
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <AiHeader :title="t('ai.voice.title')" :description="t('ai.voice.description')" :status="status.data.value">
      <template v-if="show.dictate || show.smartAdd" #actions>
        <UiButton v-if="show.smartAdd" :size="isPhone ? 'lg' : 'md'" :icon="Sparkles" class="max-sm:flex-1" @click="openDictation('text')">{{ t("ai.dictate.smartAdd") }}</UiButton>
        <UiButton v-if="show.dictate" variant="primary" :size="isPhone ? 'lg' : 'md'" :icon="Mic" class="max-sm:flex-1" @click="openDictation('voice')">{{ t("ai.dictate.button") }}</UiButton>
      </template>
    </AiHeader>

    <div class="flex flex-wrap items-center gap-2">
      <div class="no-scrollbar -mx-1 flex min-w-0 flex-1 gap-1.5 overflow-x-auto px-1 py-0.5" role="group" :aria-label="t('ai.voice.filter')">
        <button
          v-for="value in STATUS_FILTERS"
          :key="value || 'all'"
          type="button"
          :aria-pressed="statusFilter === value"
          :class="[
            'pressable inline-flex h-10 shrink-0 items-center rounded-full border px-3.5 text-sm md:h-9',
            statusFilter === value ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-surface-2',
          ]"
          :data-filter="value || 'all'"
          @click="statusFilter = value"
        >
          {{ t(`ai.voice.filter.${value || "all"}`) }}
        </button>
      </div>
      <SelectBox v-model="source" :options="sourceOptions" :size="isPhone ? 'lg' : 'md'" class="w-full sm:w-[200px]" :aria-label="t('ai.voice.source')" />
    </div>

    <section class="ui-card overflow-hidden">
      <div v-if="drafts.isPending.value" class="flex flex-col divide-y divide-line" aria-hidden="true">
        <div v-for="n in 5" :key="n" class="flex items-center gap-3 px-4 py-3.5">
          <SkeletonBlock circle width="36px" height="36px" />
          <div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock height="14px" width="40%" /><SkeletonBlock height="12px" width="75%" /></div>
        </div>
      </div>
      <ErrorState v-else-if="drafts.isError.value && !rows.length" class="m-4" :error="drafts.error.value" :retry="() => drafts.refetch()" />
      <EmptyState
        v-else-if="!rows.length"
        class="py-12"
        :icon="AudioLines"
        :title="statusFilter || source ? t('ai.voice.emptyFiltered') : t('ai.voice.empty')"
        :description="statusFilter || source ? undefined : t('ai.voice.emptyBody')"
      >
        <UiButton v-if="!statusFilter && !source && show.dictate" variant="primary" :icon="Mic" @click="openDictation('voice')">{{ t("ai.dictate.button") }}</UiButton>
      </EmptyState>
      <ul v-else class="flex flex-col divide-y divide-line" data-testid="ai-voice-list">
        <li v-for="draft in rows" :key="draft.id">
          <button type="button" class="pressable flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-surface-2 md:items-center" :data-draft="draft.id" @click="open(draft)">
            <UserAvatar :name="draft.author?.name ?? '?'" :size="36" class="mt-0.5 md:mt-0" />
            <span class="flex min-w-0 flex-1 flex-col gap-0.5">
              <span class="flex min-w-0 items-center gap-2">
                <span class="truncate text-base font-semibold text-fg">{{ draft.author?.name ?? t("ai.voice.unknownAuthor") }}</span>
                <DraftStatusPill :status="draft.status" size="sm" class="md:hidden" />
              </span>
              <span class="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm text-muted">
                <component :is="SOURCE_ICON[draft.source]" :size="13" class="shrink-0" aria-hidden="true" />
                <span>{{ t(`ai.source.${draft.source}`) }}</span>
                <span aria-hidden="true">·</span>
                <time class="num" :datetime="draft.created_at" :title="fmt.instant(draft.created_at)">{{ fmt.relative(draft.created_at, now) }}</time>
                <span aria-hidden="true">·</span>
                <span v-if="draft.audio" class="num inline-flex items-center gap-1"><Mic :size="12" aria-hidden="true" />{{ formatSeconds(draft.audio.seconds) }}</span>
                <span v-else class="inline-flex items-center gap-1"><Keyboard :size="12" aria-hidden="true" />{{ t("ai.voice.typed") }}</span>
                <template v-if="taskCount(draft)"><span aria-hidden="true">·</span><span>{{ taskCount(draft) }}</span></template>
              </span>
              <span v-if="draft.transcript" class="line-clamp-1 text-sm text-subtle">{{ draft.transcript }}</span>
            </span>
            <DraftStatusPill :status="draft.status" class="max-md:hidden" />
          </button>
        </li>
      </ul>
      <div v-if="rows.length < total" class="flex justify-center border-t border-line p-2">
        <UiButton variant="ghost" size="lg" :loading="drafts.isFetching.value" @click="pageSize += 20">{{ t("ai.voice.more") }}</UiButton>
      </div>
    </section>

    <UiDrawer query-key="draft" :title="t('ai.voice.drawerTitle')" size="lg">
      <template #default="{ value }">
        <DraftDrawerBody v-if="value && /^\d+$/.test(value)" :id="Number(value)" @close="closeQueryKey(router, 'draft')" />
      </template>
    </UiDrawer>
  </div>
</template>
