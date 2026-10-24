<script setup lang="ts">
/**
 * Marks on a task in lists and cards for what waits on the giver: "Can't do" (contract 7, with
 * the reason on hover) and "Asks for time" (contract 8, with the deadline asked for).
 */
import { Ban, Hourglass } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import type { TaskExtras } from "../types";

defineProps<{ task: TaskExtras; size?: number }>();

const { t } = useI18n();
const fmt = useFormat();
</script>

<template>
  <span
    v-if="task.blocker"
    class="inline-flex shrink-0 items-center gap-0.5 font-semibold text-danger"
    :title="`${t(`tasks.blocker.reason.${task.blocker.reason_code}`)}${task.blocker.note ? `: ${task.blocker.note}` : ''}`"
    data-flag="blocked"
  >
    <Ban :size="size ?? 11" aria-hidden="true" />{{ t("tasks.flag.blocked") }}
  </span>
  <span v-if="task.extension" class="inline-flex shrink-0 items-center gap-0.5 font-semibold text-warning" :title="t('tasks.extension.until', { time: fmt.instant(task.extension.until, 'short') })" data-flag="extension">
    <Hourglass :size="size ?? 11" aria-hidden="true" />{{ t("tasks.flag.extension") }}
  </span>
</template>
