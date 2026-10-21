<script setup lang="ts">
/**
 * The company's front page (plan §6.2): a greeting with the company's date, the `overview.hero`
 * slot (N's AI briefing card), then every widget the visible modules registered, arranged as one
 * cockpit (layout.ts): the cards that lead the page, every KPI tile in one band, then the cards and
 * charts in rows that never leave a hole. Each widget fetches its own data and fails on its own.
 *
 * "Customize" lets the person drag cards into their own order and hide the ones they don't need;
 * the arrangement is their `overview` SavedView, and "Reset" goes back to the registered order.
 */
import { Check, LayoutGrid, RotateCcw, SlidersHorizontal } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import PageHeader from "@/components/PageHeader.vue";
import UiButton from "@/components/UiButton.vue";
import WidgetGrid from "@/components/WidgetGrid.vue";
import { arrange, EMPTY_LAYOUT, type WidgetLayout } from "@/components/widgetLayout";
import { isModuleVisible } from "@/core/access";
import { modules, type WidgetSpan } from "@/core/modules";
import { dayPart, formatDay, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useSavedViews } from "@/lib/useSavedViews";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import WidgetCell from "../components/WidgetCell.vue";
import { cockpit, isDefaultLayout, LAYOUT_VIEW, layoutFromState, layoutToState } from "../layout";

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

// The person's own arrangement (their `overview` SavedView), applied as soon as it arrives.
const views = useSavedViews("overview");
const saved = computed(() => (views.list.data.value ?? []).find((view) => view.is_mine && view.name === LAYOUT_VIEW) ?? null);
const layout = ref<WidgetLayout>(EMPTY_LAYOUT);
const editing = ref(false);
watch(
  saved,
  (view) => {
    if (!editing.value) layout.value = layoutFromState(view?.state);
  },
  { immediate: true },
);

const shown = computed(() => arrange(widgets.value, layout.value).filter((widget) => !widget.hidden));
const bands = computed(() => cockpit(shown.value));

/** Two columns below desktop (an odd last tile takes the whole row), the packed span on desktop. */
const KPI_SPAN: Record<WidgetSpan, string> = { 1: "lg:col-span-1", 2: "lg:col-span-2", 3: "lg:col-span-3", 4: "lg:col-span-4" };
const CARD_SPAN: Record<WidgetSpan, string> = { 1: "md:col-span-1 lg:col-span-1", 2: "md:col-span-2 lg:col-span-2", 3: "md:col-span-2 lg:col-span-3", 4: "md:col-span-2 lg:col-span-4" };

async function finish(): Promise<void> {
  editing.value = false;
  const current = saved.value;
  try {
    if (isDefaultLayout(widgets.value, layout.value)) {
      if (current) await views.remove.mutateAsync(current.id);
    } else {
      const state = { ...layoutToState(widgets.value, layout.value) };
      if (current) await views.update.mutateAsync({ id: current.id, state });
      else await views.create.mutateAsync({ name: LAYOUT_VIEW, state });
    }
  } catch {
    // The API layer already said what went wrong; the layout stays as arranged on this page.
  }
}
</script>

<template>
  <div>
    <PageHeader :title="greeting" :description="subtitle">
      <template v-if="widgets.length" #actions>
        <template v-if="editing">
          <UiButton variant="ghost" size="sm" :icon="RotateCcw" :disabled="isDefaultLayout(widgets, layout)" @click="layout = EMPTY_LAYOUT">
            {{ t("overview.customize.reset") }}
          </UiButton>
          <UiButton variant="primary" size="sm" :icon="Check" @click="finish">{{ t("common.done") }}</UiButton>
        </template>
        <UiButton v-else variant="ghost" size="sm" :icon="SlidersHorizontal" @click="editing = true">{{ t("overview.customize.open") }}</UiButton>
      </template>
    </PageHeader>
    <ExtensionSlot name="overview.hero" class="mb-4 empty:hidden" :context="{ companyId: company.currentId }" />

    <template v-if="editing">
      <p class="mb-3 text-sm text-muted">{{ t("overview.customize.hint") }}</p>
      <WidgetGrid v-model:layout="layout" :widgets="widgets" editing>
        <template #widget="{ widget }">
          <WidgetCell :widget="widget" :widget-props="widgetProps" />
        </template>
      </WidgetGrid>
    </template>

    <div v-else-if="shown.length" class="flex flex-col gap-3">
      <div v-for="widget in bands.lead" :key="widget.id" :data-widget="widget.id" class="min-w-0 empty:hidden">
        <WidgetCell :widget="widget" :widget-props="widgetProps" />
      </div>
      <div v-if="bands.kpis.length" class="grid grid-cols-2 gap-3 lg:grid-cols-4" data-band="kpis">
        <div
          v-for="{ widget, span } in bands.kpis"
          :key="widget.id"
          :data-widget="widget.id"
          :class="['min-w-0 empty:hidden max-lg:last:odd:col-span-2', KPI_SPAN[span]]"
        >
          <WidgetCell :widget="widget" :widget-props="widgetProps" />
        </div>
      </div>
      <!-- A row is as tall as its tallest card, at most 22rem (26rem stacked on phones): longer lists scroll inside. -->
      <div v-if="bands.cards.length" class="grid grid-flow-row-dense grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4" data-band="cards">
        <div v-for="{ widget, span } in bands.cards" :key="widget.id" :data-widget="widget.id" :class="['min-w-0 max-h-[26rem] empty:hidden lg:max-h-[22rem]', CARD_SPAN[span]]">
          <WidgetCell :widget="widget" :widget-props="widgetProps" />
        </div>
      </div>
    </div>

    <div v-else class="ui-card">
      <EmptyState v-if="widgets.length" :icon="LayoutGrid" :title="t('overview.customize.allHidden')" :description="t('overview.customize.allHiddenBody')">
        <UiButton variant="secondary" :icon="SlidersHorizontal" @click="editing = true">{{ t("overview.customize.open") }}</UiButton>
      </EmptyState>
      <EmptyState v-else :icon="LayoutGrid" :title="t('overview.empty.title')" :description="t('overview.empty.body')" />
    </div>
  </div>
</template>
