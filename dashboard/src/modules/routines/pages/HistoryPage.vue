<script setup lang="ts">
/**
 * Routines → History: how routine work went, per routine per day (a completion heatmap, the last
 * 30 days by default), for all routines together and per person. A cell opens that day's runs
 * with their proofs (Today, on that day, for that routine). Rates count the work whose time has
 * come; what's still ahead today isn't held against anyone.
 */
import { CalendarRange, Store, Users } from "@lucide/vue";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DateRangePicker from "@/components/DateRangePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import KpiStrip from "@/components/KpiStrip.vue";
import PageSection from "@/components/PageSection.vue";
import { useScopedBranches } from "@/components/pickers";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useRangeState } from "@/lib/useRangeState";
import { useCompanyStore } from "@/stores/company";

import { usePlanOptions, useRoutineHistory } from "../api";
import RoutinesHeader from "../components/RoutinesHeader.vue";
import { weekdayOf } from "../lib";
import type { HistoryCell } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();

const period = useRangeState({ preset: "last_30" });
const options = usePlanOptions();
const branches = useScopedBranches();
const defs = computed<FilterDef[]>(() => [
  { key: "branch", label: t("routines.filter.branch"), type: "multi", icon: Store, options: branches.value.map((b) => ({ value: String(b.id), label: b.name, description: b.code })) },
  { key: "position", label: t("routines.filter.position"), type: "multi", icon: Users, options: (options.data.value?.positions ?? []).map((p) => ({ value: String(p.id), label: p.name })) },
]);
const filters = useUrlFilters(defs);
const params = computed(() => ({
  from: period.value.range.from,
  to: period.value.range.to,
  branch: (filters.params.value.branch as string[] | undefined) ?? undefined,
  position: (filters.params.value.position as string[] | undefined) ?? undefined,
}));
const query = useRoutineHistory(params);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const data = computed(() => query.data.value ?? null);
const today = computed(() => todayIn(company.timezone));

const kpis = computed(() => {
  const totals = data.value?.totals;
  return [
    { id: "percent", label: t("routines.history.kpi.finished"), value: totals?.percent ?? null, format: "percent" as const, hint: t("routines.history.kpi.finishedHint") },
    { id: "on_time", label: t("routines.history.kpi.onTime"), value: totals?.on_time_percent ?? null, format: "percent" as const },
    { id: "missed", label: t("routines.history.kpi.missed"), value: totals?.missed ?? null },
    { id: "made", label: t("routines.history.kpi.made"), value: totals?.made ?? null },
  ];
});

/** A cell's colour: full green when all done, then lighter, amber, red; grey while nothing was due. */
function shade(cell: HistoryCell): string {
  if (cell.percent === null) return "transparent";
  if (cell.percent >= 100) return "var(--c-success)";
  if (cell.percent >= 80) return "color-mix(in srgb, var(--c-success) 55%, var(--c-surface))";
  if (cell.percent >= 50) return "color-mix(in srgb, var(--c-warning) 70%, var(--c-surface))";
  return "color-mix(in srgb, var(--c-danger) 75%, var(--c-surface))";
}

function tip(cell: HistoryCell, day: string, title: string): string {
  const head = `${title} · ${fmt.day(day, "weekdayShort")}`;
  if (cell.percent === null) return `${head}: ${t("routines.history.notDueYet", { n: cell.made }, cell.made)}`;
  const parts = [t("routines.history.tipDone", { done: cell.finished, total: cell.made - cell.open, percent: fmt.percent(cell.percent, 0) })];
  if (cell.late) parts.push(t("routines.history.tipLate", { n: cell.late }, cell.late));
  if (cell.missed) parts.push(t("routines.history.tipMissed", { n: cell.missed }, cell.missed));
  if (cell.open) parts.push(t("routines.history.tipOpen", { n: cell.open }, cell.open));
  return `${head}: ${parts.join(", ")}`;
}

function open(day: string, routineId?: number): void {
  void router.push({ name: "routines.today", query: { ...(day === today.value ? {} : { day }), ...(routineId ? { routine: String(routineId) } : {}) } });
}

// Narrow screens see the latest days first: the grid opens scrolled to its end.
const scroller = ref<HTMLElement | null>(null);
watch(data, async () => {
  await nextTick();
  if (scroller.value) scroller.value.scrollLeft = scroller.value.scrollWidth;
});

