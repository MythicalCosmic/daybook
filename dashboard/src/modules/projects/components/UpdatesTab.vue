<script setup lang="ts">
/**
 * The Updates tab: the lead's status posts, newest first, each with its health, author and time;
 * a strip of past healths shows the trend at a glance. Leads get a weekly nudge in Telegram.
 */
import { HeartPulse, MessageSquarePlus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MarkdownView from "@/components/MarkdownView.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";

import { useUpdates } from "../api";
import { HEALTH_TONE, healthVar } from "../lib";
import type { ProjectDetail } from "../types";

const props = defineProps<{ project: ProjectDetail }>();
const emit = defineEmits<{ post: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const query = useUpdates(() => props.project.id);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const updates = computed(() => query.data.value ?? []);
const trend = computed(() => [...updates.value].slice(0, 12).reverse());
</script>

<template>
  <div class="mx-auto flex max-w-[820px] flex-col gap-4">
    <section class="ui-card flex flex-wrap items-center gap-4 p-4">
      <span class="grid size-10 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent-fg"><HeartPulse :size="19" /></span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">{{ t("projects.updates.headline") }}</p>
        <p class="text-sm text-muted">{{ t("projects.updates.headlineBody") }}</p>
      </div>
      <div v-if="trend.length > 1" class="flex items-center gap-1" :aria-label="t('projects.updates.trend')">
        <UiTooltip v-for="update in trend" :key="update.id" :content="`${t(`projects.health.${update.health}`)} · ${fmt.instant(update.created_at, 'date')}`">
          <span class="h-6 w-2 rounded-full" :style="{ background: healthVar(update.health) }" />
        </UiTooltip>
      </div>
      <UiButton v-if="project.capabilities.post_update" variant="primary" :icon="MessageSquarePlus" @click="emit('post')">{{ t("projects.action.postUpdate") }}</UiButton>
    </section>

    <div v-if="skeleton" class="flex flex-col gap-3">
      <SkeletonBlock v-for="n in 3" :key="n" height="110px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !updates.length" :icon="HeartPulse" :title="t('projects.updates.emptyTitle')" :description="t('projects.updates.emptyBody')">
      <UiButton v-if="project.capabilities.post_update" variant="primary" :icon="MessageSquarePlus" @click="emit('post')">{{ t("projects.action.postUpdate") }}</UiButton>
    </EmptyState>
    <ol v-else class="flex flex-col gap-3">
      <li v-for="update in updates" :key="update.id">
        <article class="ui-card relative overflow-hidden p-4 pl-5">
          <span class="absolute inset-y-0 left-0 w-1" :style="{ background: healthVar(update.health) }" aria-hidden="true" />
          <header class="flex flex-wrap items-center gap-2">
            <UserAvatar :name="update.author?.name ?? '—'" :src="update.author?.photo_url" :size="28" />
            <span class="text-sm font-semibold text-fg">{{ update.author?.name ?? t("projects.updates.someone") }}</span>
            <RelativeTime :value="update.created_at" class="text-xs text-muted" />
            <span class="flex-1" />
            <StatusPill size="sm" :tone="HEALTH_TONE[update.health]" :label="t(`projects.health.${update.health}`)" />
          </header>
          <MarkdownView v-if="update.text" :source="update.text" size="sm" class="mt-2.5" />
          <p v-else class="mt-2 text-sm italic text-subtle">{{ t("projects.updates.noText") }}</p>
        </article>
      </li>
    </ol>
  </div>
</template>
