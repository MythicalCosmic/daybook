<script setup lang="ts">
/**
 * The top of every Routines page: the title, one line on what a routine is (it gives each person a
 * task every day it's due, unlike a one-off task), and the sections as tabs: Today, History,
 * To confirm (with its count) and All routines, each shown to whoever may open it.
 */
import { CalendarCheck, ClipboardCheck, History, Repeat } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import PageHeader, { type PageTab } from "@/components/PageHeader.vue";
import { usePulseCount } from "@/core/pulse";
import { usePermission } from "@/lib/usePermission";

withDefaults(defineProps<{ description?: string }>(), { description: undefined });

const { t } = useI18n();
const route = useRoute();
const { can } = usePermission();
const toConfirm = usePulseCount("tasks.routine_review");

const tabs = computed<PageTab[]>(() => {
  const list: PageTab[] = [];
  if (can("tasks.view_all")) {
    list.push({ id: "today", label: t("routines.nav.today"), icon: CalendarCheck, to: { name: "routines.today" } });
    list.push({ id: "history", label: t("routines.nav.history"), icon: History, to: { name: "routines.history" } });
  }
  if (can("tasks.confirm")) {
    list.push({ id: "confirm", label: t("routines.nav.confirm"), icon: ClipboardCheck, to: { name: "routines.confirm" }, count: toConfirm.value || undefined });
  }
  if (can("tasks.templates")) {
    // Onboarding templates sit beside the routines, under the same tab.
    const onboarding = route.name === "routines.onboarding";
    list.push({ id: "all", label: t("routines.nav.all"), icon: Repeat, to: { name: onboarding ? "routines.onboarding" : "routines.list" } });
  }
  return list.length > 1 ? list : [];
});
</script>

<template>
  <PageHeader :title="t('routines.title')" :description="description ?? t('routines.help')" :tabs="tabs">
    <template v-if="$slots.actions" #actions><slot name="actions" /></template>
  </PageHeader>
</template>
