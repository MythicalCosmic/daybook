<script setup lang="ts">
/**
 * The prompt of an agent an owner made: its job first, in its owner's words (Edit opens the form,
 * for who may set up AI), then what it asks Claude, word for word as Claude reads it (English):
 * the rules every such agent follows with the job after them, and the translation it asks for when
 * someone reads another language. Read-only here; the job changes in the form.
 */
import { ChevronDown, Pencil, Sparkles } from "@lucide/vue";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

import type { AgentDetail, CustomAgentInfo } from "../types";

defineProps<{ agent: AgentDetail & { custom: CustomAgentInfo }; canConfigure: boolean }>();
const emit = defineEmits<{ edit: [] }>();

const { t } = useI18n();
// One prompt open at a time; none to start with (the job above says what it does).
const open = ref(-1);
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="custom-prompt">
    <section class="ui-card flex flex-col gap-3 p-4 md:p-5">
      <div class="flex flex-wrap items-start gap-2">
        <div class="min-w-0 flex-1">
          <h3 class="text-md font-semibold text-fg">{{ t("ai.custom.jobTitle") }}</h3>
          <p class="mt-1 text-sm text-muted">{{ t("ai.custom.jobBody") }}</p>
        </div>
        <UiButton v-if="canConfigure" size="sm" :icon="Pencil" data-testid="custom-prompt-edit" @click="emit('edit')">{{ t("ai.custom.edit") }}</UiButton>
      </div>
      <p class="whitespace-pre-wrap rounded-[10px] bg-surface-2/70 px-3 py-2.5 text-sm leading-relaxed text-fg dark:bg-surface-2" data-testid="custom-job-text">{{ agent.custom.job }}</p>
    </section>

    <section class="ui-card flex flex-col p-2 md:p-3">
      <div class="px-2 pb-2 pt-1 md:px-3">
        <h3 class="text-md font-semibold text-fg">{{ t("ai.agent.prompt.claudeTitle") }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t("ai.custom.claudeBody") }}</p>
      </div>
      <div v-for="(prompt, index) in agent.prompts" :key="prompt.label" class="border-t border-line">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-[10px] px-2 py-2.5 text-left hover:bg-surface-2/60 md:px-3"
          :aria-expanded="open === index"
          data-testid="agent-prompt-toggle"
          @click="open = open === index ? -1 : index"
        >
          <Sparkles :size="15" class="shrink-0 text-accent-fg" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-sm font-medium text-fg">{{ prompt.label }}</span>
          <ChevronDown :size="16" class="shrink-0 text-subtle transition-transform" :class="{ 'rotate-180': open === index }" aria-hidden="true" />
        </button>
        <div v-if="open === index" class="mx-2 mb-3 overflow-hidden rounded-[10px] bg-surface-2/70 md:mx-3 dark:bg-surface-2">
          <pre class="max-h-80 overflow-auto whitespace-pre-wrap px-3 py-2.5 font-mono text-xs leading-relaxed text-fg" lang="en" data-testid="agent-prompt-text">{{ prompt.text }}</pre>
        </div>
      </div>
    </section>
  </div>
</template>
