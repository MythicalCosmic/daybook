<script setup lang="ts">
/**
 * Company switcher (plan §13.1): its button in the sidebar, the rail or the phone's top bar, and
 * the menu of every company (CompanySwitcherMenu.vue). The menu is reka-ui and loads with the
 * other menus once the browser is idle, or when the button is first used: until then the button is
 * plain, and using it loads the menu and opens it (README "Budgets").
 */
import { ref, shallowRef } from "vue";

import LazyTrigger from "@/components/LazyTrigger";
import UiTooltip from "@/components/UiTooltip.vue";

import CompanySwitcherButton from "./CompanySwitcherButton.vue";
import { companyMenu, useCompanySwitcher, type SwitcherVariant } from "./companySwitcher";

const props = withDefaults(defineProps<{ variant?: SwitcherVariant }>(), { variant: "sidebar" });

const { current, label, elsewhere } = useCompanySwitcher();
const Menu = shallowRef(companyMenu.current);
const open = ref(false);

function activate(): void {
  void companyMenu.load().then((menu) => {
    Menu.value = menu;
    open.value = true;
  });
}
</script>

<template>
  <!-- The rail shows only the logo: its name is the tooltip (the menu puts it around its own trigger). -->
  <component :is="Menu" v-if="Menu" v-model:open="open" :variant="variant" :tooltip="props.variant === 'rail' ? label : undefined">
    <template #trigger>
      <CompanySwitcherButton :variant="variant" :current="current" :label="label" :elsewhere="elsewhere" />
    </template>
  </component>
  <UiTooltip v-else :content="label" side="right" :disabled="props.variant !== 'rail'">
    <LazyTrigger @activate="activate">
      <CompanySwitcherButton :variant="variant" :current="current" :label="label" :elsewhere="elsewhere" />
    </LazyTrigger>
  </UiTooltip>
</template>
