<script setup lang="ts">
/**
 * Overview widget "Activity" (plan §6.2, `GET stream/`): the latest things that happened in the
 * company, from every module that registered a stream source, newest first, each with the app's
 * icon on the person's avatar. It refetches whenever the pulse reports a change anywhere.
 */
import { Activity } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import { iconForKind } from "@/components/kindIcons";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";
import { pulse } from "@/core/pulse";
import { companyUrl } from "@/lib/links";

import { useStream } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const query = useStream(12);
const skeleton = useWidgetSkeleton(() => query.isPending.value);
const items = computed(() => query.data.value?.items ?? []);

// Something changed somewhere (a version moved): the stream may have news.
watch(
  () => pulse.value.versions,
  (next, previous) => {
    if (previous && Object.keys(previous).length && JSON.stringify(next) !== JSON.stringify(previous)) void query.refetch();
  },
);
</script>

<template>
  <WidgetCard :title="t('overview.activity.title')" :icon="Activity">
    <div v-if="skeleton" class="flex flex-col gap-1 p-2">
      <div v-for="n in 5" :key="n" class="flex items-center gap-3 py-1.5">
        <SkeletonBlock circle height="28px" />
        <div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="35%" height="11px" /><SkeletonBlock width="75%" /></div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
    <EmptyState v-else-if="query.data.value && !items.length" class="my-auto" size="sm" tone="neutral" :icon="Activity" :title="t('overview.activity.empty')" :description="t('overview.activity.emptyBody')" />
    <TransitionGroup v-else name="list" tag="ol" class="relative flex flex-col">
      <li v-for="item in items" :key="`${item.kind}:${item.at}:${item.title}`">
        <RouterLink :to="companyUrl(props.companyId, item.url)" class="flex items-start gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
          <span class="relative shrink-0">
            <UserAvatar v-if="item.actor" :name="item.actor.name" :src="item.actor.photo_url" :size="28" />
            <span v-else class="grid size-7 place-items-center rounded-full bg-surface-2 text-muted" aria-hidden="true"><component :is="iconForKind(item.kind)" :size="14" /></span>
            <span
              v-if="item.actor"
              class="absolute -bottom-1 -right-1 grid size-4 place-items-center rounded-full bg-surface text-muted ring-1 ring-[var(--c-border)]"
              aria-hidden="true"
            >
              <component :is="iconForKind(item.kind)" :size="10" :stroke-width="2.25" />
            </span>
          </span>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-fg">{{ item.actor?.name ?? t("overview.activity.system") }}</p>
            <p class="line-clamp-2 text-sm text-muted">{{ item.title }}</p>
          </div>
          <RelativeTime :value="item.at" class="shrink-0 pt-0.5 text-xs text-subtle" />
        </RouterLink>
      </li>
    </TransitionGroup>
  </WidgetCard>
</template>
