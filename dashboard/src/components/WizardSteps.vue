<script setup lang="ts">
/**
 * Progress through a multi-step flow (offboarding wizard, import wizard, company setup): numbered
 * steps with a check when done and a mark when a step has a problem. Completed steps can be clicked
 * to go back. Phones show "Step 2 of 3 · Title" and a bar.
 *
 *   <WizardSteps v-model="step" :steps="[{ id: 'when', label: t('people.offboard.when') }, …]" :completed="['when']" />
 */
import { Check, X } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

export interface WizardStep {
  id: string;
  label: string;
  description?: string;
}

const current = defineModel<string>({ required: true });

const props = withDefaults(
  defineProps<{ steps: WizardStep[]; completed?: string[]; errors?: string[]; linear?: boolean; orientation?: "horizontal" | "vertical" }>(),
  { completed: () => [], errors: () => [], linear: true, orientation: "horizontal" },
);

const { t } = useI18n();
const currentIndex = computed(() => Math.max(0, props.steps.findIndex((step) => step.id === current.value)));

function state(step: WizardStep, index: number): "current" | "complete" | "error" | "upcoming" {
  if (props.errors.includes(step.id)) return "error";
  if (step.id === current.value) return "current";
  if (props.completed.includes(step.id) || index < currentIndex.value) return "complete";
  return "upcoming";
}

function canVisit(step: WizardStep, index: number): boolean {
  if (step.id === current.value) return false;
  return !props.linear || props.completed.includes(step.id) || index < currentIndex.value;
}
</script>

<template>
  <nav :aria-label="t('common.wizard.label')">
    <!-- Phones: one line and a bar -->
    <div class="sm:hidden">
      <p class="text-xs font-medium text-muted">{{ t("common.wizard.step", { n: currentIndex + 1, total: steps.length }) }}</p>
      <p class="mt-0.5 text-base font-semibold text-fg">{{ steps[currentIndex]?.label }}</p>
      <div class="mt-2 flex gap-1">
        <span
          v-for="(step, index) in steps"
          :key="step.id"
          :class="['h-1 flex-1 rounded-full transition-colors', index <= currentIndex ? 'bg-primary' : 'bg-[color-mix(in_srgb,var(--c-text)_10%,transparent)]']"
        />
      </div>
    </div>
    <ol :class="['hidden sm:flex', orientation === 'vertical' ? 'flex-col gap-1' : 'items-center gap-2']">
      <li
        v-for="(step, index) in steps"
        :key="step.id"
        :class="['flex min-w-0 items-center gap-2', orientation === 'horizontal' && index < steps.length - 1 && 'flex-1']"
      >
        <button
          type="button"
          :disabled="!canVisit(step, index)"
          :aria-current="state(step, index) === 'current' ? 'step' : undefined"
          :class="['group flex min-w-0 items-center gap-2.5 rounded-[8px] py-1 pr-2 text-left', canVisit(step, index) ? 'cursor-pointer hover:bg-highlight' : 'cursor-default']"
          @click="current = step.id"
        >
          <span
            :class="[
              'grid size-7 shrink-0 place-items-center rounded-full text-xs font-bold tabular-nums transition-colors',
              state(step, index) === 'current' && 'bg-primary text-on-primary shadow-[0_0_0_4px_var(--c-accent-soft)]',
              state(step, index) === 'complete' && 'bg-success-soft text-success',
              state(step, index) === 'error' && 'bg-danger-soft text-danger',
              state(step, index) === 'upcoming' && 'border border-line-strong text-muted',
            ]"
          >
            <Check v-if="state(step, index) === 'complete'" :size="14" :stroke-width="2.75" />
            <X v-else-if="state(step, index) === 'error'" :size="14" :stroke-width="2.75" />
            <template v-else>{{ index + 1 }}</template>
          </span>
          <span class="min-w-0">
            <span :class="['block truncate text-sm font-semibold', state(step, index) === 'upcoming' ? 'text-muted' : 'text-fg']">{{ step.label }}</span>
            <span v-if="step.description" class="block truncate text-xs text-muted">{{ step.description }}</span>
          </span>
        </button>
        <span
          v-if="orientation === 'horizontal' && index < steps.length - 1"
          :class="['h-px min-w-4 flex-1 transition-colors', index < currentIndex ? 'bg-success' : 'bg-line-strong']"
          aria-hidden="true"
        />
      </li>
    </ol>
  </nav>
</template>
