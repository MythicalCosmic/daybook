<script setup lang="ts">
/**
 * Overview widget `hr.coverage_week` (plan §14.9): a qualified pharmacist whenever a pharmacy is
 * open, over the next seven days of the roster, and any pharmacy without one checked in right now.
 * Hidden (renders nothing) while the rule is off or nobody has said who counts as a pharmacist.
 */
import { CircleCheck, ShieldAlert, ShieldCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useWidgetSkeleton } from "@/components/widgetSkeleton";
import { addDays } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import { useCoverage, useLiveCoverage } from "../api";
import { allGaps, coverageTotals } from "../coverage";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const SHOWN = 4;
const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();
const query = useCoverage(computed(() => ({ from: today.value, to: addDays(today.value, 6) })));
const live = useLiveCoverage();
const skeleton = useWidgetSkeleton(() => query.isPending.value);
const data = computed(() => query.data.value ?? null);
const running = computed(() => data.value?.state === "ok" && coverageTotals(data.value.branches).branches > 0);
// Gaps not over yet (today's morning that has passed is the live check's business).
const gaps = computed(() => allGaps(data.value?.branches ?? []).filter((gap) => Date.parse(gap.end) > Date.now()));
const nowGaps = computed(() => live.data.value?.gaps ?? []);
const link = computed(() => `/c/${props.companyId}/hr/coverage`);

function when(gap: { start: string; end: string }): string {
  return `${fmt.day(gap.start.slice(0, 10), "weekdayShort")}, ${fmt.instant(gap.start, "time")}–${fmt.instant(gap.end, "time")}`;
}
</script>

<template>
  <WidgetCard v-if="skeleton || query.isError.value || running" :title="t('hr.coverage.widget.title')" :icon="ShieldCheck" :to="link" :link-label="t('hr.coverage.widget.open')">
    <div v-if="skeleton" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 3" :key="n" height="28px" radius="8px" /></div>
    <ErrorState v-else-if="query.isError.value" compact :error="query.error.value" :retry="() => query.refetch()" class="m-2" />
    <div v-else class="flex flex-col gap-3 p-2" data-coverage-widget>
      <ul v-if="nowGaps.length" class="flex flex-col gap-1">
        <li v-for="gap in nowGaps" :key="gap.branch.id" class="flex items-start gap-2 rounded-[10px] bg-danger-soft px-3 py-2 text-sm text-danger">
          <ShieldAlert :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{{ t("hr.coverage.widget.now", { branch: gap.branch.name, time: fmt.instant(gap.since, "time") }) }}</span>
        </li>
      </ul>
      <template v-if="gaps.length">
        <p class="px-1 text-sm font-semibold text-fg">{{ t("hr.coverage.widget.gaps", { n: gaps.length }, gaps.length) }}</p>
        <ul class="flex flex-col">
          <li v-for="gap in gaps.slice(0, SHOWN)" :key="`${gap.branch_id}-${gap.start}`" class="flex items-baseline justify-between gap-3 rounded-[8px] px-1 py-1 text-sm">
            <span class="truncate text-fg">{{ gap.branchName }}</span>
            <span class="shrink-0 tabular-nums text-danger">{{ when(gap) }}</span>
          </li>
        </ul>
        <p v-if="gaps.length > SHOWN" class="px-1 text-xs text-muted">{{ t("hr.coverage.slot.more", { n: gaps.length - SHOWN }, gaps.length - SHOWN) }}</p>
      </template>
      <EmptyState v-else-if="!nowGaps.length" size="sm" tone="success" :icon="CircleCheck" :title="t('hr.coverage.widget.covered')" :description="t('hr.coverage.widget.coveredBody')" />
    </div>
  </WidgetCard>
</template>
