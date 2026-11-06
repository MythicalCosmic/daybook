<script setup lang="ts">
/**
 * One month at a time ("‹ November 2026 ›" and "This month"), as the timesheet steps through
 * months. `max` stops the forward arrow (budgets can be planned a year ahead, not further). The
 * page decides whether a step may happen (unsaved budgets ask first), so the arrows emit `go`.
 */
import { CalendarDays, ChevronLeft, ChevronRight } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import IconButton from "@/components/IconButton.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";

import { monthStart, shiftMonth } from "../lib";

const props = withDefaults(defineProps<{ month: string; current: string; max?: string | null }>(), { max: null });
const emit = defineEmits<{ go: [month: string] }>();

const { t } = useI18n();
const fmt = useFormat();

function step(amount: number): void {
  emit("go", shiftMonth(props.month, amount));
}
</script>

<template>
  <div class="flex items-center gap-1">
    <IconButton :icon="ChevronLeft" :label="t('common.date.prevMonth')" size="sm" variant="secondary" @click="step(-1)" />
    <span class="inline-flex min-w-40 items-center justify-center gap-1.5 text-base font-semibold text-fg" aria-live="polite" data-month>
      <CalendarDays :size="15" class="text-subtle" aria-hidden="true" />{{ fmt.day(monthStart(month), "monthYear") }}
    </span>
    <IconButton :icon="ChevronRight" :label="t('common.date.nextMonth')" size="sm" variant="secondary" :disabled="!!max && month >= max" @click="step(1)" />
    <UiButton v-if="month !== current" size="sm" variant="ghost" @click="emit('go', current)">{{ t("finance.budgets.thisMonth") }}</UiButton>
  </div>
</template>
