<script setup lang="ts">
/** How far a day is from today, in words: "Today", "Tomorrow", "in 9 days", "3 days ago". */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { diffDays } from "@/lib/dates";

const props = defineProps<{ day: string | null | undefined; today: string }>();

const { t } = useI18n();
const text = computed(() => {
  if (!props.day) return "";
  const days = diffDays(props.today, props.day);
  if (days === 0) return t("lifecycle.countdown.today");
  if (days === 1) return t("lifecycle.countdown.tomorrow");
  if (days > 1) return t("lifecycle.countdown.inDays", { n: days }, days);
  return t("lifecycle.countdown.ago", { n: -days }, -days);
});
</script>

<template>
  <span v-if="text" :class="['tabular-nums', day && day === today ? 'font-medium text-warning' : '']">{{ text }}</span>
</template>
