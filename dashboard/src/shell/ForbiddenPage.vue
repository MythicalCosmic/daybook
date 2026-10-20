<script setup lang="ts">
/** Shown in place of a page the person's role or the company's switches don't allow (the URL stays). */
import { Lock } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

const { t } = useI18n();
const company = useCompanyStore();
const name = computed(() => company.current?.name ?? "");
</script>

<template>
  <div class="grid min-h-[60vh] place-items-center">
    <EmptyState size="lg" tone="neutral" :icon="Lock" :title="t('shell.forbidden.title')" :description="t('shell.forbidden.body', { company: name })">
      <UiButton variant="primary" :to="company.currentId ? `/c/${company.currentId}` : '/'">{{ t("shell.forbidden.home") }}</UiButton>
    </EmptyState>
  </div>
</template>
