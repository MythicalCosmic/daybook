<script setup lang="ts">
/**
 * A vacancy's applicants by stage in one slim bar (each stage its colour, as wide as its share)
 * with the counts under it; an empty vacancy shows a quiet track.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { STAGE_COLORS, stageSegments } from "../lib";
import { STAGES, type StageCounts } from "../types";

const props = withDefaults(defineProps<{ counts: StageCounts; legend?: boolean }>(), { legend: true });

const { t } = useI18n();
const segments = computed(() => stageSegments(props.counts));
const shown = computed(() => STAGES.filter((stage) => props.counts[stage] > 0));
const label = computed(() => shown.value.map((stage) => `${t(`hr.hiring.stage.${stage}`)}: ${props.counts[stage]}`).join(", "));
</script>

<template>
  <div class="flex flex-col gap-2" data-stage-bar>
    <div class="flex h-2 w-full gap-[3px] overflow-hidden rounded-full bg-surface-2 dark:bg-surface-3" role="img" :aria-label="label || t('hr.hiring.noApplicants')">
      <span v-for="segment in segments" :key="segment.stage" class="h-full first:rounded-l-full last:rounded-r-full" :style="{ width: `${segment.share * 100}%`, background: STAGE_COLORS[segment.stage] }" />
    </div>
    <ul v-if="legend && shown.length" class="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
      <li v-for="stage in shown" :key="stage" class="inline-flex items-center gap-1.5">
        <span class="size-2 rounded-full" :style="{ background: STAGE_COLORS[stage] }" aria-hidden="true" />
        {{ t(`hr.hiring.stage.${stage}`) }}
        <span class="font-semibold tabular-nums text-fg">{{ counts[stage] }}</span>
      </li>
    </ul>
  </div>
</template>
