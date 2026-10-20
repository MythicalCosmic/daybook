<script setup lang="ts">
/**
 * A month of items (company calendar, tasks by due date, finance calendar, briefings archive):
 * Monday-first weeks, today marked, holidays shaded, up to `maxPerDay` chips a day and "+N more".
 * Arrow keys move between days. On phones days show dots and the chosen day's items list below.
 *
 *   <CalendarMonth v-model:month="month" v-model:selected="day" :items="items" :holidays="holidays" @item-click="open" />
 */
import { ChevronLeft, ChevronRight } from "@lucide/vue";
import { computed, nextTick, ref } from "vue";
import { useI18n } from "vue-i18n";

import { formatDay, todayIn } from "@/lib/dates";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { isWeekend, keyTarget, monthOf, monthWeeks, shiftMonth, type Month } from "./calendar";
import { itemColor, itemsByDay, type CalendarItem } from "./calendarItems";
import UiButton from "./UiButton.vue";
import UiPopover from "./UiPopover.vue";

const month = defineModel<Month>("month", { required: true });
const selected = defineModel<string | null>("selected", { default: null });

const props = withDefaults(defineProps<{ items: CalendarItem[]; holidays?: Record<string, string>; maxPerDay?: number; loading?: boolean }>(), {
  holidays: () => ({}),
  maxPerDay: 3,
  loading: false,
});

const emit = defineEmits<{ "item-click": [item: CalendarItem]; "day-click": [day: string] }>();
defineSlots<{ toolbar?: () => unknown; item?: (props: { item: CalendarItem }) => unknown }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();
const grid = ref<HTMLElement | null>(null);

const today = computed(() => todayIn(company.timezone));
const weeks = computed(() => monthWeeks(month.value));
const days = computed(() => weeks.value.flat());
const placed = computed(() => itemsByDay(props.items, days.value, company.timezone));
const focusDay = ref<string | null>(null);
const tabStop = computed(() => {
  const candidates = [focusDay.value, selected.value, today.value].filter((d): d is string => !!d && monthOf(d) === month.value);
  return candidates[0] ?? `${month.value}-01`;
});

function pick(day: string): void {
  selected.value = day;
  emit("day-click", day);
}

async function onKeydown(event: KeyboardEvent, day: string): Promise<void> {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    pick(day);
    return;
  }
  const target = keyTarget(day, event.key, event.shiftKey);
  if (!target) return;
  event.preventDefault();
  focusDay.value = target;
  if (monthOf(target) !== month.value) month.value = monthOf(target);
  await nextTick();
  grid.value?.querySelector<HTMLElement>(`[data-day="${target}"]`)?.focus();
}

const selectedItems = computed(() => (selected.value ? (itemsByDay(props.items, [selected.value], company.timezone).get(selected.value) ?? []) : []));

