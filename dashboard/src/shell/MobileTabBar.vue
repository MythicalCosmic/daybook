<script setup lang="ts">
/**
 * Phones (< 768 px): Today · Work · People · Money · More (plan §6.1). Each tab goes to the first
 * module of its area the person can open; "More" opens the full navigation in a sheet.
 */
import { House, LayoutGrid, ListChecks, Users, Wallet } from "@lucide/vue";
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import type { ModuleGroup } from "@/core/modules";
import type { NavGroup, NavModule } from "@/core/nav";
import { findModule } from "@/core/modules";
import { formatCount } from "@/lib/format";

const props = defineProps<{ groups: NavGroup[]; moreOpen: boolean }>();
const emit = defineEmits<{ more: [] }>();

const { t } = useI18n();
const route = useRoute();

interface Tab {
  id: string;
  label: string;
  icon: Component;
  target: NavModule;
  groups: ModuleGroup[];
  badge: number;
}

function firstIn(groupIds: ModuleGroup[], preferred: string[] = []): NavModule | undefined {
  const all = props.groups.filter((g) => groupIds.includes(g.id)).flatMap((g) => g.modules);
  return preferred.map((id) => all.find((m) => m.moduleId === id)).find(Boolean) ?? all[0];
}

function badgeOf(groupIds: ModuleGroup[]): number {
  return props.groups.filter((g) => groupIds.includes(g.id)).reduce((sum, g) => sum + g.badge, 0);
}

const tabs = computed<Tab[]>(() => {
  const specs: Array<{ id: string; icon: Component; groups: ModuleGroup[]; preferred: string[] }> = [
    { id: "today", icon: House, groups: ["overview"], preferred: ["overview", "inbox"] },
    { id: "work", icon: ListChecks, groups: ["work"], preferred: ["tasks", "projects"] },
    { id: "people", icon: Users, groups: ["people"], preferred: ["people", "attendance"] },
    { id: "money", icon: Wallet, groups: ["money"], preferred: ["sales", "finance", "payroll"] },
  ];
  return specs.flatMap((spec) => {
    const target = firstIn(spec.groups, spec.preferred);
    if (!target) return [];
    return [{ id: spec.id, label: t(`shell.tabs.${spec.id}`), icon: spec.icon, target, groups: spec.groups, badge: badgeOf(spec.groups) }];
  });
});

const currentGroup = computed(() => findModule(route.matched.map((r) => r.meta.module).find(Boolean))?.group);
const activeTab = computed(() => {
  if (props.moreOpen) return "more";
  const group = currentGroup.value;
  return tabs.value.find((tab) => group && tab.groups.includes(group))?.id ?? "more";
});
const moreBadge = computed(() => badgeOf(["comms", "insights", "company"]));
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/90 pb-[var(--safe-bottom)] backdrop-blur-xl"
    :aria-label="t('shell.nav.label')"
  >
    <ul class="mx-auto flex h-[var(--tabbar-h)] max-w-[560px] items-stretch px-1">
      <li v-for="tab in tabs" :key="tab.id" class="flex-1">
        <RouterLink :to="tab.target.path" :class="['tab', activeTab === tab.id && 'is-active']" :aria-current="activeTab === tab.id ? 'page' : undefined">
          <span class="tab-icon">
            <component :is="tab.icon" :size="20" aria-hidden="true" />
            <span v-if="tab.badge && tab.id === 'today'" class="tab-badge">{{ formatCount(tab.badge) }}</span>
            <span v-else-if="tab.badge" class="tab-dot" />
          </span>
          <span class="truncate">{{ tab.label }}</span>
        </RouterLink>
      </li>
      <li class="flex-1">
        <button type="button" :class="['tab', activeTab === 'more' && 'is-active']" :aria-expanded="moreOpen" @click="emit('more')">
          <span class="tab-icon">
            <LayoutGrid :size="20" aria-hidden="true" />
            <span v-if="moreBadge" class="tab-dot" />
          </span>
          <span class="truncate">{{ t("shell.tabs.more") }}</span>
        </button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.tab {
  display: flex;
  height: 100%;
  width: 100%;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 0 2px;
  font-size: 11px;
  font-weight: 600;
  color: var(--c-muted);
  -webkit-tap-highlight-color: transparent;
  transition: color var(--dur-press) var(--ease-standard);
}
.tab-icon {
  position: relative;
  display: grid;
  place-items: center;
  width: 52px;
  height: 28px;
  border-radius: 999px;
  transition:
    background-color var(--dur-fade) var(--ease-out),
    transform var(--dur-press) var(--ease-standard);
}
.tab:active .tab-icon {
  transform: scale(0.94);
}
.tab.is-active {
  color: var(--c-text);
}
.tab.is-active .tab-icon {
  background: var(--c-accent-soft);
  color: var(--c-accent-fg);
}
.tab-dot {
  position: absolute;
  top: 2px;
  right: 13px;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--c-subtle);
  box-shadow: 0 0 0 2px var(--c-surface);
}
.tab-badge {
  position: absolute;
  top: -2px;
  right: 6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--c-primary);
  color: var(--c-on-primary);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  box-shadow: 0 0 0 2px var(--c-surface);
}
</style>
