<script setup lang="ts">
/**
 * The full Inbox (plan §6.1: `inbox`, W0): "Needs you" (decisions from every module) and
 * "Notifications" (what happened), as tabs kept in the URL (`?tab=notifications`). The shell's
 * drawer is the quick view of the same data; this page is where the person works through it.
 */
import { BellRing, Inbox, Settings } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import PageHeader from "@/components/PageHeader.vue";
import UiButton from "@/components/UiButton.vue";
import { counter, pulse } from "@/core/pulse";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useQueue } from "../api";
import NotificationsPanel from "../components/NotificationsPanel.vue";
import QueueList from "../components/QueueList.vue";
import type { InboxTab } from "../types";

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();

const tab = useRouteState<InboxTab>("tab", rs.enum(["needs", "notifications"] as const, "needs"));
const queue = useQueue(null);
const unread = computed(() => counter("inbox.unread")(pulse.value));

const tabs = computed(() => [
  { id: "needs", label: t("inbox.tabNeeds"), icon: Inbox, count: queue.data.value?.total ?? 0 },
  { id: "notifications", label: t("inbox.tabNotifications"), icon: BellRing, count: unread.value || undefined },
]);

/** Notification preferences are a Settings panel (package A); link to it only once it exists. */
const preferences = computed(() => {
  const path = `/c/${company.currentId}/settings/notifications`;
  return router.resolve(path).name !== "company-not-found" ? path : null;
});
</script>

<template>
  <div>
    <PageHeader v-model:tab="tab" :title="t('inbox.title')" :description="t('inbox.description')" :tabs="tabs">
      <template v-if="preferences" #actions>
        <UiButton :to="preferences" variant="ghost" :icon="Settings">{{ t("inbox.preferences") }}</UiButton>
      </template>
    </PageHeader>
    <QueueList v-if="tab === 'needs'" />
    <NotificationsPanel v-else />
  </div>
</template>
