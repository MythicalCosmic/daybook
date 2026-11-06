<script setup lang="ts">
/**
 * Overview card `tasks.readings_today` (PLAN-OWNER §14.10): today's storage readings that need
 * someone. Each value out of range (fridge, room, humidity) with its note, and "back in range" once
 * a recheck brought it back; each reading that was due and nobody took. Each row opens its
 * routine. A company that never set readings up sees nothing: the card renders nothing until the
 * answer says a readings routine runs (and on an older backend without the endpoint).
 */
import { useQuery } from "@tanstack/vue-query";
import { CalendarX, CircleCheck, Thermometer, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useFormat } from "@/lib/useFormat";

import { taskKeys, tasksApi } from "../api";
import { rangeText, valueText } from "../readings";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();
const fmt = useFormat();

const query = useQuery({
  queryKey: computed(() => taskKeys.readingsToday(props.companyId)),
  queryFn: ({ signal }) => tasksApi.readingsToday(props.companyId, signal),
  enabled: computed(() => props.companyId > 0),
  staleTime: 30_000,
  retry: false,
});
const data = computed(() => (query.data.value?.set_up ? query.data.value : null));

const routineLink = (id: number | undefined) => (id ? `/c/${props.companyId}/routines/${id}` : `/c/${props.companyId}/routines`);

const excursions = computed(() =>
  (data.value?.excursions ?? []).map((item) => ({
    ...item,
    valueLabel: `${item.label} ${valueText(item.value, item.unit, fmt.number)}`,
    allowed: rangeText(item.min, item.max, item.unit, fmt.number),
    where: [item.routine?.title, item.branch?.name, item.time].filter(Boolean).join(" · "),
  })),
);
const missed = computed(() =>
  (data.value?.missed ?? []).map((item) => ({
    ...item,
    where: [item.branch?.name, fmt.instant(item.due_at, "time"), item.assignee].filter(Boolean).join(" · "),
  })),
);
/** What still needs someone: values not back in range, and readings nobody took. */
const waiting = computed(() => excursions.value.filter((item) => !item.back_in_range_at).length + missed.value.length);
</script>

<template>
  <WidgetCard
    v-if="data"
    :title="t('tasks.widget.readings')"
    :icon="Thermometer"
    :count="waiting"
    count-tone="danger"
    :to="`/c/${companyId}/routines`"
    :link-label="t('tasks.widget.readingsLink')"
    data-testid="readings-today"
  >
    <EmptyState
      v-if="!excursions.length && !missed.length"
      class="my-auto"
      size="sm"
      tone="success"
      :icon="CircleCheck"
      :title="t('tasks.widget.readingsOk')"
      :description="t('tasks.widget.readingsTaken', { n: data.taken })"
    />
    <div v-else class="flex flex-col gap-3 pt-1">
      <ul v-if="excursions.length" class="flex flex-col" data-testid="readings-excursions">
        <li v-for="item in excursions" :key="item.id">
          <RouterLink :to="routineLink(item.routine?.id)" class="pressable flex min-w-0 items-start gap-2.5 rounded-[8px] px-2 py-2 hover:bg-highlight">
            <span :class="['mt-0.5 grid size-7 shrink-0 place-items-center rounded-full', item.back_in_range_at ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger']" aria-hidden="true">
              <component :is="item.back_in_range_at ? CircleCheck : TriangleAlert" :size="14" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="flex flex-wrap items-baseline gap-x-2">
                <span :class="['text-sm font-semibold tabular-nums', item.back_in_range_at ? 'text-fg' : 'text-danger']">{{ item.valueLabel }}</span>
                <span v-if="item.allowed" class="text-xs text-muted">{{ t("tasks.readings.allowed", { range: item.allowed }) }}</span>
              </span>
              <span class="block truncate text-xs text-muted" :title="item.where">{{ item.where }}</span>
              <span v-if="item.note" class="mt-0.5 block text-xs text-fg">{{ t("tasks.quoted", { text: item.note }) }}</span>
              <span v-if="item.back_in_range_at" class="mt-0.5 block text-xs font-medium text-success" data-testid="back-in-range">
                {{ t("tasks.widget.backInRange", { time: fmt.instant(item.back_in_range_at, "time") }) }}
              </span>
            </span>
          </RouterLink>
        </li>
      </ul>
      <div v-if="missed.length" class="flex flex-col gap-0.5" data-testid="readings-missed">
        <p class="px-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("tasks.widget.readingsMissed") }}</p>
        <RouterLink
          v-for="item in missed"
          :key="item.task_id"
          :to="routineLink(item.routine.id)"
          class="pressable flex min-w-0 items-center gap-2.5 rounded-[8px] px-2 py-1.5 hover:bg-highlight"
        >
          <CalendarX :size="15" class="shrink-0 text-warning" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-sm text-fg" :title="item.routine.title">{{ item.routine.title }}</span>
          <span class="shrink-0 text-xs text-muted">{{ item.where }}</span>
        </RouterLink>
      </div>
    </div>
  </WidgetCard>
</template>
