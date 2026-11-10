<script setup lang="ts">
/**
 * One business goal: what it measures, its state, a progress ring, the value against the target,
 * the forecast to the period's end, how many days are left, its weekly trend, who owns it and
 * where. Opens the goal's drawer; owners get its menu (change, archive, delete).
 */
import { Building2, CalendarClock, MoreHorizontal, UserRound } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import type { MenuEntry } from "@/components/menuTypes";
import ProgressRing from "@/components/ProgressRing.vue";
import SparkLine from "@/components/SparkLine.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";

import { ringTone, STATE_TONES, type Goal } from "../api";
import { METRIC_ICONS, useGoalFormat } from "../format";

const props = defineProps<{ goal: Goal; menu: MenuEntry[] }>();
const emit = defineEmits<{ open: [goal: Goal] }>();

const { t } = useI18n();
const fmt = useFormat();
const show = useGoalFormat();
const progress = computed(() => Math.max(0, Math.min(Number(props.goal.progress ?? 0), 100)));
const spark = computed(() => props.goal.series.map((point) => point.value));
const sparkColor = computed(() => {
  const tone = ringTone(props.goal);
  return tone === "primary" ? "var(--c-primary)" : `var(--c-${tone})`;
});
const finished = computed(() => props.goal.status === "achieved" || props.goal.status === "missed");
const showForecast = computed(() => (props.goal.kind === "sum" || props.goal.kind === "rate") && !finished.value && props.goal.state !== "not_started");
</script>

<template>
  <article
    class="ui-card group relative flex cursor-pointer flex-col gap-3 p-4 transition-[box-shadow,border-color] duration-120 hover:border-line-strong hover:shadow-raised focus-within:border-line-strong sm:p-5"
    :data-goal="goal.id"
    :data-state="goal.state"
    @click="emit('open', goal)"
  >
    <header class="flex items-start gap-2">
      <span class="grid size-7 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted" aria-hidden="true">
        <component :is="METRIC_ICONS[goal.metric]" :size="15" />
      </span>
      <p class="min-w-0 flex-1 truncate pt-1 text-xs font-medium text-muted">{{ t(`goals.metric.${goal.metric}`) }}</p>
      <StatusPill :tone="STATE_TONES[goal.state]" :label="t(`goals.state.${goal.state}`)" size="sm" dot />
      <div v-if="menu.length" class="-mr-1.5 -mt-1" @click.stop>
        <DropdownMenu :items="menu" width="200px">
          <template #trigger>
            <IconButton :icon="MoreHorizontal" :label="t('goals.actions', { title: goal.title })" size="sm" />
          </template>
        </DropdownMenu>
      </div>
    </header>

    <button type="button" class="text-left text-md font-semibold leading-snug text-fg outline-none after:absolute after:inset-0 focus-visible:underline" :title="goal.title" @click.stop="emit('open', goal)">
      {{ goal.title }}
    </button>

    <div class="flex items-center gap-4">
      <ProgressRing :value="progress" :max="100" :size="76" :stroke="7" :tone="ringTone(goal)" :label="t('goals.progressLabel', { n: fmt.number(goal.progress ?? 0, 0) })">
        <span class="text-sm font-semibold tabular-nums text-fg">{{ fmt.number(goal.progress ?? 0, 0) }}%</span>
      </ProgressRing>
      <div class="min-w-0 flex-1">
        <p class="flex flex-wrap items-baseline gap-x-1.5 tabular-nums">
          <span class="text-xl font-semibold text-fg">{{ show.value(goal, goal.value) }}</span>
          <span class="text-sm text-muted">{{ goal.better === "down" ? t("goals.atMost", { target: show.value(goal, goal.target) }) : t("goals.ofTarget", { target: show.value(goal, goal.target) }) }}</span>
        </p>
        <p v-if="showForecast" class="mt-0.5 text-sm" :class="goal.state === 'on_track' ? 'text-success' : goal.state === 'at_risk' ? 'text-warning' : 'text-danger'">
          {{ t("goals.forecast", { value: show.value(goal, goal.forecast) }) }}
        </p>
        <p v-else-if="goal.kind === 'level' && goal.baseline !== null && !finished" class="mt-0.5 text-sm text-muted">{{ t("goals.fromBaseline", { value: show.value(goal, goal.baseline) }) }}</p>
        <p v-else-if="!goal.available" class="mt-0.5 text-sm text-warning">{{ t("goals.moduleOff") }}</p>
      </div>
    </div>

    <SparkLine v-if="spark.filter((value) => value !== null).length > 1" :data="spark" :color="sparkColor" :height="34" fluid area :label="t('goals.trendLabel')" />

    <footer class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-2.5 text-xs text-muted">
      <span class="inline-flex items-center gap-1">
        <CalendarClock :size="13" aria-hidden="true" />
        <template v-if="goal.state === 'not_started'">{{ t("goals.startsOn", { date: fmt.day(goal.starts_on, "short") }) }}</template>
        <template v-else-if="finished">{{ fmt.day(goal.starts_on, "short") }} – {{ fmt.day(goal.ends_on, "short") }}</template>
        <template v-else>{{ t("goals.daysLeft", { n: goal.days_left }, goal.days_left) }}</template>
      </span>
      <span v-if="goal.branch" class="inline-flex min-w-0 items-center gap-1"><Building2 :size="13" aria-hidden="true" /><span class="truncate">{{ goal.branch.name }}</span></span>
      <span v-if="goal.owner" class="inline-flex min-w-0 items-center gap-1"><UserRound :size="13" aria-hidden="true" /><span class="truncate">{{ goal.owner.name }}</span></span>
    </footer>
  </article>
</template>
