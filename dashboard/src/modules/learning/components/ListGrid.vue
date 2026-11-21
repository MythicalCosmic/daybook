<script setup lang="ts">
/**
 * An unchangeable list's grid: topics are rows (number and title in a sticky first column),
 * students are columns (name, note or position, how many topics they studied). A cell holding a
 * line shows a check, the day (dd.mm) and who wrote it; a cell whose history has a correction
 * carries a small marker. A cell opens its line, or the form to write one (manage, open list).
 * On a phone the grid scrolls sideways inside its card with the topic column kept in view.
 */
import { Check, Ellipsis, Lock, Pencil, Plus, Trash2 } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";

import { cellKey, dayMonth, shortName, studentLine, type StudyCell, type StudyProgress } from "../lists";
import type { StudyListDetail, StudyStudent, StudyTopic } from "../types";

const props = defineProps<{
  list: StudyListDetail;
  cells: Map<string, StudyCell>;
  progress: StudyProgress;
  /** Manage permission and an open list: cells can be written, topics and students changed. */
  canWrite: boolean;
}>();

const emit = defineEmits<{
  open: [topicId: number, studentId: number];
  editTopic: [topic: StudyTopic];
  removeTopic: [topic: StudyTopic];
  editStudent: [student: StudyStudent];
  removeStudent: [student: StudyStudent];
}>();

const { t } = useI18n();

const cellOf = (topic: StudyTopic, student: StudyStudent): StudyCell | null => props.cells.get(cellKey(topic.id, student.id)) ?? null;

/** Holding a line, with a history to read, or ready to be written. */
const clickable = (cell: StudyCell | null) => Boolean(cell?.standing || cell?.history.length || props.canWrite);

function cellLabel(topic: StudyTopic, student: StudyStudent, cell: StudyCell | null): string {
  const where = t("learning.lists.cell.where", { student: student.name, n: topic.number, topic: topic.title });
  const what = cell?.standing
    ? t("learning.lists.cell.holds", { day: dayMonth(cell.standing.studied_on), name: cell.standing.written_by })
    : props.canWrite
      ? t("learning.lists.cell.write")
      : t("learning.lists.cell.empty");
  return `${where}: ${what}${cell?.corrected ? ` · ${t("learning.lists.cell.hasCorrections")}` : ""}`;
}

function topicMenu(topic: StudyTopic): MenuEntry[] {
  return [
    { label: t("learning.lists.topic.rename"), icon: Pencil, onSelect: () => emit("editTopic", topic) },
    { type: "separator" },
    { label: t("learning.lists.topic.remove"), icon: Trash2, danger: true, onSelect: () => emit("removeTopic", topic) },
  ];
}
function studentMenu(student: StudyStudent): MenuEntry[] {
  return [
    { label: t("learning.lists.student.edit"), icon: Pencil, onSelect: () => emit("editStudent", student) },
    { type: "separator" },
    { label: t("learning.lists.student.remove"), icon: Trash2, danger: true, onSelect: () => emit("removeStudent", student) },
  ];
}
</script>

