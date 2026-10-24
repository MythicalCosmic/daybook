<script setup lang="ts">
/**
 * A task's priority the way every surface shows it (the mini app and the bot say the same): Urgent
 * is a red flag chip with the word, High a plain flag with the word, Normal and Low stay quiet
 * (`quiet` prints them as muted words, for the table's Priority column). Never colour alone.
 */
import { Flag } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import type { TaskPriority } from "../types";

withDefaults(defineProps<{ priority: TaskPriority; quiet?: boolean; size?: number }>(), { quiet: false, size: 12 });

const { t } = useI18n();
</script>

<template>
  <span
    v-if="priority === 'urgent'"
    class="inline-flex shrink-0 items-center gap-1 rounded-full bg-danger-soft px-1.5 py-px text-xs font-semibold leading-4 text-danger"
    data-priority="urgent"
  >
    <Flag :size="size" class="shrink-0 fill-current" aria-hidden="true" />{{ t("tasks.priority.urgent") }}
  </span>
  <span v-else-if="priority === 'high'" class="inline-flex shrink-0 items-center gap-1 text-xs font-semibold leading-4 text-fg" data-priority="high">
    <Flag :size="size" class="shrink-0" aria-hidden="true" />{{ t("tasks.priority.high") }}
  </span>
  <span v-else-if="quiet" class="text-sm text-muted">{{ t(`tasks.priority.${priority}`) }}</span>
</template>
