<script setup lang="ts">
/** The wordmark of the sign-in pages: the round check mark, "Daybook" in Caprasimo, "Console". */
import { useI18n } from "vue-i18n";

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });

const { t } = useI18n();
</script>

<template>
  <div class="flex items-center gap-3">
    <svg viewBox="0 0 50 50" :class="compact ? 'size-9' : 'size-11'" aria-hidden="true">
      <circle cx="21" cy="21" r="21" class="fill-chart-1" />
      <path d="M12.25 21.9 18.4 28 29.6 15.8" fill="none" class="stroke-white" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="39" cy="39" r="11" class="fill-chart-2 stroke-canvas" stroke-width="3" />
    </svg>
    <span :class="['font-display leading-none text-fg', compact ? 'text-[28px]' : 'text-[32px]']">{{ t("shell.brand") }}</span>
    <span class="mt-1 rounded-full border border-line bg-surface px-2 py-0.5 text-xs font-semibold text-muted">{{ t("shell.brandSuffix") }}</span>
  </div>
</template>
