<script setup lang="ts">
/**
 * Package F's `ShiftGrid` (plan §6.3): one week of the roster, people as rows and days as columns,
 * with an "Open shifts" row on top. Shifts are chips you drag to another person or day; templates
 * dragged from the palette make new shifts; a click on an empty day adds one and a click on a chip
 * edits it. Drafts have a dashed edge until the roster is published. Leave and holidays are shaded;
 * each day shows its coverage. Dragging is a pointer convenience: everything is also a click away.
 */
import { CalendarOff, Check, Move, Plus, Repeat2, StickyNote, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import { hours, slotColor } from "../lib";
import type { Roster, RosterMember, Shift, ShiftSource, ShiftTemplate } from "../types";

const props = defineProps<{ roster: Roster; editable: boolean; today: string }>();
const emit = defineEmits<{
  add: [target: { memberId: number | null; date: string }];
  edit: [shift: Shift];
  move: [shift: Shift, target: { memberId: number | null; date: string }];
  place: [template: ShiftTemplate, target: { memberId: number | null; date: string }];
  person: [member: RosterMember];
}>();

const { t } = useI18n();
const fmt = useFormat();

const SOURCE_SLOTS: Record<ShiftSource, number> = { schedule: 3, manual: 1, swap: 6 };
const SHIFT_MIME = "application/x-attendance-shift";
const TEMPLATE_MIME = "application/x-attendance-template";

const byCell = computed(() => {
  const map = new Map<string, Shift[]>();
  for (const shift of props.roster.shifts) {
    const key = `${shift.member_id ?? "open"}|${shift.date}`;
    const list = map.get(key) ?? [];
    list.push(shift);
    map.set(key, list);
  }
  return map;
});
const openCount = computed(() => props.roster.shifts.filter((shift) => shift.status === "open").length);
const shiftsAt = (memberId: number | null, day: string) => byCell.value.get(`${memberId ?? "open"}|${day}`) ?? [];
const leaveOf = (member: RosterMember) => new Set(member.leave);

function chipStyle(shift: Shift): Record<string, string> {
  if (shift.status === "open") return { "--chip": "var(--c-warning)" };
  if (shift.status === "leave") return { "--chip": "var(--c-info)" };
  return { "--chip": slotColor(SOURCE_SLOTS[shift.source]) };
}

// Drag and drop ------------------------------------------------------------------------

const over = ref<string | null>(null);
const dragging = ref<number | null>(null);
const canDrop = (day: string) => props.editable && day >= props.today;

function startShift(event: DragEvent, shift: Shift): void {
  if (!event.dataTransfer) return;
  event.dataTransfer.setData(SHIFT_MIME, String(shift.id));
  event.dataTransfer.effectAllowed = "move";
  dragging.value = shift.id;
}

function startTemplate(event: DragEvent, template: ShiftTemplate): void {
  if (!event.dataTransfer) return;
  event.dataTransfer.setData(TEMPLATE_MIME, String(template.id));
  event.dataTransfer.effectAllowed = "copy";
}

function enter(event: DragEvent, key: string, day: string): void {
  if (!canDrop(day)) return;
  event.preventDefault();
  over.value = key;
}

function drop(event: DragEvent, memberId: number | null, day: string): void {
  over.value = null;
  dragging.value = null;
  if (!canDrop(day) || !event.dataTransfer) return;
  event.preventDefault();
  const shiftId = Number(event.dataTransfer.getData(SHIFT_MIME));
  const templateId = Number(event.dataTransfer.getData(TEMPLATE_MIME));
  if (shiftId) {
    const shift = props.roster.shifts.find((row) => row.id === shiftId);
    if (shift && (shift.member_id !== memberId || shift.date !== day)) emit("move", shift, { memberId, date: day });
  } else if (templateId) {
    const template = props.roster.templates.find((row) => row.id === templateId);
    if (template) emit("place", template, { memberId, date: day });
  }
}

const memberSubtitle = (member: RosterMember) =>
  [member.minutes ? t("attendance.roster.weekHours", { h: hours(member.minutes) }) : t("attendance.roster.noShiftsWeek"), member.schedule?.name ?? member.position?.name].filter(Boolean).join(" · ");
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="att-grid-scroll overflow-auto rounded-[12px] border border-line bg-surface">
      <div class="att-grid min-w-[916px] sm:min-w-[1060px]" role="grid" :aria-label="t('attendance.roster.gridLabel')">
        <!-- Header -->
        <div class="att-cell att-head att-corner flex items-end px-3 pb-2" role="columnheader">
          <span class="inline-flex items-center gap-1.5 text-xs font-semibold text-muted"><Users :size="13" aria-hidden="true" />{{ t("attendance.roster.team", { n: roster.members.length }) }}</span>
        </div>
        <div
          v-for="day in roster.days"
          :key="`h-${day}`"
          role="columnheader"
          :class="['att-cell att-head flex flex-col gap-0.5 px-2 py-2', roster.holidays[day] && 'att-holiday', day === today && 'att-today-head']"
        >
          <span :class="['text-xs font-semibold', day === today ? 'text-primary' : 'text-fg']">{{ fmt.day(day, "weekdayShort") }}</span>
          <span class="truncate text-[11px] text-muted">
            <template v-if="roster.holidays[day]"><CalendarOff :size="11" class="mr-0.5 inline -translate-y-px" />{{ roster.holidays[day] }}</template>
            <template v-else>{{ t("attendance.roster.coverage", { n: roster.coverage[day]?.planned ?? 0, h: hours(roster.coverage[day]?.minutes ?? 0) }) }}</template>
          </span>
          <span v-if="roster.coverage[day]?.open" class="w-fit rounded-full bg-warning-soft px-1.5 text-[10px] font-semibold text-warning">{{ t("attendance.roster.openCount", { n: roster.coverage[day]!.open }) }}</span>
        </div>

        <!-- Open shifts -->
        <template v-if="editable || openCount">
          <div class="att-cell att-side flex items-center gap-2 px-3 py-2" role="rowheader" :title="`${t('attendance.roster.openShifts')} · ${t('attendance.roster.openShiftsHint')}`">
            <span class="grid size-7 shrink-0 place-items-center rounded-full bg-warning-soft text-warning"><Plus :size="14" aria-hidden="true" /></span>
            <div class="min-w-0">
              <p class="truncate text-sm font-semibold text-fg">{{ t("attendance.roster.openShifts") }}</p>
              <p class="truncate text-[11px] text-muted">{{ t("attendance.roster.openShiftsHint") }}</p>
            </div>
          </div>
          <div
            v-for="day in roster.days"
            :key="`open-${day}`"
            role="gridcell"
            :class="['att-cell att-day group/cell', roster.holidays[day] && 'att-holiday', day < today && 'att-past', over === `open|${day}` && 'att-over']"
            @dragover="enter($event, `open|${day}`, day)"
            @dragleave="over = null"
            @drop="drop($event, null, day)"
          >
            <button
              v-for="shift in shiftsAt(null, day)"
              :key="shift.id"
              type="button"
              :draggable="editable && day >= today"
              :class="['att-chip', !shift.published && 'att-draft', dragging === shift.id && 'opacity-40']"
              :style="chipStyle(shift)"
              @dragstart="startShift($event, shift)"
              @dragend="dragging = null"
              @click="emit('edit', shift)"
            >
              <span class="tabular-nums">{{ shift.start }}–{{ shift.end }}</span>
              <span class="att-chip-sub">{{ shift.position?.name ?? t("attendance.roster.anyone") }}</span>
            </button>
            <button v-if="canDrop(day)" type="button" class="att-add" :aria-label="t('attendance.roster.addOpen', { day: fmt.day(day, 'weekdayShort') })" @click="emit('add', { memberId: null, date: day })">
              <Plus :size="14" aria-hidden="true" />
            </button>
          </div>
        </template>

        <!-- People -->
        <template v-for="member in roster.members" :key="member.id">
          <button type="button" class="att-cell att-side flex items-center gap-2 px-3 py-2 text-left hover:bg-highlight" role="rowheader" :title="`${member.name} · ${memberSubtitle(member)}`" @click="emit('person', member)">
            <UserAvatar :name="member.name" :src="member.photo_url" :size="28" />
            <div class="min-w-0">
              <p class="truncate text-sm font-semibold text-fg">{{ member.name }}</p>
              <p class="truncate text-[11px] text-muted">{{ memberSubtitle(member) }}</p>
            </div>
          </button>
          <div
            v-for="day in roster.days"
            :key="`${member.id}-${day}`"
            role="gridcell"
            :class="[
              'att-cell att-day group/cell',
              roster.holidays[day] && 'att-holiday',
              leaveOf(member).has(day) && 'att-leave',
              day < today && 'att-past',
              over === `${member.id}|${day}` && 'att-over',
            ]"
            @dragover="enter($event, `${member.id}|${day}`, day)"
            @dragleave="over = null"
            @drop="drop($event, member.id, day)"
          >
            <button
              v-for="shift in shiftsAt(member.id, day)"
              :key="shift.id"
              type="button"
              :draggable="editable && day >= today && !shift.has_record && shift.status !== 'leave'"
              :class="['att-chip', !shift.published && 'att-draft', dragging === shift.id && 'opacity-40']"
              :style="chipStyle(shift)"
              :title="shift.note || undefined"
              @dragstart="startShift($event, shift)"
              @dragend="dragging = null"
              @click="emit('edit', shift)"
            >
              <template v-if="shift.status === 'leave'">
                <span class="font-semibold">{{ t("attendance.roster.onLeave") }}</span>
              </template>
              <template v-else>
                <!-- The hours stay on one line; in a narrow day the marks give way first. -->
                <span class="flex w-full min-w-0 items-center gap-1 overflow-hidden tabular-nums">
                  <span class="whitespace-nowrap">{{ shift.start }}–{{ shift.end }}</span>
                  <Repeat2 v-if="shift.swap_pending" :size="11" class="shrink-0 text-warning" :aria-label="t('attendance.roster.swapPending')" />
                  <Check v-if="shift.has_record" :size="11" class="shrink-0 text-success" :aria-label="t('attendance.roster.happened')" />
                  <StickyNote v-if="shift.note" :size="10" class="shrink-0 opacity-60" aria-hidden="true" />
                </span>
                <span class="att-chip-sub">
                  <template v-if="!shift.published">{{ t("attendance.roster.draft") }} · </template>
                  <template v-if="shift.branch && shift.branch.id !== member.home_branch?.id">{{ shift.branch.code || shift.branch.name }} · </template>{{ hours(shift.minutes) }} {{ t("attendance.unit.h") }}
                </span>
              </template>
            </button>
            <span v-if="leaveOf(member).has(day) && !shiftsAt(member.id, day).length" class="px-1 text-[11px] font-medium text-info">{{ t("attendance.roster.onLeave") }}</span>
            <button v-else-if="canDrop(day)" type="button" class="att-add" :aria-label="t('attendance.roster.addFor', { name: member.name, day: fmt.day(day, 'weekdayShort') })" @click="emit('add', { memberId: member.id, date: day })">
              <Plus :size="14" aria-hidden="true" />
            </button>
          </div>
        </template>
      </div>
    </div>

    <div v-if="editable && roster.templates.length" class="flex flex-wrap items-center gap-2">
      <span class="text-xs font-medium text-muted">{{ t("attendance.roster.palette") }}</span>
      <span
        v-for="template in roster.templates"
        :key="template.id"
        draggable="true"
        class="inline-flex cursor-grab select-none items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium text-fg shadow-xs active:cursor-grabbing"
        @dragstart="startTemplate($event, template)"
      >
        <span class="size-2 rounded-full" :style="{ background: slotColor(template.color) }" aria-hidden="true" />
        {{ template.name }} <span class="tabular-nums text-muted">{{ template.starts_at }}–{{ template.ends_at }}</span>
      </span>
      <span class="inline-flex items-center gap-1 text-[11px] text-subtle"><Move :size="11" aria-hidden="true" />{{ t("attendance.roster.paletteHint") }}</span>
    </div>
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span class="inline-flex items-center gap-1.5"><span class="att-swatch" :style="{ '--chip': slotColor(3) }" />{{ t("attendance.roster.legendSchedule") }}</span>
      <span class="inline-flex items-center gap-1.5"><span class="att-swatch" :style="{ '--chip': slotColor(1) }" />{{ t("attendance.roster.legendManual") }}</span>
      <span class="inline-flex items-center gap-1.5"><span class="att-swatch" :style="{ '--chip': slotColor(6) }" />{{ t("attendance.roster.legendSwap") }}</span>
      <span class="inline-flex items-center gap-1.5"><span class="att-swatch att-draft" :style="{ '--chip': 'var(--c-muted)' }" />{{ t("attendance.roster.legendDraft") }}</span>
    </div>
  </div>
