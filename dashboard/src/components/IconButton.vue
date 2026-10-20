<script setup lang="ts">
/**
 * A square button with one icon. `label` is required: it is the accessible name and the tooltip.
 * `badge` puts a count (or a dot for `true`) on the corner.
 */
import { computed, type Component } from "vue";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import { formatCount } from "@/lib/format";

import UiSpinner from "./UiSpinner.vue";
import UiTooltip from "./UiTooltip.vue";

// The root is the tooltip; classes and listeners belong on the button itself.
defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    icon: Component;
    label: string;
    variant?: "ghost" | "secondary" | "primary" | "soft";
    size?: "sm" | "md" | "lg";
    badge?: number | boolean;
    badgeTone?: "primary" | "danger";
    shortcut?: string;
    tooltip?: boolean;
    tooltipSide?: "top" | "right" | "bottom" | "left";
    active?: boolean;
    loading?: boolean;
    disabled?: boolean;
    to?: RouteLocationRaw;
    type?: "button" | "submit";
  }>(),
  {
    variant: "ghost",
    size: "md",
    badge: undefined,
    badgeTone: "danger",
    shortcut: undefined,
    tooltip: true,
    tooltipSide: "bottom",
    active: false,
    loading: false,
    disabled: false,
    to: undefined,
    type: "button",
  },
);

const sizes = { sm: "size-7 rounded-[7px]", md: "size-8 rounded-button", lg: "size-10 rounded-[10px]" } as const;
const iconSizes = { sm: 15, md: 17, lg: 19 } as const;
const variants = {
  ghost: "text-muted hover:bg-highlight hover:text-fg",
  secondary: "border border-line bg-surface text-fg shadow-xs hover:bg-surface-2",
  primary: "bg-primary text-on-primary hover:bg-primary-hover",
  soft: "bg-accent-soft text-accent-fg hover:brightness-95",
} as const;

const showBadge = computed(() => props.badge === true || (typeof props.badge === "number" && props.badge > 0));
const badgeText = computed(() => (typeof props.badge === "number" ? formatCount(props.badge) : ""));
</script>

<template>
  <UiTooltip :content="label" :shortcut="shortcut" :side="tooltipSide" :disabled="!tooltip">
    <component
      :is="to ? RouterLink : 'button'"
      v-bind="$attrs"
      :to="to"
      :type="to ? undefined : type"
      :aria-label="label"
      :aria-pressed="active ? 'true' : undefined"
      :disabled="to ? undefined : disabled || loading"
      :class="[
        'pressable relative inline-flex shrink-0 items-center justify-center',
        sizes[size],
        variants[variant],
        active && 'bg-highlight text-fg',
        (disabled || loading) && 'pointer-events-none opacity-50',
      ]"
    >
      <UiSpinner v-if="loading" :size="iconSizes[size] - 2" />
      <component :is="icon" v-else :size="iconSizes[size]" aria-hidden="true" />
      <span
        v-if="showBadge"
        :class="[
          'pointer-events-none absolute flex items-center justify-center rounded-full font-semibold leading-none ring-2 ring-[var(--badge-ring,var(--c-surface))]',
          badgeText ? '-right-1 -top-1 h-4 min-w-4 px-1 text-[10px]' : 'right-1.5 top-1.5 size-2',
          badgeTone === 'danger' ? 'bg-danger text-white' : 'bg-primary text-on-primary',
        ]"
        >{{ badgeText }}</span
      >
    </component>
  </UiTooltip>
</template>
