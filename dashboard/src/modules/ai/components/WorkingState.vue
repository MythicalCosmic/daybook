<script setup lang="ts">
/**
 * While the AI works: a breathing orb, the phase in words ("Eshitayapman…" while the voice turns
 * into words, "Tushunyapman…" while tasks are read from them), three steps that fill as it goes,
 * and shimmering placeholders where the tasks will appear.
 */
import { Check, Sparkles } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(defineProps<{ phase: "upload" | "listening" | "thinking"; voice?: boolean; compact?: boolean }>(), { voice: true, compact: false });
const { t } = useI18n();

const steps = computed(() => {
  const list: Array<{ id: string; label: string }> = [{ id: "upload", label: t("ai.working.step.sent") }];
  if (props.voice) list.push({ id: "listening", label: t("ai.working.step.heard") });
  list.push({ id: "thinking", label: t("ai.working.step.understood") });
  return list;
});
const order = ["upload", "listening", "thinking"];
const position = computed(() => order.indexOf(props.phase));
const title = computed(() => t(`ai.working.${props.phase}`));
const body = computed(() => t(`ai.working.${props.phase}Body`));
</script>

<template>
  <div :class="['flex flex-col items-center text-center', compact ? 'gap-3 py-4' : 'gap-5 py-6']" role="status" aria-live="polite" data-testid="ai-working">
    <span :class="['ai-orb relative grid place-items-center rounded-full text-on-primary', compact ? 'size-14' : 'size-20']" aria-hidden="true">
      <Sparkles :size="compact ? 24 : 32" class="relative z-[1]" />
    </span>
    <div class="flex flex-col gap-1">
      <p :class="['font-display text-fg', compact ? 'text-lg' : 'text-xl']">{{ title }}</p>
      <p class="max-w-[360px] text-base text-muted">{{ body }}</p>
    </div>
    <ol class="flex flex-wrap items-center justify-center gap-x-1.5 gap-y-2 text-sm" :aria-label="t('ai.working.steps')">
      <li v-for="(step, index) in steps" :key="step.id" class="flex items-center gap-1.5">
        <span
          :class="[
            'grid size-5 place-items-center rounded-full transition-colors duration-200',
            order.indexOf(step.id) < position ? 'bg-success text-on-primary' : order.indexOf(step.id) === position ? 'ai-step-live bg-accent-soft text-accent-fg' : 'bg-surface-2 text-subtle dark:bg-surface-3',
          ]"
          aria-hidden="true"
        >
          <Check v-if="order.indexOf(step.id) < position" :size="12" />
          <span v-else class="size-1.5 rounded-full bg-current" />
        </span>
        <span :class="order.indexOf(step.id) <= position ? 'font-medium text-fg' : 'text-subtle'">{{ step.label }}</span>
        <span v-if="index < steps.length - 1" class="mx-1 h-px w-5 bg-line-strong" aria-hidden="true" />
      </li>
    </ol>
    <div v-if="!compact" class="flex w-full max-w-[460px] flex-col gap-2.5" aria-hidden="true">
      <div v-for="n in 2" :key="n" class="ai-ghost flex items-center gap-3 rounded-card border border-line bg-surface p-3">
        <span class="ai-line size-6 shrink-0 rounded-full" />
        <span class="flex flex-1 flex-col gap-2">
          <span class="ai-line h-3 rounded-full" :style="{ width: n === 1 ? '72%' : '58%' }" />
          <span class="ai-line h-2.5 rounded-full" :style="{ width: n === 1 ? '44%' : '36%' }" />
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai-orb {
  background: radial-gradient(circle at 30% 30%, color-mix(in srgb, var(--c-primary) 70%, white) 0%, var(--c-primary) 60%, color-mix(in srgb, var(--c-primary) 70%, var(--c-success)) 100%);
  box-shadow: 0 8px 24px -8px color-mix(in srgb, var(--c-primary) 60%, transparent);
  animation: ai-breathe 2.4s var(--ease-standard) infinite;
}
.ai-orb::before {
  content: "";
  position: absolute;
  inset: -6px;
  border-radius: 999px;
  background: conic-gradient(from 0deg, transparent 0deg, color-mix(in srgb, var(--c-primary) 55%, transparent) 90deg, transparent 180deg, color-mix(in srgb, var(--c-success) 45%, transparent) 270deg, transparent 360deg);
  mask: radial-gradient(circle, transparent 58%, #000 60%);
  animation: spin 2.2s linear infinite;
}
@keyframes ai-breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.05);
  }
}
.ai-step-live {
  animation: breathe 1.6s var(--ease-standard) infinite;
}
.ai-line {
  background: linear-gradient(90deg, var(--c-skeleton) 0%, var(--c-skeleton) 35%, var(--c-skeleton-shine) 50%, var(--c-skeleton) 65%, var(--c-skeleton) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.4s linear infinite;
}
.ai-ghost:nth-child(2) .ai-line {
  animation-delay: 0.18s;
}
</style>
