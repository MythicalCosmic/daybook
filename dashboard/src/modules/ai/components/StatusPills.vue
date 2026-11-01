<script setup lang="ts">
/** "Claude: connected" and "Speech: ready", the two engines behind every AI feature. */
import { AudioLines, Sparkles } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import StatusPill from "@/components/StatusPill.vue";
import UiTooltip from "@/components/UiTooltip.vue";

import { CLAUDE_TONE, SPEECH_TONE } from "../lib";
import type { AiStatus } from "../types";

defineProps<{ status: AiStatus }>();
const { t } = useI18n();
</script>

<template>
  <UiTooltip :content="t(`ai.claude.${status.claude}.hint`)" side="bottom">
    <span class="inline-flex" tabindex="0" data-testid="ai-pill-claude">
      <StatusPill :tone="CLAUDE_TONE[status.claude]" :icon="Sparkles" :label="t(`ai.claude.${status.claude}`)" />
    </span>
  </UiTooltip>
  <UiTooltip :content="t(`ai.speech.${status.speech}.hint`)" side="bottom">
    <span class="inline-flex" tabindex="0" data-testid="ai-pill-speech">
      <StatusPill :tone="SPEECH_TONE[status.speech]" :icon="AudioLines" :label="t(`ai.speech.${status.speech}`)" />
    </span>
  </UiTooltip>
</template>
