<script setup lang="ts">
/**
 * Overview KPI "Present now" (plan §1.2 KPI strip): people checked in against those rostered today,
 * the late and missing ones, and the last 14 days as tiny bars; links to the day board. Built from
 * plain markup (no chart library) because Overview widgets are part of the first load.
 */
import { ArrowUpRight, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";

import { useBoard, useSummary } from "../api";
import { STATE_COLORS } from "../lib";
import type { BoardState } from "../types";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const board = useBoard({ date: null, branch: [] });
const trend = useSummary({ preset: "last_30" });

const totals = computed(() => board.data.value?.totals);
const present = computed(() => (totals.value ? totals.value.in + totals.value.late : 0));
const days = computed(() => (trend.data.value?.series ?? []).slice(-14));
const peak = computed(() => Math.max(1, ...days.value.map((day) => day.rostered || day.present)));
const share = computed(() => (totals.value?.rostered ? Math.round((present.value / totals.value.rostered) * 100) : null));
const breakdown = computed(() => {
  const value = totals.value;
  if (!value) return [];
  const states: Array<[BoardState, number]> = [
    ["in", value.in],
    ["late", value.late],
    ["not_yet", value.not_yet],
    ["absent", value.absent],
  ];
  return states.map(([state, count]) => ({ state, count, label: t(`attendance.state.${state}`) }));
});
</script>

<template>
  <ErrorState v-if="board.isError.value" compact :error="board.error.value" :retry="() => board.refetch()" class="ui-card h-full" />
  <RouterLink
    v-else
    :to="`/c/${props.companyId}/attendance`"
    class="ui-card group flex h-full min-w-0 flex-col gap-3 p-4 transition-colors hover:border-line-strong"
    :aria-label="t('attendance.kpi.presentNow')"
  >
    <div class="flex items-center gap-2 text-sm text-muted">
      <Users :size="15" class="text-subtle" aria-hidden="true" />
      <span class="font-medium">{{ t("attendance.kpi.presentNow") }}</span>
      <span class="flex-1" />
      <ArrowUpRight :size="14" class="text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <div v-if="board.isPending.value" class="flex flex-col gap-2">
      <SkeletonBlock width="40%" height="28px" />
      <SkeletonBlock width="70%" height="12px" />
    </div>
    <template v-else-if="totals">
      <div class="flex items-baseline gap-1.5">
        <span class="text-2xl font-semibold tabular-nums text-fg">{{ present }}</span>
        <span class="text-base tabular-nums text-subtle">/ {{ totals.rostered }}</span>
        <span v-if="share !== null" class="ml-auto rounded-full bg-success-soft px-2 py-0.5 text-xs font-semibold tabular-nums text-success">{{ share }}%</span>
      </div>
      <p class="truncate text-xs text-muted">{{ t("attendance.kpi.ofRostered", { n: totals.rostered }) }}</p>
      <!-- Today's board in four lines: the same states as its columns. -->
      <ul class="flex flex-col gap-1.5 border-t border-line pt-3">
        <li v-for="item in breakdown" :key="item.state" class="flex items-center gap-2 text-xs">
          <span class="size-2 shrink-0 rounded-full" :style="{ background: STATE_COLORS[item.state] }" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-muted">{{ item.label }}</span>
          <span :class="['tabular-nums', item.count ? 'font-semibold text-fg' : 'text-subtle']">{{ item.count }}</span>
        </li>
      </ul>
    </template>
    <div v-if="days.length" class="mt-auto flex flex-col gap-1.5">
      <span class="text-[11px] text-subtle">{{ t("attendance.widget.last14") }}</span>
      <div class="flex h-8 items-end gap-[3px]" aria-hidden="true">
        <span
          v-for="day in days"
          :key="day.date"
          class="flex-1 rounded-t-[2px] bg-[color-mix(in_srgb,var(--c-chart-2)_70%,transparent)]"
          :style="{ height: `${Math.max(6, (day.present / peak) * 100)}%` }"
          :title="`${day.date}: ${day.present}/${day.rostered}`"
        />
      </div>
    </div>
  </RouterLink>
</template>
