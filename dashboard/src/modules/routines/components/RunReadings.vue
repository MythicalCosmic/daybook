<script setup lang="ts">
/**
 * A readings run's values on one line (PLAN-OWNER §14.10): each value with its unit, out of range
 * in the danger tone with the allowed range on hover, a recheck after it ("→ 5,6 °C"), and the
 * note underneath. Nothing for a run without readings.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import { rangeText, valueText } from "../readings";
import type { ReadingTaken } from "../types";

const props = defineProps<{ readings: readonly ReadingTaken[] }>();

const { t } = useI18n();
const fmt = useFormat();
const lang = computed(() => fmt.lang.value);

/** One chip per key: its first measurement and the rechecks after it. */
const keys = computed(() => {
  const groups = new Map<string, { first: ReadingTaken | null; rechecks: ReadingTaken[] }>();
  const sorted = [...props.readings].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at) || a.id - b.id);
  for (const row of sorted) {
    const group = groups.get(row.key) ?? { first: null, rechecks: [] };
    if (row.is_recheck) group.rechecks.push(row);
    else group.first ??= row;
    groups.set(row.key, group);
  }
  return [...groups.values()].filter((group) => group.first !== null) as Array<{ first: ReadingTaken; rechecks: ReadingTaken[] }>;
});
const notes = computed(() => [...new Set(props.readings.map((row) => row.note).filter(Boolean))]);

function title(row: ReadingTaken): string {
  const range = rangeText(row.min, row.max, row.unit, lang.value);
  const state = row.in_range ? t("routines.readings.inRange") : t("routines.readings.outOfRange");
  return [row.label, range && t("routines.readings.allowed", { range }), state].filter(Boolean).join(" · ");
}
</script>

<template>
  <div v-if="keys.length" class="mt-1 flex min-w-0 flex-col gap-1" data-testid="run-readings">
    <p class="flex min-w-0 flex-wrap items-center gap-1">
      <span
        v-for="group in keys"
        :key="group.first.key"
        :class="[
          'inline-flex max-w-full items-center gap-1 rounded-full px-2 py-px text-xs font-medium tabular-nums',
          group.first.in_range ? 'bg-surface-2 text-fg' : 'bg-danger-soft text-danger',
        ]"
        :title="title(group.first)"
        :data-in-range="group.first.in_range"
      >
        <span class="truncate text-muted">{{ group.first.label }}</span>
        <span>{{ valueText(group.first.value, group.first.unit, lang) }}</span>
        <span
          v-for="again in group.rechecks"
          :key="again.id"
          :class="again.in_range ? 'text-success' : 'text-danger'"
          :title="`${t('routines.readings.recheck')} · ${fmt.instant(again.recorded_at, 'time')}`"
          >→ {{ valueText(again.value, again.unit, lang) }}</span
        >
      </span>
    </p>
    <p v-for="note in notes" :key="note" class="line-clamp-2 text-xs text-muted" :title="note">{{ note }}</p>
  </div>
</template>
