<script setup lang="ts">
/**
 * A goal in full (`?goal=<id>`, where the owner bot's note leads): its state and progress, the
 * weekly series against the pace a target needs (sums) or the target line (the rest), the
 * forecast, the day-one level, who owns it and why; owners change, archive or delete it here.
 */
import { Archive, ArchiveRestore, Pencil, Trash2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DescriptionList from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import LineChart from "@/components/LineChart.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { ringTone, STATE_TONES, useGoal, type Goal } from "../api";
import { useGoalFormat } from "../format";

const emit = defineEmits<{ edit: [goal: Goal]; archive: [goal: Goal]; restore: [goal: Goal]; remove: [goal: Goal] }>();

const { t } = useI18n();
const fmt = useFormat();
const show = useGoalFormat();
const goalId = useRouteState("goal", rs.optionalNumber());
const query = useGoal(goalId);
const goal = computed(() => query.data.value ?? null);

const days = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000) + 1;
const chart = computed(() => {
  const row = goal.value;
  if (!row) return null;
  const points = row.series.filter((point) => point.value !== null);
  const categories = points.map((point) => point.on);
  const series: Array<{ name: string; data: Array<string | number | null>; color?: string; dashed?: boolean }> = [
    { name: t(`goals.metric.${row.metric}`), data: points.map((point) => point.value), color: "var(--c-primary)" },
  ];
  if (row.kind === "sum" || row.kind === "rate") {
    const total = days(row.starts_on, row.ends_on);
    series.push({ name: t("goals.paceNeeded"), data: points.map((point) => ((Number(row.target) * days(row.starts_on, point.on)) / total).toFixed(2)), color: "var(--c-subtle)", dashed: true });
  }
  return { categories, series, target: row.kind === "sum" || row.kind === "rate" ? null : { value: row.target, label: t("goals.target") } };
});
const details = computed(() => {
  const row = goal.value;
  if (!row) return [];
  return [
    { key: "period", label: t("goals.period"), value: `${fmt.day(row.starts_on, "medium")} – ${fmt.day(row.ends_on, "medium")}` },
    { key: "target", label: row.better === "down" ? t("goals.ceiling") : t("goals.target"), value: show.value(row, row.target, { full: true }) },
    { key: "now", label: t("goals.now"), value: show.value(row, row.value, { full: true }) },
    ...(row.kind === "sum" || row.kind === "rate" ? [{ key: "pace", label: t("goals.pace"), value: show.value(row, row.forecast, { full: true }) }] : []),
    ...(row.kind === "level" ? [{ key: "baseline", label: t("goals.onDayOne"), value: show.value(row, row.baseline) }] : []),
    { key: "where", label: t("goals.where"), value: row.branch?.name ?? t("goals.wholeCompany") },
    { key: "owner", label: t("goals.owner"), value: row.owner?.name ?? "—" },
    ...(row.note ? [{ key: "note", label: t("goals.note"), value: row.note, wide: true }] : []),
  ];
});
</script>

<template>
  <UiDrawer query-key="goal" :title="goal?.title ?? t('goals.title')" :description="goal ? t(`goals.metric.${goal.metric}`) : undefined" size="lg">
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="!goal" class="flex flex-col gap-3"><SkeletonBlock height="96px" /><SkeletonBlock height="220px" /></div>
    <div v-else class="flex flex-col gap-5" :data-goal-drawer="goal.id">
      <div class="flex items-center gap-4">
        <ProgressRing :value="Math.min(Number(goal.progress ?? 0), 100)" :size="96" :stroke="9" :tone="ringTone(goal)">
          <span class="text-md font-semibold tabular-nums text-fg">{{ fmt.number(goal.progress ?? 0, 0) }}%</span>
        </ProgressRing>
        <div class="min-w-0 flex-1">
          <StatusPill :tone="STATE_TONES[goal.state]" :label="t(`goals.state.${goal.state}`)" dot />
          <p class="mt-2 text-2xl font-semibold tabular-nums text-fg">{{ show.value(goal, goal.value) }}</p>
          <p class="text-sm text-muted">{{ goal.better === "down" ? t("goals.atMost", { target: show.value(goal, goal.target) }) : t("goals.ofTarget", { target: show.value(goal, goal.target) }) }}</p>
          <p class="mt-1 text-xs text-muted">{{ t(`goals.explain.${goal.kind}`) }}</p>
        </div>
      </div>

      <section v-if="chart && chart.categories.length > 1" class="rounded-[12px] border border-line p-3" :aria-label="t('goals.trendLabel')">
        <p class="mb-1 text-xs font-semibold text-muted">{{ t("goals.trendTitle") }}</p>
        <LineChart :categories="chart.categories" :series="chart.series" :value-format="goal.unit === 'money' ? 'money' : goal.unit === 'percent' ? 'percent' : 'number'" x-format="day" height="220px" :target="chart.target" legend />
      </section>
      <p v-else class="rounded-[12px] bg-surface-2/60 px-3 py-2.5 text-sm text-muted dark:bg-surface-3/40">{{ t("goals.trendSoon") }}</p>

      <DescriptionList :items="details" />

      <div v-if="goal.can_edit" class="flex flex-wrap gap-2 border-t border-line pt-4">
        <UiButton v-if="goal.status !== 'archived'" variant="secondary" :icon="Pencil" data-edit @click="emit('edit', goal)">{{ t("common.edit") }}</UiButton>
        <UiButton v-if="goal.status !== 'archived'" variant="ghost" :icon="Archive" data-archive @click="emit('archive', goal)">{{ t("goals.archive") }}</UiButton>
        <UiButton v-else variant="secondary" :icon="ArchiveRestore" data-restore @click="emit('restore', goal)">{{ t("goals.restore") }}</UiButton>
        <UiButton variant="ghost" :icon="Trash2" class="ms-auto text-danger" data-delete @click="emit('remove', goal)">{{ t("common.delete") }}</UiButton>
      </div>
    </div>
  </UiDrawer>
</template>
