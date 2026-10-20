<script setup lang="ts">
/** Kitchen: page header, sections, breadcrumbs, grids, the widget grid, split view, wizard, sticky bar. */
import { Bell, Inbox, LayoutGrid, Plus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import Breadcrumbs from "@/components/Breadcrumbs.vue";
import EmptyState from "@/components/EmptyState.vue";
import KpiCard from "@/components/KpiCard.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import ResponsiveGrid from "@/components/ResponsiveGrid.vue";
import SplitView from "@/components/SplitView.vue";
import StatusPill from "@/components/StatusPill.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import UiButton from "@/components/UiButton.vue";
import WidgetGrid from "@/components/WidgetGrid.vue";
import type { WidgetLayout } from "@/components/widgetLayout";
import WizardSteps from "@/components/WizardSteps.vue";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { PEOPLE } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});

const tab = ref("overview");
const tabs = computed(() => [
  { id: "overview", label: k("tab.overview") },
  { id: "tasks", label: k("tab.tasks"), count: 7 },
  { id: "attendance", label: k("tab.attendance") },
  { id: "pay", label: k("tab.pay") },
  { id: "history", label: k("tab.history") },
]);

const customizing = ref(false);
const layout = ref<WidgetLayout>({ order: [], hidden: ["w4"] });
const widgets = computed(() => [
  { id: "w1", span: 2 as const, label: k("kpi.net"), value: "48120000.00" },
  { id: "w2", span: 1 as const, label: k("kpi.receipts"), value: 1204 },
  { id: "w3", span: 1 as const, label: k("kpi.late"), value: 3 },
  { id: "w4", span: 4 as const, label: k("kpi.cash"), value: "86420000.00" },
]);

const selected = ref<number | null>(14);
const step = ref("when");
const steps = computed(() => [
  { id: "when", label: k("wizard.when"), description: k("wizard.whenHint") },
  { id: "steps", label: k("wizard.steps"), description: k("wizard.stepsHint") },
  { id: "confirm", label: k("wizard.confirm") },
]);
const dirty = ref(true);
</script>

<template>
  <KitchenSection id="layout" :title="k('section.layout')" :description="k('section.layoutHint')">
    <KitchenSpecimen name="PageHeader.vue · Breadcrumbs.vue" wide>
      <Breadcrumbs :items="[{ label: t('shell.group.people'), to: '/' }, { label: k('team'), to: '/' }, { label: 'Madina Saidova', to: '/' }, { label: k('tab.history') }]" class="mb-4" />
      <PageHeader v-model:tab="tab" title="Madina Saidova" :description="k('personSub')" :tabs="tabs">
        <template #actions>
          <UiButton :icon="Bell">{{ k("nudge") }}</UiButton>
          <UiButton variant="primary" :icon="Plus">{{ k("newTask") }}</UiButton>
        </template>
        <template #meta>
          <StatusPill tone="success" live :label="k('inSince', { time: '08:57' })" size="sm" />
          <StatusPill tone="neutral" :label="k('tenure')" size="sm" />
        </template>
      </PageHeader>
    </KitchenSpecimen>
    <KitchenSpecimen name="PageSection.vue · ResponsiveGrid.vue">
      <PageSection id="kitchen-branches" :title="k('branches')" :count="3" :description="k('branchesHint')" collapsible>
        <template #actions><UiButton size="sm" variant="ghost">{{ t("common.viewAll") }}</UiButton></template>
        <ResponsiveGrid min="150px">
          <div v-for="name in ['Chilonzor', 'Yunusobod', 'Sergeli']" :key="name" class="ui-card p-3">
            <p class="text-sm font-semibold text-fg">{{ name }}</p>
            <StatusPill class="mt-2" size="sm" :tone="name === 'Yunusobod' ? 'danger' : 'success'" :label="name === 'Yunusobod' ? k('notOpened') : k('opened', { time: '08:57' })" />
          </div>
        </ResponsiveGrid>
      </PageSection>
      <PageSection class="mt-6" :title="k('payments')" variant="card" flush>
        <EmptyState size="sm" tone="neutral" :icon="Inbox" :title="k('noPayments')" />
      </PageSection>
    </KitchenSpecimen>
    <KitchenSpecimen name="WizardSteps.vue · StickyActionBar.vue">
      <WizardSteps v-model="step" :steps="steps" :completed="step === 'confirm' ? ['when', 'steps'] : step === 'steps' ? ['when'] : []" />
      <div class="mt-4 flex gap-2">
        <UiButton size="sm" :disabled="step === 'when'" @click="step = step === 'confirm' ? 'steps' : 'when'">{{ t("common.back") }}</UiButton>
        <UiButton size="sm" variant="primary" :disabled="step === 'confirm'" @click="step = step === 'when' ? 'steps' : 'confirm'">{{ t("common.continue") }}</UiButton>
        <UiButton size="sm" variant="ghost" @click="dirty = !dirty">{{ k("toggleBar") }}</UiButton>
      </div>
      <div class="relative mt-2 h-20">
        <StickyActionBar :show="dirty" :message="t('common.unsaved')" tone="warning" class="!sticky !bottom-0">
          <UiButton size="sm" variant="ghost" @click="dirty = false">{{ t("common.discard") }}</UiButton>
          <UiButton size="sm" variant="primary" @click="dirty = false">{{ t("common.save") }}</UiButton>
        </StickyActionBar>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="WidgetGrid.vue" :note="k('widgetsNote')" wide canvas>
      <div class="mb-3 flex items-center gap-2">
        <UiButton size="sm" :variant="customizing ? 'primary' : 'secondary'" :icon="LayoutGrid" @click="customizing = !customizing">
          {{ customizing ? t("common.done") : k("customize") }}
        </UiButton>
        <UiButton v-if="customizing" size="sm" variant="ghost" @click="layout = { order: [], hidden: [] }">{{ t("common.reset") }}</UiButton>
      </div>
      <WidgetGrid v-model:layout="layout" :widgets="widgets" :editing="customizing">
        <template #widget="{ widget }">
          <KpiCard :label="widget.label" :value="widget.value" :format="typeof widget.value === 'string' ? 'money' : 'number'" compact />
        </template>
      </WidgetGrid>
    </KitchenSpecimen>
    <KitchenSpecimen name="SplitView.vue" wide flush>
      <SplitView id="kitchen-split" :detail-open="selected !== null" height="300px" @back="selected = null">
        <template #list>
          <ul class="flex-1 overflow-y-auto p-1.5">
            <li v-for="person in PEOPLE.slice(0, 7)" :key="person.id">
              <button
                type="button"
                :class="['flex w-full flex-col rounded-[8px] px-3 py-2 text-left', selected === person.id ? 'bg-accent-soft' : 'hover:bg-highlight']"
                @click="selected = person.id"
              >
                <span class="text-sm font-semibold text-fg">{{ person.name }}</span>
                <span class="text-xs text-muted">{{ person.subtitle }}</span>
              </button>
            </li>
          </ul>
        </template>
        <template #detail>
          <div class="p-5">
            <p class="text-md font-semibold text-fg">{{ PEOPLE.find((p) => p.id === selected)?.name }}</p>
            <p class="mt-1 text-sm text-muted">{{ k("splitHint") }}</p>
          </div>
        </template>
        <template #empty>
          <EmptyState size="sm" tone="neutral" :title="k('pickSomeone')" />
        </template>
      </SplitView>
    </KitchenSpecimen>
  </KitchenSection>
</template>
