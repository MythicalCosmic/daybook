<script setup lang="ts">
/**
 * The top of every AI page: the page's title and one line on it, the engines' state (Claude,
 * speech) and the sections as tabs: Agents, Activity, Voice notes, Ask AI.
 */
import { Activity, AudioLines, Bot, MessagesSquare } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import PageHeader, { type PageTab } from "@/components/PageHeader.vue";
import { usePermission } from "@/lib/usePermission";

import type { AiStatus } from "../types";
import StatusPills from "./StatusPills.vue";

withDefaults(defineProps<{ title: string; description?: string; status?: AiStatus | null }>(), { description: undefined, status: null });

const { t } = useI18n();
const { can } = usePermission();

const tabs = computed<PageTab[]>(() => {
  const list: PageTab[] = [
    { id: "agents", label: t("ai.nav.agents"), icon: Bot, to: { name: "ai.agents" } },
    { id: "activity", label: t("ai.nav.activity"), icon: Activity, to: { name: "ai.activity" } },
    { id: "voice", label: t("ai.nav.voice"), icon: AudioLines, to: { name: "ai.voice" } },
  ];
  if (can("ai.use")) list.push({ id: "ask", label: t("ai.nav.ask"), icon: MessagesSquare, to: { name: "ai.ask" } });
  return list;
});
</script>

<template>
  <PageHeader :title="title" :description="description" :tabs="tabs">
    <template v-if="$slots.actions" #actions><slot name="actions" /></template>
    <template v-if="status" #meta><StatusPills :status="status" /></template>
  </PageHeader>
</template>