const percentText = (value: number | null) => (value === null ? "—" : fmt.percent(value, 0));
const tone = (value: number | null) => (value === null ? "neutral" : value >= 90 ? "success" : value >= 70 ? "warning" : "danger");
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <RoutinesHeader>
      <template #actions>
        <DateRangePicker v-model="period" align="end" />
      </template>
    </RoutinesHeader>

    <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="compact" />
    <FilterBar v-model="filters.values.value" :defs="defs" />

    <div v-if="skeleton" class="ui-card flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 5" :key="n" height="28px" /></div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="data && !data.routines.length" class="ui-card">
      <EmptyState :icon="CalendarRange" :title="t('routines.history.emptyTitle')" :description="t('routines.history.emptyBody')" />
    </div>
    <template v-else-if="data">
      <section class="ui-card min-w-0 overflow-hidden" data-testid="heatmap">
        <header class="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3">
          <div class="min-w-0 flex-1">
            <h2 class="text-sm font-semibold text-fg">{{ t("routines.history.heatmapTitle") }}</h2>
            <p class="text-xs text-muted">{{ t("routines.history.heatmapHint") }}</p>
          </div>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted" aria-hidden="true">
            <span class="inline-flex items-center gap-1.5"><span class="size-3 rounded-[3px]" style="background: var(--c-success)" />100 %</span>
            <span class="inline-flex items-center gap-1.5"><span class="size-3 rounded-[3px]" style="background: color-mix(in srgb, var(--c-success) 55%, var(--c-surface))" />80–99 %</span>
            <span class="inline-flex items-center gap-1.5"><span class="size-3 rounded-[3px]" style="background: color-mix(in srgb, var(--c-warning) 70%, var(--c-surface))" />50–79 %</span>
            <span class="inline-flex items-center gap-1.5"><span class="size-3 rounded-[3px]" style="background: color-mix(in srgb, var(--c-danger) 75%, var(--c-surface))" />&lt; 50 %</span>
            <span class="inline-flex items-center gap-1.5"><span class="size-3 rounded-[3px] border border-dashed border-line-strong" />{{ t("routines.history.legendAhead") }}</span>
          </div>
        </header>
        <div ref="scroller" class="overflow-x-auto">
          <table class="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th class="sticky left-0 z-10 min-w-[132px] max-w-[260px] bg-surface px-4 py-2 text-left text-xs font-medium text-muted sm:min-w-[180px]">{{ t("routines.history.routine") }}</th>
                <th v-for="day in data.days" :key="day" :class="['px-[1px] pb-1.5 pt-2 text-center font-medium', day === today ? 'text-accent-fg' : weekdayOf(day) >= 5 ? 'text-subtle' : 'text-muted']">
                  <span class="block text-[10px] leading-3">{{ t(`routines.day.${weekdayOf(day)}`) }}</span>
                  <span class="block text-[11px] tabular-nums leading-4">{{ Number(day.slice(8)) }}</span>
                </th>
                <th class="whitespace-nowrap px-4 py-2 text-right text-xs font-medium text-muted">{{ t("routines.history.total") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr class="font-semibold">
                <th class="sticky left-0 z-10 bg-surface px-4 py-1 text-left text-sm text-fg">{{ t("routines.history.allRoutines") }}</th>
                <td v-for="(cell, index) in data.series" :key="cell.date" class="p-[1px]">
                  <button
                    v-if="cell.made"
                    type="button"
                    :class="['pressable block h-7 w-full min-w-[22px] rounded-[5px] outline-offset-1', cell.percent === null && 'border border-dashed border-line-strong']"
                    :style="{ background: shade(cell) }"
                    :title="tip(cell, data.days[index]!, t('routines.history.allRoutines'))"
                    :aria-label="tip(cell, data.days[index]!, t('routines.history.allRoutines'))"
                    @click="open(cell.date)"
                  />
                  <span v-else class="block h-7 min-w-[22px] rounded-[5px] bg-surface-2/60" />
                </td>
                <td class="px-4 text-right tabular-nums text-fg">{{ percentText(data.totals.percent) }}</td>
              </tr>
              <tr v-for="row in data.routines" :key="row.routine.id">
                <th class="sticky left-0 z-10 max-w-[150px] bg-surface px-4 py-1 text-left font-normal sm:max-w-[260px]">
                  <span class="block truncate text-sm text-fg" :title="row.routine.title">{{ row.routine.title }}</span>
                </th>
                <td v-for="(cell, index) in row.cells" :key="data.days[index]" class="p-[1px]">
                  <button
                    v-if="cell"
                    type="button"
                    :class="['pressable block h-7 w-full min-w-[22px] rounded-[5px] outline-offset-1', cell.percent === null && 'border border-dashed border-line-strong']"
                    :style="{ background: shade(cell) }"
                    :title="tip(cell, data.days[index]!, row.routine.title)"
                    :aria-label="tip(cell, data.days[index]!, row.routine.title)"
                    @click="open(data.days[index]!, row.routine.id)"
                  />
                  <span v-else class="block h-7 min-w-[22px] rounded-[5px] bg-surface-2/60" />
                </td>
                <td class="px-4 text-right font-semibold tabular-nums text-fg">{{ percentText(row.totals.percent) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <PageSection :title="t('routines.history.people')" :description="t('routines.history.peopleHint')" variant="card" flush>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[620px] text-sm">
            <thead class="bg-surface-2 text-left text-xs font-medium text-muted">
              <tr>
                <th class="px-4 py-2.5 font-medium">{{ t("routines.detail.person") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.history.colMade") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.history.colDone") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.history.colOnTime") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.detail.missed") }}</th>
                <th class="w-[240px] px-4 py-2.5 font-medium">{{ t("routines.history.colRate") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in data.people" :key="row.member.id" class="border-t border-line">
                <td class="px-4 py-2.5">
                  <span class="flex min-w-0 items-center gap-2">
                    <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="24" />
                    <span class="min-w-0">
                      <span class="block truncate font-medium text-fg" :title="row.member.name">{{ row.member.name }}</span>
                      <span v-if="row.member.position" class="block truncate text-xs text-muted">{{ row.member.position }}</span>
                    </span>
                  </span>
                </td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.made }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.finished }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums text-success">{{ percentText(row.on_time_percent) }}</td>
                <td :class="['px-3 py-2.5 text-right tabular-nums', row.missed ? 'text-danger' : 'text-muted']">{{ row.missed }}</td>
                <td class="px-4 py-2.5">
                  <span class="flex items-center gap-2">
                    <ProgressBar class="flex-1" :value="row.percent ?? 0" :tone="tone(row.percent)" />
                    <span class="w-12 text-right tabular-nums text-muted">{{ percentText(row.percent) }}</span>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </PageSection>
    </template>
  </div>
</template>
