<script setup lang="ts">
/**
 * One person on the day board: who, their shift, when they came and left, and the trust signals of
 * the check-in (distance from the branch, accuracy, flags). Clicking opens the record (or the
 * person's month when there is no record).
 */
import { CircleAlert, LocateOff, MapPin, Smartphone, Bot, UserPen } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";

import { clockOf, formatDistance, STATE_COLORS } from "../lib";
import type { BoardRow } from "../types";

const props = defineProps<{ row: BoardRow; showBranch?: boolean; /** The board's "now" (ISO), for how late someone not here yet is. */ now?: string | null }>();
defineEmits<{ open: [row: BoardRow] }>();

const { t } = useI18n();
const fmt = useFormat();

const record = computed(() => props.row.record);
const shift = computed(() => props.row.shift);
const units = computed(() => ({ m: t("attendance.unit.m"), km: t("attendance.unit.km") }));
const outside = computed(() => record.value?.flags.includes("outside_geofence") ?? false);
const imprecise = computed(() => record.value?.flags.includes("low_accuracy") ?? false);
const noLocation = computed(() => record.value?.flags.includes("no_location") ?? false);
const unscheduled = computed(() => record.value?.flags.includes("unscheduled") ?? false);

const sourceIcon = computed(() => {
  switch (record.value?.in_source) {
    case "bot":
      return Bot;
    case "manual":
      return UserPen;
    default:
      return Smartphone;
  }
});

/** Minutes past the start for someone whose shift began and who isn't here yet. */
const overdue = computed(() => {
  if (props.row.state !== "not_yet" || props.row.reason !== "late" || !props.now || !shift.value) return 0;
  return Math.max(0, Math.floor((Date.parse(props.now) - Date.parse(shift.value.starts_at)) / 60_000));
});

/** The detail line: what the day looks like for them. */
const detail = computed(() => {
  const row = props.row;
  if (row.state === "off") return t(`attendance.reason.${row.reason ?? "no_shift"}`);
  if (row.state === "not_yet") {
    if (row.reason === "late" && shift.value) return t("attendance.board.notInYet", { time: shift.value.start });
    return shift.value ? t("attendance.board.startsAt", { time: shift.value.start }) : "";
  }
  if (row.state === "absent") return t("attendance.board.noCheckIn");
  if (!record.value?.check_in_at) return "";
  const came = clockOf(record.value.check_in_at);
  const left = clockOf(record.value.check_out_at);
  return left ? t("attendance.board.inOut", { in: came, out: left }) : t("attendance.board.inSince", { time: came });
});
</script>

<template>
  <button
    type="button"
    class="group flex w-full min-w-0 flex-col gap-2 rounded-[10px] border border-line bg-surface p-2.5 text-left transition-[border-color,box-shadow] duration-[120ms] hover:border-line-strong hover:shadow-xs focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--c-ring)]"
    :data-state="row.state"
    @click="$emit('open', row)"
  >
    <div class="flex min-w-0 items-center gap-2.5">
      <span class="relative shrink-0">
        <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="32" />
        <span class="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-surface" :style="{ background: STATE_COLORS[row.state] }" aria-hidden="true" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-semibold text-fg" :title="row.member.name">{{ row.member.name }}</p>
        <p class="truncate text-xs text-muted">
          <!-- The hours first: they matter most and must never be cut off. -->
          <template v-if="shift && row.state !== 'off'"><span class="font-medium tabular-nums text-fg/80">{{ shift.start }}–{{ shift.end }}</span><span v-if="row.member.position || (showBranch && row.branch)"> · </span></template>
          <template v-if="row.member.position">{{ row.member.position.name }}</template>
          <template v-if="showBranch && row.branch"><span v-if="row.member.position"> · </span>{{ row.branch.name }}</template>
        </p>
      </div>
    </div>
    <div v-if="detail || record" class="flex min-w-0 flex-wrap items-center gap-1.5 text-xs">
      <span :class="['min-w-0 truncate tabular-nums', row.state === 'absent' ? 'font-medium text-danger' : row.state === 'late' || overdue ? 'font-medium text-warning' : 'text-muted']">
        <component :is="sourceIcon" v-if="record?.check_in_at" :size="11" class="mr-1 inline -translate-y-px text-subtle" aria-hidden="true" />{{ detail }}
      </span>
      <span v-if="record?.is_late" class="rounded-full bg-warning-soft px-1.5 py-px text-[11px] font-semibold tabular-nums text-warning">+{{ fmt.duration(record.late_minutes) }}</span>
      <span v-else-if="overdue" class="rounded-full bg-warning-soft px-1.5 py-px text-[11px] font-semibold tabular-nums text-warning">+{{ fmt.duration(overdue) }}</span>
      <span class="flex-1" />
      <span
        v-if="record && record.in_distance_m !== null && !noLocation"
        :class="[
          'inline-flex items-center gap-0.5 rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums',
          outside ? 'bg-danger-soft text-danger' : imprecise ? 'bg-warning-soft text-warning' : 'bg-surface-2 text-muted',
        ]"
        :title="record.in_accuracy_m ? t('attendance.board.accuracy', { m: record.in_accuracy_m }) : undefined"
      >
        <MapPin :size="10" aria-hidden="true" />{{ formatDistance(record.in_distance_m, units) }}
      </span>
      <span v-else-if="noLocation" class="inline-flex items-center gap-0.5 rounded-full bg-surface-2 px-1.5 py-px text-[11px] text-muted" :title="t('attendance.flag.no_location')">
        <LocateOff :size="10" aria-hidden="true" />
      </span>
      <span v-if="unscheduled" class="inline-flex items-center gap-0.5 rounded-full bg-info-soft px-1.5 py-px text-[11px] font-medium text-info">
        {{ t("attendance.flag.unscheduledShort") }}
      </span>
      <CircleAlert v-if="record?.flags.includes('auto_closed')" :size="13" class="text-warning" :aria-label="t('attendance.flag.auto_closed')" />
    </div>
  </button>
</template>
