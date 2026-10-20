<script setup lang="ts">
/**
 * The header every attendance page shares: title, one line of context and the section tabs
 * (Today · Timesheet · Roster · Schedules · Swaps · Corrections) as links, with the waiting counts
 * from the pulse. Tabs the person may not open are left out.
 */
import { CalendarClock, CalendarDays, CalendarRange, ClipboardCheck, Clock3, Repeat2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import PageHeader, { type PageTab } from "@/components/PageHeader.vue";
import { pulse, pulseCount } from "@/core/pulse";
import { useCompanyStore } from "@/stores/company";

defineProps<{ title: string; description?: string }>();

const { t } = useI18n();
const company = useCompanyStore();
const base = computed(() => `/c/${company.currentId}/attendance`);

const tabs = computed<PageTab[]>(() => {
  const manage = company.can("attendance.manage");
  const list: PageTab[] = [
    { id: "today", label: t("attendance.nav.today"), to: base.value, icon: Clock3 },
    { id: "timesheet", label: t("attendance.nav.timesheet"), to: `${base.value}/timesheet`, icon: CalendarDays },
    { id: "roster", label: t("attendance.nav.roster"), to: `${base.value}/roster`, icon: CalendarRange },
  ];
  if (manage) {
    list.push(
      { id: "schedules", label: t("attendance.nav.schedules"), to: `${base.value}/schedules`, icon: CalendarClock },
      { id: "swaps", label: t("attendance.nav.swaps"), to: `${base.value}/swaps`, icon: Repeat2, count: pulseCount(pulse.value, "attendance.swaps") || undefined },
      {
        id: "corrections",
        label: t("attendance.nav.corrections"),
        to: `${base.value}/corrections`,
        icon: ClipboardCheck,
        count: pulseCount(pulse.value, "attendance.corrections") || undefined,
      },
    );
  }
  return list;
});
</script>

<template>
  <PageHeader :title="title" :description="description" :tabs="tabs">
    <template v-if="$slots.actions" #actions><slot name="actions" /></template>
    <template v-if="$slots.meta" #meta><slot name="meta" /></template>
  </PageHeader>
</template>
