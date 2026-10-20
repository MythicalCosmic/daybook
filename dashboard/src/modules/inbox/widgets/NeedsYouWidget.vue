<script setup lang="ts">
/**
 * Overview widget "Needs you" (plan §6.2: the needs-you queue on the Overview): the count, the four
 * oldest waiting decisions and a link to the inbox. Fetches its own data and fails on its own.
 */
import { ArrowRight, Inbox } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useQueue } from "../api";
import { queueKey } from "../types";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const queue = useQueue(null);
const skeleton = useDelayedPending(computed(() => queue.isPending.value));
// The queue comes oldest first: the four that have waited longest.
const items = computed(() => (queue.data.value?.items ?? []).slice(0, 4));
const rest = computed(() => Math.max(0, (queue.data.value?.total ?? 0) - items.value.length));
const labelOf = (kind: string) => queue.data.value?.kinds.find((k) => k.kind === kind)?.label ?? kind;
const inbox = computed(() => `/c/${props.companyId}/inbox`);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('inbox.widget.title')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <Inbox :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("inbox.widget.title") }}</h3>
      <UiBadge v-if="queue.data.value?.total" :count="queue.data.value.total" tone="primary" />
      <span class="flex-1" />
      <RouterLink :to="inbox" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div class="min-h-0 flex-1 px-2 pb-2">
      <div v-if="skeleton" class="flex flex-col gap-1 p-2">
        <div v-for="n in 4" :key="n" class="flex items-center gap-3 py-1.5"><SkeletonBlock circle height="30px" /><div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="70%" /><SkeletonBlock width="40%" height="11px" /></div></div>
      </div>
      <ErrorState v-else-if="queue.isError.value" compact :error="queue.error.value" :retry="() => queue.refetch()" class="m-2" />
      <EmptyState v-else-if="queue.data.value && !items.length" size="sm" tone="success" :title="t('inbox.widget.empty')" :description="t('inbox.emptyNeedsBody')" />
      <ul v-else class="flex flex-col">
        <li v-for="item in items" :key="queueKey(item)">
          <RouterLink :to="{ path: inbox, query: { kind: item.kind } }" class="flex items-center gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
            <span class="grid size-[30px] shrink-0 place-items-center rounded-[9px] bg-accent-soft text-accent-fg" aria-hidden="true"><Inbox :size="15" /></span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-semibold text-fg">{{ item.title }}</p>
              <p class="truncate text-xs text-muted">{{ labelOf(item.kind) }}</p>
            </div>
            <RelativeTime v-if="item.created_at" :value="item.created_at" class="shrink-0 text-xs text-subtle" />
          </RouterLink>
        </li>
      </ul>
    </div>
    <footer v-if="rest" class="border-t border-line px-4 py-2.5 text-xs font-medium text-muted">{{ t("inbox.widget.more", { n: rest }) }}</footer>
  </section>
</template>
