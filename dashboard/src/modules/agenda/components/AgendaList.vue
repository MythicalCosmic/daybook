<script setup lang="ts">
/**
 * The agenda view: the next thirty days as a list, one block per day that has something (today
 * and tomorrow named), each date with its time, colour and calendar.
 */
import { CalendarCheck2, ChevronLeft, ChevronRight, Repeat } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { itemColor, itemsByDay, type CalendarItem } from "@/components/calendarItems";
import EmptyState from "@/components/EmptyState.vue";
import UiButton from "@/components/UiButton.vue";
import { addDays, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

const anchor = defineModel<string>("anchor", { required: true });
const props = withDefaults(defineProps<{ items: CalendarItem[]; days?: number; canCreate?: boolean; mine?: Set<string> }>(), {
  days: 30,
  canCreate: false,
  mine: () => new Set<string>(),
});
const emit = defineEmits<{ "item-click": [item: CalendarItem]; create: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));
const dayList = computed(() => Array.from({ length: props.days }, (_, i) => addDays(anchor.value, i)));
const byDay = computed(() => itemsByDay(props.items, dayList.value, company.timezone));
const blocks = computed(() => dayList.value.map((day) => ({ day, entries: byDay.value.get(day) ?? [] })).filter((block) => block.entries.length));

function label(day: string): string {
  if (day === today.value) return t("common.today");
  if (day === addDays(today.value, 1)) return t("agenda.tomorrow");
  return fmt.day(day, "weekday");
}

function timeOf(item: CalendarItem): string {
  if (item.all_day || /^\d{4}-\d{2}-\d{2}$/.test(item.start)) return t("common.calendar.allDay");
  const start = fmt.instant(item.start, "time");
  return item.end ? `${start} – ${fmt.instant(item.end, "time")}` : start;
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 flex-1 text-md font-semibold text-fg" aria-live="polite">
        {{ t("agenda.agendaRange", { from: fmt.day(anchor, "medium"), to: fmt.day(addDays(anchor, days - 1), "medium") }) }}
      </h3>
      <UiButton size="sm" variant="secondary" @click="anchor = today">{{ t("common.today") }}</UiButton>
      <button type="button" class="pressable grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('agenda.earlier')" @click="anchor = addDays(anchor, -days)">
        <ChevronLeft :size="16" />
      </button>
      <button type="button" class="pressable grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('agenda.later')" @click="anchor = addDays(anchor, days)">
        <ChevronRight :size="16" />
      </button>
    </div>

    <EmptyState v-if="!blocks.length" class="ui-card" :icon="CalendarCheck2" :title="t('agenda.emptyTitle')" :description="t('agenda.emptyBody')">
      <UiButton v-if="canCreate" variant="primary" @click="emit('create')">{{ t("agenda.newEvent") }}</UiButton>
    </EmptyState>

    <div v-else class="ui-card divide-y divide-line overflow-hidden">
      <section v-for="block in blocks" :key="block.day" class="grid gap-x-4 px-4 py-3 sm:grid-cols-[132px_minmax(0,1fr)]">
        <h4 :class="['pb-1.5 pt-1 text-sm font-semibold sm:pb-0', block.day === today ? 'text-accent-fg' : 'text-fg']">
          {{ label(block.day) }}
          <span v-if="block.day === today || block.day === addDays(today, 1)" class="block text-xs font-normal text-muted">{{ fmt.day(block.day, "medium") }}</span>
        </h4>
        <ul class="flex min-w-0 flex-col gap-0.5">
          <li v-for="entry in block.entries" :key="`${block.day}-${entry.item.id}`">
            <button type="button" class="group flex w-full min-w-0 items-center gap-3 rounded-[9px] px-2 py-1.5 text-left transition-colors hover:bg-highlight" @click="emit('item-click', entry.item)">
              <span class="w-[78px] shrink-0 text-xs tabular-nums text-muted sm:w-[92px]">{{ timeOf(entry.item) }}</span>
              <span class="h-7 w-1 shrink-0 rounded-full" :style="{ background: itemColor(entry.item) }" aria-hidden="true" />
              <span class="min-w-0 flex-1">
                <span class="flex min-w-0 items-center gap-1.5">
                  <span class="line-clamp-2 min-w-0 text-base font-medium text-fg group-hover:text-accent-fg sm:line-clamp-1">{{ entry.item.title }}</span>
                  <Repeat v-if="entry.item.kind === 'agenda.event' && String(entry.item.id).split(':')[1]?.includes('-')" :size="12" class="shrink-0 text-subtle" :aria-label="t('agenda.repeats')" />
                </span>
                <span v-if="entry.item.subtitle" class="block truncate text-xs text-muted">{{ entry.item.subtitle }}</span>
              </span>
              <span v-if="mine.has(String(entry.item.id))" class="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent-fg">{{ t("agenda.invited") }}</span>
            </button>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>
