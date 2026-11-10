<script setup lang="ts">
/**
 * A rating from 1 to 5 as five pills, the chosen one's word under them ("4 · Very good"). Keyboard:
 * the arrow keys move the choice (a radio group). `mark` shows where someone else put it (the
 * person's own rating beside the reviewer's) as a small dot over that pill.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { RATINGS, ratingTone } from "../../reviews/lib";

const model = defineModel<number | null>({ default: null });
const props = withDefaults(defineProps<{ readonly?: boolean; size?: "sm" | "md"; mark?: number | null; label?: string; showWord?: boolean }>(), {
  readonly: false,
  size: "md",
  mark: null,
  label: undefined,
  showWord: true,
});

const { t } = useI18n();
const TONE_FILL = { danger: "bg-danger text-white", warning: "bg-warning text-white", success: "bg-success text-white", neutral: "bg-surface-3 text-fg" } as const;
const fill = computed(() => TONE_FILL[(ratingTone(model.value) as keyof typeof TONE_FILL) ?? "neutral"] ?? TONE_FILL.neutral);

function pick(value: number): void {
  if (props.readonly) return;
  model.value = model.value === value ? null : value;
}
function onKey(event: KeyboardEvent): void {
  if (props.readonly) return;
  const step = event.key === "ArrowRight" || event.key === "ArrowUp" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowDown" ? -1 : 0;
  if (!step) return;
  event.preventDefault();
  const next = Math.min(5, Math.max(1, (model.value ?? (step > 0 ? 0 : 6)) + step));
  model.value = next;
  const group = event.currentTarget as HTMLElement;
  group.querySelector<HTMLButtonElement>(`[data-value="${next}"]`)?.focus();
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <div role="radiogroup" :aria-label="label ?? t('lifecycle.reviews.rating.label')" :aria-readonly="readonly || undefined" class="flex items-center gap-1.5" data-rating @keydown="onKey">
      <button
        v-for="value in RATINGS"
        :key="value"
        type="button"
        role="radio"
        :data-value="value"
        :aria-checked="model === value"
        :aria-label="`${value} · ${t(`lifecycle.reviews.rating.word${value}`)}`"
        :tabindex="readonly ? -1 : model === value || (model === null && value === 1) ? 0 : -1"
        :disabled="readonly && model !== value"
        :class="[
          'relative grid place-items-center rounded-full font-semibold tabular-nums transition-all duration-150',
          size === 'sm' ? 'size-7 text-xs' : 'size-9 text-sm',
          model === value ? `${fill} shadow-sm` : 'border border-line bg-surface text-muted',
          !readonly && model !== value ? 'hover:border-line-strong hover:text-fg' : '',
          readonly ? 'cursor-default disabled:opacity-100' : 'cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--c-primary)]',
          readonly && model !== value ? 'opacity-50' : '',
        ]"
        @click="pick(value)"
      >
        {{ value }}
        <span v-if="mark === value" class="absolute -top-1 right-0 size-2.5 rounded-full border-2 border-surface bg-info" aria-hidden="true" />
      </button>
    </div>
    <p v-if="showWord" class="min-h-4 text-xs text-muted" aria-live="polite">{{ model ? t(`lifecycle.reviews.rating.word${model}`) : readonly ? "—" : t("lifecycle.reviews.rating.pick") }}</p>
  </div>
</template>
