<script setup lang="ts">
/**
 * Finance settings (plan §6.2 "Settings: category tree (drag, merge), rates, period lock,
 * thresholds, how reimbursements are paid"), one tab each at `finance/settings/:tab`.
 */
import { CalendarCheck, Landmark, SlidersHorizontal, Tags } from "@lucide/vue";
import { computed, defineAsyncComponent } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import PageHeader from "@/components/PageHeader.vue";
import { useCompanyStore } from "@/stores/company";

import { SETTINGS_TABS, type SettingsTab } from "../routes";

const panels: Record<SettingsTab, ReturnType<typeof defineAsyncComponent>> = {
  categories: defineAsyncComponent(() => import("../components/settings/CategoriesPanel.vue")),
  rates: defineAsyncComponent(() => import("../components/settings/RatesPanel.vue")),
  period: defineAsyncComponent(() => import("../components/settings/PeriodLockPanel.vue")),
  preferences: defineAsyncComponent(() => import("../components/settings/PreferencesPanel.vue")),
};
const icons = { categories: Tags, rates: Landmark, period: CalendarCheck, preferences: SlidersHorizontal } as const;

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();
const tab = computed<SettingsTab>(() => ((SETTINGS_TABS as readonly string[]).includes(String(route.params.tab)) ? (route.params.tab as SettingsTab) : "categories"));
const tabs = computed(() => SETTINGS_TABS.map((id) => ({ id, label: t(`finance.settings.tab.${id}`), icon: icons[id], to: `/c/${company.currentId}/finance/settings/${id}` })));
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.settings')" :description="t(`finance.settings.about.${tab}`)" :tabs="tabs" />
    <component :is="panels[tab]" :key="tab" />
  </div>
</template>
