<script setup lang="ts">
/**
 * Overview widget "Team": who works here now, on leave today, newcomers this month, suspended,
 * and join requests waiting. Fetches its own numbers and fails on its own.
 */
import { ArrowRight, UserPlus, Users } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const stats = useQuery({
  queryKey: computed(() => qk(props.companyId, "people", "stats")),
  queryFn: ({ signal }) =>
    http.get<{ active: number; on_leave_today: number; joined_30d: number; suspended: number; pending_requests: number }>(ownerPath(props.companyId, "people/stats/"), undefined, {
      signal,
    }),
  staleTime: 30_000,
});
const skeleton = useDelayedPending(computed(() => stats.isPending.value));
const rows = computed(() => {
  const s = stats.data.value;
  if (!s) return [];
  return [
    { key: "leave", label: t("people.widget.onLeave"), value: s.on_leave_today },
    { key: "joined", label: t("people.widget.joined"), value: s.joined_30d },
    { key: "suspended", label: t("people.widget.suspended"), value: s.suspended },
  ];
});
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('people.widget.title')">
    <header class="flex items-center gap-2 px-4 pb-1 pt-4">
      <Users :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("people.widget.title") }}</h3>
      <span class="flex-1" />
      <RouterLink :to="`/c/${companyId}/people`" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div v-if="skeleton" class="flex flex-col gap-3 p-4"><SkeletonBlock width="40%" height="32px" /><SkeletonBlock :lines="3" /></div>
    <ErrorState v-else-if="stats.isError.value" compact :error="stats.error.value" :retry="() => stats.refetch()" class="m-3" />
    <div v-else-if="stats.data.value" class="flex flex-1 flex-col px-4 pb-4">
      <p class="mt-1 flex items-baseline gap-2">
        <span class="text-2xl font-semibold tabular-nums text-fg">{{ stats.data.value.active }}</span>
        <span class="text-sm text-muted">{{ t("people.widget.working", { n: stats.data.value.active }, stats.data.value.active) }}</span>
      </p>
      <dl class="mt-3 flex flex-col divide-y divide-[var(--c-border)]">
        <div v-for="row in rows" :key="row.key" class="flex items-center justify-between py-1.5 text-sm">
          <dt class="text-muted">{{ row.label }}</dt>
          <dd class="font-semibold tabular-nums text-fg">{{ row.value }}</dd>
        </div>
      </dl>
      <RouterLink
        v-if="stats.data.value.pending_requests"
        :to="`/c/${companyId}/people/requests`"
        class="mt-3 inline-flex items-center gap-2 rounded-[10px] bg-accent-soft px-3 py-2 text-sm font-semibold text-accent-fg transition-colors hover:bg-[color-mix(in_srgb,var(--c-primary)_14%,var(--c-accent-soft))]"
      >
        <UserPlus :size="15" aria-hidden="true" />{{ t("people.widget.requests", { n: stats.data.value.pending_requests }, stats.data.value.pending_requests) }}
      </RouterLink>
    </div>
  </section>
</template>
