<script setup lang="ts">
/**
 * People against the mandatory courses: one row per person (in the viewer's branches), one cell
 * per course with its state (not started, in progress with the percent, done, late, excused), the
 * count done and late. Filters: position, a name, late only. A row opens the person's training.
 */
import { CircleCheck, CircleDashed, Clock, Minus, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useGrid } from "../api";
import type { GridCell } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();

const search = useRouteState("q", rs.string(""));
const position = useRouteState("position", rs.optionalNumber());
const late = useRouteState("late", rs.boolean(false));
const params = computed(() => ({
  q: search.value || undefined,
  position: position.value ?? undefined,
  late: late.value || undefined,
  branch: company.branchFilter.length === 1 ? company.branchFilter[0] : undefined,
}));
const grid = useGrid(params);
const data = computed(() => grid.data.value);

function cellClass(cell: GridCell | null): string {
  if (!cell) return "bg-surface-2 text-subtle";
  if (cell.state === "completed") return "bg-success-soft text-success";
  if (cell.late) return "bg-danger-soft text-danger";
  if (cell.state === "exempt" || cell.state === "cancelled") return "bg-surface-2 text-muted";
  if (cell.state === "in_progress") return "bg-info-soft text-info";
  return "bg-warning-soft text-warning";
}
function cellLabel(cell: GridCell | null): string {
  if (!cell) return t("learning.grid.none");
  if (cell.state === "completed") return t("learning.state.completed");
  if (cell.late) return t("learning.grid.late");
  if (cell.state === "in_progress") return `${cell.percent}%`;
  return t(`learning.state.${cell.state}`);
}
function cellTitle(cell: GridCell | null, course: string): string {
  const due = cell?.due_at ? ` · ${t("learning.people.dueOn", { day: fmt.instant(cell.due_at, "date") })}` : "";
  return `${course}: ${cellLabel(cell)}${due}`;
}
function iconOf(cell: GridCell | null) {
  if (!cell || cell.state === "exempt" || cell.state === "cancelled") return Minus;
  if (cell.state === "completed") return CircleCheck;
  if (cell.late) return Clock;
  return CircleDashed;
}
function open(memberId: number): void {
  void router.push(`/c/${company.currentId}/learning/people/${memberId}`);
}
</script>

<template>
  <div>
    <PageHeader :title="t('learning.nav.people')" :description="t('learning.grid.description')" />
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('learning.grid.search')" clearable />
      <PositionPicker v-model="position" size="sm" class="w-56" clearable :placeholder="t('learning.grid.anyPosition')" />
      <ToggleSwitch v-model="late" size="sm" :label="t('learning.grid.lateOnly')" />
    </div>

    <ErrorState v-if="grid.isError.value" :error="grid.error.value" :retry="() => grid.refetch()" />
    <template v-else-if="!data">
      <SkeletonBlock v-for="n in 6" :key="n" height="48px" radius="8px" class="mb-2" />
    </template>
    <div v-else-if="!data.courses.length" class="ui-card">
      <EmptyState :icon="Users" :title="t('learning.grid.noCourses')" :description="t('learning.grid.noCoursesBody')" />
    </div>
    <div v-else-if="!data.rows.length" class="ui-card">
      <EmptyState size="sm" :icon="Users" :title="t('learning.grid.nobody')" />
    </div>
    <div v-else class="ui-card overflow-x-auto">
      <table class="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr class="border-b border-line text-left text-xs text-muted">
            <th scope="col" class="sticky left-0 z-10 bg-surface px-4 py-2 font-medium">{{ t("learning.grid.person") }}</th>
            <th v-for="course in data.courses" :key="course.id" scope="col" class="px-2 py-2 text-center font-medium">
              <RouterLink :to="`/c/${company.currentId}/learning/courses/${course.id}`" class="inline-flex max-w-[10rem] items-center gap-1 truncate hover:underline">
                <span aria-hidden="true">{{ course.emoji }}</span><span class="truncate">{{ course.title }}</span>
              </RouterLink>
            </th>
            <th scope="col" class="px-4 py-2 text-right font-medium">{{ t("learning.grid.done") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in data.rows" :key="row.member.id" class="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2" @click="open(row.member.id)">
            <th scope="row" class="sticky left-0 z-10 bg-surface px-4 py-2 text-left font-normal">
              <PersonCell :person="row.member" :subtitle="row.member.position" size="sm" />
            </th>
            <td v-for="course in data.courses" :key="course.id" class="px-2 py-2 text-center">
              <span
                class="inline-flex min-w-[5.5rem] items-center justify-center gap-1 rounded-full px-2 py-1 text-xs font-medium"
                :class="cellClass(row.cells[String(course.id)] ?? null)"
                :title="cellTitle(row.cells[String(course.id)] ?? null, course.title)"
              >
                <component :is="iconOf(row.cells[String(course.id)] ?? null)" :size="12" aria-hidden="true" />
                {{ cellLabel(row.cells[String(course.id)] ?? null) }}
              </span>
            </td>
            <td class="px-4 py-2 text-right tabular-nums">
              <span :class="row.late ? 'font-semibold text-danger' : 'text-fg'">{{ row.done }}/{{ row.total }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
