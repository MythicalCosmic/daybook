<script setup lang="ts">
/**
 * Overview widget "Team": who works here now, on leave today, newcomers this month, suspended,
 * and join requests waiting. A tile with a headline number like the KPIs it usually sits beside;
 * fetches its own numbers and fails on its own.
 */
import { ArrowUpRight, UserPlus, Users } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";

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
const skeleton = useWidgetSkeleton(() => stats.isPending.value);
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
  <div class="ui-card group relative flex h-full min-w-0 flex-col p-4 transition-colors @container hover:border-line-strong" :aria-label="t('people.widget.title')">
    <!-- The whole tile opens the team; the join-requests button below is its own link. -->
    <RouterLink :to="`/c/${companyId}/people`" class="absolute inset-0 rounded-[inherit]" :aria-label="t('people.widget.title')" />
    <div class="pointer-events-none flex items-center gap-2">
      <Users :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-muted">{{ t("people.widget.title") }}</span>
      <ArrowUpRight :size="15" class="shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <ErrorState v-if="stats.isError.value" class="relative mt-2.5" compact bare :error="stats.error.value" :retry="() => stats.refetch()" />
    <div v-else-if="skeleton" class="flex flex-col gap-3"><SkeletonBlock class="mt-2.5" width="40%" height="26px" /><SkeletonBlock :lines="3" /></div>
    <template v-else-if="stats.data.value">
      <p class="pointer-events-none mt-1.5 flex min-w-0 items-baseline gap-2">
        <span class="kpi-value">{{ stats.data.value.active }}</span>
        <span class="truncate text-sm text-muted">{{ t("people.widget.working", { n: stats.data.value.active }, stats.data.value.active) }}</span>
      </p>
      <dl class="pointer-events-none mt-3 flex flex-col gap-1.5 border-t border-line pt-3">
        <div v-for="row in rows" :key="row.key" class="flex items-center justify-between gap-2 text-xs">
          <dt class="min-w-0 truncate text-muted">{{ row.label }}</dt>
          <dd :class="['tabular-nums', row.value ? 'font-semibold text-fg' : 'text-subtle']">{{ row.value }}</dd>
        </div>
      </dl>
      <div v-if="stats.data.value.pending_requests" class="relative mt-auto pt-3">
        <RouterLink
          :to="`/c/${companyId}/people/requests`"
          class="flex min-w-0 items-center gap-2 rounded-[10px] bg-accent-soft px-3 py-2 text-xs font-semibold text-accent-fg transition-colors hover:bg-[color-mix(in_srgb,var(--c-primary)_14%,var(--c-accent-soft))]"
        >
          <UserPlus :size="14" class="shrink-0" aria-hidden="true" /><span class="truncate">{{ t("people.widget.requests", { n: stats.data.value.pending_requests }, stats.data.value.pending_requests) }}</span>
        </RouterLink>
      </div>
    </template>
  </div>
</template>
