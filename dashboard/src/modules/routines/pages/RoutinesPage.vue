<script setup lang="ts">
/**
 * Routines → All routines (plan §6.2): the routines themselves, each with its days, when its next
 * tasks come, who does it, its branch, and how often it got done in the last 30 days (with a
 * 14-day sparkline), so routines nobody does stand out. Onboarding (beside it) lists the
 * first-days tasks new people get.
 */
import { CalendarClock, ChevronRight, Clock, Ellipsis, GraduationCap, ListChecks, Pencil, Plus, Repeat, Store, Trash2, UsersRound } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AvatarStack from "@/components/AvatarStack.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import SparkLine from "@/components/SparkLine.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useDeleteRoutine, useRoutines, useToggleActive } from "../api";
import RoutineEditor from "../components/RoutineEditor.vue";
import RoutinesHeader from "../components/RoutinesHeader.vue";
import WeekdayDots from "../components/WeekdayDots.vue";
import { onTimeShare, runLabel, wholePercent } from "../lib";
import type { Routine } from "../types";
import { useRunWords } from "../useRunWords";

const { t } = useI18n();
const fmt = useFormat();
const words = useRunWords();
const route = useRoute();
const router = useRouter();
const confirm = useConfirm();

const onboarding = computed(() => route.name === "routines.onboarding");
const search = useRouteState("q", rs.string(""));
const state = useRouteState("state", rs.enum(["all", "active", "paused"] as const, "all"));

const query = useRoutines(computed(() => ({ onboarding: onboarding.value })));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const toggle = useToggleActive();
const remove = useDeleteRoutine();

const rows = computed(() => {
  const q = search.value.trim().toLowerCase();
  return (query.data.value ?? []).filter((routine) => {
    if (state.value === "active" && !routine.is_active) return false;
    if (state.value === "paused" && routine.is_active) return false;
    return !q || routine.title.toLowerCase().includes(q) || routine.description.toLowerCase().includes(q);
  });
});
const counts = computed(() => {
  const all = query.data.value ?? [];
  return { all: all.length, active: all.filter((r) => r.is_active).length, paused: all.filter((r) => !r.is_active).length };
});

// Routines and onboarding templates sit side by side under "All routines".
const kind = computed({
  get: () => (onboarding.value ? "onboarding" : "routines"),
  set: (value: string) => void router.push({ name: value === "onboarding" ? "routines.onboarding" : "routines.list" }),
});
const kinds = computed(() => [
  { value: "routines", label: t("routines.tabs.routines"), icon: Repeat },
  { value: "onboarding", label: t("routines.tabs.onboarding"), icon: GraduationCap },
]);

// Editor
const editorOpen = ref(false);
const editing = ref<Routine | null>(null);
function create(): void {
  editing.value = null;
  editorOpen.value = true;
}
function edit(routine: Routine): void {
  editing.value = routine;
  editorOpen.value = true;
}
useHotkey("n", create, { description: "routines.keys.new", group: "page" });
// The palette's "New routine" lands here with `?new=1`.
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    create();
    newParam.value = false;
  },
  { immediate: true },
);

async function setActive(routine: Routine, active: boolean): Promise<void> {
  try {
    await toggle.mutateAsync({ routine, active });
    toast.success(active ? t("routines.toast.resumed") : t("routines.toast.paused"), { description: routine.title });
  } catch {
    // rolled back
  }
}

