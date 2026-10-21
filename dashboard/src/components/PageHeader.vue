<script setup lang="ts">
/**
 * The top of every page: optional back link, title, description, actions, a meta row (pills) and
 * tabs. Tabs are links when they have `to` (synced with the route) or buttons bound to `v-model:tab`.
 * The active tab's underline slides between tabs.
 */
import { ArrowLeft } from "@lucide/vue";
import { useEventListener } from "@vueuse/core";
import { computed, onMounted, ref, type Component } from "vue";
import { RouterLink, useRoute, useRouter, type RouteLocationRaw } from "vue-router";

import UiBadge from "./UiBadge.vue";
import { useSlidingIndicator } from "./useSlidingIndicator";

export interface PageTab {
  id: string;
  label: string;
  to?: RouteLocationRaw;
  count?: number;
  icon?: Component;
}

const activeTab = defineModel<string>("tab", { default: "" });

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    back?: RouteLocationRaw;
    backLabel?: string;
    tabs?: PageTab[];
  }>(),
  { description: undefined, back: undefined, backLabel: undefined, tabs: () => [] },
);

const route = useRoute();
const router = useRouter();

function isActive(tab: PageTab): boolean {
  if (tab.to) return router.resolve(tab.to).path === route.path;
  return activeTab.value === tab.id;
}

const current = computed(() => props.tabs.find(isActive)?.id ?? null);

/**
 * The same distance to the content on every page: 24 px (20 px under tabs). Half the pages put the
 * header in a `flex-col gap-5` column, whose gap used to add to the header's own margin (44 px
 * there, 24 px elsewhere), so the parent's row gap is taken off the margin.
 */
const root = ref<HTMLElement | null>(null);
const parentGap = ref(0);
function measureGap(): void {
  const parent = root.value?.parentElement;
  if (!parent || typeof getComputedStyle === "undefined") return;
  const style = getComputedStyle(parent);
  const stacked = style.display.includes("grid") || (style.display.includes("flex") && style.flexDirection.startsWith("column"));
  parentGap.value = stacked ? Number.parseFloat(style.rowGap) || 0 : 0;
}
onMounted(measureGap);
useEventListener("resize", measureGap, { passive: true });
const spacing = computed(() => `${Math.max(0, (props.tabs.length ? 20 : 24) - parentGap.value)}px`);

// The underline follows the active tab, also when a count arrives and widens a tab before it.
const tabsEl = ref<HTMLElement | null>(null);
const { indicator } = useSlidingIndicator(tabsEl, {
  active: () => `[data-tab="${current.value}"]`,
  items: "[data-tab]",
  deps: [current, () => props.tabs.map((tab) => `${tab.id}:${tab.label}:${tab.count ?? ""}`).join("|")],
});
</script>

<template>
  <header ref="root" class="flex flex-col gap-1" :style="{ marginBottom: spacing }">
    <RouterLink
      v-if="back"
      :to="back"
      class="group -ml-1 mb-1 inline-flex w-fit items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg"
    >
      <ArrowLeft :size="15" class="transition-transform duration-150 group-hover:-translate-x-0.5" />
      {{ backLabel }}
    </RouterLink>
    <div class="flex flex-wrap items-start gap-x-4 gap-y-3">
      <div class="min-w-[min(100%,260px)] flex-1">
        <h1 class="text-lg font-semibold tracking-[-0.01em] text-fg md:text-xl">{{ title }}</h1>
        <p v-if="description" class="mt-1 max-w-[720px] text-base text-muted">{{ description }}</p>
      </div>
      <!-- Never wider than the header: on phones the actions take their own full row and wrap inside it. -->
      <div v-if="$slots.actions" class="flex min-w-0 max-w-full shrink-0 flex-wrap items-center gap-2 max-sm:w-full" data-page-actions>
        <slot name="actions" />
      </div>
    </div>
    <div v-if="$slots.meta" class="mt-2 flex flex-wrap items-center gap-2">
      <slot name="meta" />
    </div>
    <nav v-if="tabs.length" ref="tabsEl" class="no-scrollbar relative -mb-px mt-4 flex gap-1 overflow-x-auto border-b border-line">
      <template v-for="tab in tabs" :key="tab.id">
        <RouterLink
          v-if="tab.to"
          :to="tab.to"
          :data-tab="tab.id"
          :class="['tab', isActive(tab) && 'is-active']"
          :aria-current="isActive(tab) ? 'page' : undefined"
        >
          <component :is="tab.icon" v-if="tab.icon" :size="15" />
          {{ tab.label }}
          <UiBadge v-if="tab.count !== undefined" :count="tab.count" :tone="isActive(tab) ? 'primary' : 'neutral'" />
        </RouterLink>
        <button
          v-else
          type="button"
          :data-tab="tab.id"
          :class="['tab', isActive(tab) && 'is-active']"
          :aria-pressed="isActive(tab)"
          @click="activeTab = tab.id"
        >
          <component :is="tab.icon" v-if="tab.icon" :size="15" />
          {{ tab.label }}
          <UiBadge v-if="tab.count !== undefined" :count="tab.count" :tone="isActive(tab) ? 'primary' : 'neutral'" />
        </button>
      </template>
      <span
        v-if="indicator"
        class="pointer-events-none absolute bottom-0 h-[2px] rounded-full bg-primary transition-[left,width] duration-240 ease-out"
        :style="{ left: `${indicator.left}px`, width: `${indicator.width}px` }"
        aria-hidden="true"
      />
    </nav>
  </header>
</template>

<style scoped>
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  padding: 0 10px;
  white-space: nowrap;
  font-size: var(--text-base);
  font-weight: 550;
  color: var(--c-muted);
  border-radius: 6px 6px 0 0;
  transition: color var(--dur-press) var(--ease-standard);
}
.tab:hover {
  color: var(--c-text);
}
.tab.is-active {
  color: var(--c-text);
}
</style>
