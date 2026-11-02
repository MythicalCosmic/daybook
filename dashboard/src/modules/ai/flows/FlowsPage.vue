<script setup lang="ts">
/**
 * AI › Flows: the company's automations, "when this happens, AI reads it and acts" (briefs/v3-contract.md §4).
 * Placeholder of the v0.3 scaffold: the Flows UI work replaces it.
 */
import { Workflow } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";

import { useAiStatus } from "../api";
import AiHeader from "../components/AiHeader.vue";

const { t } = useI18n();
const status = useAiStatus();
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <AiHeader :title="t('ai.flows.title')" :description="t('ai.flows.description')" :status="status.data.value" />
    <EmptyState :icon="Workflow" :title="t('ai.flows.title')" :description="t('ai.flows.description')" />
  </div>
</template>
