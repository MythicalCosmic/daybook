<script setup lang="ts">
/**
 * Shown in place of a page the person can't open (the URL stays). Two reasons, said differently:
 * the company has the module switched off ("Sales is off in Demo Distribyutor", with Settings ›
 * Modules for whoever may turn it on), or the person's role doesn't include the page.
 */
import { Lock, PowerOff, Settings2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import UiButton from "@/components/UiButton.vue";
import { switchedOff } from "@/core/access";
import { useCompanyStore } from "@/stores/company";

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();
const name = computed(() => company.current?.name ?? "");
const home = computed(() => (company.currentId ? `/c/${company.currentId}` : "/"));

const off = computed(() => switchedOff(route.matched, company.current));
const offTitle = computed(() => {
  const module = off.value?.module;
  return module ? t("shell.forbidden.offTitle", { module: t(module.title), company: name.value }) : t("shell.forbidden.offTitleAny", { company: name.value });
});
const canSwitch = computed(() => company.can("company.settings"));
</script>

<template>
  <div class="grid min-h-[60vh] place-items-center">
    <EmptyState
      v-if="off"
      size="lg"
      tone="neutral"
      :icon="PowerOff"
      :title="offTitle"
      :description="canSwitch ? t('shell.forbidden.offBodyOwner') : t('shell.forbidden.offBody')"
      data-switched-off
    >
      <UiButton v-if="canSwitch" variant="primary" :icon="Settings2" :to="`${home}/settings/features`">{{ t("shell.forbidden.openModules") }}</UiButton>
      <UiButton :variant="canSwitch ? 'secondary' : 'primary'" :to="home">{{ t("shell.forbidden.home") }}</UiButton>
    </EmptyState>
    <EmptyState v-else size="lg" tone="neutral" :icon="Lock" :title="t('shell.forbidden.title')" :description="t('shell.forbidden.body', { company: name })">
      <UiButton variant="primary" :to="home">{{ t("shell.forbidden.home") }}</UiButton>
    </EmptyState>
  </div>
</template>
