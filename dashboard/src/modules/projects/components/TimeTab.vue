<script setup lang="ts">
/**
 * The Time tab: a week grid per person (hours per day, totals per person and per day, billable
 * share), who is tracking time right now, the week's entries (yours, and everyone's for people who
 * manage the project or hold `projects.time_view`), logging, a timer and the Excel export.
 */
import { ChevronLeft, ChevronRight, Clock, Play, Plus, Square, Timer, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addDays, startOfWeek, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { deleteTime, startTimer, stopTimer, useCompanyId, useRefreshProjects, useTimeWeek } from "../api";
import { colorVar, hhmm } from "../lib";
import type { ProjectDetail, TimeEntry } from "../types";
import LogTimeDialog from "./LogTimeDialog.vue";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const now = useNow();
const confirm = useConfirm();
const company = useCompanyStore();
const companyId = useCompanyId();
const refresh = useRefreshProjects();

const today = computed(() => todayIn(company.timezone));
const week = useRouteState("week", rs.day());
const weekStart = computed(() => startOfWeek(week.value ?? today.value));
const query = useTimeWeek(() => ({ week: weekStart.value, project: props.project.id }));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const logging = ref(false);
const logDay = ref<string | null>(null);

const data = computed(() => query.data.value);
const maxCell = computed(() => Math.max(240, ...(data.value?.rows.flatMap((r) => r.days) ?? [0])));
const me = computed(() => company.current?.membership_id ?? null);
const myTimer = computed(() => data.value?.running.find((timer) => timer.person.id === me.value) ?? null);
const isThisWeek = computed(() => weekStart.value === startOfWeek(today.value));
const canTrack = computed(() => props.project.capabilities.edit_cards);

function shift(weeks: number): void {
  const next = addDays(weekStart.value, weeks * 7);
  week.value = next === startOfWeek(today.value) ? null : next;
}

function cellStyle(minutes: number) {
  if (!minutes) return undefined;
  const strength = Math.round(10 + (minutes / maxCell.value) * 40);
  return { background: `color-mix(in srgb, ${colorVar(props.project.color)} ${strength}%, var(--c-surface))` };
}

function elapsed(startedAt: string): string {
  return hhmm(Math.max(0, Math.floor((now.value - new Date(startedAt).getTime()) / 60000)));
}

async function toggleTimer(): Promise<void> {
  try {
    if (myTimer.value) {
      const entry = await stopTimer(companyId.value);
      toast.success(entry ? t("projects.time.logged", { time: hhmm(entry.minutes) }) : t("projects.time.stopped"));
    } else {
      await startTimer(companyId.value, { project: props.project.id });
      toast.success(t("projects.time.started", { key: props.project.key }));
    }
    void refresh();
  } catch {
    // The HTTP layer showed why.
  }
}

async function remove(entry: TimeEntry): Promise<void> {
  const answer = await confirm({ title: t("projects.time.deleteTitle"), message: t("projects.time.deleteBody", { time: hhmm(entry.minutes), day: fmt.day(entry.day, "medium") }), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  await deleteTime(companyId.value, entry.id);
  void refresh();
}

function logOn(day: string | null): void {
  logDay.value = day && day <= today.value ? day : null;
  logging.value = true;
}

const exportParams = computed(() => ({ project: props.project.id, from: weekStart.value, to: addDays(weekStart.value, 6) }));
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('projects.time.prevWeek')" variant="secondary" size="sm" @click="shift(-1)" />
        <IconButton :icon="ChevronRight" :label="t('projects.time.nextWeek')" variant="secondary" size="sm" :disabled="isThisWeek" @click="shift(1)" />
      </div>
      <h3 class="text-md font-semibold text-fg">{{ fmt.range({ from: weekStart, to: addDays(weekStart, 6) }) }}</h3>
      <UiButton v-if="!isThisWeek" size="sm" variant="ghost" @click="week = null">{{ t("projects.time.thisWeek") }}</UiButton>
      <span class="flex-1" />
      <ExportButton kind="projects.time" :params="exportParams" size="sm" variant="ghost" />
      <UiButton v-if="canTrack" size="sm" :variant="myTimer ? 'primary' : 'secondary'" :icon="myTimer ? Square : Play" @click="toggleTimer">
        {{ myTimer ? t("projects.time.stopAt", { time: elapsed(myTimer.started_at) }) : t("projects.time.startProject") }}
      </UiButton>
      <UiButton size="sm" variant="primary" :icon="Plus" @click="logOn(null)">{{ t("projects.time.log") }}</UiButton>
    </div>

    <div v-if="skeleton" class="ui-card flex flex-col gap-3 p-4">
      <SkeletonBlock v-for="n in 5" :key="n" height="36px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="data">
      <section v-if="data.running.length" class="ui-card flex flex-wrap items-center gap-3 border-primary/30 bg-accent-soft/40 px-4 py-3">
        <span class="inline-flex items-center gap-1.5 text-sm font-semibold text-accent-fg"><Timer :size="15" class="animate-pulse" />{{ t("projects.time.trackingNow") }}</span>
        <span v-for="timer in data.running" :key="timer.id" class="inline-flex items-center gap-2 rounded-full bg-surface py-1 pl-1 pr-3 text-sm shadow-xs">
          <UserAvatar :name="timer.person.name" :src="timer.person.photo_url" :size="22" />
          <span class="font-medium text-fg">{{ timer.person.name }}</span>
          <span v-if="timer.task_key" class="font-mono text-xs text-muted">{{ timer.task_key }}</span>
          <span class="font-semibold tabular-nums text-primary">{{ elapsed(timer.started_at) }}</span>
        </span>
      </section>

      <EmptyState v-if="!data.rows.length" :icon="Clock" :title="t('projects.time.emptyTitle')" :description="t('projects.time.emptyBody')">
        <UiButton variant="primary" :icon="Plus" @click="logOn(null)">{{ t("projects.time.log") }}</UiButton>
      </EmptyState>
      <section v-else class="ui-card overflow-x-auto">
        <table class="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr class="border-b border-line bg-surface-2/50 text-xs font-semibold text-muted">
              <th class="sticky left-0 bg-surface-2 px-4 py-2.5 text-left">{{ t("projects.time.person") }}</th>
              <th v-for="day in data.days" :key="day" class="px-2 py-2.5 text-center" :class="day === today && 'text-primary'">
                <span class="block whitespace-nowrap tabular-nums">{{ fmt.day(day, "weekdayShort") }}</span>
              </th>
              <th class="px-4 py-2.5 text-right">{{ t("projects.time.total") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in data.rows" :key="row.person.id" class="border-b border-line last:border-b-0">
              <td class="sticky left-0 bg-surface px-4 py-2">
                <span class="flex items-center gap-2"><UserAvatar :name="row.person.name" :src="row.person.photo_url" :size="26" /><span class="truncate font-medium text-fg">{{ row.person.name }}</span></span>
              </td>
              <td v-for="(minutes, index) in row.days" :key="index" class="p-1 text-center">
                <button
                  type="button"
                  class="h-9 w-full rounded-[8px] text-sm tabular-nums transition-[filter] hover:brightness-95"
                  :class="minutes ? 'font-semibold text-fg' : 'text-subtle hover:bg-highlight'"
                  :style="cellStyle(minutes)"
                  :title="t('projects.time.logOn', { day: fmt.day(data.days[index]!, 'medium') })"
                  @click="logOn(data.days[index]!)"
                >
                  {{ minutes ? hhmm(minutes) : "·" }}
                </button>
              </td>
              <td class="px-4 py-2 text-right">
                <span class="font-semibold tabular-nums text-fg">{{ hhmm(row.total) }}</span>
                <span v-if="row.billable" class="block text-[11px] text-muted">{{ t("projects.time.billableShort", { time: hhmm(row.billable) }) }}</span>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr class="border-t border-line bg-surface-2/50 text-xs font-semibold text-muted">
              <td class="sticky left-0 bg-surface-2 px-4 py-2.5">{{ t("projects.time.total") }}</td>
              <td v-for="(minutes, index) in data.totals" :key="index" class="px-2 py-2.5 text-center tabular-nums">{{ minutes ? hhmm(minutes) : "—" }}</td>
              <td class="px-4 py-2.5 text-right text-sm tabular-nums text-fg">{{ hhmm(data.total) }}</td>
            </tr>
          </tfoot>
        </table>
      </section>

      <section v-if="data.entries.length" class="ui-card overflow-hidden">
        <h3 class="border-b border-line px-4 py-2.5 text-sm font-semibold text-fg">{{ t("projects.time.entries") }}</h3>
        <ul class="divide-y divide-line">
          <li v-for="entry in data.entries.slice(0, 40)" :key="entry.id" class="flex items-center gap-3 px-4 py-2.5 text-sm">
            <UserAvatar :name="entry.person.name" :src="entry.person.photo_url" :size="24" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-fg">
                <span class="font-medium">{{ entry.person.name }}</span>
                <span v-if="entry.task" class="text-muted"> · {{ entry.task.name }}</span>
              </p>
              <p class="truncate text-xs text-muted">
                {{ fmt.day(entry.day, "weekday") }}<span v-if="entry.note"> · {{ entry.note }}</span>
                <span v-if="entry.source === 'timer'"> · {{ t("projects.time.byTimer") }}</span>
              </p>
            </div>
            <span v-if="entry.billable" class="rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">{{ t("projects.time.billable") }}</span>
            <span class="w-12 text-right font-semibold tabular-nums text-fg">{{ hhmm(entry.minutes) }}</span>
            <IconButton v-if="entry.can_edit" :icon="Trash2" :label="t('common.delete')" size="sm" @click="remove(entry)" />
          </li>
        </ul>
      </section>
    </template>
    <LogTimeDialog v-model:open="logging" :project="project" :day="logDay" />
  </div>
</template>
