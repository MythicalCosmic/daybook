<script setup lang="ts">
/**
 * AI › Activity: everything the agents did, live. The newest page is fetched again every 10 s
 * while the page is in view; new items slide in at the top, older ones load as you scroll. One
 * agent at a time with the chips (`?agent=deadline_watcher`).
 */
import { Activity } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useActivityFeed, useAgents, useAiStatus } from "../api";
import ActivityFeed from "../components/ActivityFeed.vue";
import AgentIcon from "../components/AgentIcon.vue";
import AiHeader from "../components/AiHeader.vue";

const { t } = useI18n();
const status = useAiStatus();
const agents = useAgents();
const agent = useRouteState("agent", rs.string(""));
const feed = useActivityFeed(() => agent.value || null);

const filters = computed(() => [{ key: "", name: t("ai.activity.all"), icon: null as string | null }, ...(agents.data.value ?? []).map((item) => ({ key: item.key, name: item.name, icon: item.icon }))]);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <AiHeader :title="t('ai.activity.title')" :description="t('ai.activity.description')" :status="status.data.value" />

    <div class="flex flex-wrap items-center gap-3">
      <div class="no-scrollbar -mx-1 flex min-w-0 flex-1 gap-1.5 overflow-x-auto px-1 py-0.5" role="group" :aria-label="t('ai.activity.filter')">
        <button
          v-for="filter in filters"
          :key="filter.key"
          type="button"
          :aria-pressed="agent === filter.key"
          :class="[
            'pressable inline-flex h-10 shrink-0 items-center gap-2 rounded-full border pl-2 pr-3.5 text-sm md:h-9',
            agent === filter.key ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-surface-2',
            !filter.icon && 'pl-3.5',
          ]"
          :data-filter="filter.key || 'all'"
          @click="agent = filter.key"
        >
          <AgentIcon v-if="filter.icon" :name="filter.icon" size="sm" :on="agent === filter.key" class="!size-6" />
          {{ filter.name }}
        </button>
      </div>
      <StatusPill tone="success" dot live :label="t('ai.activity.live')" class="max-sm:hidden" />
    </div>

    <section class="ui-card px-3 py-2 md:px-5 md:py-4">
      <div v-if="feed.isPending.value" class="flex flex-col gap-3 py-2" aria-hidden="true">
        <div v-for="n in 6" :key="n" class="flex items-start gap-3">
          <SkeletonBlock circle width="32px" height="32px" />
          <div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock height="14px" width="80%" /><SkeletonBlock height="12px" width="40%" /></div>
        </div>
      </div>
      <ErrorState v-else-if="feed.isError.value" :error="feed.error.value" :retry="() => feed.refetch()" />
      <EmptyState
        v-else-if="!feed.items.value.length"
        class="py-10"
        :icon="Activity"
        :title="agent ? t('ai.activity.emptyAgent') : t('ai.activity.empty')"
        :description="t('ai.activity.emptyBody')"
      />
      <ActivityFeed
        v-else
        :items="feed.items.value"
        :fresh="feed.fresh.value"
        :has-older="feed.hasOlder.value"
        :loading-older="feed.loadingOlder.value"
        :older-failed="feed.olderFailed.value"
        @older="feed.loadOlder()"
      />
    </section>
  </div>
</template>
