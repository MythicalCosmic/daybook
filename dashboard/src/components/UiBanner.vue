<script setup lang="ts">
/**
 * A page-wide notice across the top of a page or panel: "AI is off: an owner must accept the
 * terms", "October is locked", "You're viewing Demo Distribyutor". Bolder than InlineAlert. With
 * `storage-key` a dismissed banner stays dismissed in this browser.
 */
import { CircleAlert, Info, Sparkles, TriangleAlert, X } from "@lucide/vue";
import { computed, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";

import { isBoolean, readStored, writeStored } from "@/lib/storage";

const props = withDefaults(
  defineProps<{
    tone?: "info" | "warning" | "danger" | "brand";
    title?: string;
    message?: string;
    icon?: Component;
    dismissible?: boolean;
    storageKey?: string;
  }>(),
  { tone: "info", title: undefined, message: undefined, icon: undefined, dismissible: false, storageKey: undefined },
);

const emit = defineEmits<{ dismiss: [] }>();
const { t } = useI18n();
const dismissed = ref(props.storageKey ? readStored(`banner.${props.storageKey}`, false, isBoolean) : false);

function dismiss(): void {
  dismissed.value = true;
  if (props.storageKey) writeStored(`banner.${props.storageKey}`, true);
  emit("dismiss");
}

const tones = {
  info: { box: "bg-info-soft text-fg border-[color-mix(in_srgb,var(--c-info)_22%,transparent)]", icon: "bg-info text-white dark:text-[#0c1622]", glyph: Info },
  warning: { box: "bg-warning-soft text-fg border-[color-mix(in_srgb,var(--c-warning)_26%,transparent)]", icon: "bg-warning text-white dark:text-[#2a1c05]", glyph: TriangleAlert },
  danger: { box: "bg-danger-soft text-fg border-[color-mix(in_srgb,var(--c-danger)_24%,transparent)]", icon: "bg-danger text-white dark:text-[#2a0c06]", glyph: CircleAlert },
  brand: {
    box: "border-[color-mix(in_srgb,var(--c-primary)_22%,transparent)] bg-[linear-gradient(100deg,var(--c-accent-soft),color-mix(in_srgb,var(--c-accent-soft)_55%,var(--c-surface)))] text-fg",
    icon: "bg-primary text-on-primary",
    glyph: Sparkles,
  },
} as const;
const glyph = computed(() => props.icon ?? tones[props.tone].glyph);
</script>

<template>
  <Transition name="fade">
    <div
      v-if="!dismissed"
      :role="tone === 'danger' ? 'alert' : 'status'"
      :class="['flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[12px] border px-3 py-2.5 sm:flex-nowrap sm:px-4', tones[tone].box]"
    >
      <span :class="['grid size-7 shrink-0 place-items-center rounded-full', tones[tone].icon]" aria-hidden="true">
        <component :is="glyph" :size="15" />
      </span>
      <p class="min-w-0 flex-1 text-sm">
        <span v-if="title" class="font-semibold text-fg">{{ title }}</span>
        <span v-if="title && (message || $slots.default)" class="text-muted"> · </span>
        <span class="text-muted"><slot>{{ message }}</slot></span>
      </p>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2 max-sm:w-full max-sm:pl-10">
        <slot name="actions" />
      </div>
      <button
        v-if="dismissible || storageKey"
        type="button"
        class="pressable -mr-1 grid size-7 shrink-0 place-items-center rounded-[7px] text-muted hover:bg-[color-mix(in_srgb,var(--c-text)_7%,transparent)] hover:text-fg"
        :aria-label="t('common.dismiss')"
        @click="dismiss"
      >
        <X :size="15" />
      </button>
    </div>
  </Transition>
</template>
