<script setup lang="ts">
/**
 * The sidebar (plan §6.1): 248 px, or a 64 px rail (toggled with "["). Groups and items come from
 * the registry, already filtered by permission and feature switch; badges come from pulse.
 * Hovering a link starts loading its page.
 */
import { ChevronRight, PanelLeftClose, PanelLeftOpen } from "@lucide/vue";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { prefetchPath } from "@/app/navigation";
import ConnectionPill from "@/components/ConnectionPill.vue";
import KbdKey from "@/components/KbdKey.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { activeEntryKey, isActivePath, type NavGroup, type NavModule } from "@/core/nav";
import { formatCount } from "@/lib/format";
import { readStored, writeStored } from "@/lib/storage";

import CompanySwitcher from "./CompanySwitcher.vue";

const props = defineProps<{ groups: NavGroup[]; rail: boolean; ready: boolean; canCollapse: boolean }>();
const emit = defineEmits<{ toggle: []; retry: [] }>();

const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const activeKey = computed(() => activeEntryKey(props.groups, route.path));

const expanded = ref<string[]>(readStored("navExpanded", [], (v): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string")));

function containsRoute(module: NavModule): boolean {
  return [module, ...module.children].some((entry) => isActivePath(entry, route.path));
}

function isOpen(module: NavModule): boolean {
  return module.children.length > 0 && (expanded.value.includes(module.key) || containsRoute(module));
}

function toggle(module: NavModule): void {
  const open = isOpen(module);
  expanded.value = open ? expanded.value.filter((key) => key !== module.key) : [...expanded.value, module.key];
  writeStored("navExpanded", expanded.value);
}

// Entering a module from elsewhere remembers it as expanded, so it stays open when you leave.
watch(
  () => route.path,
  () => {
    for (const group of props.groups) {
      for (const module of group.modules) {
        if (module.children.length && containsRoute(module) && !expanded.value.includes(module.key)) {
          expanded.value = [...expanded.value, module.key];
          writeStored("navExpanded", expanded.value);
        }
      }
    }
  },
);

const scroller = ref<HTMLElement | null>(null);
watch(
  () => [route.path, props.ready] as const,
  async () => {
    await nextTick();
    scroller.value?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView({ block: "nearest" });
  },
  { immediate: true },
);

function prefetch(path: string): void {
  prefetchPath(router, path);
}
</script>

<template>
  <nav
    :aria-label="t('shell.nav.label')"
    class="sticky top-0 flex h-dvh flex-col overflow-hidden bg-[var(--c-nav)] transition-[width] duration-240 ease-out"
    :style="{ width: rail ? 'var(--rail-w)' : 'var(--nav-w)' }"
  >
    <div :class="['flex h-[var(--topbar-h)] shrink-0 items-center', rail ? 'justify-center px-0 pt-2' : 'px-3 pt-2']">
      <CompanySwitcher :variant="rail ? 'rail' : 'sidebar'" />
    </div>

    <div ref="scroller" class="scroll-fade-y no-scrollbar min-h-0 flex-1 overflow-y-auto px-3 pb-3 pt-2">
      <div v-if="!ready" class="flex flex-col gap-2.5 px-2 pt-2">
        <SkeletonBlock v-for="n in 9" :key="n" :width="rail ? '24px' : `${55 + ((n * 17) % 40)}%`" height="14px" />
      </div>
      <template v-else>
        <section v-for="(group, groupIndex) in groups" :key="group.id" :class="groupIndex > 0 && (rail ? 'mt-2 border-t border-line pt-2' : 'mt-5')">
          <h2 v-if="!rail && group.id !== 'overview'" class="mb-1 truncate px-2.5 text-xs font-medium text-subtle">
            {{ t(`shell.group.${group.id}`) }}
          </h2>
          <ul class="flex flex-col gap-px">
            <li v-for="module in group.modules" :key="module.key">
              <!-- Rail: one icon per module, title and count in the tooltip. -->
              <UiTooltip v-if="rail" side="right" :side-offset="10">
                <template #content>
                  <span>{{ t(module.title) }}</span>
                  <span v-if="module.badge" class="rounded-full bg-white/15 px-1.5 text-[10px] font-semibold">{{ formatCount(module.badge) }}</span>
                </template>
                <RouterLink
                  :to="module.path"
                  :class="['nav-rail-item', containsRoute(module) && 'is-active']"
                  :aria-label="t(module.title)"
                  :aria-current="containsRoute(module) ? 'page' : undefined"
                  @pointerenter="prefetch(module.path)"
                >
                  <component :is="module.icon" :size="18" aria-hidden="true" />
                  <span v-if="module.badge" class="absolute right-2 top-2 size-[7px] rounded-full bg-[var(--c-subtle)] ring-2 ring-[var(--c-nav)]" />
                </RouterLink>
              </UiTooltip>

              <template v-else>
                <div class="group/row relative flex items-center">
                  <RouterLink
                    :to="module.path"
                    :class="[
                      'nav-item',
                      module.children.length === 0 && activeKey === module.key && 'is-current',
                      containsRoute(module) && 'is-within',
                    ]"
                    :aria-current="module.children.length === 0 && activeKey === module.key ? 'page' : undefined"
                    @pointerenter="prefetch(module.path)"
                  >
                    <component :is="module.icon" :size="17" class="nav-icon" aria-hidden="true" />
                    <span class="min-w-0 flex-1 truncate">{{ t(module.title) }}</span>
                    <UiBadge v-if="module.badge && !isOpen(module)" :count="module.badge" :tone="containsRoute(module) ? 'primary' : 'neutral'" />
                    <span v-if="module.children.length" class="w-5 shrink-0" aria-hidden="true" />
                  </RouterLink>
                  <button
                    v-if="module.children.length"
                    type="button"
                    :class="[
                      'absolute right-1 grid size-6 place-items-center rounded-[6px] text-subtle transition-opacity duration-120 hover:bg-[var(--c-nav-hover)] hover:text-fg focus-visible:opacity-100',
                      isOpen(module) || containsRoute(module) ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100',
                    ]"
                    :aria-expanded="isOpen(module)"
                    :aria-label="t('shell.nav.showPages')"
                    @click="toggle(module)"
                  >
                    <ChevronRight :size="14" :class="['transition-transform duration-180 ease-out', isOpen(module) && 'rotate-90']" />
                  </button>
                </div>
                <Transition name="collapse">
                  <div v-if="isOpen(module)">
                    <ul class="ml-[19px] mt-px flex min-h-0 flex-col gap-px overflow-hidden border-l border-line py-0.5 pl-2">
                      <li v-for="child in module.children" :key="child.key">
                        <RouterLink
                          :to="child.path"
                          :class="['nav-child', activeKey === child.key && 'is-current']"
                          :aria-current="activeKey === child.key ? 'page' : undefined"
                          @pointerenter="prefetch(child.path)"
                        >
                          <span class="min-w-0 flex-1 truncate">{{ t(child.title) }}</span>
                          <UiBadge v-if="child.badge" :count="child.badge" :tone="activeKey === child.key ? 'primary' : 'neutral'" />
                        </RouterLink>
                      </li>
                    </ul>
                  </div>
                </Transition>
              </template>
            </li>
          </ul>
        </section>
      </template>
    </div>

    <div :class="['flex shrink-0 items-center gap-1 border-t border-line py-2', rail ? 'flex-col px-2' : 'px-3']">
      <ConnectionPill :compact="rail" @retry="emit('retry')" />
      <span v-if="!rail" class="flex-1" />
      <UiTooltip v-if="canCollapse" :content="rail ? t('shell.nav.expand') : t('shell.nav.collapse')" shortcut="[" :side="rail ? 'right' : 'top'">
        <button
          type="button"
          class="pressable flex h-8 items-center gap-2 rounded-button px-2 text-sm font-medium text-muted hover:bg-[var(--c-nav-hover)] hover:text-fg"
          :class="rail && 'w-10 justify-center px-0'"
          :aria-label="rail ? t('shell.nav.expand') : t('shell.nav.collapse')"
          @click="emit('toggle')"
        >
          <PanelLeftOpen v-if="rail" :size="17" />
          <PanelLeftClose v-else :size="17" />
          <KbdKey v-if="!rail" keys="[" />
        </button>
      </UiTooltip>
    </div>
  </nav>
