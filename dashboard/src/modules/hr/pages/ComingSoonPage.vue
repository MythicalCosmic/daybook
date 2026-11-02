<script setup lang="ts">
/**
 * A page that is designed but not built yet (policies, hiring): what it will do, in one line, and
 * where to go meanwhile.
 */
import { ArrowRight, BookOpenCheck, Sparkles, UserPlus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

const props = defineProps<{ page: "policies" | "hiring" }>();

const { t } = useI18n();
const company = useCompanyStore();
const meanwhile = computed(() => (props.page === "policies" ? { to: "knowledge", icon: BookOpenCheck } : { to: "settings/invite", icon: UserPlus }));
</script>

<template>
  <div>
    <PageHeader :title="t(`hr.nav.${page}`)" :description="t(`hr.soon.${page}.line`)">
      <template #meta><StatusPill tone="info" size="sm" :label="t('hr.soon.badge')" /></template>
    </PageHeader>
    <div class="ui-card">
      <EmptyState :icon="Sparkles" size="lg" tone="neutral" :title="t('hr.soon.title')" :description="t(`hr.soon.${page}.body`)">
        <UiButton :to="`/c/${company.currentId}/${meanwhile.to}`" :icon="meanwhile.icon" :icon-right="ArrowRight">{{ t(`hr.soon.${page}.meanwhile`) }}</UiButton>
      </EmptyState>
    </div>
  </div>
</template>
