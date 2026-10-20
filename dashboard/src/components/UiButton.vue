<script setup lang="ts">
/**
 * The button. Variants: primary (one per view), secondary (default), ghost, soft, danger, link.
 * Renders a RouterLink with `to`, an anchor with `href`, a button otherwise. `loading` swaps the
 * leading icon for a spinner and keeps the width; `kbd` shows the shortcut at the end.
 */
import { computed, type Component } from "vue";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import KbdKey from "./KbdKey.vue";
import UiSpinner from "./UiSpinner.vue";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "soft" | "danger" | "link";
export type ButtonSize = "sm" | "md" | "lg";

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariant;
    size?: ButtonSize;
    icon?: Component;
    iconRight?: Component;
    loading?: boolean;
    disabled?: boolean;
    block?: boolean;
    type?: "button" | "submit" | "reset";
    to?: RouteLocationRaw;
    href?: string;
    target?: string;
    kbd?: string;
  }>(),
  {
    variant: "secondary",
    size: "md",
    icon: undefined,
    iconRight: undefined,
    loading: false,
    disabled: false,
    block: false,
    type: "button",
    to: undefined,
    href: undefined,
    target: undefined,
    kbd: undefined,
  },
);

const tag = computed(() => (props.to ? RouterLink : props.href ? "a" : "button"));
const inactive = computed(() => props.disabled || props.loading);

const sizes: Record<ButtonSize, string> = {
  sm: "h-7 gap-1.5 px-2.5 text-sm rounded-[7px]",
  md: "h-8 gap-2 px-3 text-sm rounded-button",
  lg: "h-10 gap-2 px-4 text-base rounded-[10px]",
};

const variants: Record<ButtonVariant, string> = {
  primary:
    "bg-primary text-on-primary shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_1px_2px_rgb(32_30_29/0.14)] hover:bg-primary-hover",
  secondary: "border border-line bg-surface text-fg shadow-xs hover:border-line-strong hover:bg-surface-2",
  ghost: "text-fg hover:bg-highlight",
  soft: "bg-accent-soft text-accent-fg hover:bg-[color-mix(in_srgb,var(--c-accent-soft)_80%,var(--c-primary))]",
  danger: "bg-danger text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.14)] hover:bg-[color-mix(in_srgb,var(--c-danger)_88%,black)]",
  link: "h-auto px-0 text-primary underline-offset-4 hover:underline",
};

const iconSize = computed(() => (props.size === "lg" ? 18 : 16));
</script>

<template>
  <component
    :is="tag"
    :to="to"
    :href="to ? undefined : href"
    :target="target"
    :type="to || href ? undefined : type"
    :disabled="tag === 'button' ? inactive : undefined"
    :aria-disabled="inactive ? 'true' : undefined"
    :aria-busy="loading ? 'true' : undefined"
    :tabindex="inactive && tag !== 'button' ? -1 : undefined"
    :class="[
      'pressable relative inline-flex select-none items-center justify-center whitespace-nowrap font-[550] outline-offset-2',
      variant === 'link' ? 'gap-1.5 text-sm' : sizes[size],
      variants[variant],
      block && 'w-full',
      inactive && 'pointer-events-none opacity-55',
    ]"
  >
    <UiSpinner v-if="loading" :size="iconSize" />
    <component :is="icon" v-else-if="icon" :size="iconSize" class="-ml-0.5 opacity-90" aria-hidden="true" />
    <span v-if="$slots.default" class="truncate"><slot /></span>
    <component :is="iconRight" v-if="iconRight" :size="iconSize" class="-mr-0.5 opacity-80" aria-hidden="true" />
    <KbdKey
      v-if="kbd"
      :keys="kbd"
      :inverted="variant === 'primary' || variant === 'danger'"
      class="-mr-1 ml-0.5"
    />
  </component>
</template>
