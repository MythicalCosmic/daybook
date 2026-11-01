<script setup lang="ts">
/**
 * The AI module's part of the shell (`shell.panel`): it hosts the dictate dialog, so "Dictate" in
 * the New task dialog can close that dialog and open this one, and it answers the shell's own
 * "Ask AI" (top bar, ⌘J, the palette's "Ask AI: …") by opening AI › Ask AI with the question.
 * The dialog's code loads the first time it opens.
 */
import { defineAsyncComponent, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { useCompanyStore } from "@/stores/company";
import { useUiStore } from "@/stores/ui";

import { dictation } from "../dictation";

defineProps<{ context?: Record<string, unknown> }>();

const DictateDialog = defineAsyncComponent(() => import("./DictateDialog.vue"));

const router = useRouter();
const ui = useUiStore();
const company = useCompanyStore();
const used = ref(false);

watch(
  () => dictation.open,
  (open) => {
    if (open) used.value = true;
  },
  { immediate: true },
);

watch(
  () => ui.aiPanelOpen,
  (open) => {
    if (!open || !company.currentId) return;
    const question = ui.aiPrompt.trim();
    ui.aiPanelOpen = false;
    ui.aiPrompt = "";
    void router.push({ path: `/c/${company.currentId}/ai/ask`, query: question ? { q: question } : {} });
  },
  { immediate: true },
);
</script>

<template>
  <DictateDialog v-if="used" :key="dictation.session" v-model:open="dictation.open" :mode="dictation.mode" :initial-text="dictation.text" />
</template>