</template>

<style scoped>
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 32px;
  padding: 0 8px 0 10px;
  border-radius: 8px;
  font-size: var(--text-base);
  font-weight: 500;
  color: color-mix(in srgb, var(--c-text) 82%, var(--c-muted));
  transition:
    background-color var(--dur-press) var(--ease-standard),
    color var(--dur-press) var(--ease-standard),
    box-shadow var(--dur-press) var(--ease-standard);
}
.nav-item:hover {
  background: var(--c-nav-hover);
  color: var(--c-text);
}
.nav-item .nav-icon {
  color: var(--c-muted);
  transition: color var(--dur-press) var(--ease-standard);
}
.nav-item:hover .nav-icon {
  color: var(--c-text);
}
.nav-item.is-within {
  color: var(--c-text);
  font-weight: 600;
}
.nav-item.is-within .nav-icon {
  color: var(--c-primary);
}
.nav-item.is-current {
  background: var(--c-nav-active);
  box-shadow: var(--sh-raised);
}

.nav-child {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 8px;
  border-radius: 7px;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--c-muted);
  transition:
    background-color var(--dur-press) var(--ease-standard),
    color var(--dur-press) var(--ease-standard);
}
.nav-child:hover {
  background: var(--c-nav-hover);
  color: var(--c-text);
}
.nav-child.is-current {
  background: var(--c-nav-active);
  color: var(--c-text);
  font-weight: 600;
  box-shadow: var(--sh-raised);
}

.nav-rail-item {
  position: relative;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  margin: 0 auto;
  border-radius: 10px;
  color: var(--c-muted);
  transition:
    background-color var(--dur-press) var(--ease-standard),
    color var(--dur-press) var(--ease-standard);
}
.nav-rail-item:hover {
  background: var(--c-nav-hover);
  color: var(--c-text);
}
.nav-rail-item.is-active {
  background: var(--c-nav-active);
  color: var(--c-primary);
  box-shadow: var(--sh-raised);
}
</style>
