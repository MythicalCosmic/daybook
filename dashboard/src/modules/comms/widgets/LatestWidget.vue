<script setup lang="ts">
/**
 * Overview widget "Announcements": the latest one and how many have read it, with a link to remind
 * the rest, plus the next scheduled one. Fetches its own data and fails on its own.
 */
import { ArrowRight, CalendarClock, Megaphone } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";

import { useAnnouncements } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const sent = useAnnouncements({ status: ["sent"], page_size: 1 });
const scheduled = useAnnouncements({ status: ["scheduled"], page_size: 1 });
const skeleton = useDelayedPending(computed(() => sent.isPending.value));
const latest = computed(() => sent.data.value?.results[0] ?? null);
const next = computed(() => scheduled.data.value?.results[0] ?? null);
const percent = computed(() => (latest.value?.recipients_count ? (latest.value.read_count / latest.value.recipients_count) * 100 : 0));
const base = computed(() => `/c/${props.companyId}/announcements`);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('comms.widget.title')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <Megaphone :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("comms.widget.title") }}</h3>
      <span class="flex-1" />
      <RouterLink :to="base" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div v-if="skeleton" class="flex flex-col gap-2 p-4"><SkeletonBlock width="80%" /><SkeletonBlock width="50%" height="12px" /><SkeletonBlock height="10px" /></div>
    <ErrorState v-else-if="sent.isError.value" compact class="m-3" :error="sent.error.value" :retry="() => sent.refetch()" />
    <EmptyState v-else-if="sent.data.value && !latest" size="sm" :icon="Megaphone" :title="t('comms.widget.emptyTitle')" :description="t('comms.widget.emptyBody')" />
    <div v-else-if="latest" class="flex flex-1 flex-col gap-2 px-4 pb-4">
      <RouterLink :to="`${base}/${latest.id}`" class="line-clamp-2 text-base font-semibold text-fg hover:text-primary">{{ latest.title }}</RouterLink>
      <p class="text-xs text-muted">{{ latest.author?.name ?? "—" }} · {{ latest.sent_at ? fmt.relative(latest.sent_at) : "" }}</p>
      <ProgressBar class="mt-1" size="sm" :value="percent" :tone="percent >= 80 ? 'success' : percent >= 50 ? 'warning' : 'danger'" />
      <p class="text-sm text-fg">{{ t("comms.readOf", { read: latest.read_count, total: latest.recipients_count }) }}</p>
      <RouterLink v-if="next" :to="`${base}/${next.id}`" class="mt-auto inline-flex items-center gap-2 rounded-[10px] bg-info-soft px-3 py-2 text-xs font-semibold text-info">
        <CalendarClock :size="14" aria-hidden="true" /><span class="truncate">{{ t("comms.widget.next", { when: fmt.instant(next.scheduled_for!, "short") }) }}</span>
      </RouterLink>
    </div>
  </section>
</template>
