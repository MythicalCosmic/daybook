<script setup lang="ts">
/**
 * Person 360's tabs as links (the tab is part of the path, so a tab can be shared): the same look
 * as PageHeader's tabs, with the sliding underline, scrolling sideways on phones.
 */
import { nextTick, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";

const props = defineProps<{ tabs: Array<{ id: string; label: string; to: string }>; active: string }>();

const strip = ref<HTMLElement | null>(null);
const indicator = ref<{ left: number; width: number } | null>(null);

function measure(): void {
  const el = strip.value?.querySelector<HTMLElement>(`[data-tab="${props.active}"]`);
  indicator.value = el ? { left: el.offsetLeft, width: el.offsetWidth } : null;
  // Bring the active tab into view sideways only: scrollIntoView would also scroll the page.
  const nav = strip.value;
  if (el && nav && nav.scrollWidth > nav.clientWidth) {
    const left = el.offsetLeft;
    const right = left + el.offsetWidth;
    if (left < nav.scrollLeft) nav.scrollLeft = left;
    else if (right > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = right - nav.clientWidth;
  }
}

watch(() => [props.active, props.tabs.length], () => nextTick(measure));
onMounted(() => {
  measure();
  void document.fonts?.ready.then(measure);
});
</script>

<template>
  <nav ref="strip" class="no-scrollbar relative flex gap-1 overflow-x-auto border-b border-line" :aria-label="$attrs['aria-label'] as string">
    <RouterLink
      v-for="tab in tabs"
      :key="tab.id"
      :to="tab.to"
      :data-tab="tab.id"
      :class="['tab', tab.id === active && 'is-active']"
      :aria-current="tab.id === active ? 'page' : undefined"
      >{{ tab.label }}</RouterLink
    >
    <span
      v-if="indicator"
      class="pointer-events-none absolute bottom-0 h-[2px] rounded-full bg-primary transition-[left,width] duration-240 ease-out"
      :style="{ left: `${indicator.left}px`, width: `${indicator.width}px` }"
      aria-hidden="true"
    />
  </nav>
</template>

<style scoped>
.tab {
  display: inline-flex;
  align-items: center;
  height: 38px;
  padding: 0 10px;
  white-space: nowrap;
  font-size: var(--text-base);
  font-weight: 550;
  color: var(--c-muted);
  border-radius: 6px 6px 0 0;
  transition: color var(--dur-press) var(--ease-standard);
}
.tab:hover,
.tab.is-active {
  color: var(--c-text);
}
</style>
