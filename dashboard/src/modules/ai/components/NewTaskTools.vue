<script setup lang="ts">
/**
 * In the New task dialog (`tasks.create.tools`): "Dictate" and "Smart add", for several tasks at
 * once in a few words. Each closes New task and opens the dictate dialog (Smart add takes along
 * what was typed as the title). Shown only while the company's AI can do it.
 */
import { Mic, Sparkles } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { useAiStatus } from "../api";
import { openDictation, type DictationMode } from "../dictation";
import { aiVisibility } from "../lib";

const props = defineProps<{ context?: { companyId?: number | null; title?: string; close?: () => void } }>();

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const status = useAiStatus();
const show = computed(() => aiVisibility(status.data.value));

function start(mode: DictationMode): void {
  const text = mode === "text" ? (props.context?.title ?? "") : "";
  props.context?.close?.();
  openDictation(mode, { text });
}
</script>

<template>
  <div
    v-if="show.dictate || show.smartAdd"
    class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[10px] border border-dashed border-[color-mix(in_srgb,var(--c-primary)_35%,var(--c-border))] bg-accent-soft/50 px-3 py-2"
    data-testid="ai-new-task-tools"
  >
    <span class="flex min-w-0 flex-1 basis-[200px] items-center gap-2 text-sm text-fg">
      <Sparkles :size="15" class="shrink-0 text-accent-fg" aria-hidden="true" />{{ t("ai.newTask.hint") }}
    </span>
    <span class="flex shrink-0 gap-1.5 max-sm:w-full">
      <UiButton v-if="show.dictate" variant="soft" :size="isPhone ? 'lg' : 'sm'" :icon="Mic" class="max-sm:flex-1" data-testid="ai-new-task-dictate" @click="start('voice')">{{ t("ai.dictate.button") }}</UiButton>
      <UiButton v-if="show.smartAdd" variant="soft" :size="isPhone ? 'lg' : 'sm'" :icon="Sparkles" class="max-sm:flex-1" data-testid="ai-new-task-smart" @click="start('text')">{{ t("ai.dictate.smartAdd") }}</UiButton>
    </span>
  </div>
</template>
