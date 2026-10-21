<script setup lang="ts">
/**
 * DropdownMenu's menu itself, on reka-ui (its positioning comes with it). Not used directly: pages
 * use DropdownMenu.vue, which loads this the first time a menu opens or once the browser is idle,
 * so none of it is in the first load (README "Budgets").
 */
import { Check, ChevronRight } from "@lucide/vue";
import {
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuItemIndicator,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "reka-ui";

import KbdKey from "./KbdKey.vue";
import type { MenuEntry } from "./menuTypes";

const open = defineModel<boolean>("open", { default: false });

withDefaults(
  defineProps<{
    items: MenuEntry[];
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
    sideOffset?: number;
    width?: string;
  }>(),
  { side: "bottom", align: "end", sideOffset: 6, width: "220px" },
);

const itemClass =
  "group relative flex h-8 cursor-default select-none items-center gap-2.5 rounded-[7px] px-2 text-base text-fg outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-highlight data-[disabled]:opacity-45";
const panelClass = "anim-pop z-[70] rounded-[12px] border border-line bg-surface p-1 text-fg shadow-pop outline-none";
</script>

<template>
  <DropdownMenuRoot v-model:open="open">
    <DropdownMenuTrigger as-child>
      <slot name="trigger" :open="open" />
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent :side="side" :align="align" :side-offset="sideOffset" :collision-padding="8" :class="panelClass" :style="{ width }">
        <slot name="header" />
        <template v-for="(entry, index) in items" :key="index">
          <DropdownMenuSeparator v-if="entry.type === 'separator'" class="-mx-1 my-1 h-px bg-line" />
          <DropdownMenuLabel v-else-if="entry.type === 'label'" class="px-2 pb-1 pt-2 text-xs font-medium text-muted">{{ entry.label }}</DropdownMenuLabel>
          <DropdownMenuCheckboxItem
            v-else-if="entry.type === 'checkbox'"
            :model-value="entry.checked"
            :disabled="entry.disabled"
            :class="itemClass"
            @update:model-value="(value: boolean) => entry.onToggle(value)"
          >
            <component :is="entry.icon" v-if="entry.icon" :size="16" class="text-muted" />
            <span class="flex-1 truncate">{{ entry.label }}</span>
            <DropdownMenuItemIndicator><Check :size="15" class="text-primary" /></DropdownMenuItemIndicator>
          </DropdownMenuCheckboxItem>
          <DropdownMenuRadioGroup
            v-else-if="entry.type === 'radio'"
            :model-value="entry.value"
            @update:model-value="(value) => entry.onChange(String(value))"
          >
            <DropdownMenuRadioItem v-for="option in entry.options" :key="option.value" :value="option.value" :class="itemClass">
              <component :is="option.icon" v-if="option.icon" :size="16" class="text-muted" />
              <span class="flex-1 truncate">{{ option.label }}</span>
              <DropdownMenuItemIndicator><Check :size="15" class="text-primary" /></DropdownMenuItemIndicator>
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
          <DropdownMenuSub v-else-if="entry.type === 'sub'">
            <DropdownMenuSubTrigger :class="[itemClass, 'data-[state=open]:bg-highlight']">
              <component :is="entry.icon" v-if="entry.icon" :size="16" class="text-muted" />
              <span class="flex-1 truncate">{{ entry.label }}</span>
              <span v-if="entry.hint" class="text-sm text-muted">{{ entry.hint }}</span>
              <ChevronRight :size="15" class="text-muted" />
            </DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent :side-offset="6" :collision-padding="8" :class="panelClass" style="min-width: 200px">
                <template v-for="(child, childIndex) in entry.items" :key="childIndex">
                  <DropdownMenuSeparator v-if="child.type === 'separator'" class="-mx-1 my-1 h-px bg-line" />
                  <DropdownMenuRadioGroup
                    v-else-if="child.type === 'radio'"
                    :model-value="child.value"
                    @update:model-value="(value) => child.onChange(String(value))"
                  >
                    <DropdownMenuRadioItem v-for="option in child.options" :key="option.value" :value="option.value" :class="itemClass">
                      <component :is="option.icon" v-if="option.icon" :size="16" class="text-muted" />
                      <span class="flex-1 truncate">{{ option.label }}</span>
                      <DropdownMenuItemIndicator><Check :size="15" class="text-primary" /></DropdownMenuItemIndicator>
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                  <DropdownMenuItem
                    v-else-if="child.type === undefined || child.type === 'item'"
                    :disabled="child.disabled"
                    :class="[itemClass, child.danger && 'text-danger data-[highlighted]:bg-danger-soft']"
                    @select="child.onSelect()"
                  >
                    <component :is="child.icon" v-if="child.icon" :size="16" :class="child.danger ? '' : 'text-muted'" />
                    <span class="flex-1 truncate">{{ child.label }}</span>
                  </DropdownMenuItem>
                </template>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>
          <DropdownMenuItem
            v-else
            :disabled="entry.disabled"
            :class="[itemClass, entry.description && 'h-auto py-1.5', entry.danger && 'text-danger data-[highlighted]:bg-danger-soft']"
            @select="entry.onSelect()"
          >
            <component :is="entry.icon" v-if="entry.icon" :size="16" :class="entry.danger ? '' : 'text-muted group-data-[highlighted]:text-fg'" />
            <span class="min-w-0 flex-1">
              <span class="block truncate">{{ entry.label }}</span>
              <span v-if="entry.description" class="block truncate text-xs text-muted">{{ entry.description }}</span>
            </span>
            <KbdKey v-if="entry.shortcut" :keys="entry.shortcut" />
          </DropdownMenuItem>
        </template>
        <slot name="footer" />
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
