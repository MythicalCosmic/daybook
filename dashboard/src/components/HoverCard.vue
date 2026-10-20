<script setup lang="ts">
/**
 * A preview on hover or keyboard focus. With `person` it shows the person card (photo, position,
 * branch, today's status, a few numbers, "Open profile"); otherwise the `content` slot. Supplementary
 * only: touch screens never see it, so never put the only path to something here.
 *
 *   <HoverCard :person="{ name, photo_url, subtitle: 'Cashier · Chilonzor', status: { tone: 'success', label: 'In since 08:57' } }" :to="profileUrl">
 *     <RouterLink :to="profileUrl">{{ name }}</RouterLink>
 *   </HoverCard>
 */
import { ArrowUpRight, MapPin, Phone } from "@lucide/vue";
import { HoverCardArrow, HoverCardContent, HoverCardPortal, HoverCardRoot, HoverCardTrigger } from "reka-ui";
import { useI18n } from "vue-i18n";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import { formatPhone } from "@/lib/format";

import StatusPill, { type StatusTone } from "./StatusPill.vue";
import UserAvatar from "./UserAvatar.vue";

export interface PersonPreview {
  name: string;
  photo_url?: string | null;
  subtitle?: string;
  phone?: string | null;
  branch?: string | null;
  status?: { tone: StatusTone; label: string; live?: boolean } | null;
  stats?: Array<{ label: string; value: string }>;
}

withDefaults(
  defineProps<{
    person?: PersonPreview | null;
    to?: RouteLocationRaw;
    side?: "top" | "right" | "bottom" | "left";
    align?: "start" | "center" | "end";
    openDelay?: number;
    width?: string;
  }>(),
  { person: null, to: undefined, side: "bottom", align: "start", openDelay: 450, width: "300px" },
);

const { t } = useI18n();
</script>

<template>
  <HoverCardRoot :open-delay="openDelay" :close-delay="120">
    <HoverCardTrigger as-child>
      <slot />
    </HoverCardTrigger>
    <HoverCardPortal>
      <HoverCardContent
        :side="side"
        :align="align"
        :side-offset="8"
        :collision-padding="8"
        class="anim-pop z-[75] overflow-hidden rounded-[12px] border border-line bg-surface text-fg shadow-pop outline-none"
        :style="{ width }"
      >
        <slot name="content">
          <div v-if="person" class="flex flex-col">
            <div class="flex items-start gap-3 p-4 pb-3">
              <UserAvatar :name="person.name" :src="person.photo_url" :size="44" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-md font-semibold leading-6 text-fg">{{ person.name }}</p>
                <p v-if="person.subtitle" class="truncate text-sm text-muted">{{ person.subtitle }}</p>
                <StatusPill v-if="person.status" class="mt-1.5" size="sm" :tone="person.status.tone" :label="person.status.label" :live="person.status.live" />
              </div>
            </div>
            <dl v-if="person.stats?.length" class="mx-4 mb-3 grid grid-cols-3 gap-2 rounded-[10px] bg-surface-2/70 p-2.5 dark:bg-surface-3/50">
              <div v-for="stat in person.stats" :key="stat.label" class="min-w-0">
                <dt class="truncate text-[11px] text-muted">{{ stat.label }}</dt>
                <dd class="truncate text-sm font-semibold tabular-nums text-fg">{{ stat.value }}</dd>
              </div>
            </dl>
            <div v-if="person.phone || person.branch" class="flex flex-col gap-1.5 px-4 pb-3 text-sm text-muted">
              <span v-if="person.branch" class="flex items-center gap-2"><MapPin :size="14" class="text-subtle" />{{ person.branch }}</span>
              <a v-if="person.phone" :href="`tel:${person.phone}`" class="flex items-center gap-2 hover:text-fg"
                ><Phone :size="14" class="text-subtle" />{{ formatPhone(person.phone) }}</a
              >
            </div>
            <RouterLink
              v-if="to"
              :to="to"
              class="flex items-center justify-between border-t border-line px-4 py-2.5 text-sm font-semibold text-primary transition-colors hover:bg-surface-2/60"
            >
              {{ t("common.person.open") }}
              <ArrowUpRight :size="15" />
            </RouterLink>
          </div>
        </slot>
        <HoverCardArrow class="fill-[var(--c-surface)]" :width="12" :height="6" />
      </HoverCardContent>
    </HoverCardPortal>
  </HoverCardRoot>
</template>
