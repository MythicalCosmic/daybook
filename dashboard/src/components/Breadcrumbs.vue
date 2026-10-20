<script setup lang="ts">
/**
 * Where you are: "Money › Finance › Accounts › Kapitalbank". Links for every level but the last;
 * with more than `max` levels the middle ones fold into a "…" menu.
 */
import { ChevronRight, Ellipsis } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter, type RouteLocationRaw } from "vue-router";

import DropdownMenu, { type MenuEntry } from "./DropdownMenu.vue";

export interface Crumb {
  label: string;
  to?: RouteLocationRaw;
}

const props = withDefaults(defineProps<{ items: Crumb[]; max?: number; size?: "sm" | "md" }>(), { max: 4, size: "md" });

const { t } = useI18n();
const router = useRouter();

const folded = computed(() => (props.items.length > props.max ? props.items.slice(1, props.items.length - (props.max - 2)) : []));
const visible = computed<Array<Crumb | "fold">>(() => {
  if (!folded.value.length) return props.items;
  return [props.items[0]!, "fold", ...props.items.slice(props.items.length - (props.max - 2))];
});
const foldMenu = computed<MenuEntry[]>(() =>
  folded.value.map((crumb) => ({ label: crumb.label, onSelect: () => crumb.to && void router.push(crumb.to) })),
);
</script>

<template>
  <nav :aria-label="t('shell.topbar.breadcrumb')" class="min-w-0">
    <ol :class="['flex min-w-0 items-center gap-1', size === 'sm' ? 'text-sm' : 'text-base']">
      <li v-for="(crumb, index) in visible" :key="index" class="flex min-w-0 items-center gap-1" :class="index === visible.length - 1 ? 'min-w-0' : 'shrink-0'">
        <ChevronRight v-if="index > 0" :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
        <DropdownMenu v-if="crumb === 'fold'" :items="foldMenu" align="start" width="200px">
          <template #trigger>
            <button type="button" class="grid h-6 w-7 place-items-center rounded-[6px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('common.more')">
              <Ellipsis :size="15" />
            </button>
          </template>
        </DropdownMenu>
        <RouterLink
          v-else-if="crumb.to && index < visible.length - 1"
          :to="crumb.to"
          class="truncate rounded-[6px] px-1.5 py-0.5 font-medium text-muted transition-colors hover:bg-highlight hover:text-fg"
          >{{ crumb.label }}</RouterLink
        >
        <span
          v-else
          :class="['truncate px-1.5', index === visible.length - 1 ? 'font-semibold text-fg' : 'font-medium text-muted']"
          :aria-current="index === visible.length - 1 ? 'page' : undefined"
          >{{ crumb.label }}</span
        >
      </li>
    </ol>
  </nav>
</template>
