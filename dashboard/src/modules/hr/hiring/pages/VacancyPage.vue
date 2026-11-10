<script setup lang="ts">
/**
 * One vacancy (HR › Hiring › Farmatsevt): its numbers, and its applicants on a pipeline board, a
 * column per stage. Drag a card (or use its arrow) to move them on: a move the bot tells them about
 * (an interview, an offer), a refusal and the hire ask first; screening moves at once, with undo.
 * Phones get a list by stage instead of the board (and so does "List" on a desktop). A card opens
 * the applicant's panel (`?applicant=`): answers, diploma photo, notes, history and the next step.
 */
import { ArrowRight, Briefcase, CalendarClock, Columns3, EllipsisVertical, EyeOff, Inbox, Link2, ListFilter, MapPin, MessagesSquare, Pause, Pencil, Play, Rows3, Search, Share2, UserCheck, UserX, Wallet, XCircle } from "@lucide/vue";
import { useElementSize } from "@vueuse/core";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import KanbanBoard from "@/components/KanbanBoard.vue";
import type { KanbanColumn, KanbanMove } from "@/components/kanban";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { hiringApi, useBoard, useHiringMutation, useVacancy } from "../api";
import ApplicantCard from "../components/ApplicantCard.vue";
import ApplicantDrawer from "../components/ApplicantDrawer.vue";
import DecisionDialog, { type Decision } from "../components/DecisionDialog.vue";
import ShareDialog from "../components/ShareDialog.vue";
import VacancyFormDialog from "../components/VacancyFormDialog.vue";
import { STAGE_COLORS, STATE_TONES, canDrop, inProgress, nextStage, salaryText, toldByDefault, vacancyState } from "../lib";
import { STAGES, type Applicant, type PipelineStage, type Stage } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const { isPhone } = useBreakpoints();

const vacancyId = computed(() => {
  const value = Number(route.params.vacancyId);
  return Number.isInteger(value) && value > 0 ? value : null;
});
const vacancyQuery = useVacancy(vacancyId);
const vacancy = computed(() => vacancyQuery.data.value ?? null);
const board = useBoard(vacancyId);
const applicants = computed(() => board.data.value?.results ?? []);
const skeleton = useDelayedPending(computed(() => vacancyQuery.isPending.value || board.isPending.value));
const base = computed(() => `/c/${company.currentId}/hr/hiring`);

const layout = useRouteState("layout", rs.enum(["board", "list"] as const, "board"));
const showList = computed(() => isPhone.value || layout.value === "list");
const search = useRouteState("q", rs.string(""));
const stageFilter = useRouteState<Stage | "all">("stage", rs.enum(["all", ...STAGES] as const, "all"));

const filtered = computed(() => {
  const words = search.value.trim().toLocaleLowerCase();
  const digits = words.replace(/\D/g, "");
  if (!words) return applicants.value;
  return applicants.value.filter(
    (row) => row.name.toLocaleLowerCase().includes(words) || (digits.length >= 3 && row.phone.replace(/\D/g, "").includes(digits)) || row.telegram_username.toLocaleLowerCase().includes(words.replace(/^@/, "")),
  );
});
const stageCount = (stage: Stage) => applicants.value.filter((row) => row.stage === stage).length;
// The board fits the page: the turned-down column shows on demand, and the columns share the width.
const showRejected = useRouteState("rejected", rs.boolean(false));
const rejectedCount = computed(() => stageCount("rejected"));
const columns = computed<KanbanColumn[]>(() =>
  STAGES.filter((stage) => stage !== "rejected" || showRejected.value).map((stage) => ({ id: stage, title: t(`hr.hiring.stage.${stage}`), color: STAGE_COLORS[stage] })),
);
const boardBox = ref<HTMLElement | null>(null);
const { width: boardWidth } = useElementSize(boardBox);
const columnWidth = computed(() => {
  const count = columns.value.length;
  const room = boardWidth.value || 1100;
  return Math.round(Math.min(288, Math.max(208, (room - 12 * (count - 1)) / count)));
});
const groups = computed(() =>
  STAGES.filter((stage) => stageFilter.value === "all" || stage === stageFilter.value)
    .map((stage) => ({ stage, rows: filtered.value.filter((row) => row.stage === stage) }))
    .filter((group) => group.rows.length),
);
const stageOptions = computed(() => [
  { value: "all" as const, label: t("common.all"), count: applicants.value.length },
  ...STAGES.map((stage) => ({ value: stage, label: t(`hr.hiring.stage.${stage}`), count: stageCount(stage) })),
]);

