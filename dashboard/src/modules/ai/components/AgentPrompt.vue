<script setup lang="ts">
/**
 * An agent's prompt on its page: first the owner's own instructions to it (what they can change),
 * then what it asks Claude, word for word as Claude reads it (English), one block per job, with
 * the instructions shown where they are added: after each prompt, every time it asks Claude. Its
 * own rules, what it may share and its answer's format still come first (apps.ai.instructions).
 * An agent that works by fixed rules has no prompt to see or change. Editing needs ai.configure;
 * everyone else reads.
 */
import { Check, ChevronDown, ScrollText, Sparkles, Undo2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";

import { INSTRUCTIONS_MAX } from "../agentPage";
import { usePatchAgent } from "../api";
import { buddyVariant } from "../lib";
import type { AgentDetail } from "../types";

const props = defineProps<{ agent: AgentDetail; canConfigure: boolean }>();

const { t, te } = useI18n();
const patch = usePatchAgent();

const draft = ref<string | null>(props.agent.instructions);
const text = computed(() => draft.value ?? "");
const dirty = computed(() => text.value.trim() !== props.agent.instructions.trim());
const tooLong = computed(() => text.value.length > INSTRUCTIONS_MAX);
const saving = ref(false);
// Saved elsewhere (another tab, a refetch): the box follows unless something is being written.
watch(
  () => props.agent.instructions,
  (saved) => {
    if (!dirty.value || saving.value) draft.value = saved;
  },
);

/** The box's example, in the agent's own words ("fridge problems are always urgent"). */
const example = computed(() => {
  const key = `ai.agent.prompt.example.${buddyVariant(props.agent.key)}`;
  return te(key) ? t(key) : t("ai.agent.prompt.example.claude");
});

// One prompt open at a time; the first to start with.
const open = ref(0);

async function save(): Promise<void> {
  if (!dirty.value || tooLong.value) return;
  const value = text.value.trim();
  saving.value = true;
  try {
    await patch.mutateAsync({ key: props.agent.key, patch: { instructions: value } });
    draft.value = value;
    toast.success(value ? t("ai.agent.prompt.saved") : t("ai.agent.prompt.cleared"));
  } catch {
    // The reason is a toast from the HTTP layer; what was written stays in the box.
  } finally {
    saving.value = false;
  }
}

function reset(): void {
  draft.value = props.agent.instructions;
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="agent-prompt">
    <EmptyState v-if="!agent.prompts.length" :icon="ScrollText" :title="t('ai.agent.prompt.rulesTitle')" :description="t('ai.agent.prompt.rulesBody')" />
    <template v-else>
      <section class="ui-card flex flex-col gap-3 p-4 md:p-5">
        <div>
          <h3 class="text-md font-semibold text-fg">{{ t("ai.agent.prompt.yoursTitle") }}</h3>
          <p class="mt-1 text-sm text-muted">{{ t("ai.agent.prompt.yoursBody") }}</p>
        </div>
        <template v-if="canConfigure">
          <TextArea v-model="draft" :rows="4" autosize :max-rows="12" :maxlength="INSTRUCTIONS_MAX" :invalid="tooLong" :placeholder="example" data-testid="agent-instructions" />
          <div class="flex flex-wrap items-center gap-2">
            <span class="mr-auto text-xs" :class="tooLong ? 'text-danger' : 'text-subtle'">{{ t("ai.agent.prompt.count", { n: text.length, max: INSTRUCTIONS_MAX }) }}</span>
            <UiButton v-if="dirty" variant="ghost" size="sm" :icon="Undo2" @click="reset">{{ t("common.cancel") }}</UiButton>
            <UiButton variant="primary" size="sm" :icon="Check" :loading="saving" :disabled="!dirty || tooLong" data-testid="agent-instructions-save" @click="save">{{ t("common.save") }}</UiButton>
          </div>
        </template>
        <p v-else-if="agent.instructions" class="whitespace-pre-wrap rounded-[10px] bg-surface-2/70 px-3 py-2.5 text-sm text-fg dark:bg-surface-2">{{ agent.instructions }}</p>
        <p v-else class="text-sm text-subtle">{{ t("ai.agent.prompt.none") }}</p>
      </section>

      <section class="ui-card flex flex-col p-2 md:p-3">
        <div class="px-2 pb-2 pt-1 md:px-3">
          <h3 class="text-md font-semibold text-fg">{{ t("ai.agent.prompt.claudeTitle") }}</h3>
          <p class="mt-1 text-sm text-muted">{{ t("ai.agent.prompt.claudeBody") }}</p>
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
            <div v-if="agent.instructions" class="border-t border-line px-3 py-2.5" data-testid="agent-prompt-yours">
              <p class="text-xs font-semibold text-accent-fg">{{ t("ai.agent.prompt.yours") }}</p>
              <p class="mt-1 whitespace-pre-wrap font-mono text-xs leading-relaxed text-fg">{{ agent.instructions }}</p>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
