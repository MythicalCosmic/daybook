<script setup lang="ts">
/**
 * Who comes on time (the Reports page): the selection's average punctuality, the five most
 * punctual with their rank, and the five who need attention (late at least once, the least
 * punctual first) with how often and by how much they were late. Nobody is in both lists.
 */
import { CircleCheck, ClockAlert, Medal, Trophy } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";

import { rankingEnds, rateTone, TONE_TEXT } from "../reports";
import type { PunctualityReport, RankingRow } from "../types";

const props = withDefaults(defineProps<{ report?: PunctualityReport | null; loading?: boolean; error?: unknown; retry?: () => unknown }>(), {
  report: null,
  loading: false,
  error: undefined,
  retry: undefined,
});

const { t } = useI18n();
const fmt = useFormat();
const skeleton = useDelayedPending(computed(() => props.loading));

const ends = computed(() => rankingEnds(props.report?.rows ?? []));
const average = computed(() => props.report?.average ?? null);

/** Gold, silver and bronze in the theme's own tints; the rest plain. */
function rankClass(rank: number): string {
  if (rank === 1) return "bg-warning-soft text-warning";
  if (rank === 2) return "bg-surface-2 text-fg ring-1 ring-inset ring-line-strong";
  if (rank === 3) return "bg-accent-soft text-accent-fg";
  return "bg-surface-2 text-muted";
}

function bestLine(row: RankingRow): string {
  return [row.employee.position?.name, t("attendance.reports.ranking.arrivals", { n: row.arrivals }, row.arrivals)].filter(Boolean).join(" · ");
}

function worstLine(row: RankingRow): string {
  return t("attendance.reports.ranking.lateLine", { n: row.late_count, d: fmt.duration(row.average_late_minutes) }, row.late_count);
}
</script>

<template>
  <section class="ui-card flex min-w-0 flex-col" :aria-label="t('attendance.reports.ranking.title')" :aria-busy="loading || undefined">
    <header class="flex items-start gap-3 px-4 pb-2 pt-4 md:px-5">
      <div class="min-w-0 flex-1">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg">
          <Trophy :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <span class="truncate">{{ t("attendance.reports.ranking.title") }}</span>
        </h3>
        <p class="mt-0.5 text-xs text-muted">{{ t("attendance.reports.ranking.subtitle") }}</p>
      </div>
      <div v-if="!loading && average !== null" class="shrink-0 text-right" data-ranking-average>
        <p :class="['text-xl font-semibold tracking-[-0.015em] tabular-nums', TONE_TEXT[rateTone(average)]]">{{ fmt.percent(average, 1) }}</p>
        <p class="text-xs text-muted">{{ t("attendance.reports.ranking.average") }}</p>
      </div>
    </header>

    <div class="min-w-0 flex-1 px-4 pb-4 md:px-5">
      <div v-if="loading" class="grid gap-x-8 gap-y-2 sm:grid-cols-2">
        <template v-if="skeleton">
          <div v-for="n in 6" :key="n" class="flex items-center gap-3 py-2">
            <SkeletonBlock circle width="32px" height="32px" />
            <div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="60%" /><SkeletonBlock width="35%" height="10px" /></div>
          </div>
        </template>
      </div>
      <ErrorState v-else-if="error" compact class="border-0 bg-transparent" :error="error" :retry="retry" />
      <EmptyState v-else-if="!report?.rows.length" class="py-8" size="sm" tone="neutral" :icon="Trophy" :title="t('attendance.reports.ranking.empty')" />
      <div v-else class="grid gap-x-8 gap-y-5 sm:grid-cols-2">
        <div class="min-w-0">
          <p class="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">
            <Medal :size="14" aria-hidden="true" />{{ t("attendance.reports.ranking.best") }}
          </p>
          <ol class="divide-y divide-line" data-ranking="best">
            <li v-for="row in ends.best" :key="row.employee.id" class="flex items-center gap-3 py-2.5">
              <span :class="['grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold tabular-nums', rankClass(row.rank)]">{{ row.rank }}</span>
              <UserAvatar :name="row.employee.name" :src="row.employee.photo_url" :size="32" />
              <div class="min-w-0 flex-1">
                <div class="flex min-w-0 items-baseline gap-2">
                  <p class="min-w-0 flex-1 truncate text-sm font-medium text-fg" :title="row.employee.name">{{ row.employee.name }}</p>
                  <span :class="['shrink-0 text-sm font-semibold tabular-nums', TONE_TEXT[rateTone(row.punctuality_percent)]]">{{ fmt.percent(row.punctuality_percent, 0) }}</span>
                </div>
                <ProgressBar class="mt-1" size="xs" :value="row.punctuality_percent ?? 0" :tone="rateTone(row.punctuality_percent)" :label="row.employee.name" />
                <p class="mt-1 truncate text-xs text-muted">{{ bestLine(row) }}</p>
              </div>
            </li>
          </ol>
        </div>
        <div class="min-w-0">
          <p class="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">
            <ClockAlert :size="14" aria-hidden="true" />{{ t("attendance.reports.ranking.worst") }}
          </p>
          <ol v-if="ends.worst.length" class="divide-y divide-line" data-ranking="worst">
            <li v-for="row in ends.worst" :key="row.employee.id" class="flex items-center gap-3 py-2.5">
              <UserAvatar :name="row.employee.name" :src="row.employee.photo_url" :size="32" status="late" />
              <div class="min-w-0 flex-1">
                <div class="flex min-w-0 items-baseline gap-2">
                  <p class="min-w-0 flex-1 truncate text-sm font-medium text-fg" :title="row.employee.name">{{ row.employee.name }}</p>
                  <span :class="['shrink-0 text-sm font-semibold tabular-nums', TONE_TEXT[rateTone(row.punctuality_percent)]]">{{ fmt.percent(row.punctuality_percent, 0) }}</span>
                </div>
                <ProgressBar class="mt-1" size="xs" :value="row.punctuality_percent ?? 0" :tone="rateTone(row.punctuality_percent)" :label="row.employee.name" />
                <p class="mt-1 truncate text-xs text-muted">{{ worstLine(row) }}</p>
              </div>
            </li>
          </ol>
          <p v-else class="flex items-center gap-2 py-3 text-sm text-success" data-ranking="perfect">
            <CircleCheck :size="16" aria-hidden="true" />{{ t("attendance.reports.ranking.perfect") }}
          </p>
        </div>
      </div>
    </div>
  </section>
</template>
