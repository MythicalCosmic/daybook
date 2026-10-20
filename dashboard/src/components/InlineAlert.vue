<script setup lang="ts">
/**
 * A message inside a page or form: "This period is locked", "3 people have no pay setup", "The AI
 * read a different total". Tones info, success, warning, danger, neutral; optional title, actions
 * and a dismiss button.
 *
 *   <InlineAlert tone="warning" :title="t('payroll.warnings', { n: 4 })">…<template #actions>…</template></InlineAlert>
 */
import { CircleAlert, CircleCheck, Info, Lightbulb, TriangleAlert, X } from "@lucide/vue";
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(
  defineProps<{
    tone?: "info" | "success" | "warning" | "danger" | "neutral";
    title?: string;
    description?: string;
    icon?: Component | false;
    dismissible?: boolean;
    size?: "sm" | "md";
  }>(),
  { tone: "info", title: undefined, description: undefined, icon: undefined, dismissible: false, size: "md" },
);

const emit = defineEmits<{ dismiss: [] }>();
const { t } = useI18n();

const tones = {
  info: { box: "border-[color-mix(in_srgb,var(--c-info)_24%,transparent)] bg-info-soft/70", icon: "text-info", fallback: Info },
  success: { box: "border-[color-mix(in_srgb,var(--c-success)_24%,transparent)] bg-success-soft/70", icon: "text-success", fallback: CircleCheck },
  warning: { box: "border-[color-mix(in_srgb,var(--c-warning)_28%,transparent)] bg-warning-soft/70", icon: "text-warning", fallback: TriangleAlert },
  danger: { box: "border-[color-mix(in_srgb,var(--c-danger)_26%,transparent)] bg-danger-soft/70", icon: "text-danger", fallback: CircleAlert },
  neutral: { box: "border-line bg-surface-2/60 dark:bg-surface-3/40", icon: "text-muted", fallback: Lightbulb },
} as const;

const glyph = computed(() => (props.icon === false ? null : (props.icon ?? tones[props.tone].fallback)));
</script>

<template>
  <div
    :role="tone === 'danger' || tone === 'warning' ? 'alert' : 'status'"
    :class="['flex items-start gap-3 rounded-[10px] border', size === 'sm' ? 'px-3 py-2' : 'px-3.5 py-3', tones[tone].box]"
  >
    <component :is="glyph" v-if="glyph" :size="size === 'sm' ? 15 : 17" :class="['mt-px shrink-0', tones[tone].icon]" aria-hidden="true" />
    <div class="min-w-0 flex-1">
      <p v-if="title" :class="['font-semibold text-fg', size === 'sm' ? 'text-sm' : 'text-base']">{{ title }}</p>
      <div :class="['text-muted', size === 'sm' ? 'text-xs' : 'text-sm', title && 'mt-0.5']">
        <slot>{{ description }}</slot>
      </div>
      <div v-if="$slots.actions" class="mt-2.5 flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <button
      v-if="dismissible"
      type="button"
      class="pressable -mr-1 -mt-0.5 grid size-6 shrink-0 place-items-center rounded-[6px] text-muted hover:bg-[color-mix(in_srgb,var(--c-text)_7%,transparent)] hover:text-fg"
      :aria-label="t('common.dismiss')"
      @click="emit('dismiss')"
    >
      <X :size="14" />
    </button>
  </div>
</template>
