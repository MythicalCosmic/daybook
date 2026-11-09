<script setup lang="ts">
/**
 * A person's day on one bar (v8 F bar, "a person's day"): the hours of the day, the shift's window
 * behind, the time at work from check-in to check-out (the late part marked), every scan at its
 * terminal as a tick, and a line at "now" on today. It reads the day's scans (the same query as
 * the scan list beside it) and attendance's board for the shift and the record.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { zonedDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useBoard, type Scan } from "../overview/overviewApi";
import { SCAN_TONES } from "./team";
import { useMemberScans } from "./teamApi";

const props = defineProps<{ memberId: number; day: string }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const now = useNow();

const scansQuery = useMemberScans(() => props.memberId, () => props.day);
const board = useBoard(() => [], () => props.day);
const row = computed(() => board.data.value?.people.find((person) => person.member.id === props.memberId) ?? null);
const scans = computed<Scan[]>(() => [...(scansQuery.data.value?.results ?? [])].sort((a, b) => a.event_at.localeCompare(b.event_at)));
const loading = computed(() => scansQuery.isPending.value || board.isPending.value);

/** Minutes since the company's midnight of `props.day` (its clock, whatever the browser's). */
function minuteOf(iso: string): number {
  const [hours, minutes] = fmt.instant(iso, "time").split(":").map(Number);
  const base = (hours ?? 0) * 60 + (minutes ?? 0);
  const day = zonedDay(iso, company.timezone);
  // A check-out after midnight belongs past the end of this day's bar, an evening before it before.
  if (day > props.day) return base + 24 * 60;
  if (day < props.day) return base - 24 * 60;
  return base;
}

const shift = computed(() => (row.value?.shift ? { from: minuteOf(row.value.shift.starts_at), to: minuteOf(row.value.shift.ends_at) } : null));
const record = computed(() => row.value?.record ?? null);
const span = computed(() => {
  const r = record.value;
  if (!r?.check_in_at) return null;
  const from = minuteOf(r.check_in_at);
  const isToday = props.day === today.value;
  const to = r.check_out_at ? minuteOf(r.check_out_at) : isToday ? Math.max(from, minuteOf(new Date(now.value).toISOString())) : from;
  return { from, to, open: !r.check_out_at };
});
const lateFrom = computed(() => (record.value?.is_late && shift.value && span.value && span.value.from > shift.value.from ? shift.value.from : null));

/** The bar's hours: 06–22, widened to whatever the day had. */
const range = computed(() => {
  const points = [...scans.value.map((scan) => minuteOf(scan.event_at)), shift.value?.from, shift.value?.to, span.value?.from, span.value?.to].filter(
    (value): value is number => typeof value === "number",
  );
  const first = Math.min(6 * 60, ...points);
  const last = Math.max(22 * 60, ...points);
  return { from: Math.floor(first / 60) * 60, to: Math.min(30 * 60, Math.ceil(last / 60) * 60) };
});
const at = (minute: number) => `${((minute - range.value.from) / (range.value.to - range.value.from)) * 100}%`;
const width = (from: number, to: number) => `${(Math.max(0, to - from) / (range.value.to - range.value.from)) * 100}%`;
const hours = computed(() => {
  const list: number[] = [];
  for (let minute = range.value.from; minute <= range.value.to; minute += 180) list.push(minute);
  return list;
});
const label = (minute: number) => String(Math.floor(minute / 60) % 24).padStart(2, "0");

const nowMinute = computed(() => (props.day === today.value ? minuteOf(new Date(now.value).toISOString()) : null));

const tickTone: Record<string, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  primary: "bg-primary",
  neutral: "bg-subtle",
};
function toneOf(scan: Scan): string {
  if (scan.action === "checked_in" && scan.record?.is_late) return "warning";
  return SCAN_TONES[scan.action] ?? "neutral";
}

