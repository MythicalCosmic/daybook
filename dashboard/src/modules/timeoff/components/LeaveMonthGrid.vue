<script setup lang="ts">
/**
 * The time-off month (plan §6.2 "Month Gantt calendar with leave bars and holidays"): people as
 * rows, the month's days as columns, a bar per stretch of time off (approved, waiting, recorded by
 * a manager), holidays and days off shaded, today marked. Names stay put while the days scroll
 * sideways on small screens. A bar opens its request.
 */
import { useResizeObserver } from "@vueuse/core";
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { addDays, diffDays, parseDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";

import type { CalendarItem, CalendarMonth } from "../types";

const props = defineProps<{ month: CalendarMonth; activeId?: number | null }>();
const emit = defineEmits<{ open: [id: number]; person: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();

const days = computed(() => {
  const out: Array<{ day: string; number: number; weekday: number; off: boolean; holiday: string | null; today: boolean }> = [];
  const holidays = new Map(props.month.holidays.map((h) => [h.date, h.name]));
  const total = diffDays(props.month.from, props.month.to) + 1;
  for (let i = 0; i < total; i++) {
    const day = addDays(props.month.from, i);
    const js = parseDay(day).getUTCDay();
    const weekday = (js + 6) % 7; // Monday = 0, like Company.workdays
    out.push({ day, number: i + 1, weekday, off: !props.month.workdays.includes(weekday), holiday: holidays.get(day) ?? null, today: day === props.month.today });
  }
  return out;
});
const count = computed(() => days.value.length);
const todayIndex = computed(() => days.value.findIndex((d) => d.today));

// When the month does not fit, start scrolled so today sits near the left edge of the days.
const wrap = ref<HTMLElement | null>(null);
function scrollToToday() {
  const el = wrap.value;
  if (!el || el.scrollWidth <= el.clientWidth) return;
  const name = el.querySelector<HTMLElement>(".name")?.offsetWidth ?? 0;
  const dayWidth = (el.scrollWidth - name) / count.value;
  const target = todayIndex.value > 2 ? (todayIndex.value - 2) * dayWidth : 0;
  // Late in the month the days run out before today reaches the left edge: stop on a whole day
  // rather than at the very end, which would leave the first visible day cut in half.
  el.scrollLeft = Math.min(target, Math.floor((el.scrollWidth - el.clientWidth) / dayWidth) * dayWidth);
}
onMounted(scrollToToday);
// The days stretch with the card (the waiting list beside it arrives later), which would leave the
// first visible day cut in half: start again on a whole day when the width changes.
let lastWidth = 0;
useResizeObserver(wrap, (entries) => {
  const width = Math.round(entries[0]?.contentRect.width ?? 0);
  if (width && width !== lastWidth) {
    lastWidth = width;
    scrollToToday();
  }
});
watch(
  () => props.month.from,
  () => void nextTick(scrollToToday),
);

function bar(item: CalendarItem) {
  const start = Math.max(0, diffDays(props.month.from, item.first_day));
  const end = Math.min(count.value - 1, diffDays(props.month.from, item.last_day));
  return {
    left: `calc(${(start / count.value) * 100}% + 2px)`,
    width: `calc(${((end - start + 1) / count.value) * 100}% - 4px)`,
    clippedStart: item.first_day < props.month.from,
    clippedEnd: item.last_day > props.month.to,
    narrow: end - start < 2,
  };
}

function tone(item: CalendarItem): "approved" | "pending" | "recorded" {
  if (item.status === "pending") return "pending";
  return item.recorded ? "recorded" : "approved";
}

function label(item: CalendarItem): string {
  return item.reason || t("timeoff.days", { n: item.days }, item.days);
}

function tip(item: CalendarItem, name: string): string {
  const range = item.first_day === item.last_day ? fmt.day(item.first_day, "medium") : fmt.range({ from: item.first_day, to: item.last_day });
  const status = t(`timeoff.status.${tone(item)}`);
  return [name, range, status, item.reason].filter(Boolean).join(" · ");
}

</script>

<template>
  <div ref="wrap" class="grid-wrap ui-card overflow-x-auto" :style="{ '--days': count }">
    <div class="board" role="grid" :aria-rowcount="month.rows.length + 1" :aria-label="t('timeoff.calendar.label', { month: fmt.day(month.from, 'monthYear') })">
      <!-- Header -->
      <div class="row head" role="row">
        <div class="name sticky left-0 z-20 flex items-end border-b border-r border-line bg-surface px-4 pb-2 text-xs font-semibold uppercase tracking-[0.05em] text-subtle" role="columnheader">
          {{ t("timeoff.calendar.person") }}
        </div>
        <div class="track border-b border-line" role="presentation">
          <div class="cells">
            <UiTooltip v-for="d in days" :key="d.day" :content="d.holiday ?? undefined" :disabled="!d.holiday">
              <div
                role="columnheader"
                :aria-label="fmt.day(d.day, 'weekday')"
                :class="['flex flex-col items-center justify-end gap-0.5 pb-1.5 pt-2', (d.off || d.holiday) && 'shade', d.holiday && 'holiday']"
              >
                <span :class="['text-[10px] font-medium uppercase', d.off || d.holiday ? 'text-subtle' : 'text-muted']">{{ t(`common.weekday.min.${d.weekday}`) }}</span>
                <span
                  :class="[
                    'grid size-6 place-items-center rounded-full text-xs font-semibold tabular-nums',
                    d.today ? 'bg-primary text-on-primary' : d.holiday ? 'text-warning' : d.off ? 'text-subtle' : 'text-fg',
                  ]"
                  >{{ d.number }}</span
                >
              </div>
            </UiTooltip>
          </div>
        </div>
      </div>

      <!-- People -->
      <div v-for="row in month.rows" :key="row.member.id" class="row body" role="row">
        <button
          type="button"
          class="name sticky left-0 z-10 flex min-w-0 items-center gap-2.5 border-b border-r border-line bg-surface px-4 text-left hover:bg-[color-mix(in_srgb,var(--c-text)_4%,var(--c-surface))]"
          role="rowheader"
          :title="[row.member.name, row.position, row.home_branch?.name].filter(Boolean).join(' · ')"
          @click="emit('person', row.member.id)"
        >
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="26" />
          <span class="min-w-0 leading-tight">
            <span class="block truncate text-sm font-medium text-fg">{{ row.member.name }}</span>
            <span class="block truncate text-[11px] text-muted">{{ [row.position, row.home_branch?.name].filter(Boolean).join(" · ") || "—" }}</span>
          </span>
        </button>
        <div class="track relative border-b border-line" role="gridcell">
          <div class="cells" aria-hidden="true">
            <div v-for="d in days" :key="d.day" :class="[(d.off || d.holiday) && 'shade', d.holiday && 'holiday']" />
          </div>
          <span v-if="todayIndex >= 0" class="today-line" :style="{ left: `calc(${((todayIndex + 0.5) / count) * 100}% - 1px)` }" aria-hidden="true" />
          <UiTooltip v-for="item in row.items" :key="item.id" :content="tip(item, row.member.name)">
            <button
              type="button"
              :class="['leave', `is-${tone(item)}`, bar(item).clippedStart && 'clip-start', bar(item).clippedEnd && 'clip-end', activeId === item.id && 'is-active']"
              :style="{ left: bar(item).left, width: bar(item).width }"
              :aria-label="tip(item, row.member.name)"
              @click="emit('open', item.id)"
            >
              <span v-if="!bar(item).narrow" class="truncate">{{ label(item) }}</span>
            </button>
          </UiTooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grid-wrap {
  --name-w: 228px;
  --day-w: 34px;
}
.board {
  min-width: calc(var(--name-w) + var(--days) * var(--day-w));
}
.row {
  display: grid;
  grid-template-columns: var(--name-w) minmax(0, 1fr);
}
.row.body {
  height: 48px;
}
.row.head {
  position: sticky;
  top: 0;
  z-index: 15;
  background: var(--c-surface);
}
.row.body:last-child > * {
  border-bottom: 0;
}
.cells {
  display: grid;
  grid-template-columns: repeat(var(--days), minmax(0, 1fr));
  height: 100%;
}
.cells > * {
  border-right: 1px solid color-mix(in srgb, var(--c-border) 55%, transparent);
}
.cells > *:last-child {
  border-right: 0;
}
.shade {
  background: color-mix(in srgb, var(--c-text) 3.5%, transparent);
}
.holiday {
  background: repeating-linear-gradient(
    -45deg,
    color-mix(in srgb, var(--c-warning) 9%, transparent) 0 5px,
    transparent 5px 10px
  );
}
.today-line {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--c-primary) 55%, transparent);
  pointer-events: none;
}
.leave {
  position: absolute;
  top: 9px;
  bottom: 9px;
  display: flex;
  align-items: center;
  min-width: 0;
  padding: 0 8px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  text-align: left;
  transition:
    transform var(--dur-press) var(--ease-standard),
    box-shadow var(--dur-press) var(--ease-standard);
}
.leave:hover,
.leave:focus-visible,
.leave.is-active {
  transform: translateY(-1px);
  box-shadow: var(--sh-raised);
  outline: none;
}
.leave.is-active {
  box-shadow: 0 0 0 2px var(--c-surface), 0 0 0 4px var(--c-primary);
}
.leave.is-approved {
  background: color-mix(in srgb, var(--c-success) 16%, var(--c-surface));
  border-color: color-mix(in srgb, var(--c-success) 38%, transparent);
  color: var(--c-success);
}
.leave.is-recorded {
  background: color-mix(in srgb, var(--c-info) 16%, var(--c-surface));
  border-color: color-mix(in srgb, var(--c-info) 38%, transparent);
  color: var(--c-info);
}
.leave.is-pending {
  background: color-mix(in srgb, var(--c-warning) 10%, var(--c-surface));
  border: 1px dashed color-mix(in srgb, var(--c-warning) 65%, transparent);
  color: var(--c-warning);
}
.leave.clip-start {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}
.leave.clip-end {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}
@media (max-width: 767.98px) {
  .grid-wrap {
    --name-w: 156px;
    --day-w: 32px;
  }
}
</style>
