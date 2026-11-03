<script setup lang="ts">
/**
 * An agent's settings on its page (they lived in its drawer before): why it can't run (when it
 * can't), what it sends to Claude, and its fields, each change saved at once. Read-only for people
 * who don't set up AI, and while AI is off.
 */
import { Info, KeyRound, Lock, Settings2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import { toast } from "@/components/useToast";

import { usePatchAgent } from "../api";
import type { Agent, AgentConfigValue } from "../types";
import AgentField from "./AgentField.vue";

const props = defineProps<{ agent: Agent; canConfigure: boolean; aiOn: boolean }>();

const { t } = useI18n();
const patch = usePatchAgent();
const saving = ref<string | null>(null);
const editable = computed(() => props.canConfigure && props.aiOn);

async function save(key: string, value: AgentConfigValue): Promise<void> {
  saving.value = key;
  try {
    await patch.mutateAsync({ key: props.agent.key, patch: { config: { [key]: value } } });
    toast.success(t("ai.agents.saved"));
  } catch {
    // Rolled back; the reason is a toast from the HTTP layer (or the field's own error).
  } finally {
    saving.value = null;
  }
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="agent-settings">
    <InlineAlert v-if="agent.unavailable_reason === 'needs_claude'" tone="warning" :icon="KeyRound" :title="t('ai.agents.needsClaudeTitle')" :description="t('ai.agents.needsClaudeBody')" />
    <InlineAlert v-else-if="agent.unavailable_reason === 'needs_speech'" tone="warning" :icon="Lock" :title="t('ai.agents.needsSpeechTitle')" :description="t('ai.agents.needsSpeechBody')" />
    <InlineAlert v-if="agent.key === 'photo_checker'" tone="info" :icon="Info" :description="t('ai.agents.photosNote')" />

    <div v-if="agent.fields.length" class="ui-card flex flex-col divide-y divide-line">
      <div v-for="field in agent.fields" :key="field.key" class="px-4 py-3.5 md:px-5">
        <AgentField :field="field" :value="agent.config[field.key]" :disabled="!editable" :saving="saving === field.key" @change="(value) => save(field.key, value)" />
      </div>
    </div>
    <EmptyState v-else class="ui-card" size="sm" :icon="Settings2" :title="t('ai.agent.settings.none')" :description="t('ai.agent.settings.noneBody')" />

    <p v-if="!canConfigure" class="flex items-start gap-2 px-1 text-sm text-muted" data-testid="agent-read-only">
      <Lock :size="14" class="mt-0.5 shrink-0" aria-hidden="true" />{{ t("ai.agents.onlyOwner") }}
    </p>
    <p v-else-if="!aiOn" class="px-1 text-sm text-muted">{{ t("ai.agent.settings.aiOff") }}</p>
  </div>
</template>
