<script setup lang="ts">
/**
 * What the AI looked at for an answer, as a checklist ("Vazifalarni ko‘rib chiqyapman…"): ticked
 * as each step finishes, with a spinner on the one under way. A finished answer folds it into
 * one line ("Checked 3 things") that opens.
 */
import { Check, ChevronDown, LoaderCircle, X } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import type { TurnStep } from "../types";

const props = withDefaults(defineProps<{ steps: TurnStep[]; live?: boolean }>(), { live: false });
const { t } = useI18n();
const open = ref(false);
const shown = computed(() => props.live || open.value);
</script>

<template>
  <div v-if="steps.length || live" class="flex flex-col gap-1" data-testid="ai-steps">
    <button
      v-if="!live"
      type="button"
      class="inline-flex h-8 w-fit items-center gap-1.5 rounded-full px-2 text-xs font-medium text-muted hover:bg-highlight hover:text-fg"
      :aria-expanded="open"
      @click="open = !open"
    >
      <Check :size="13" class="text-success" aria-hidden="true" />{{ t("ai.chat.checked", { n: steps.length }, steps.length) }}
      <ChevronDown :size="13" :class="['transition-transform', open && 'rotate-180']" aria-hidden="true" />
    </button>
    <TransitionGroup v-if="shown" tag="ol" name="list" class="relative flex flex-col gap-1 pl-1" :aria-label="t('ai.chat.steps')">
      <li v-for="(step, index) in steps" :key="`${index}:${step.label}`" class="flex items-center gap-2 text-sm">
        <span
          :class="[
            'grid size-[18px] shrink-0 place-items-center rounded-full',
            step.status === 'error' ? 'bg-danger-soft text-danger' : step.status === 'done' ? 'bg-success-soft text-success' : 'bg-accent-soft text-accent-fg',
          ]"
          aria-hidden="true"
        >
          <X v-if="step.status === 'error'" :size="11" />
          <Check v-else-if="step.status === 'done'" :size="11" />
          <LoaderCircle v-else :size="11" class="animate-spin" />
        </span>
        <span :class="step.status === 'done' ? 'text-muted' : 'text-fg'">{{ step.label }}</span>
        <span v-if="step.ms && !live" class="num text-xs text-subtle">{{ (step.ms / 1000).toFixed(1) }} s</span>
      </li>
      <li v-if="live" key="thinking" class="flex items-center gap-2 text-sm">
        <span class="grid size-[18px] shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><LoaderCircle :size="11" class="animate-spin" /></span>
        <span class="ai-typing text-fg">{{ steps.length ? t("ai.chat.stillThinking") : t("ai.chat.thinking") }}</span>
      </li>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.ai-typing {
  background: linear-gradient(90deg, var(--c-text) 0%, var(--c-text) 40%, var(--c-subtle) 50%, var(--c-text) 60%, var(--c-text) 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: shimmer 1.6s linear infinite;
}
</style>
