<script setup lang="ts">
/**
 * Reminders (plan §6.2): how hard the bot chases late work. Policies with their timeline and
 * texts, the log of every reminder sent, and the people who blocked the bot. Tabs in the URL.
 */
import { BellRing, BellOff, ScrollText } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import PageHeader from "@/components/PageHeader.vue";
import { usePermission } from "@/lib/usePermission";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useBlocked } from "../api";
import BlockedList from "../components/BlockedList.vue";
import PolicyList from "../components/PolicyList.vue";
import ReminderLog from "../components/ReminderLog.vue";

const { t } = useI18n();
const { can } = usePermission();
const tab = useRouteState("tab", rs.enum(["policies", "log", "blocked"] as const, "policies"));
const blocked = useBlocked(computed(() => can("members.view")));

const tabs = computed(() => [
  { id: "policies", label: t("reminders.tabs.policies"), icon: BellRing },
  { id: "log", label: t("reminders.tabs.log"), icon: ScrollText },
  ...(can("members.view") ? [{ id: "blocked", label: t("reminders.tabs.blocked"), icon: BellOff, count: blocked.data.value?.length || undefined }] : []),
]);
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <PageHeader v-model:tab="tab" :title="t('reminders.title')" :description="t('reminders.description')" :tabs="tabs" />
    <PolicyList v-if="tab === 'policies'" />
    <ReminderLog v-else-if="tab === 'log'" />
    <BlockedList v-else />
  </div>
</template>