</template>

<style scoped>
.att-grid {
  display: grid;
  grid-template-columns: 224px repeat(7, minmax(118px, 1fr));
}
.att-grid-scroll {
  max-height: calc(100dvh - 290px);
}
.att-cell {
  border-bottom: 1px solid var(--c-border);
  border-right: 1px solid var(--c-border);
  min-width: 0;
}
.att-head {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--c-surface);
}
.att-corner,
.att-side {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--c-surface);
}
.att-corner {
  z-index: 3;
}
.att-today-head {
  box-shadow: inset 0 -2px 0 var(--c-primary);
}
.att-day {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px;
  min-height: 62px;
  transition: background 120ms var(--ease-out);
}
.att-holiday {
  background: repeating-linear-gradient(135deg, transparent 0 6px, var(--c-surface-2) 6px 7px);
}
.att-leave {
  background: color-mix(in srgb, var(--c-info) 9%, transparent);
}
.att-past {
  background-color: color-mix(in srgb, var(--c-canvas) 55%, transparent);
}
.att-past .att-chip {
  opacity: 0.8;
}
.att-over {
  background: var(--c-accent-soft);
  box-shadow: inset 0 0 0 2px var(--c-primary);
}
.att-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  width: 100%;
  padding: 4px 7px;
  border-radius: 7px;
  border: 1px solid color-mix(in srgb, var(--chip) 38%, transparent);
  border-left: 3px solid var(--chip);
  background: color-mix(in srgb, var(--chip) 12%, var(--c-surface));
  color: var(--c-text);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.25;
  text-align: left;
  cursor: pointer;
  transition:
    transform 120ms var(--ease-out),
    box-shadow 120ms var(--ease-out);
}
.att-chip:hover {
  box-shadow: var(--sh-xs);
  transform: translateY(-1px);
}
.att-chip:focus-visible {
  outline: 2px solid var(--c-ring);
  outline-offset: 1px;
}
.att-chip[draggable="true"] {
  cursor: grab;
}
.att-chip-sub {
  font-size: 10.5px;
  font-weight: 500;
  color: var(--c-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.att-draft {
  border-style: dashed;
  border-left-style: dashed;
  background: var(--c-surface);
}
.att-add {
  display: grid;
  place-items: center;
  height: 24px;
  border-radius: 7px;
  color: var(--c-subtle);
  border: 1px dashed transparent;
  opacity: 0;
  transition: opacity 120ms var(--ease-out);
}
.att-day:hover .att-add,
.att-add:focus-visible {
  opacity: 1;
  border-color: var(--c-border-strong);
}
.att-add:hover {
  color: var(--c-primary);
  background: var(--c-accent-soft);
}
.att-swatch {
  display: inline-block;
  width: 14px;
  height: 10px;
  border-radius: 3px;
  border: 1px solid color-mix(in srgb, var(--chip) 38%, transparent);
  border-left: 3px solid var(--chip);
  background: color-mix(in srgb, var(--chip) 12%, var(--c-surface));
}
@media (hover: none) {
  .att-add {
    opacity: 1;
    border-color: var(--c-border);
  }
}
/* Phones: a narrow name column, so a day or two of the week is visible next to it; the rest
   scrolls sideways with the names pinned. */
@media (max-width: 639.98px) {
  .att-grid {
    grid-template-columns: 132px repeat(7, minmax(112px, 1fr));
  }
  .att-chip {
    padding: 4px 6px;
    font-size: 11px;
  }
}
</style>
