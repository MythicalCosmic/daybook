<script setup lang="ts">
/**
 * What a reminder policy does to a task due at a given time (plan §6.2: "heads-up → every 20 min →
 * escalation at #3 → stop at #12, quiet hours shaded"). Built from the same rules as the engine
 * (`../schedule.ts`); long quiet nights are squeezed so the reminders stay readable.
 */
import { BellRing, Flag, Moon, Siren, Square } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { clock, dayOffset, planReminders, trackScale, type PolicyShape } from "../schedule";

const props = withDefaults(defineProps<{ policy: PolicyShape; due?: number; weekday?: number; compact?: boolean }>(), {
  due: 18 * 60,
  weekday: 0,
  compact: false,
});

const { t } = useI18n();
const plan = computed(() => planReminders(props.policy, props.due, props.weekday, props.compact ? 12 : 16));
const scale = computed(() => trackScale(plan.value.start, plan.value.end, plan.value.quiet));
const pct = (minutes: number) => `${(scale.value(minutes) * 100).toFixed(2)}%`;

const labelled = computed(() => {
  // Label the heads-up, the first, the escalation and the last; others when there's room.
  const keep = new Set<number>();
  let lastX = -1;
  plan.value.events.forEach((event, index) => {
    const x = scale.value(event.at);
    const important = event.kind === "heads_up" || event.step === 1 || event.escalate || event.last;
    if (important || x - lastX > (props.compact ? 0.16 : 0.085)) {
      keep.add(index);
      lastX = x;
    }
  });
  return keep;
});

function when(minutes: number): string {
  const day = dayOffset(minutes);
  return day > 0 ? `${clock(minutes)}${day === 1 ? ` ${t("reminders.timeline.nextDay")}` : ` +${day}`}` : clock(minutes);
}
</script>

<template>
  <div class="min-w-0" :aria-label="t('reminders.timeline.label')" role="img">
    <div :class="['relative mx-3', compact ? 'h-[54px]' : 'h-[104px]']">
      <!-- Quiet hours and quiet days -->
      <div
        v-for="band in plan.quiet"
        :key="`${band.from}-${band.to}`"
        class="absolute inset-y-0 flex items-start justify-center overflow-hidden rounded-[6px] bg-surface-2"
        :style="{
          left: pct(band.from),
          width: `calc(${pct(band.to)} - ${pct(band.from)})`,
          backgroundImage: 'repeating-linear-gradient(135deg, transparent 0 6px, var(--c-border) 6px 7px)',
        }"
        :title="t('reminders.timeline.quiet', { from: clock(band.from), to: clock(band.to) })"
      >
        <span v-if="!compact" class="mt-1 inline-flex items-center gap-1 rounded-full bg-surface px-1.5 py-px text-[10px] font-medium text-muted shadow-xs">
          <Moon :size="10" />{{ band.day ? t("reminders.timeline.quietDay") : `${clock(band.from)}–${clock(band.to)}` }}
        </span>
      </div>

      <!-- The line -->
      <div :class="['absolute inset-x-0 h-[2px] rounded-full bg-line-strong', compact ? 'top-[22px]' : 'top-[52px]']" />

      <!-- Deadline -->
      <div :class="['absolute flex -translate-x-1/2 flex-col items-center', compact ? 'top-0' : 'top-0']" :style="{ left: pct(plan.due) }">
        <span v-if="!compact" class="mb-1 inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-accent-soft px-1.5 py-px text-[10px] font-semibold text-accent-fg">
          <Flag :size="10" />{{ t("reminders.timeline.deadline") }} {{ clock(plan.due) }}
        </span>
        <span :class="['w-[2px] bg-primary', compact ? 'h-[22px]' : 'h-[26px]']" />
      </div>

      <!-- Heads-up and reminders -->
      <div
        v-for="(event, index) in plan.events"
        :key="`${event.kind}-${event.step}`"
        class="absolute flex -translate-x-1/2 flex-col items-center"
        :style="{ left: pct(event.at), top: compact ? '13px' : '42px' }"
        :title="event.kind === 'heads_up' ? t('reminders.timeline.headsUpAt', { time: when(event.at) }) : t('reminders.timeline.reminderAt', { n: event.step, time: when(event.at) })"
      >
        <span
          :class="[
            'grid shrink-0 place-items-center rounded-full border-2 border-surface font-semibold tabular-nums shadow-xs',
            compact ? 'size-[20px] text-[9px]' : 'size-[22px] text-[10px]',
            event.kind === 'heads_up' ? 'bg-info-soft text-info' : event.escalate ? 'bg-danger text-on-primary' : event.last ? 'bg-fg text-surface' : 'bg-warning text-on-primary',
          ]"
        >
          <BellRing v-if="event.kind === 'heads_up'" :size="11" />
          <Siren v-else-if="event.escalate" :size="11" />
          <Square v-else-if="event.last && compact" :size="8" />
          <template v-else>{{ event.step }}</template>
        </span>
        <span v-if="!compact && labelled.has(index)" class="mt-1 whitespace-nowrap text-[10px] tabular-nums text-muted">{{ when(event.at) }}</span>
      </div>
    </div>

    <ul v-if="!compact" class="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 text-xs text-muted">
      <li v-if="plan.events.some((e) => e.kind === 'heads_up')" class="inline-flex items-center gap-1.5"><span class="grid size-3.5 place-items-center rounded-full bg-info-soft text-info"><BellRing :size="8" /></span>{{ t("reminders.timeline.legend.headsUp") }}</li>
      <li class="inline-flex items-center gap-1.5"><span class="size-3 rounded-full bg-warning" />{{ t("reminders.timeline.legend.reminder") }}</li>
      <li v-if="plan.events.some((e) => e.escalate)" class="inline-flex items-center gap-1.5"><span class="grid size-3.5 place-items-center rounded-full bg-danger text-on-primary"><Siren :size="8" /></span>{{ t("reminders.timeline.legend.escalation") }}</li>
      <li v-if="plan.events.some((e) => e.last)" class="inline-flex items-center gap-1.5"><span class="size-3 rounded-full bg-fg" />{{ t("reminders.timeline.legend.last") }}</li>
      <li v-if="plan.endless" class="inline-flex items-center gap-1.5 font-medium text-fg">{{ t("reminders.timeline.legend.endless") }}</li>
      <li v-if="plan.quiet.length" class="inline-flex items-center gap-1.5"><Moon :size="12" />{{ t("reminders.timeline.legend.quiet") }}</li>
    </ul>
  </div>
</template>
