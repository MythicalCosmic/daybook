<script setup lang="ts">
/**
 * A project's health: a coloured dot (with a soft pulse when off track), optionally its label.
 * The computed health comes from the server (milestones, budget, due date); `reported` is what the
 * lead last said, shown in the tooltip when it differs.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiTooltip from "@/components/UiTooltip.vue";

import { healthVar } from "../lib";
import type { Health } from "../types";

const props = withDefaults(defineProps<{ health: Health | null; reported?: Health | null; label?: boolean; size?: number }>(), {
  reported: null,
  label: false,
  size: 8,
});

const { t } = useI18n();
const text = computed(() => (props.health ? t(`projects.health.${props.health}`) : t("projects.health.none")));
const tip = computed(() =>
  props.reported && props.reported !== props.health ? t("projects.health.reportedTip", { health: text.value, reported: t(`projects.health.${props.reported}`) }) : text.value,
);
</script>

<template>
  <UiTooltip :content="tip">
    <span class="inline-flex shrink-0 items-center gap-1.5" :aria-label="tip" role="img">
      <span class="relative inline-flex" :style="{ width: `${size}px`, height: `${size}px` }">
        <span v-if="health === 'off_track'" class="absolute inset-0 animate-ping rounded-full opacity-40 motion-reduce:hidden" :style="{ background: healthVar(health) }" />
        <span class="relative inline-flex size-full rounded-full" :style="{ background: healthVar(health) }" />
      </span>
      <span v-if="label" class="text-xs font-semibold" :style="{ color: health ? healthVar(health) : undefined }" :class="!health && 'text-muted'">{{ text }}</span>
    </span>
  </UiTooltip>
</template>
