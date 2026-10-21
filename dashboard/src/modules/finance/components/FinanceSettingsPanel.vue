<script setup lang="ts">
/**
 * The finance panel of Settings (plan §6.2 "module settings panels"): the same four sections as
 * `finance/settings` (categories, rates, period lock, preferences) as tabs inside the panel, so the
 * company's Settings page and the finance module show one source of truth.
 */
import { CalendarCheck, Landmark, SlidersHorizontal, Tags } from "@lucide/vue";
import { defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";

import SegmentedControl from "@/components/SegmentedControl.vue";

import type { SettingsTab } from "../routes";

const panels = {
  categories: defineAsyncComponent(() => import("./settings/CategoriesPanel.vue")),
  rates: defineAsyncComponent(() => import("./settings/RatesPanel.vue")),
  period: defineAsyncComponent(() => import("./settings/PeriodLockPanel.vue")),
  preferences: defineAsyncComponent(() => import("./settings/PreferencesPanel.vue")),
};

const props = withDefaults(defineProps<{ initial?: SettingsTab }>(), { initial: "preferences" });
const { t } = useI18n();
const tab = ref<SettingsTab>(props.initial);
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- Four tabs don't fit a phone: they scroll sideways inside the panel, never the page. -->
    <div class="no-scrollbar overflow-x-auto">
      <SegmentedControl
        v-model="tab"
        :options="[
          { value: 'preferences', label: t('finance.settings.tab.preferences'), icon: SlidersHorizontal },
          { value: 'categories', label: t('finance.settings.tab.categories'), icon: Tags },
          { value: 'rates', label: t('finance.settings.tab.rates'), icon: Landmark },
          { value: 'period', label: t('finance.settings.tab.period'), icon: CalendarCheck },
        ]"
      />
    </div>
    <component :is="panels[tab]" />
  </div>
</template>