const state = computed(() => (vacancy.value ? vacancyState(vacancy.value, today.value) : "draft"));
const salary = computed(() => (vacancy.value ? salaryText(vacancy.value, fmt.money, t) : null));
const dates = computed(() => {
  const v = vacancy.value;
  if (!v) return null;
  if (state.value === "scheduled" && v.opens_on) return t("hr.hiring.opensOn", { date: fmt.day(v.opens_on, "medium") });
  if (state.value === "ended" && v.closes_on) return t("hr.hiring.endedOn", { date: fmt.day(v.closes_on, "medium") });
  if (v.closes_on) return t("hr.hiring.until", { date: fmt.day(v.closes_on, "medium") });
  return null;
});
const kpis = computed(() => {
  const v = vacancy.value;
  if (!v) return [];
  return [
    { id: "opens", label: t("hr.hiring.kpi.opens"), value: v.link_opens, icon: Link2, hint: t("hr.hiring.kpi.opensHint") },
    { id: "applied", label: t("hr.hiring.kpi.applied"), value: v.counts.total, icon: Inbox, hint: v.link_opens ? t("hr.hiring.kpi.conversion", { n: Math.round((v.counts.total / Math.max(v.link_opens, v.counts.total)) * 100) }) : undefined },
    { id: "progress", label: t("hr.hiring.kpi.progress"), value: inProgress(v.counts), icon: MessagesSquare },
    { id: "hired", label: t("hr.hiring.kpi.hired"), value: v.counts.hired, icon: UserCheck },
  ];
});

// Opening an applicant.
function open(applicant: Applicant): void {
  void router.push({ query: { ...route.query, applicant: String(applicant.id) } });
}

// Moving: some moves ask first (DecisionDialog), screening and back go at once with undo.
const decision = ref<Decision | null>(null);
let revert: (() => void) | null = null;
const quickMove = useHiringMutation((cid, args: { id: number; stage: PipelineStage }) => hiringApi.move(cid, args.id, { stage: args.stage }));

function ask(next: Decision, undo: (() => void) | null = null): void {
  revert = undo;
  decision.value = next;
}

async function moveAtOnce(applicant: Applicant, stage: PipelineStage, undo: (() => void) | null = null): Promise<void> {
  const was = applicant.stage;
  try {
    await quickMove.mutateAsync({ id: applicant.id, stage });
  } catch (failure) {
    undo?.();
    if (isApiError(failure) && failure.detail === null) toast.error(t("common.error.generic"));
    return;
  }
  const back = was !== "hired" && was !== "rejected" && was !== stage ? (was as PipelineStage) : null;
  toast.success(t("hr.hiring.decide.moved", { name: applicant.name, stage: t(`hr.hiring.stage.${stage}`) }), {
    action: back ? { label: t("common.undo"), onClick: () => quickMove.mutateAsync({ id: applicant.id, stage: back }) } : undefined,
  });
}

function goTo(applicant: Applicant, to: Stage, undo: (() => void) | null = null): void {
  if (to === applicant.stage) return;
  if (to === "hired") {
    if (vacancy.value?.hire_blocker) {
      undo?.();
      toast.error(vacancy.value.hire_blocker);
      return;
    }
    ask({ mode: "hire", applicant }, undo);
    return;
  }
  if (to === "rejected") {
    ask({ mode: "reject", applicant }, undo);
    return;
  }
  if (toldByDefault(to)) {
    ask({ mode: "move", applicant, stage: to }, undo);
    return;
  }
  void moveAtOnce(applicant, to, undo);
}

function onMove(move: KanbanMove<Applicant>): void {
  goTo(move.item, move.to as Stage, move.revert);
}

function advance(applicant: Applicant): void {
  const next = nextStage(applicant.stage);
  if (next) goTo(applicant, next);
}

function cancelled(): void {
  revert?.();
  revert = null;
}
function decided(): void {
  revert = null;
}

