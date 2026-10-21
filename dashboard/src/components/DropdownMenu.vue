<script lang="ts">
export type { MenuAction, MenuCheckbox, MenuEntry, MenuRadio, MenuSub } from "./menuTypes";
</script>

<script setup lang="ts">
/**
 * A menu of actions from data: items, separators, labels, checkboxes, radio groups and submenus.
 *
 *   <DropdownMenu :items="[{ label: 'Edit', icon: Pencil, onSelect: edit }, { type: 'separator' },
 *                         { label: 'Delete', icon: Trash, danger: true, onSelect: remove }]">
 *     <template #trigger><IconButton :icon="Ellipsis" label="More" /></template>
 *   </DropdownMenu>
 *
 * The `header` and `footer` slots take custom content (the user card in the account menu).
 *
 * The menu itself (DropdownMenuPanel.vue, reka-ui and its positioning) is not in the first load:
 * it loads once the browser is idle after the first paint (AppShell), or the first time a menu
 * opens. A menu mounted before that (the top bar's) shows its trigger as it is until then; opening
 * it loads the menu and opens it, and from then on it is the real one.
 */
import { shallowRef, watch } from "vue";

import { menuPanel } from "./lazyPart";
import LazyTrigger from "./LazyTrigger";
import type { MenuEntry } from "./menuTypes";

const open = defineModel<boolean>("open", { default: false });

const props = withDefaults(
  defineProps<{
    items: MenuEntry[];
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
    sideOffset?: number;
    width?: string;
  }>(),
  { side: "bottom", align: "end", sideOffset: 6, width: "220px" },
);

const Panel = shallowRef(menuPanel.current);

function activate(): void {
  void menuPanel.load().then((panel) => {
    Panel.value = panel;
    open.value = true;
  });
}

// Opened from outside (`v-model:open`) before the menu was here.
watch(open, (value) => {
  if (value && !Panel.value) activate();
});
</script>

<template>
  <!-- Each prop by name: `props` also holds the model's own `open`, which would undo v-model. -->
  <component :is="Panel" v-if="Panel" v-model:open="open" :items="props.items" :side="props.side" :align="props.align" :side-offset="props.sideOffset" :width="props.width">
    <template #trigger="scope"><slot name="trigger" v-bind="scope" /></template>
    <template v-if="$slots.header" #header><slot name="header" /></template>
    <template v-if="$slots.footer" #footer><slot name="footer" /></template>
  </component>
  <LazyTrigger v-else @activate="activate"><slot name="trigger" :open="false" /></LazyTrigger>
</template>
