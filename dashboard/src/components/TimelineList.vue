<script setup lang="ts">
/**
 * Events in time order, grouped by day ("Today", "Yesterday", "12 Oct"): a task's history, a
 * person's career, an audit trail, an activity stream. Each event has an icon (or the actor's
 * avatar), a title, an optional body and its time; `#event` replaces the default body.
 * `newKeys` makes freshly arrived events glow (plan §6.3: live inserts glow 1.5 s).
 *
 *   <TimelineList :events="[{ key: 1, at, title: 'Aziz closed shift CHL-1042', icon: Store, tone: 'success' }]" />
 */
import { computed, type Component } from "vue";
import { useI18n } from "vue-i18n";

import { addDays, formatDay, todayIn, zonedDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import UserAvatar from "./UserAvatar.vue";

export interface TimelineEvent {
  key: string | number;
  /** ISO instant. */
  at: string;
  title: string;
  body?: string;
  icon?: Component;
  tone?: "neutral" | "primary" | "success" | "warning" | "danger" | "info";
  actor?: { name: string; photo_url?: string | null } | null;
  meta?: string;
}

const props = withDefaults(defineProps<{ events: TimelineEvent[]; group?: boolean; newKeys?: Array<string | number>; dense?: boolean }>(), {
  group: true,
  newKeys: () => [],
  dense: false,
});

defineSlots<{ event?: (props: { event: TimelineEvent }) => unknown }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const groups = computed(() => {
  const today = todayIn(company.timezone);
  const out: Array<{ day: string; label: string; events: TimelineEvent[] }> = [];
  const sorted = [...props.events].sort((a, b) => (a.at < b.at ? 1 : -1));
  for (const event of sorted) {
    const day = zonedDay(event.at, company.timezone);
    let group = out.at(-1);
    if (!group || group.day !== day) {
      const label = day === today ? t("common.today") : day === addDays(today, -1) ? t("common.yesterday") : formatDay(day, fmt.lang.value, day.slice(0, 4) === today.slice(0, 4) ? "weekday" : "long");
      group = { day, label, events: [] };
      out.push(group);
    }
    group.events.push(event);
  }
  return props.group ? out : [{ day: "", label: "", events: sorted }];
});

const tones = {
  neutral: "bg-surface-2 text-muted dark:bg-surface-3",
  primary: "bg-accent-soft text-accent-fg",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
} as const;
</script>

<template>
  <div class="flex flex-col gap-5">
    <section v-for="day in groups" :key="day.day">
      <h4 v-if="group" class="mb-2 text-xs font-semibold uppercase tracking-[0.04em] text-subtle">{{ day.label }}</h4>
      <ol class="relative">
        <li
          v-for="(event, index) in day.events"
          :key="event.key"
          :class="['relative flex gap-3 rounded-[10px]', dense ? 'pb-3' : 'pb-4', newKeys.includes(event.key) && 'live-glow']"
        >
          <span
            v-if="index < day.events.length - 1"
            class="absolute bottom-0 left-[13px] top-8 w-px bg-line"
            aria-hidden="true"
          />
          <UserAvatar v-if="!event.icon && event.actor" :name="event.actor.name" :src="event.actor.photo_url" :size="28" />
          <span v-else :class="['relative grid size-7 shrink-0 place-items-center rounded-full ring-4 ring-[var(--c-surface)]', tones[event.tone ?? 'neutral']]" aria-hidden="true">
            <component :is="event.icon" v-if="event.icon" :size="14" />
            <span v-else class="size-1.5 rounded-full bg-current" />
          </span>
          <div class="min-w-0 flex-1 pt-0.5">
            <slot name="event" :event="event">
              <div class="flex items-baseline gap-3">
                <p class="min-w-0 flex-1 text-base text-fg">
                  <template v-if="event.actor && event.icon"><span class="font-semibold">{{ event.actor.name }}</span>{{ " " }}</template>
                  <span>{{ event.title }}</span>
                </p>
                <time :datetime="event.at" class="shrink-0 text-xs tabular-nums text-subtle" :title="fmt.instant(event.at)">{{ fmt.instant(event.at, "time") }}</time>
              </div>
              <p v-if="event.body" class="mt-0.5 text-sm text-muted">{{ event.body }}</p>
              <p v-if="event.meta" class="mt-1 text-xs text-subtle">{{ event.meta }}</p>
            </slot>
          </div>
        </li>
      </ol>
    </section>
  </div>
</template>
