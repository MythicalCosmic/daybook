<script setup lang="ts">
/**
 * A titled block of a page ("Branches", "Needs you", "Recent payments"): heading, optional count,
 * description and actions; `variant="card"` puts the body in a card, `"divided"` draws a rule above.
 * `collapsible` lets the person fold it (remembered per `id` in this browser).
 */
import { ChevronDown } from "@lucide/vue";
import { ref, watch } from "vue";

import { isBoolean, readStored, writeStored } from "@/lib/storage";

import UiBadge from "./UiBadge.vue";

const props = withDefaults(
  defineProps<{
    title?: string;
    description?: string;
    count?: number;
    variant?: "plain" | "card" | "divided";
    /** Body without padding inside the card (tables, lists). */
    flush?: boolean;
    collapsible?: boolean;
    id?: string;
    headingLevel?: 2 | 3;
  }>(),
  { title: undefined, description: undefined, count: undefined, variant: "plain", flush: false, collapsible: false, id: undefined, headingLevel: 2 },
);

const collapsed = ref(props.collapsible && props.id ? readStored(`section.${props.id}`, false, isBoolean) : false);
watch(collapsed, (value) => props.id && writeStored(`section.${props.id}`, value || null));
</script>

<template>
  <section :id="id" :class="['min-w-0', variant === 'divided' && 'border-t border-line pt-6']" :aria-labelledby="id && title ? `${id}-title` : undefined">
    <header v-if="title || $slots.actions || $slots.title" class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <button
          v-if="collapsible"
          type="button"
          class="pressable -ml-1 grid size-6 shrink-0 place-items-center rounded-[6px] text-muted hover:bg-highlight hover:text-fg"
          :aria-expanded="!collapsed"
          :aria-controls="id ? `${id}-body` : undefined"
          @click="collapsed = !collapsed"
        >
          <ChevronDown :size="16" :class="['transition-transform duration-200', collapsed && '-rotate-90']" />
        </button>
        <div class="min-w-0">
          <component :is="`h${headingLevel}`" :id="id ? `${id}-title` : undefined" class="flex items-center gap-2 text-md font-semibold text-fg">
            <slot name="title">{{ title }}</slot>
            <UiBadge v-if="count !== undefined" :count="count" tone="neutral" />
          </component>
          <p v-if="description" class="mt-0.5 text-sm text-muted">{{ description }}</p>
        </div>
      </div>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </header>
    <Transition name="collapse">
      <div v-show="!collapsed" :id="id ? `${id}-body` : undefined">
        <div class="min-h-0">
          <div v-if="variant === 'card'" :class="['ui-card overflow-hidden', !flush && 'p-4 md:p-5']">
            <slot />
          </div>
          <slot v-else />
        </div>
      </div>
    </Transition>
  </section>
</template>
