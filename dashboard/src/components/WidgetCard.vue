<script setup lang="ts">
/**
 * The frame of an Overview card (plan §6.2): icon, title, an optional count and subtitle, the
 * link to the page behind it, and a body that scrolls (with a soft edge fade) when the Overview
 * grid caps the card's height. Every list widget uses it, so cards from different modules line
 * up: same header height, same link, same padding.
 *
 *   <WidgetCard :title="t('projects.widget.atRisk')" :icon="FolderKanban" :count="projects.length" count-tone="warning" :to="all">
 *     <ul>…</ul>
 *     <template #footer>3 more waiting</template>
 *   </WidgetCard>
 */
import { ArrowRight } from "@lucide/vue";
import { ref, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import UiBadge, { type BadgeTone } from "./UiBadge.vue";
import { useScrollFade } from "./useScrollFade";

withDefaults(
  defineProps<{
    title: string;
    icon?: Component;
    subtitle?: string;
    /** A count beside the title (hidden at 0). */
    count?: number | null;
    countTone?: BadgeTone;
    /** The page behind the card: "View all →" in the header. */
    to?: RouteLocationRaw;
    linkLabel?: string;
    /** "list": rows that pad themselves (8 px inset); "content": free content (16 px, like the header). */
    inset?: "list" | "content";
  }>(),
  { icon: undefined, subtitle: undefined, count: null, countTone: "primary", to: undefined, linkLabel: undefined, inset: "list" },
);

const { t } = useI18n();
const body = ref<HTMLElement | null>(null);
const content = ref<HTMLElement | null>(null);
const fade = useScrollFade(body, content);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col @container" :aria-label="title" data-widget-card>
    <header class="flex min-h-[52px] shrink-0 items-start gap-2 px-4 pb-2 pt-4">
      <div class="min-w-0 flex-1">
        <div class="flex min-h-5 min-w-0 items-center gap-2">
          <component :is="icon" v-if="icon" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <h3 class="truncate text-sm font-semibold text-fg">{{ title }}</h3>
          <UiBadge v-if="count" :count="count" :tone="countTone" />
        </div>
        <p v-if="subtitle" class="mt-0.5 truncate text-xs text-muted">{{ subtitle }}</p>
      </div>
      <slot name="aside" />
      <RouterLink
        v-if="to"
        :to="to"
        :title="linkLabel ?? t('common.viewAll')"
        class="group/link -mr-1.5 -mt-1 inline-flex min-h-7 min-w-7 shrink-0 items-center justify-center gap-1 rounded-[6px] px-1.5 text-sm font-semibold text-muted transition-colors hover:bg-highlight hover:text-fg"
      >
        <!-- A narrow card keeps its title whole: the link shrinks to its arrow (the label stays for screen readers). -->
        <span class="@max-[19rem]:sr-only">{{ linkLabel ?? t("common.viewAll") }}</span><ArrowRight :size="14" class="transition-transform duration-150 group-hover/link:translate-x-0.5" aria-hidden="true" />
      </RouterLink>
    </header>
    <div ref="body" class="no-scrollbar min-h-0 flex-1 overflow-y-auto" :style="fade">
      <div ref="content" :class="['flex min-h-full flex-col', inset === 'list' ? 'px-2 pb-2' : 'px-4 pb-4']">
        <slot />
      </div>
    </div>
    <footer v-if="$slots.footer" class="shrink-0 border-t border-line px-4 py-2.5 text-xs font-medium text-muted">
      <slot name="footer" />
    </footer>
  </section>
</template>