<template>
  <div class="ui-card max-w-full overflow-x-auto overscroll-x-contain" data-testid="list-grid">
    <table class="w-max min-w-full border-separate border-spacing-0 text-sm">
      <thead>
        <tr class="text-left text-xs text-muted">
          <th
            scope="col"
            class="sticky left-0 z-20 w-[168px] min-w-[168px] border-b border-r border-line bg-surface px-3 py-2.5 align-bottom font-medium sm:w-[280px] sm:min-w-[280px] sm:px-4"
          >
            {{ t("learning.lists.topic.column") }}
          </th>
          <th v-for="student in list.students" :key="student.id" scope="col" class="w-[112px] min-w-[112px] max-w-[112px] border-b border-r border-line px-2 py-2.5 align-bottom font-normal last:border-r-0">
            <div class="flex items-start gap-1">
              <div class="min-w-0 flex-1">
                <span class="block truncate text-[13px] font-semibold text-fg" :title="student.name">{{ student.name }}</span>
                <span v-if="studentLine(student)" class="block truncate text-[11px] text-muted" :title="studentLine(student)">{{ studentLine(student) }}</span>
                <span class="mt-1 block text-[11px] text-subtle tabular-nums">{{ progress.byStudent[student.id] ?? 0 }}/{{ list.topics.length }}</span>
              </div>
              <DropdownMenu v-if="canWrite && !student.locked" :items="studentMenu(student)" width="200px">
                <template #trigger>
                  <IconButton :icon="Ellipsis" size="sm" :label="t('learning.lists.student.menu', { name: student.name })" class="-mr-1 -mt-1" />
                </template>
              </DropdownMenu>
              <span v-else-if="canWrite" class="mt-0.5 shrink-0 text-subtle" :title="t('learning.lists.lockedHint')"><Lock :size="11" aria-hidden="true" /></span>
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="topic in list.topics" :key="topic.id" class="group/row">
          <th scope="row" class="sticky left-0 z-10 border-b border-r border-line bg-surface px-3 py-2 text-left align-middle font-normal sm:px-4">
            <div class="flex items-start gap-2">
              <span class="mt-px grid h-5 min-w-5 shrink-0 place-items-center rounded-[6px] bg-surface-2 px-1 text-[11px] font-semibold text-muted tabular-nums">{{ topic.number }}</span>
              <div class="min-w-0 flex-1">
                <span class="line-clamp-2 text-[13px] font-medium leading-5 text-fg" :title="topic.title">{{ topic.title }}</span>
                <span class="block text-[11px] text-subtle tabular-nums">{{ progress.byTopic[topic.id] ?? 0 }}/{{ list.students.length }}</span>
              </div>
              <DropdownMenu v-if="canWrite && !topic.locked" :items="topicMenu(topic)" width="200px">
                <template #trigger>
                  <IconButton :icon="Ellipsis" size="sm" :label="t('learning.lists.topic.menu', { n: topic.number })" class="-mr-1.5 shrink-0" />
                </template>
              </DropdownMenu>
              <span v-else-if="canWrite" class="mt-1 shrink-0 text-subtle" :title="t('learning.lists.lockedHint')"><Lock :size="11" aria-hidden="true" /></span>
            </div>
          </th>
          <td v-for="student in list.students" :key="student.id" class="border-b border-r border-line p-1 text-center align-middle last:border-r-0">
            <button
              v-if="clickable(cellOf(topic, student))"
              type="button"
              :data-cell="`${topic.id}:${student.id}`"
              :aria-label="cellLabel(topic, student, cellOf(topic, student))"
              :class="[
                'pressable group/cell relative flex h-12 w-full flex-col items-center justify-center rounded-[8px] px-1 outline-offset-[-2px] transition-colors',
                cellOf(topic, student)?.standing
                  ? 'bg-success-soft text-success hover:brightness-[0.97]'
                  : 'text-subtle hover:bg-highlight hover:text-fg',
              ]"
              @click="emit('open', topic.id, student.id)"
            >
              <template v-if="cellOf(topic, student)?.standing">
                <span class="inline-flex items-center gap-1 text-[13px] font-semibold leading-none tabular-nums">
                  <Check :size="13" :stroke-width="3" aria-hidden="true" />{{ dayMonth(cellOf(topic, student)!.standing!.studied_on) }}
                </span>
                <span class="mt-1 max-w-full truncate text-[10px] leading-none opacity-80">{{ shortName(cellOf(topic, student)!.standing!.written_by) }}</span>
              </template>
              <Plus v-else-if="canWrite" :size="15" class="opacity-0 transition-opacity group-hover/cell:opacity-100 group-focus-visible/cell:opacity-100 pointer-coarse:opacity-40" aria-hidden="true" />
              <span v-else class="size-1 rounded-full bg-current opacity-40" aria-hidden="true" />
              <span
                v-if="cellOf(topic, student)?.corrected"
                class="absolute right-1 top-1 size-1.5 rounded-full bg-warning ring-2 ring-[var(--c-surface)]"
                data-corrected
                aria-hidden="true"
              />
            </button>
            <span v-else class="flex h-12 items-center justify-center" aria-hidden="true"><span class="size-1 rounded-full bg-line-strong" /></span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
