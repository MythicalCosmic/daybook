<script setup lang="ts">
/**
 * Overview card `tasks.top_bottom` (plan §1.2): the five people most and least on time over the
 * last 30 days (people with work only; personal tasks never count), from `reports/team/`.
 */
import { useQuery } from "@tanstack/vue-query";
import { Trophy } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";

interface Row {
  key: string;
  label: string;
  total: number;
  on_time_percent: number | null;
  member?: { id: number; name: string; photo_url: string | null };
}

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const fmt = useFormat();

const query = useQuery({
  queryKey: computed(() => qk(props.companyId, "tasks", "top-bottom")),
  queryFn: ({ signal }) => http.get<{ breakdown: Row[] }>(ownerPath(props.companyId, "reports/team/"), { preset: "last_30" }, { signal }),
  staleTime: 5 * 60_000,
});
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const ranked = computed(() =>
  (query.data.value?.breakdown ?? [])
    .filter((row) => row.total > 0 && row.on_time_percent !== null)
    .sort((a, b) => (b.on_time_percent ?? 0) - (a.on_time_percent ?? 0)),
);
const top = computed(() => ranked.value.slice(0, 5));
// Never the same person in both lists.
const bottom = computed(() => (ranked.value.length > 5 ? ranked.value.slice(Math.max(5, ranked.value.length - 5)).reverse() : []));
const tone = (value: number | null) => (value === null ? "primary" : value >= 90 ? "success" : value >= 75 ? "warning" : "danger");
</script>

<template>
  <WidgetCard :title="t('tasks.widget.topBottom')" :icon="Trophy" :to="`/c/${companyId}/reports/team?preset=last_30`" :link-label="t('tasks.widget.allResults')" inset="content">
    <div v-if="skeleton" class="flex flex-col gap-3 pt-2"><SkeletonBlock v-for="n in 5" :key="n" height="22px" /></div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !ranked.length" class="my-auto" size="sm" tone="neutral" :icon="Trophy" :title="t('tasks.widget.noResults')" />
    <div v-else :class="['grid gap-x-6 gap-y-4 pt-1', bottom.length ? '@md:grid-cols-2' : '']">
      <div v-for="block in [{ id: 'top', rows: top }, { id: 'bottom', rows: bottom }].filter((b) => b.rows.length)" :key="block.id" class="flex min-w-0 flex-col gap-2.5">
        <p class="text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">{{ block.id === "top" ? t("tasks.widget.best") : t("tasks.widget.needsHelp") }}</p>
        <div v-for="row in block.rows" :key="row.key" class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.label" :src="row.member?.photo_url" :size="24" />
          <div class="min-w-0 flex-1">
            <p class="flex items-baseline gap-2 text-sm"><span class="min-w-0 flex-1 truncate font-medium text-fg" :title="row.label">{{ row.label }}</span><span class="shrink-0 text-xs font-semibold tabular-nums text-muted">{{ fmt.percent(row.on_time_percent, 0) }}</span></p>
            <ProgressBar class="mt-1" :value="row.on_time_percent ?? 0" :max="100" :tone="tone(row.on_time_percent)" size="xs" />
          </div>
        </div>
      </div>
    </div>
  </WidgetCard>
</template>
