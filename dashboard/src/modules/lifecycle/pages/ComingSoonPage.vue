<script setup lang="ts">
/**
 * A lifecycle page that is designed but not built yet (org chart, equipment): what it
 * will do, in one line, and where to go meanwhile.
 */
import { ArrowRight, Network, Sparkles } from "@lucide/vue";
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

type Page = "org" | "equipment";
const props = defineProps<{ page: Page }>();

const { t } = useI18n();
const company = useCompanyStore();

const MEANWHILE: Partial<Record<Page, { to: string; icon: Component }>> = {
  org: { to: "people/departments", icon: Network },
};
const meanwhile = computed(() => MEANWHILE[props.page] ?? null);
</script>

<template>
  <div>
    <PageHeader :title="t(`lifecycle.nav.${page}`)" :description="t(`lifecycle.soon.${page}.line`)">
      <template #meta><StatusPill tone="info" size="sm" :label="t('lifecycle.soon.badge')" /></template>
    </PageHeader>
    <div class="ui-card">
      <EmptyState :icon="Sparkles" size="lg" tone="neutral" :title="t('lifecycle.soon.title')" :description="t(`lifecycle.soon.${page}.body`)">
        <UiButton v-if="meanwhile" :to="`/c/${company.currentId}/${meanwhile.to}`" :icon="meanwhile.icon" :icon-right="ArrowRight">{{ t(`lifecycle.soon.${page}.meanwhile`) }}</UiButton>
      </EmptyState>
    </div>
  </div>
</template>