function timeOf(item: CalendarItem): string | null {
  return item.all_day || /^\d{4}-\d{2}-\d{2}$/.test(item.start) ? null : fmt.instant(item.start, "time");
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 flex-1 text-md font-semibold text-fg" aria-live="polite">{{ formatDay(`${month}-01`, fmt.lang.value, "monthYear") }}</h3>
      <slot name="toolbar" />
      <div class="flex items-center gap-1">
        <UiButton size="sm" variant="secondary" @click="month = monthOf(today); selected = today">{{ t("common.today") }}</UiButton>
        <button type="button" class="pressable grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('common.date.prevMonth')" @click="month = shiftMonth(month, -1)">
          <ChevronLeft :size="16" />
        </button>
        <button type="button" class="pressable grid size-7 place-items-center rounded-[7px] text-muted hover:bg-highlight hover:text-fg" :aria-label="t('common.date.nextMonth')" @click="month = shiftMonth(month, 1)">
          <ChevronRight :size="16" />
        </button>
      </div>
    </div>

    <div class="ui-card overflow-hidden" :aria-busy="loading || undefined">
      <div class="grid grid-cols-7 border-b border-line bg-surface-2/60 dark:bg-surface-2" aria-hidden="true">
        <span v-for="n in 7" :key="n" class="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-subtle">
          {{ t(isPhone ? `common.weekday.min.${n - 1}` : `common.weekday.short.${n - 1}`) }}
        </span>
      </div>
      <div ref="grid" role="grid" :aria-label="formatDay(`${month}-01`, fmt.lang.value, 'monthYear')" :class="['grid grid-cols-7', loading && 'opacity-60 transition-opacity']">
        <template v-for="(week, w) in weeks" :key="w">
          <div
            v-for="day in week"
            :key="day"
            role="gridcell"
            :aria-selected="day === selected"
            :class="[
              'group relative flex min-w-0 flex-col border-b border-r border-line [&:nth-child(7n)]:border-r-0',
              isPhone ? 'min-h-[52px]' : 'min-h-[112px]',
              monthOf(day) !== month && 'bg-canvas/60',
              (holidays[day] || isWeekend(day)) && monthOf(day) === month && 'bg-surface-2/35 dark:bg-surface-2/40',
              day === selected && 'bg-accent-soft/50',
              w === weeks.length - 1 && 'border-b-0',
            ]"
          >
            <button
              type="button"
              :data-day="day"
              :tabindex="day === tabStop ? 0 : -1"
              :aria-label="formatDay(day, fmt.lang.value, 'long') + (holidays[day] ? ` · ${holidays[day]}` : '')"
              :aria-current="day === today ? 'date' : undefined"
              class="absolute inset-0 z-0 outline-offset-[-2px]"
              @click="pick(day)"
              @focus="focusDay = day"
              @keydown="onKeydown($event, day)"
            />
            <div class="pointer-events-none relative z-[1] flex items-center gap-1 px-1.5 pt-1.5">
              <span
                :class="[
                  'grid h-6 min-w-6 place-items-center rounded-full px-1 text-xs font-semibold tabular-nums',
                  day === today ? 'bg-primary text-on-primary' : monthOf(day) === month ? 'text-fg' : 'text-subtle',
                ]"
                >{{ Number(day.slice(8)) }}</span
              >
              <span v-if="holidays[day] && !isPhone" class="min-w-0 truncate text-[10px] font-semibold text-danger/80">{{ holidays[day] }}</span>
            </div>

            <!-- Phones: dots -->
            <div v-if="isPhone" class="pointer-events-none relative z-[1] flex flex-wrap justify-center gap-0.5 px-1 pb-1.5 pt-1">
              <span v-for="entry in (placed.get(day) ?? []).slice(0, 4)" :key="String(entry.item.id)" class="size-1.5 rounded-full" :style="{ background: itemColor(entry.item) }" />
            </div>
            <!-- Desktop: chips -->
            <div v-else class="relative z-[1] flex min-w-0 flex-col gap-0.5 px-1 pb-1.5 pt-1">
              <button
                v-for="entry in (placed.get(day) ?? []).slice(0, maxPerDay)"
                :key="String(entry.item.id)"
                type="button"
                :class="[
                  'flex h-[22px] min-w-0 items-center gap-1.5 px-1.5 text-left text-xs font-medium text-fg transition-[filter] hover:brightness-95 dark:hover:brightness-125',
                  entry.fromBefore ? '-ml-1 rounded-l-none pl-2' : 'rounded-l-[6px]',
                  entry.toAfter ? '-mr-1 rounded-r-none' : 'rounded-r-[6px]',
                ]"
                :style="{ background: `color-mix(in srgb, ${itemColor(entry.item)} 16%, var(--c-surface))`, boxShadow: entry.fromBefore ? undefined : `inset 2px 0 0 ${itemColor(entry.item)}` }"
                :title="entry.item.title"
                @click.stop="emit('item-click', entry.item)"
              >
                <slot name="item" :item="entry.item">
                  <span v-if="timeOf(entry.item) && !entry.fromBefore" class="shrink-0 tabular-nums text-muted">{{ timeOf(entry.item) }}</span>
                  <span class="truncate">{{ entry.fromBefore ? "" : entry.item.title }}</span>
                </slot>
              </button>
              <UiPopover v-if="(placed.get(day) ?? []).length > maxPerDay" width="260px">
                <template #trigger>
                  <button type="button" class="h-5 rounded-[5px] px-1.5 text-left text-[11px] font-semibold text-muted hover:bg-highlight hover:text-fg">
                    {{ t("common.moreCount", { n: (placed.get(day) ?? []).length - maxPerDay }) }}
                  </button>
                </template>
                <p class="mb-2 text-sm font-semibold text-fg">{{ formatDay(day, fmt.lang.value, "weekday") }}</p>
                <div class="flex flex-col gap-1">
                  <button
                    v-for="entry in placed.get(day) ?? []"
                    :key="String(entry.item.id)"
                    type="button"
                    class="flex items-center gap-2 rounded-[7px] px-2 py-1.5 text-left text-sm hover:bg-highlight"
                    @click="emit('item-click', entry.item)"
                  >
                    <span class="size-2 shrink-0 rounded-full" :style="{ background: itemColor(entry.item) }" />
                    <span class="min-w-0 flex-1 truncate">{{ entry.item.title }}</span>
                    <span v-if="timeOf(entry.item)" class="shrink-0 text-xs tabular-nums text-muted">{{ timeOf(entry.item) }}</span>
                  </button>
                </div>
              </UiPopover>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Phones: the chosen day's agenda -->
    <div v-if="isPhone && selected" class="ui-card p-3">
      <p class="mb-2 text-sm font-semibold text-fg">{{ formatDay(selected, fmt.lang.value, "weekday") }}<span v-if="holidays[selected]" class="text-danger"> · {{ holidays[selected] }}</span></p>
      <p v-if="!selectedItems.length" class="py-3 text-center text-sm text-muted">{{ t("common.calendar.empty") }}</p>
      <button
        v-for="entry in selectedItems"
        :key="String(entry.item.id)"
        type="button"
        class="flex w-full items-center gap-3 rounded-[8px] px-2 py-2 text-left hover:bg-highlight"
        @click="emit('item-click', entry.item)"
      >
        <span class="h-8 w-1 shrink-0 rounded-full" :style="{ background: itemColor(entry.item) }" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-base font-medium text-fg">{{ entry.item.title }}</span>
          <span v-if="entry.item.subtitle" class="block truncate text-xs text-muted">{{ entry.item.subtitle }}</span>
        </span>
        <span class="shrink-0 text-xs tabular-nums text-muted">{{ timeOf(entry.item) ?? t("common.calendar.allDay") }}</span>
      </button>
    </div>
  </div>
</template>