async function onDelete(routine: Routine): Promise<void> {
  const answer = await confirm({ title: t("routines.delete.title"), message: t("routines.delete.body", { title: routine.title }), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  try {
    await remove.mutateAsync(routine.id);
    toast.success(t("routines.toast.deleted"), { description: routine.title });
  } catch {
    // shown by the HTTP layer
  }
}

function menu(routine: Routine): MenuEntry[] {
  return [
    { label: t("common.edit"), icon: Pencil, onSelect: () => edit(routine) },
    ...(onboarding.value ? [] : [{ label: t("routines.open"), icon: ChevronRight, onSelect: () => open(routine) }]),
    { type: "separator" },
    { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => onDelete(routine) },
  ];
}

function open(routine: Routine): void {
  if (onboarding.value) edit(routine);
  else void router.push({ name: "routines.detail", params: { id: routine.id } });
}

// The days it ran, joined: days off (a Mon–Fri routine's weekend) would cut the line into dashes.
// A line through two points says nothing: new routines show only their percentage. Neither does a
// line that never moves (done every day: the percentage says it), which SparkLine draws at the bottom.
function sparkOf(routine: Routine): number[] {
  const points = (routine.stats?.spark ?? []).filter((value): value is number => value !== null);
  return points.length >= 4 && new Set(points).size > 1 ? points : [];
}

/** The 30 days behind the headline, on hover. */
function shareHint(routine: Routine): string | undefined {
  const share = onTimeShare(routine.stats);
  return share ? t("routines.share30Hint", { made: share.made, onTime: share.onTime, late: share.late, missed: share.missed }) : undefined;
}

function completionTone(value: number | null): string {
  if (value === null) return "text-subtle";
  if (value >= 90) return "text-success";
  if (value >= 70) return "text-warning";
  return "text-danger";
}

function who(routine: Routine): string {
  const parts = routine.positions.map((p) => p.name);
  if (routine.assignees.length) parts.push(t("routines.peopleCount", { n: routine.assignees.length }, routine.assignees.length));
  return parts.join(" · ") || (routine.onboarding ? t("routines.everyone") : t("routines.nobody"));
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <RoutinesHeader :description="onboarding ? t('routines.onboardingDescription') : t('routines.description')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" kbd="N" @click="create">{{ onboarding ? t("routines.newOnboarding") : t("routines.new") }}</UiButton>
      </template>
    </RoutinesHeader>

    <div class="flex flex-wrap items-center gap-2">
      <SegmentedControl v-model="kind" :options="kinds" :aria-label="t('routines.nav.all')" />
      <TextInput v-model="search" type="search" :icon="ListChecks" clearable :placeholder="t('routines.search')" class="w-full sm:w-[260px]" />
      <span class="flex-1" />
      <SegmentedControl
        v-model="state"
        size="sm"
        :options="[
          { value: 'all', label: t('routines.state.all'), count: counts.all },
          { value: 'active', label: t('routines.state.active'), count: counts.active },
          { value: 'paused', label: t('routines.state.paused'), count: counts.paused },
        ]"
      />
    </div>

    <div v-if="skeleton" class="flex flex-col gap-2">
      <div v-for="n in 5" :key="n" class="ui-card flex items-center gap-4 p-4"><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="40%" /><SkeletonBlock width="60%" height="12px" /></div><SkeletonBlock width="120px" height="32px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !query.data.value.length" class="ui-card">
      <EmptyState :icon="onboarding ? GraduationCap : Repeat" size="lg" :title="onboarding ? t('routines.emptyOnboardingTitle') : t('routines.emptyTitle')" :description="onboarding ? t('routines.emptyOnboardingBody') : t('routines.emptyBody')">
        <UiButton variant="primary" :icon="Plus" @click="create">{{ onboarding ? t("routines.newOnboarding") : t("routines.new") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else-if="!rows.length" class="ui-card">
      <EmptyState size="sm" tone="neutral" :title="t('routines.noMatch')" />
    </div>
    <TransitionGroup v-else name="list" tag="ul" class="relative flex flex-col gap-2">
      <li
        v-for="routine in rows"
        :key="routine.id"
        :class="['ui-card group/row flex min-w-0 cursor-pointer flex-col gap-3 p-4 transition-colors hover:border-line-strong md:flex-row md:items-center md:gap-5', !routine.is_active && 'opacity-70']"
        tabindex="0"
        @click="open(routine)"
        @keydown.enter.self="open(routine)"
      >
        <div class="min-w-0 flex-1">
          <div class="flex min-w-0 items-center gap-2">
            <p class="min-w-0 truncate text-base font-semibold text-fg">{{ routine.title }}</p>
            <span v-if="!routine.is_active" class="shrink-0 rounded-full bg-surface-2 px-2 py-px text-xs font-medium text-muted">{{ t("routines.paused") }}</span>
          </div>
          <div class="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted">
            <WeekdayDots v-if="!onboarding" :days="routine.weekdays" />
            <span v-else class="inline-flex items-center gap-1"><CalendarClock :size="14" />{{ t("routines.dueAfter", { n: routine.due_after_days }, routine.due_after_days) }}</span>
            <span v-if="!onboarding && routine.next_run" class="inline-flex items-center gap-1 tabular-nums" :title="t('routines.nextRunHint')" data-testid="next-run">
              <Clock :size="14" /><span class="text-subtle">{{ t("routines.next") }}</span><span class="font-medium text-fg">{{ runLabel(routine.next_run, words) }}</span>
            </span>
            <span v-else class="inline-flex items-center gap-1 tabular-nums"><Clock :size="14" />{{ routine.due_time.slice(0, 5) }}</span>
            <span v-if="routine.branch" class="inline-flex items-center gap-1"><Store :size="14" />{{ routine.branch.name }}</span>
            <span class="inline-flex min-w-0 items-center gap-1"><UsersRound :size="14" class="shrink-0" /><span class="truncate">{{ who(routine) }}</span></span>
            <span v-if="routine.checklist.length" class="inline-flex items-center gap-1"><ListChecks :size="14" />{{ t("routines.steps", { n: routine.checklist.length }, routine.checklist.length) }}</span>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-4">
          <AvatarStack v-if="routine.assignees.length" :people="routine.assignees" :max="3" :size="24" class="max-md:hidden" />
          <div v-if="!onboarding" class="flex items-center gap-3">
            <SparkLine :data="sparkOf(routine)" :width="96" :height="28" color="var(--c-chart-2)" :label="t('routines.sparkLabel')" />
            <!-- On time is the headline (late runs count as done, so "done" alone is always green). -->
            <div class="min-w-[84px] whitespace-nowrap text-right" :title="shareHint(routine)" data-testid="on-time-share">
              <p :class="['text-md font-semibold tabular-nums', completionTone(onTimeShare(routine.stats)?.percent ?? null)]">
                {{ onTimeShare(routine.stats) ? fmt.percent(wholePercent(onTimeShare(routine.stats)!.percent), 0) : "—" }}
              </p>
              <p class="text-xs text-subtle">
                {{ t("routines.onTime30") }}<template v-if="onTimeShare(routine.stats)?.late">
                  · <span class="font-medium text-warning">{{ t("routines.late30", { n: onTimeShare(routine.stats)!.late }, onTimeShare(routine.stats)!.late) }}</span></template
                >
              </p>
            </div>
          </div>
          <div class="flex items-center gap-1" @click.stop>
            <ToggleSwitch :model-value="routine.is_active" size="sm" :aria-label="t('routines.field.active')" @update:model-value="(value) => setActive(routine, value)" />
            <DropdownMenu :items="menu(routine)">
              <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" size="sm" /></template>
            </DropdownMenu>
          </div>
        </div>
      </li>
    </TransitionGroup>

    <RoutineEditor v-model:open="editorOpen" :routine="editing" :onboarding="onboarding" />
  </div>
</template>
