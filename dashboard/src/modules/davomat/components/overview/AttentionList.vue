<script setup lang="ts">
/**
 * "Needs a look": people past their start who aren't in yet, and those who came late (most minutes
 * first); a KPI tile narrows it to one kind (late, not in yet, on leave). Calm when it's empty.
 */
import { ArrowUpRight, CircleCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useCompanyStore } from "@/stores/company";

import FaceThumb from "./FaceThumb.vue";
import type { BoardRow, FaceTone } from "./overviewApi";

const props = withDefaults(defineProps<{ rows: BoardRow[]; title: string; loading?: boolean; limit?: number; attendanceLink?: string | null }>(), {
  loading: false,
  limit: 7,
  attendanceLink: null,
});

const { t } = useI18n();
const company = useCompanyStore();

function chip(row: BoardRow): { tone: FaceTone; label: string } {
  if (row.state === "late") return { tone: "warning", label: t("davomat.overview.attention.late", { n: row.record?.late_minutes ?? 0 }) };
  if (row.state === "off") return { tone: "info", label: t("davomat.overview.kpi.leave") };
  return { tone: "danger", label: t("davomat.overview.attention.notIn") };
}
const chipClass: Record<FaceTone, string> = {
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
  primary: "bg-accent-soft text-accent-fg",
  neutral: "bg-surface-2 text-muted",
};

const shown = computed(() => props.rows.slice(0, props.limit).map((row) => ({ row, chip: chip(row) })));
const more = computed(() => Math.max(0, props.rows.length - props.limit));
const link = (row: BoardRow) => `/c/${company.currentId}/team/${row.member.id}`;
</script>

<template>
  <section class="rounded-[18px] border border-line bg-surface" :aria-label="title" data-testid="attention">
    <header class="flex items-center justify-between gap-3 border-b border-line px-4 py-3.5 md:px-5">
      <h2 class="text-md font-semibold tracking-[-0.01em] text-fg">{{ title }}</h2>
      <span v-if="rows.length" class="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-muted">{{ rows.length }}</span>
    </header>
    <div v-if="loading && !rows.length" class="flex flex-col gap-3 p-4" aria-hidden="true">
      <div v-for="n in 3" :key="n" class="flex items-center gap-3">
        <SkeletonBlock circle width="34px" height="34px" />
        <span class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="55%" /><SkeletonBlock width="35%" height="10px" /></span>
      </div>
    </div>
    <div v-else-if="!rows.length" class="flex items-center gap-3 px-5 py-6 text-sm text-muted">
      <span class="grid size-9 shrink-0 place-items-center rounded-full bg-success-soft text-success"><CircleCheck :size="18" /></span>
      {{ t("davomat.overview.attention.empty") }}
    </div>
    <ul v-else class="flex flex-col p-1.5">
      <li v-for="item in shown" :key="item.row.member.id">
        <RouterLink :to="link(item.row)" class="pressable flex items-center gap-3 rounded-[12px] px-2.5 py-2 hover:bg-highlight">
          <FaceThumb :src="item.row.member.photo_url" :name="item.row.member.name" :size="34" :tone="item.chip.tone" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-semibold text-fg">{{ item.row.member.name }}</span>
            <span class="block truncate text-xs text-muted">
              <template v-if="item.row.shift">{{ t("davomat.overview.attention.shift", { start: item.row.shift.start, end: item.row.shift.end }) }}</template>
              <template v-if="item.row.shift && item.row.branch"> · </template>
              <template v-if="item.row.branch">{{ item.row.branch.name }}</template>
            </span>
          </span>
          <span :class="['whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold', chipClass[item.chip.tone]]">{{ item.chip.label }}</span>
        </RouterLink>
      </li>
    </ul>
    <footer v-if="more || attendanceLink" class="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5 md:px-5">
      <span class="text-xs text-muted">{{ more ? t("davomat.overview.here.more", { n: more }) : "" }}</span>
      <RouterLink v-if="attendanceLink" :to="attendanceLink" class="inline-flex items-center gap-1 rounded-[8px] px-2 py-1 text-sm font-medium text-muted hover:bg-highlight hover:text-fg">
        {{ t("davomat.overview.attention.all") }}
        <ArrowUpRight :size="15" aria-hidden="true" />
      </RouterLink>
    </footer>
  </section>
</template>
