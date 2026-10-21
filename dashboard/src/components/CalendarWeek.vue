<script setup lang="ts">
/**
 * A week of timed items (company calendar, shifts, meetings): seven day columns from `startHour` to
 * `endHour`, all-day items on top, overlapping items side by side, a line at the current time.
 * Clicking empty time emits `slot-click` with the day and the half hour.
 *
 *   <CalendarWeek v-model:week="monday" :items="items" @item-click="open" @slot-click="({ day, time }) => create(day, time)" />
 */
import { ChevronLeft, ChevronRight } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { addDays, formatDay, formatRange, startOfWeek, todayIn, zonedNow } from "@/lib/dates";
import { fromMinutes } from "@/lib/time";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore } from "@/stores/company";

import { isWeekend } from "./calendar";
import { itemColor, itemsByDay, layoutTimed, type CalendarItem } from "./calendarItems";
import UiButton from "./UiButton.vue";

const week = defineModel<string>("week", { required: true });

const props = withDefaults(defineProps<{ items: CalendarItem[]; startHour?: number; endHour?: number; hourHeight?: number; holidays?: Record<string, string> }>(), {
  startHour: 7,
  endHour: 22,
  hourHeight: 48,
  holidays: () => ({}),
});

const emit = defineEmits<{ "item-click": [item: CalendarItem]; "slot-click": [slot: { day: string; time: string }] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const now = useNow();
const scroller = ref<HTMLElement | null>(null);

const monday = computed(() => startOfWeek(week.value));
const days = computed(() => Array.from({ length: 7 }, (_, i) => addDays(monday.value, i)));
const today = computed(() => todayIn(company.timezone, now.value));
const hours = computed(() => Array.from({ length: props.endHour - props.startHour }, (_, i) => props.startHour + i));
const placed = computed(() => itemsByDay(props.items, days.value, company.timezone));

function isAllDay(item: CalendarItem): boolean {
  return !!item.all_day || /^\d{4}-\d{2}-\d{2}$/.test(item.start);
}

function minutesIn(iso: string, day: string): number {
  const zoned = zonedNow(company.timezone, new Date(iso));
  const local = `${zoned.getFullYear()}-${String(zoned.getMonth() + 1).padStart(2, "0")}-${String(zoned.getDate()).padStart(2, "0")}`;
  if (local < day) return 0;
  if (local > day) return 24 * 60;
  return zoned.getHours() * 60 + zoned.getMinutes();
}

const allDay = computed(() => days.value.map((day) => (placed.value.get(day) ?? []).filter((entry) => isAllDay(entry.item))));
const timed = computed(() =>
  days.value.map((day) =>
    layoutTimed(
      (placed.value.get(day) ?? [])
        .filter((entry) => !isAllDay(entry.item))
        .map((entry) => ({ item: entry.item, start: minutesIn(entry.item.start, day), end: entry.item.end ? minutesIn(entry.item.end, day) : minutesIn(entry.item.start, day) + 60 })),
    ),
  ),
);

const top = (minutes: number) => ((minutes - props.startHour * 60) / 60) * props.hourHeight;
const nowMinutes = computed(() => {
  const zoned = zonedNow(company.timezone, now.value);
  return zoned.getHours() * 60 + zoned.getMinutes();
});

function onColumnClick(event: MouseEvent, day: string): void {
  const target = event.currentTarget as HTMLElement;
  const y = event.clientY - target.getBoundingClientRect().top;
  const minutes = props.startHour * 60 + Math.floor(((y / props.hourHeight) * 60) / 30) * 30;
  emit("slot-click", { day, time: fromMinutes(minutes) });
}

onMounted(() => {
  // Open on the working morning (or now), not at the top of the grid.
  const focus = days.value.includes(today.value) ? Math.max(props.startHour * 60, nowMinutes.value - 90) : 9 * 60;
  if (scroller.value) scroller.value.scrollTop = Math.max(0, top(focus));
});

const columns = "grid-cols-[52px_repeat(7,minmax(112px,1fr))]";
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 flex-1 text-md font-semibold text-fg" aria-live="polite">{{ formatRange({ from: days[0]!, to: days[6]! }, fmt.lang.value) }}</h3>
      <div class="flex items-center gap-1">
        <UiButton size="sm" variant="secondary" @click="week = startOfWeek(today)">{{ t("common.today") }}</UiButton>
        <button type="button" class="pressable grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('common.calendar.prevWeek')" @click="week = addDays(monday, -7)">
          <ChevronLeft :size="16" />
        </button>
        <button type="button" class="pressable grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('common.calendar.nextWeek')" @click="week = addDays(monday, 7)">
          <ChevronRight :size="16" />
        </button>
      </div>
    </div>

    <div class="ui-card overflow-hidden">
      <div ref="scroller" class="max-h-[640px] overflow-auto overscroll-contain">
        <div class="min-w-[836px]">
          <!-- Day headers and all-day items -->
          <div :class="['sticky top-0 z-[3] grid border-b border-line bg-surface', columns]">
            <span class="border-r border-line" />
            <div v-for="(day, index) in days" :key="day" :class="['min-w-0 border-r border-line px-2 py-1.5 last:border-r-0', isWeekend(day) && 'bg-surface-2/40']">
              <p :class="['flex items-baseline gap-1.5 text-xs font-semibold', day === today ? 'text-primary' : 'text-muted']">
                {{ t(`common.weekday.short.${index}`) }}
                <span :class="['grid h-6 min-w-6 place-items-center rounded-full px-1 text-sm tabular-nums', day === today ? 'bg-primary text-on-primary' : 'text-fg']">{{ Number(day.slice(8)) }}</span>
              </p>
              <p v-if="holidays[day]" class="truncate text-[10px] font-semibold text-danger/80">{{ holidays[day] }}</p>
              <div class="mt-1 flex flex-col gap-0.5">
                <button
                  v-for="entry in allDay[index]"
                  :key="String(entry.item.id)"
                  type="button"
                  class="h-5 truncate rounded-[5px] px-1.5 text-left text-[11px] font-semibold text-fg"
                  :style="{ background: `color-mix(in srgb, ${itemColor(entry.item)} 18%, var(--c-surface))` }"
                  :title="entry.item.title"
                  @click="emit('item-click', entry.item)"
                >
                  {{ entry.item.title }}
                </button>
              </div>
            </div>
          </div>

          <!-- Time grid -->
          <div :class="['relative grid', columns]">
            <div class="border-r border-line">
              <!-- Each label sits on its hour line; the first goes just below it, where the sticky day headers can't cover it. -->
              <div v-for="(hour, index) in hours" :key="hour" class="relative pr-2 text-right" :style="{ height: `${hourHeight}px` }">
                <span :class="['absolute right-2 text-[10px] font-medium tabular-nums text-subtle', index === 0 ? 'top-0.5' : '-top-2']" data-hour-label>{{ String(hour).padStart(2, "0") }}:00</span>
              </div>
            </div>
            <div
              v-for="(day, index) in days"
              :key="day"
              :class="['relative cursor-cell border-r border-line last:border-r-0', isWeekend(day) && 'bg-surface-2/30', holidays[day] && 'bg-danger-soft/25']"
              :aria-label="formatDay(day, fmt.lang.value, 'weekday')"
              @click="onColumnClick($event, day)"
            >
              <div v-for="hour in hours" :key="hour" class="border-b border-line/70" :style="{ height: `${hourHeight}px` }">
                <div class="h-1/2 border-b border-dashed border-line/50" />
              </div>
              <button
                v-for="box in timed[index]"
                :key="String(box.item.id)"
                type="button"
                class="absolute z-[1] overflow-hidden rounded-[7px] px-1.5 py-1 text-left text-xs shadow-xs ring-1 ring-[var(--c-surface)] transition-[filter] hover:brightness-95 dark:hover:brightness-125"
                :style="{
                  top: `${Math.max(0, top(box.start))}px`,
                  height: `${Math.max(20, top(box.end) - Math.max(0, top(box.start)) - 2)}px`,
                  left: `calc(${(box.column / box.columns) * 100}% + 2px)`,
                  width: `calc(${100 / box.columns}% - 4px)`,
                  background: `color-mix(in srgb, ${itemColor(box.item)} 18%, var(--c-surface))`,
                  boxShadow: `inset 3px 0 0 ${itemColor(box.item)}`,
                }"
                :title="box.item.title"
                @click.stop="emit('item-click', box.item)"
              >
                <p class="truncate pl-1 font-semibold text-fg">{{ box.item.title }}</p>
                <p class="truncate pl-1 tabular-nums text-muted">{{ fromMinutes(box.start) }}–{{ fromMinutes(Math.min(box.end, 1439)) }}<template v-if="box.item.subtitle"> · {{ box.item.subtitle }}</template></p>
              </button>
              <div
                v-if="day === today && nowMinutes >= startHour * 60 && nowMinutes <= endHour * 60"
                class="pointer-events-none absolute inset-x-0 z-[2] h-0.5 bg-danger"
                :style="{ top: `${top(nowMinutes)}px` }"
                aria-hidden="true"
              >
                <span class="absolute -left-1 -top-[3px] size-2 rounded-full bg-danger" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