const summary = computed(() => {
  const r = record.value;
  if (!r?.check_in_at) return scans.value.length ? "" : t("davomat.employee.timeline.none");
  const came = fmt.instant(r.check_in_at, "time");
  if (!r.check_out_at) return t("davomat.employee.timeline.stillIn", { in: came });
  return t("davomat.employee.timeline.summary", { in: came, out: fmt.instant(r.check_out_at, "time"), worked: fmt.duration(r.worked_minutes) });
});

</script>

<template>
  <section class="ui-card p-4 md:p-5" :aria-label="t('davomat.employee.timeline.title')" data-testid="day-timeline">
    <header class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h2 class="text-md font-semibold tracking-[-0.01em] text-fg">{{ t("davomat.employee.timeline.title") }}</h2>
      <p class="text-sm tabular-nums text-muted">{{ summary }}</p>
      <ul class="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted" aria-hidden="true">
        <li class="flex items-center gap-1.5"><span class="shift-swatch h-2.5 w-4 rounded-[3px]" />{{ t("davomat.employee.timeline.shift") }}</li>
        <li class="flex items-center gap-1.5"><span class="h-2.5 w-4 rounded-[3px] bg-success/70" />{{ t("davomat.employee.timeline.atWork") }}</li>
        <li class="flex items-center gap-1.5"><span class="h-2.5 w-4 rounded-[3px] bg-warning/70" />{{ t("davomat.employee.timeline.late") }}</li>
      </ul>
    </header>

    <SkeletonBlock v-if="loading" class="mt-5" height="44px" radius="10px" />
    <div v-else class="mt-5">
      <div class="relative h-11 rounded-[10px] bg-surface-2">
        <!-- Hour lines -->
        <span v-for="minute in hours" :key="minute" class="absolute inset-y-0 w-px bg-line" :style="{ left: at(minute) }" aria-hidden="true" />
        <!-- The shift's window -->
        <span v-if="shift" class="shift-swatch absolute inset-y-1.5 rounded-[7px]" :style="{ left: at(shift.from), width: width(shift.from, shift.to) }" :title="`${row?.shift?.start}–${row?.shift?.end}`" />
        <!-- Late: from the shift's start to the check-in -->
        <span v-if="lateFrom !== null && span" class="absolute inset-y-3 rounded-l-[6px] bg-warning/70" :style="{ left: at(lateFrom), width: width(lateFrom, span.from) }" />
        <!-- At work -->
        <span
          v-if="span"
          :class="['absolute inset-y-3 bg-success/70', lateFrom !== null ? 'rounded-r-[6px]' : 'rounded-[6px]', span.open && 'open-end']"
          :style="{ left: at(span.from), width: width(span.from, span.to) }"
        />
        <!-- Each scan -->
        <span
          v-for="scan in scans"
          :key="scan.id"
          :class="['absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-[var(--c-surface)]', tickTone[toneOf(scan)]]"
          :style="{ left: at(minuteOf(scan.event_at)) }"
          :title="`${fmt.instant(scan.event_at, 'time')} · ${scan.device.name}`"
          data-tick
        />
        <!-- Now -->
        <span v-if="nowMinute !== null && nowMinute >= range.from && nowMinute <= range.to" class="absolute -inset-y-1.5 w-0.5 rounded-full bg-primary" :style="{ left: at(nowMinute) }" :title="t('davomat.employee.timeline.now')" />
      </div>
      <div class="relative mt-1.5 h-4 text-[11px] tabular-nums text-subtle" aria-hidden="true">
        <span v-for="minute in hours" :key="minute" class="absolute -translate-x-1/2" :style="{ left: at(minute) }">{{ label(minute) }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.shift-swatch {
  background: repeating-linear-gradient(-45deg, color-mix(in srgb, var(--c-primary) 16%, transparent) 0 5px, color-mix(in srgb, var(--c-primary) 7%, transparent) 5px 10px);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--c-primary) 28%, transparent);
}
.open-end {
  mask-image: linear-gradient(90deg, #000 85%, transparent);
}
</style>
