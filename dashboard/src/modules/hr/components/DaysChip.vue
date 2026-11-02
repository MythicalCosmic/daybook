<script setup lang="ts">
/**
 * How far a date is, as a small pill: "In 5 days" (warning inside the window), "Today", "3 days
 * ago" (danger), or nothing while it is far away (unless `always`). Documents, contracts and
 * probation endings all read the same way.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import { useCompanyToday } from "@/stores/company";

import { daysUntil } from "../lib";

const props = withDefaults(defineProps<{ day: string; warnDays?: number; always?: boolean; prefix?: "ends" | "expires" | "probation" | "none"; size?: "sm" | "md" }>(), {
  warnDays: 30,
  always: false,
  prefix: "none",
  size: "sm",
});

const { t } = useI18n();
const today = useCompanyToday();
const left = computed(() => daysUntil(props.day, today.value));
const tone = computed<StatusTone>(() => (left.value < 0 ? "danger" : left.value <= Math.min(7, props.warnDays) ? "danger" : left.value <= props.warnDays ? "warning" : "neutral"));
const shown = computed(() => props.always || left.value <= props.warnDays);
const label = computed(() => {
  const n = Math.abs(left.value);
  if (left.value < 0) return t(`hr.days.ago.${props.prefix}`, { n }, n);
  if (left.value === 0) return t(`hr.days.today.${props.prefix}`);
  return t(`hr.days.in.${props.prefix}`, { n }, n);
});
</script>

<template>
  <StatusPill v-if="shown" :tone="tone" :size="size" :label="label" />
</template>
