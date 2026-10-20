<script setup lang="ts">
/** Days a routine runs, Monday first, as seven small letters: the active ones filled. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ days: number[] }>();
const { t } = useI18n();
const all = [0, 1, 2, 3, 4, 5, 6];
const label = computed(() => {
  const days = [...props.days].sort();
  if (days.length === 7) return t("routines.days.every");
  if (days.join() === "0,1,2,3,4") return t("routines.days.workdays");
  if (days.join() === "0,1,2,3,4,5") return t("routines.days.monSat");
  return days.map((day) => t(`routines.day.${day}`)).join(", ");
});
</script>

<template>
  <span class="inline-flex items-center gap-[3px]" :aria-label="label" :title="label">
    <span
      v-for="day in all"
      :key="day"
      aria-hidden="true"
      :class="[
        'grid size-[18px] place-items-center rounded-full text-[10px] font-semibold leading-none',
        days.includes(day) ? 'bg-accent-soft text-accent-fg' : 'text-subtle',
      ]"
      >{{ t(`routines.dayLetter.${day}`) }}</span
    >
  </span>
</template>
