<script setup lang="ts">
/** The next few dates from now, grouped by day: the calendar's side rail and the Overview widget. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { itemColor, itemsByDay, type CalendarItem } from "@/components/calendarItems";
import { addDays, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

const props = withDefaults(defineProps<{ items: CalendarItem[]; days?: number; limit?: number }>(), { days: 7, limit: 8 });
const emit = defineEmits<{ "item-click": [item: CalendarItem] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const blocks = computed(() => {
  const days = Array.from({ length: props.days }, (_, i) => addDays(today.value, i));
  const byDay = itemsByDay(props.items, days, company.timezone);
  const now = Date.now();
  let left = props.limit;
  const out: Array<{ day: string; entries: CalendarItem[] }> = [];
  for (const day of days) {
    if (left <= 0) break;
    const entries = (byDay.get(day) ?? [])
      .map((placed) => placed.item)
      // Today: what's still ahead (all-day items stay).
      .filter((item) => day !== today.value || item.all_day || Date.parse(item.end ?? item.start) >= now)
      .slice(0, left);
    if (entries.length) out.push({ day, entries });
    left -= entries.length;
  }
  return out;
});

function label(day: string): string {
  if (day === today.value) return t("common.today");
  if (day === addDays(today.value, 1)) return t("agenda.tomorrow");
  return fmt.day(day, "weekdayShort");
}

function timeOf(item: CalendarItem): string {
  if (item.all_day || /^\d{4}-\d{2}-\d{2}$/.test(item.start)) return t("common.calendar.allDay");
  return fmt.instant(item.start, "time");
}

defineExpose({ count: computed(() => blocks.value.reduce((sum, block) => sum + block.entries.length, 0)) });
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-for="block in blocks" :key="block.day">
      <p :class="['mb-1 px-2 text-[11px] font-semibold uppercase tracking-[0.06em]', block.day === today ? 'text-accent-fg' : 'text-subtle']">{{ label(block.day) }}</p>
      <button
        v-for="item in block.entries"
        :key="`${block.day}-${item.id}`"
        type="button"
        class="flex w-full min-w-0 items-center gap-2.5 rounded-[9px] px-2 py-1.5 text-left transition-colors hover:bg-highlight"
        @click="emit('item-click', item)"
      >
        <span class="h-6 w-1 shrink-0 rounded-full" :style="{ background: itemColor(item) }" aria-hidden="true" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium text-fg">{{ item.title }}</span>
          <span class="block truncate text-xs text-muted">{{ timeOf(item) }}<template v-if="item.subtitle"> · {{ item.subtitle }}</template></span>
        </span>
      </button>
    </div>
    <slot v-if="!blocks.length" name="empty" />
  </div>
</template>
