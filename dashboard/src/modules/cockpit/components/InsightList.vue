<script setup lang="ts">
/**
 * "What the numbers say": the live insights, urgent first, the first few at once and the rest on
 * "Show all". An insight a Telegram message opened (`focus`) is shown and brought into view.
 */
import { Sparkles } from "@lucide/vue";
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";

import type { CockpitInsights } from "../api";
import InsightCard from "./InsightCard.vue";

const props = withDefaults(defineProps<{ insights: CockpitInsights; allowed?: boolean; focus?: number | null; first?: number; wide?: boolean }>(), {
  allowed: true,
  focus: null,
  first: 4,
  wide: false,
});

const { t } = useI18n();
const open = ref(false);
const list = ref<HTMLElement | null>(null);

const focusIndex = computed(() => props.insights.items.findIndex((item) => item.id === props.focus));
const shown = computed(() => (open.value || focusIndex.value >= props.first ? props.insights.items : props.insights.items.slice(0, props.first)));
const hidden = computed(() => props.insights.items.length - shown.value.length);

async function reveal(): Promise<void> {
  if (props.focus === null || focusIndex.value < 0) return;
  await nextTick();
  list.value?.querySelector<HTMLElement>(`[data-insight="${props.focus}"]`)?.scrollIntoView?.({ block: "center", behavior: "smooth" });
}
onMounted(reveal);
watch(() => props.focus, reveal);
</script>

<template>
  <section class="ui-card flex min-w-0 flex-col" :aria-label="t('cockpit.insights.title')" data-insights>
    <header class="flex items-center gap-3 px-4 pb-3 pt-4">
      <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg" aria-hidden="true"><Sparkles :size="17" /></span>
      <div class="min-w-0 flex-1">
        <h2 class="text-base font-semibold leading-5 text-fg">{{ t("cockpit.insights.title") }}</h2>
        <p class="text-xs text-muted">{{ t("cockpit.insights.subtitle") }}</p>
      </div>
      <UiBadge v-if="insights.critical" :count="insights.critical" tone="danger" />
      <UiBadge v-else-if="insights.open" :count="insights.open" tone="primary" />
    </header>
    <EmptyState v-if="!allowed" class="border-t border-line" size="sm" :title="t('cockpit.insights.noAccess')" />
    <EmptyState v-else-if="!insights.items.length" class="border-t border-line" size="sm" tone="success" :title="t('cockpit.insights.empty')" :description="t('cockpit.insights.emptyBody')" />
    <template v-else>
      <div ref="list" :class="['border-t border-line', wide && 'lg:border-t-0 lg:px-4 lg:pb-4']">
        <TransitionGroup name="list" tag="div" :class="['relative flex flex-col divide-y divide-line', wide && 'lg:grid lg:gap-3 lg:divide-y-0 xl:grid-cols-2']">
          <InsightCard v-for="insight in shown" :key="insight.id" :insight="insight" :focused="insight.id === focus" :boxed="wide" />
        </TransitionGroup>
      </div>
      <footer v-if="hidden > 0 || open" class="border-t border-line px-4 py-2">
        <UiButton variant="ghost" size="sm" block @click="open = !open">{{ open ? t("cockpit.insights.less") : t("cockpit.insights.more", { n: insights.items.length }) }}</UiButton>
      </footer>
    </template>
  </section>
</template>
