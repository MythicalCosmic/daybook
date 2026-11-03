<script setup lang="ts">
/**
 * The numbers under an agent's scene (agentKpis builds them): last run with how it went, next
 * run, tokens this month (in / out) and the month's cost, in the KPI strip's frame, four across
 * and two by two on a phone. A cost the reader may not see reads "hidden" with a lock, never 0.
 */
import { Lock } from "@lucide/vue";

import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";

import type { AgentKpi } from "../agentPage";

withDefaults(defineProps<{ kpis: AgentKpi[]; loading?: boolean }>(), { loading: false });
</script>

<template>
  <KpiStrip :columns="4" phone="grid" data-testid="agent-kpis">
    <template v-if="loading">
      <div v-for="n in 4" :key="n" class="flex min-w-0 flex-col gap-3 p-4" aria-hidden="true">
        <SkeletonBlock width="50%" height="14px" />
        <SkeletonBlock width="70%" height="26px" />
        <SkeletonBlock width="40%" height="12px" />
      </div>
    </template>
    <template v-else>
      <div v-for="kpi in kpis" :key="kpi.id" class="flex min-w-0 flex-col p-4 @container" :data-kpi="kpi.id">
        <span class="kpi-label">{{ kpi.label }}</span>
        <p :class="['num mt-1.5 flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-xl font-semibold leading-8 tracking-[-0.02em] md:text-[1.625rem]', kpi.hidden ? 'text-muted' : 'text-fg']" aria-live="polite">
          <Lock v-if="kpi.hidden" :size="18" class="shrink-0 self-center" aria-hidden="true" />
          <span class="truncate">{{ kpi.value }}</span>
          <span v-if="kpi.secondary" class="truncate text-base font-medium tracking-normal text-muted">{{ kpi.secondary }}</span>
        </p>
        <div class="mt-auto flex min-h-[28px] min-w-0 flex-wrap items-center gap-x-2 gap-y-1 pt-2">
          <StatusPill v-if="kpi.status" size="sm" :tone="kpi.status.tone" :live="kpi.status.live" :label="kpi.status.label" />
          <span v-if="kpi.hint" class="line-clamp-2 min-w-0 text-xs text-muted">{{ kpi.hint }}</span>
        </div>
      </div>
    </template>
  </KpiStrip>
</template>
