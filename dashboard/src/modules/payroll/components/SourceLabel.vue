<script setup lang="ts">
/**
 * Where a bonus or fine came from: by hand (and who proposed it), an automatic rule (its name), a
 * task (its title, linked) or attendance. One line with an icon; tables and drawers use it.
 */
import { CalendarCheck, Gavel, Hand, ListTodo, Zap } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { useCompanyStore } from "@/stores/company";

import type { Adjustment } from "../types";

/** `plain`: "By hand" without who (where the proposer is shown beside it). */
const props = withDefaults(defineProps<{ row: Pick<Adjustment, "source" | "rule" | "task" | "proposed_by">; plain?: boolean }>(), { plain: false });

const { t } = useI18n();
const company = useCompanyStore();
const icon = computed(() => ({ manual: Hand, rule: Zap, task: ListTodo, attendance: CalendarCheck, discipline: Gavel })[props.row.source]);
const text = computed(() => {
  const row = props.row;
  if (row.source === "rule") return row.rule?.name ?? t("payroll.source.rule");
  if (row.source === "task") return row.task?.name ?? t("payroll.source.task");
  if (row.source === "manual") return row.proposed_by && !props.plain ? t("payroll.source.by", { name: row.proposed_by }) : t("payroll.source.manual");
  return t(`payroll.source.${row.source}`);
});
</script>

<template>
  <span class="flex min-w-0 items-center gap-1.5 text-sm text-muted">
    <component :is="icon" :size="14" class="shrink-0 text-subtle" aria-hidden="true" />
    <RouterLink
      v-if="row.source === 'task' && row.task"
      :to="`/c/${company.currentId}/tasks?task=${row.task.id}`"
      class="truncate hover:text-fg hover:underline"
      :title="text"
      @click.stop
      >{{ text }}</RouterLink
    >
    <span v-else class="truncate" :title="text">{{ text }}</span>
  </span>
</template>
