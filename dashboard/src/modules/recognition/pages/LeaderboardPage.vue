<script setup lang="ts">
/**
 * The leaderboard (PLAN-LEARNING §7.6, §11): points this week, this month or all time (any past
 * week or month with the arrows), all points or learning only, for every branch the viewer sees
 * or one. The top three on a podium, everyone in the table with their level, badges and streak;
 * a row opens the person's points and badges. Export: Excel/CSV from the server or this page.
 */
import { ChevronLeft, ChevronRight, Trophy } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import type { TableColumn } from "@/components/table";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteStates } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useLeaderboard } from "../api";
import PersonDrawer from "../components/PersonDrawer.vue";
import Podium from "../components/Podium.vue";
import { personRef, shiftDay } from "../lib";
import type { BoardKind, BoardRow, Period } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const state = useRouteStates({
  period: rs.enum<Period>(["week", "month", "all"], "week"),
  kind: rs.enum<BoardKind>(["all", "learning"], "all"),
  date: rs.string(""),
  branch: rs.optionalNumber(),
});
const period = computed<Period>({
  get: () => state.period.value,
  set: (value) => {
    state.date.value = "";
    state.period.value = value;
  },
});
const kind = state.kind;
const branch = state.branch;

const params = computed(() => ({
  period: period.value,
  kind: kind.value,
  ...(state.date.value && period.value !== "all" ? { date: state.date.value } : {}),
  ...(branch.value ? { branch: branch.value } : {}),
}));
const board = useLeaderboard(params);
const rows = computed(() => board.data.value?.rows ?? []);
const table = useDataTable({ id: "recognition.leaderboard", pageSize: 200 });

/** The company's date of an instant (the server sends them in UTC). */
function localDay(instant: string | number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: company.current?.timezone ?? "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(instant));
}

/** "2 Nov – 8 Nov 2026", "November 2026", or nothing for all time. */
const span = computed(() => {
  const data = board.data.value;
  if (!data?.start || !data.end) return "";
  const first = localDay(data.start);
  if (period.value === "month") return fmt.day(first, "monthYear");
  return `${fmt.day(first, "short")} – ${fmt.day(localDay(Date.parse(data.end) - 1), "medium")}`;
});

function move(steps: number): void {
  if (period.value === "all") return;
  const start = board.data.value?.start;
  const from = state.date.value || (start ? localDay(start) : localDay(Date.now()));
  state.date.value = shiftDay(from, period.value, steps);
}

const columns = computed<TableColumn<BoardRow>[]>(() => [
  { id: "place", header: "#", width: 56, numeric: true },
  { id: "member", header: t("recognition.col.person"), value: (row) => row.member.name, minWidth: 220, sticky: true },
  { id: "level", header: t("recognition.col.level"), value: (row) => `${row.level.number} · ${row.level.name}`, minWidth: 160 },
  { id: "points", header: t("recognition.col.points"), numeric: true, format: (value) => fmt.number(value as number) },
  { id: "badges", header: t("recognition.col.badges"), numeric: true },
  { id: "streak", header: t("recognition.col.streak"), numeric: true, hint: t("recognition.col.streakHint") },
]);

const drawer = ref(false);
const opened = ref<number | null>(null);
function open(row: BoardRow): void {
  opened.value = row.member.id;
  drawer.value = true;
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('recognition.nav.leaderboard')" :description="t('recognition.board.description')" />

    <div class="flex flex-wrap items-center gap-3">
      <SegmentedControl
        v-model="period"
        :aria-label="t('recognition.board.period')"
        :options="[
          { value: 'week', label: t('recognition.period.week') },
          { value: 'month', label: t('recognition.period.month') },
          { value: 'all', label: t('recognition.period.all') },
        ]"
      />
      <SegmentedControl
        v-model="kind"
        :aria-label="t('recognition.board.kind')"
        :options="[
          { value: 'all', label: t('recognition.kind.all') },
          { value: 'learning', label: t('recognition.kind.learning') },
        ]"
      />
      <div v-if="period !== 'all'" class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('recognition.board.earlier')" variant="ghost" @click="move(-1)" />
        <span class="min-w-40 text-center text-sm font-medium text-fg" data-testid="board-span">{{ span }}</span>
        <IconButton :icon="ChevronRight" :label="t('recognition.board.later')" variant="ghost" @click="move(1)" />
      </div>
      <div class="ms-auto w-56"><BranchPicker v-model="branch" clearable :placeholder="t('recognition.board.allBranches')" /></div>
    </div>

    <SkeletonBlock v-if="board.isPending.value" height="240px" radius="14px" />
    <div v-else-if="!rows.length" class="ui-card">
      <EmptyState :icon="Trophy" :title="t('recognition.board.emptyTitle')" :description="t('recognition.board.emptyBody')" />
    </div>
    <template v-else>
      <div class="ui-card px-4 pb-4"><Podium :rows="rows.slice(0, 3)" @open="open" /></div>
      <DataTable
        :state="table"
        :columns="columns"
        :rows="rows"
        :total="rows.length"
        row-key="place"
        :loading="board.isPending.value"
        :fetching="board.isFetching.value"
        :error="board.error.value"
        :retry="() => board.refetch()"
        clickable
        hide-pagination
        export-kind="recognition.leaderboard"
        :export-params="params"
        csv-name="leaderboard"
        @row-click="open"
      >
        <template #cell-member="{ row }">
          <PersonCell :person="personRef(row.member)" :subtitle="row.member.position" />
        </template>
      </DataTable>
    </template>

    <PersonDrawer v-model:open="drawer" :member-id="opened" />
  </div>
</template>
