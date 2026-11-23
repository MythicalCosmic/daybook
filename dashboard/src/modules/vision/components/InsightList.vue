<script setup lang="ts">
/**
 * What stood out on the day (docs/KOZ.md §6.1 `insights`): the server's sentences, most important
 * first, each with its severity and the hour it is about. Lost sales in red, things worth a look in
 * amber, good news in green.
 */
import { Info, Lightbulb, OctagonAlert, Sparkles, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";

import { bySeverity, hourRange } from "../lib/overview";
import type { Insight, Severity } from "../types";

const props = withDefaults(defineProps<{ insights: Insight[]; loading?: boolean }>(), { loading: false });

const { t } = useI18n();

const ICONS: Record<Severity, typeof Info> = { bad: OctagonAlert, warn: TriangleAlert, info: Info, good: Sparkles };
const items = computed(() => bySeverity(props.insights));
</script>

<template>
  <section class="ui-card flex min-w-0 flex-col" :aria-label="t('vision.insights.title')">
    <header class="flex items-center gap-2.5 px-4 pb-2 pt-4">
      <span class="grid size-7 place-items-center rounded-[9px] bg-accent-soft text-accent-fg"><Lightbulb :size="15" /></span>
      <h2 class="text-base font-semibold text-fg">{{ t("vision.insights.title") }}</h2>
    </header>
    <div v-if="loading" class="flex flex-col gap-3 px-4 pb-4 pt-1">
      <SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="12px" />
    </div>
    <p v-else-if="!items.length" class="px-4 pb-5 pt-1 text-sm text-muted">{{ t("vision.insights.empty") }}</p>
    <ul v-else class="flex flex-col gap-2 px-3 pb-3 pt-1">
      <li v-for="(insight, index) in items" :key="`${insight.kind}:${index}`" class="koz-insight relative flex gap-3 rounded-[12px] py-3 pl-4 pr-3" :data-severity="insight.severity">
        <span class="koz-insight-bar absolute inset-y-3 left-0 w-1 rounded-r-full" aria-hidden="true" />
        <span class="koz-insight-icon grid size-8 shrink-0 place-items-center rounded-[9px]" aria-hidden="true"><component :is="ICONS[insight.severity]" :size="16" /></span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span class="koz-insight-tag text-xs font-semibold">{{ t(`vision.severity.${insight.severity}`) }}</span>
            <span v-if="insight.hour !== null" class="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-muted dark:bg-surface-3">{{ hourRange(insight.hour) }}</span>
          </div>
          <p class="mt-1 text-sm leading-5 text-fg">{{ insight.text }}</p>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.koz-insight {
  --tone: var(--c-info);
  --tone-soft: var(--c-info-soft);
  background: color-mix(in srgb, var(--tone-soft) 45%, transparent);
}
.koz-insight[data-severity="bad"] {
  --tone: var(--c-danger);
  --tone-soft: var(--c-danger-soft);
}
.koz-insight[data-severity="warn"] {
  --tone: var(--c-warning);
  --tone-soft: var(--c-warning-soft);
}
.koz-insight[data-severity="good"] {
  --tone: var(--c-success);
  --tone-soft: var(--c-success-soft);
}
.koz-insight-bar {
  background: var(--tone);
}
.koz-insight-icon {
  background: var(--tone-soft);
  color: var(--tone);
}
.koz-insight-tag {
  color: var(--tone);
}
</style>