// The vacancy itself: share, edit, pause, open, close.
const shareOpen = ref(false);
const formOpen = ref(false);
const statusChange = useHiringMutation((cid, args: { id: number; verb: "open" | "pause" | "close" }) => hiringApi.setStatus(cid, args.id, args.verb));
async function setStatus(verb: "open" | "pause" | "close"): Promise<void> {
  const v = vacancy.value;
  if (!v) return;
  if (verb === "close") {
    const answer = await confirm({
      title: t("hr.hiring.confirm.closeTitle", { title: v.title }),
      message: t("hr.hiring.confirm.closeBody"),
      confirmLabel: t("hr.hiring.action.close"),
      icon: XCircle,
      onConfirm: () => statusChange.mutateAsync({ id: v.id, verb }),
    });
    if (answer) toast.success(t("hr.hiring.toast.closed", { title: v.title }));
    return;
  }
  await statusChange.mutateAsync({ id: v.id, verb });
  toast.success(t(verb === "pause" ? "hr.hiring.toast.paused" : "hr.hiring.toast.opened", { title: v.title }));
}
const menu = computed<MenuEntry[]>(() => {
  const v = vacancy.value;
  if (!v) return [];
  const entries: MenuEntry[] = [];
  if (v.status === "open") entries.push({ label: t("hr.hiring.action.pause"), icon: Pause, onSelect: () => void setStatus("pause") });
  if (v.status !== "closed") entries.push({ label: t("hr.hiring.action.close"), icon: XCircle, danger: true, onSelect: () => void setStatus("close") });
  if (v.status === "closed") entries.push({ label: t("hr.hiring.action.open"), icon: Play, onSelect: () => void setStatus("open") });
  return entries;
});
</script>

