<script setup lang="ts">
/** A task's status as a pill; open work past its deadline reads "Late" in red. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import StatusPill from "@/components/StatusPill.vue";

import { STATUS_TONE } from "../meta";
import type { TaskStatus } from "../types";

const props = withDefaults(defineProps<{ status: TaskStatus; overdue?: boolean; size?: "sm" | "md" }>(), { overdue: false, size: "sm" });

const { t } = useI18n();
const late = computed(() => props.overdue && ["todo", "in_progress", "returned"].includes(props.status));
</script>

<template>
  <StatusPill :tone="late ? 'danger' : STATUS_TONE[status]" :size="size" :live="status === 'in_progress'" :label="late ? t('tasks.status.late') : t(`tasks.status.${status}`)" />
</template>
