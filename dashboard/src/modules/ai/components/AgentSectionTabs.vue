<script setup lang="ts" generic="T extends string">
/**
 * The sections of an agent's page: tabs with a sliding underline on wider screens (arrow keys move
 * between them), a segmented control on phones, where five sections scroll sideways inside it.
 */
import { computed, ref, type Component } from "vue";

import SegmentedControl from "@/components/SegmentedControl.vue";
import { useSlidingIndicator } from "@/components/useSlidingIndicator";
import { useBreakpoints } from "@/lib/useBreakpoints";

export interface SectionTab<V extends string> {
  id: V;
  label: string;
  icon?: Component;
  count?: number;
}

const active = defineModel<T>({ required: true });
const props = defineProps<{ tabs: SectionTab<T>[]; label: string; panelId: string }>();

const { isPhone } = useBreakpoints();
const strip = ref<HTMLElement | null>(null);
const { indicator } = useSlidingIndicator(strip, {
  active: () => `[data-section="${active.value}"]`,
  items: "[data-section]",
  reveal: true,
  deps: [active, () => props.tabs.map((tab) => `${tab.id}:${tab.label}:${tab.count ?? ""}`).join("|")],
});
const options = computed(() => props.tabs.map((tab) => ({ value: tab.id, label: tab.label, count: tab.count })));

function move(event: KeyboardEvent, index: number): void {
  const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
  const target = event.key === "Home" ? 0 : event.key === "End" ? props.tabs.length - 1 : step ? (index + step + props.tabs.length) % props.tabs.length : -1;
  if (target < 0) return;
  event.preventDefault();
  active.value = props.tabs[target]!.id;
  strip.value?.querySelectorAll<HTMLElement>("[data-section]")[target]?.focus();
}
</script>

<template>
  <SegmentedControl v-if="isPhone" v-model="active" :options="options" block :aria-label="label" data-testid="agent-sections" />
  <div v-else ref="strip" class="no-scrollbar relative flex gap-1 overflow-x-auto border-b border-line" role="tablist" :aria-label="label" data-testid="agent-sections">
    <button
      v-for="(tab, index) in tabs"
      :id="`${panelId}-tab-${tab.id}`"
      :key="tab.id"
      type="button"
      role="tab"
      :aria-selected="active === tab.id"
      :aria-controls="panelId"
      :tabindex="active === tab.id ? 0 : -1"
      :data-section="tab.id"
      :class="['section-tab', active === tab.id && 'is-active']"
      @click="active = tab.id"
      @keydown="move($event, index)"
    >
      <component :is="tab.icon" v-if="tab.icon" :size="15" aria-hidden="true" />
      {{ tab.label }}
      <span v-if="tab.count !== undefined" class="rounded-full bg-[color-mix(in_srgb,var(--c-text)_8%,transparent)] px-1.5 py-px text-[11px] leading-4 tabular-nums">{{ tab.count }}</span>
    </button>
    <span
      v-if="indicator"
      class="pointer-events-none absolute bottom-0 h-[2px] rounded-full bg-primary transition-[left,width] duration-240 ease-out"
      :style="{ left: `${indicator.left}px`, width: `${indicator.width}px` }"
      aria-hidden="true"
    />
  </div>
</template>

<style scoped>
/* The same tab as PageHeader's. */
.section-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 10px;
  white-space: nowrap;
  font-size: var(--text-base);
  font-weight: 550;
  color: var(--c-muted);
  border-radius: 6px 6px 0 0;
  transition: color var(--dur-press) var(--ease-standard);
}
.section-tab:hover,
.section-tab.is-active {
  color: var(--c-text);
}
</style>