<template>
  <div>
    <ErrorState v-if="vacancyQuery.isError.value" class="ui-card" :error="vacancyQuery.error.value" :retry="() => vacancyQuery.refetch()" />

    <template v-else>
      <PageHeader :title="vacancy?.title ?? t('hr.nav.hiring')" :back="base" :back-label="t('hr.nav.hiring')">
        <template v-if="vacancy" #meta>
          <StatusPill :tone="STATE_TONES[state]" :live="state === 'open'" :label="t(`hr.hiring.state.${state}`)" />
          <span class="inline-flex items-center gap-1 text-sm text-muted"><MapPin :size="14" aria-hidden="true" />{{ vacancy.branch?.name ?? t("hr.hiring.anyBranch") }}</span>
          <span v-if="vacancy.position" class="inline-flex items-center gap-1 text-sm text-muted"><Briefcase :size="14" aria-hidden="true" />{{ vacancy.position.name }}</span>
          <span v-if="salary" class="inline-flex items-center gap-1 text-sm tabular-nums text-muted"><Wallet :size="14" aria-hidden="true" />{{ salary }}</span>
          <span v-if="dates" class="inline-flex items-center gap-1 text-sm text-muted"><CalendarClock :size="14" aria-hidden="true" />{{ dates }}</span>
        </template>
        <template v-if="vacancy" #actions>
          <UiButton v-if="vacancy.status === 'draft' || vacancy.status === 'paused'" :icon="Play" data-open-vacancy @click="setStatus('open')">{{ t(vacancy.status === "draft" ? "hr.hiring.action.publish" : "hr.hiring.action.open") }}</UiButton>
          <UiButton :icon="Pencil" @click="formOpen = true">{{ t("common.edit") }}</UiButton>
          <UiButton variant="primary" :icon="Share2" data-share-open @click="shareOpen = true">{{ t("hr.hiring.action.share") }}</UiButton>
          <DropdownMenu v-if="menu.length" :items="menu" align="end">
            <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" variant="secondary" /></template>
          </DropdownMenu>
        </template>
      </PageHeader>

      <div v-if="skeleton" class="flex flex-col gap-4">
        <SkeletonBlock height="96px" radius="12px" />
        <div class="flex gap-3 overflow-hidden"><SkeletonBlock v-for="n in 4" :key="n" width="288px" height="360px" radius="12px" /></div>
      </div>

      <div v-else-if="vacancy" class="flex flex-col gap-4">
        <KpiStrip :items="kpis" :columns="4" phone="compact" />

        <div v-if="applicants.length" class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" :icon="Search" size="sm" clearable :debounce="150" :placeholder="t('hr.hiring.searchApplicants')" class="w-full sm:w-[280px]" />
          <span class="flex-1" />
          <UiButton v-if="!showList && rejectedCount" size="sm" variant="ghost" :icon="showRejected ? EyeOff : UserX" data-toggle-rejected @click="showRejected = !showRejected">
            {{ showRejected ? t("hr.hiring.hideRejected") : t("hr.hiring.showRejected", { n: rejectedCount }) }}
          </UiButton>
          <SegmentedControl
            v-if="!isPhone"
            v-model="layout"
            size="sm"
            :options="[
              { value: 'board', label: t('hr.hiring.layout.board'), icon: Columns3 },
              { value: 'list', label: t('hr.hiring.layout.list'), icon: Rows3 },
            ]"
          />
        </div>

        <!-- Nobody yet -->
        <div v-if="!applicants.length" class="ui-card" data-board-empty>
          <EmptyState :icon="Inbox" :title="t('hr.hiring.noApplicants')" :description="vacancy.accepting ? t('hr.hiring.noApplicantsBody') : t('hr.hiring.noApplicantsClosed')">
            <UiButton v-if="vacancy.accepting" variant="primary" :icon="Share2" @click="shareOpen = true">{{ t("hr.hiring.action.share") }}</UiButton>
            <UiButton v-else-if="vacancy.status === 'draft' || vacancy.status === 'paused'" variant="primary" :icon="Play" @click="setStatus('open')">{{ t(vacancy.status === "draft" ? "hr.hiring.action.publish" : "hr.hiring.action.open") }}</UiButton>
          </EmptyState>
        </div>

        <!-- The board -->
        <div v-else-if="!showList" ref="boardBox" class="min-w-0">
          <KanbanBoard
            :columns="columns"
            :items="filtered"
            :item-key="(row: Applicant) => row.id"
            :column-of="(row: Applicant) => row.stage"
            :can-drop="canDrop"
            :sortable="false"
            :column-width="columnWidth"
            height="calc(100dvh - 330px)"
            data-board
            @move="onMove"
          >
            <template #card="{ item }">
              <ApplicantCard :applicant="item" class="cursor-pointer" @click="open(item)" @open="open" @advance="advance" />
            </template>
            <template #empty="{ column }">{{ t(`hr.hiring.columnEmpty.${column.id}`) }}</template>
          </KanbanBoard>
        </div>

        <!-- The list, by stage (phones, and "List") -->
        <div v-else class="flex flex-col gap-3" data-list>
          <div class="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 md:mx-0 md:px-0" role="group" :aria-label="t('hr.hiring.filterStage')">
            <ListFilter :size="15" class="my-auto mr-1 shrink-0 text-subtle" aria-hidden="true" />
            <button
              v-for="option in stageOptions"
              :key="option.value"
              type="button"
              :aria-pressed="stageFilter === option.value"
              :class="[
                'pressable inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors',
                stageFilter === option.value ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-highlight',
              ]"
              @click="stageFilter = option.value"
            >
              <span v-if="option.value !== 'all'" class="size-2 rounded-full" :style="{ background: STAGE_COLORS[option.value] }" aria-hidden="true" />
              {{ option.label }}
              <span class="tabular-nums text-muted">{{ option.count }}</span>
            </button>
          </div>
          <section v-for="group in groups" :key="group.stage" class="ui-card overflow-hidden" :data-group="group.stage">
            <header class="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <span class="size-2 rounded-full" :style="{ background: STAGE_COLORS[group.stage] }" aria-hidden="true" />
              <h3 class="text-sm font-semibold text-fg">{{ t(`hr.hiring.stage.${group.stage}`) }}</h3>
              <span class="text-sm tabular-nums text-muted">{{ group.rows.length }}</span>
            </header>
            <ul class="divide-y divide-[var(--c-border)]">
              <li v-for="row in group.rows" :key="row.id" class="group/card cursor-pointer px-4 py-3 transition-colors hover:bg-highlight" @click="open(row)">
                <ApplicantCard :applicant="row" @open="open" @advance="advance" />
              </li>
            </ul>
          </section>
          <p v-if="!groups.length" class="ui-card px-4 py-6 text-center text-sm text-muted">{{ t("hr.empty.noMatch") }}</p>
        </div>

        <p v-if="applicants.length && vacancy.hire_blocker" class="flex items-start gap-2 text-sm text-muted" data-hire-blocker>
          <ArrowRight :size="14" class="mt-1 shrink-0 text-subtle" aria-hidden="true" />{{ vacancy.hire_blocker }}
        </p>
      </div>
    </template>

    <ApplicantDrawer :vacancy="vacancy" @decide="(next) => ask(next)" />
    <DecisionDialog v-model:decision="decision" :vacancy="vacancy" @cancel="cancelled" @done="decided" />
    <ShareDialog v-model:open="shareOpen" :vacancy="vacancy" @publish="setStatus('open')" />
    <VacancyFormDialog v-model:open="formOpen" :vacancy="vacancy" />
  </div>
</template>
