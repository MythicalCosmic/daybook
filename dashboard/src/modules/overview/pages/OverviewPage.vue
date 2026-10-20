<script setup lang="ts">
/**
 * The company's front page (plan §6.2, W0 placeholder handed to package N): a greeting with the
 * company's date, the `overview.hero` slot (N's AI briefing card), then every widget the visible
 * modules registered, in their order, each fetching its own data and failing on its own. N adds
 * range presets, KPIs, charts and "Customize" on top of this grid.
 */
import { LayoutGrid } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import PageHeader from "@/components/PageHeader.vue";
import WidgetGrid from "@/components/WidgetGrid.vue";
import { isModuleVisible } from "@/core/access";
import { modules } from "@/core/modules";
import { dayPart, formatDay, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const session = useSessionStore();
const now = useNow();

const today = computed(() => todayIn(company.timezone, now.value));
const greeting = computed(() => t(`overview.greeting.${dayPart(company.timezone, now.value)}`, { name: session.me?.user.first_name || session.me?.user.full_name || "" }));
const subtitle = computed(() => [formatDay(today.value, fmt.lang.value, "weekday"), company.current?.name].filter(Boolean).join(" · "));

/** Widgets of every module the person can see here, allowed by their own perm and switch. */
const widgets = computed(() =>
  modules
    .filter((module) => isModuleVisible(module, company.current))
    .flatMap((module) => module.widgets ?? [])
    .filter((widget) => company.can(widget.perm) && company.enabled(widget.feature))
    .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id)),
);
const widgetProps = computed(() => ({ companyId: company.currentId ?? 0, range: { from: today.value, to: today.value }, compare: null }));
</script>

<template>
  <div>
    <PageHeader :title="greeting" :description="subtitle" />
    <ExtensionSlot name="overview.hero" class="mb-4 empty:hidden" :context="{ companyId: company.currentId }" />
    <WidgetGrid v-if="widgets.length" :widgets="widgets">
      <template #widget="{ widget }">
        <component :is="widget.component" v-bind="widgetProps" />
      </template>
    </WidgetGrid>
    <div v-else class="ui-card">
      <EmptyState :icon="LayoutGrid" :title="t('overview.empty.title')" :description="t('overview.empty.body')" />
    </div>
  </div>
</template>
