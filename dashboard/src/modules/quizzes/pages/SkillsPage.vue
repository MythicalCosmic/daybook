<script setup lang="ts">
/**
 * The skill matrix (Ko‘nikmalar xaritasi): people × topics, each cell the person's mastery of the
 * topic (their last twenty answers in it, the newest weighing most), coloured weak, ok or strong,
 * grey until three answers rate it. Column averages at the foot; a topic's weakest people first
 * by clicking its heading; filters by branch and position; a name opens the person's training.
 */
import { ArrowUp, GraduationCap } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useSkills } from "../api";
import { BAND_CELL, band } from "../lib";
import type { SkillCell } from "../types";

const { t } = useI18n();
const company = useCompanyStore();

const branch = useRouteState("branch", rs.optionalNumber());
const position = useRouteState("position", rs.optionalNumber());
const sort = useRouteState("sort", rs.optionalNumber());
const params = computed(() => ({ branch: branch.value ?? undefined, position: position.value ?? undefined, sort: sort.value ?? undefined }));
const skills = useSkills(params);
const topics = computed(() => skills.data.value?.topics ?? []);
const people = computed(() => skills.data.value?.people ?? []);

function cellOf(row: { cells: Record<string, SkillCell> }, topicId: number): SkillCell {
  return row.cells[String(topicId)] ?? { score: null, answers: 0, band: "unrated", last_at: null };
}
function title(cell: SkillCell): string {
  if (!cell.answers) return t("quizzes.skills.noAnswers");
  if (cell.score === null) return t("quizzes.skills.unrated", { n: cell.answers }, cell.answers);
  return t("quizzes.skills.cell", { score: cell.score, n: cell.answers }, cell.answers);
}
function toggleSort(topicId: number): void {
  sort.value = sort.value === topicId ? null : topicId;
}
</script>

<template>
  <div>
    <PageHeader :title="t('quizzes.nav.skills')" :description="t('quizzes.skills.description')" />
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <BranchPicker v-model="branch" clearable size="sm" class="w-48" :placeholder="t('quizzes.skills.anyBranch')" />
      <PositionPicker v-model="position" clearable size="sm" class="w-48" :placeholder="t('quizzes.skills.anyPosition')" />
      <span class="ml-auto flex flex-wrap items-center gap-2 text-xs text-muted">
        <span v-for="key in ['weak', 'ok', 'strong', 'unrated'] as const" :key="key" class="inline-flex items-center gap-1">
          <span class="inline-block size-3 rounded-sm" :class="BAND_CELL[key]" aria-hidden="true" />{{ t(`quizzes.band.${key}`) }}
        </span>
      </span>
    </div>

    <div v-if="skills.isPending.value" class="ui-card p-4"><SkeletonBlock height="240px" /></div>
    <ErrorState v-else-if="skills.error.value" :error="skills.error.value" :retry="() => skills.refetch()" />
    <div v-else-if="!topics.length || !people.length" class="ui-card">
      <EmptyState :icon="GraduationCap" :title="t('quizzes.skills.emptyTitle')" :description="t('quizzes.skills.emptyBody')" />
    </div>
    <div v-else class="ui-card overflow-x-auto" data-testid="skill-matrix">
      <table class="w-full min-w-max border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th class="sticky left-0 z-10 bg-surface px-4 py-3 text-left font-medium text-muted">{{ t("quizzes.skills.person") }}</th>
            <th v-for="topic in topics" :key="topic.id" class="px-2 py-3 text-center font-medium">
              <button type="button" class="inline-flex max-w-[9rem] items-center gap-1 truncate rounded-md px-2 py-1 hover:bg-surface-2" :class="sort === topic.id ? 'text-primary' : 'text-muted'" :title="t('quizzes.skills.sortHint')" @click="toggleSort(topic.id)">
                <span class="truncate">{{ topic.name }}</span>
                <ArrowUp v-if="sort === topic.id" :size="12" aria-hidden="true" />
              </button>
            </th>
            <th class="px-3 py-3 text-center font-medium text-muted">{{ t("quizzes.skills.average") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in people" :key="row.member.id" class="group">
            <td class="sticky left-0 z-10 border-t border-line bg-surface px-4 py-2 group-hover:bg-surface-2">
              <RouterLink :to="`/c/${company.currentId}/learning/people/${row.member.id}`" class="flex min-w-0 items-center gap-2 hover:underline">
                <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" />
                <span class="min-w-0">
                  <span class="block truncate font-medium text-fg">{{ row.member.name }}</span>
                  <span v-if="row.member.position" class="block truncate text-xs text-muted">{{ row.member.position }}</span>
                </span>
              </RouterLink>
            </td>
            <td v-for="topic in topics" :key="topic.id" class="border-t border-line px-2 py-2 text-center">
              <span class="inline-flex h-8 w-14 items-center justify-center rounded-md text-sm font-semibold tabular-nums" :class="BAND_CELL[cellOf(row, topic.id).band]" :title="title(cellOf(row, topic.id))">
                {{ cellOf(row, topic.id).score ?? (cellOf(row, topic.id).answers ? "·" : "—") }}
              </span>
            </td>
            <td class="border-t border-line px-3 py-2 text-center">
              <span class="font-semibold tabular-nums" :class="BAND_CELL[band(row.average)].split(' ')[1]">{{ row.average ?? "—" }}</span>
            </td>
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td class="sticky left-0 z-10 border-t-2 border-line bg-surface px-4 py-3 font-medium text-muted">{{ t("quizzes.skills.topicAverage") }}</td>
            <td v-for="topic in topics" :key="topic.id" class="border-t-2 border-line px-2 py-3 text-center">
              <span class="font-semibold tabular-nums" :class="BAND_CELL[band(topic.average)].split(' ')[1]">{{ topic.average ?? "—" }}</span>
              <span v-if="topic.weak" class="block text-xs text-danger">{{ t("quizzes.skills.weakCount", { n: topic.weak }, topic.weak) }}</span>
            </td>
            <td class="border-t-2 border-line" />
          </tr>
        </tfoot>
      </table>
    </div>
  </div>
</template>
