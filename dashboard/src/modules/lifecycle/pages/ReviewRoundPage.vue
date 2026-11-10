<script setup lang="ts">
/**
 * One review round (plan §13.4 `ReviewCycle`): where it is (draft, the people answering, the
 * reviewers' part, closed) with its days, how far everyone has got, and its people: who answered,
 * who is late, who reviews whom and what came of each published review. Whoever runs the round
 * opens it, reminds the late ones, starts the reviewers' part (it also begins by itself a few days
 * after the self deadline), gives a review to someone else or takes a person out, and closes it.
 * Results and the questions have their own tabs.
 */
import { BellRing, CircleCheck, ClipboardList, Lock, MoreHorizontal, Pencil, Play, Search, Send, Star, Trash2, UserMinus, UserRoundPen, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import RoundResults from "../components/reviews/RoundResults.vue";
import RoundWizard from "../components/reviews/RoundWizard.vue";
import { reviewsApi, useReviewMutation, useRound, useRows } from "../reviews/api";
import { OUTCOME_STATE_TONES, OUTCOME_TONES, ratingTone, ROUND_TONES, stageIndex, STAGES } from "../reviews/lib";
import { ROW_STATES, type ReviewRow, type RowState } from "../reviews/types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();

const roundId = computed(() => Number(route.params.roundId));
const query = useRound(roundId);
const round = computed(() => query.data.value ?? null);
const back = computed(() => ({ path: `/c/${company.currentId}/lifecycle/reviews` }));

type Tab = "people" | "results" | "questions";
const tab = useRouteState<Tab>("tab", rs.enum(["people", "results", "questions"] as const, "people"));
const tabs = computed(() => [
  { value: "people" as Tab, label: t("lifecycle.reviews.round.tabPeople"), icon: Users, count: round.value?.progress.people || undefined },
  { value: "results" as Tab, label: t("lifecycle.reviews.round.tabResults"), icon: Star },
  { value: "questions" as Tab, label: t("lifecycle.reviews.round.tabQuestions"), icon: ClipboardList, count: round.value?.questions.length || undefined },
]);

const q = useRouteState("q", rs.string(""));
const mine = useRouteState("mine", rs.boolean(false));
const state = useRouteState<RowState | "all">("state", rs.enum([...ROW_STATES, "all"] as const, "all"));
const rowParams = computed(() => ({ q: q.value || undefined, mine: mine.value || undefined, state: state.value === "all" ? undefined : state.value }));
const rows = useRows(roundId, rowParams);
const STATE_OPTIONS = computed(() => [
  { value: "all" as const, label: t("lifecycle.reviews.round.filterAll") },
  { value: "self_late" as const, label: t("lifecycle.reviews.round.filterLate") },
  { value: "self_waiting" as const, label: t("lifecycle.reviews.round.filterWaiting") },
  { value: "to_write" as const, label: t("lifecycle.reviews.round.filterToWrite") },
  { value: "published" as const, label: t("lifecycle.reviews.round.filterPublished") },
]);

// The stages, each with its day.
const stages = computed(() => {
  const value = round.value;
  if (!value) return [];
  const current = stageIndex(value.status);
  const days: Record<string, string | null> = {
    draft: value.created_at,
    self: value.self_due_on,
    manager: value.manager_due_on,
    closed: value.closed_at,
  };
  return STAGES.map((stage, index) => ({
    stage,
    state: index < current || value.status === "closed" ? "done" : index === current ? "current" : "next",
    day: days[stage],
  }));
});
function stageDay(stage: string, day: string | null): string {
  if (!day) return "";
  if (stage === "self" || stage === "manager") return t("lifecycle.reviews.round.dueOn", { date: fmt.day(day, "medium") });
  return fmt.instant(day, "date");
}

const progress = computed(() => round.value?.progress ?? null);
const share = (part: number) => (progress.value?.people ? Math.round((100 * part) / progress.value.people) : 0);

// Actions
const editing = ref(false);
const openRound = useReviewMutation((cid, id: number) => reviewsApi.openRound(cid, id));
const advance = useReviewMutation((cid, id: number) => reviewsApi.advanceRound(cid, id));
const close = useReviewMutation((cid, id: number) => reviewsApi.closeRound(cid, id));
const remind = useReviewMutation((cid, id: number) => reviewsApi.remind(cid, id));
const remove = useReviewMutation((cid, id: number) => reviewsApi.deleteRound(cid, id));

async function runOpen(): Promise<void> {
  if (!round.value) return;
  const answer = await confirm({ title: t("lifecycle.reviews.round.openTitle"), message: t("lifecycle.reviews.round.openBody"), confirmLabel: t("lifecycle.reviews.round.open"), icon: Send });
  if (!answer) return;
  const done = await openRound.mutateAsync(round.value.id);
  toast.success(t("lifecycle.reviews.wizard.opened", { count: done.progress.people }, done.progress.people));
}
async function runAdvance(): Promise<void> {
  if (!round.value) return;
  const late = round.value.progress.people - round.value.progress.self_sent;
  const answer = await confirm({
    title: t("lifecycle.reviews.round.advanceTitle"),
    message: late ? t("lifecycle.reviews.round.advanceLate", { count: late }, late) : t("lifecycle.reviews.round.advanceBody"),
    confirmLabel: t("lifecycle.reviews.round.advance"),
    icon: Play,
  });
  if (!answer) return;
  await advance.mutateAsync(round.value.id);
  toast.success(t("lifecycle.reviews.round.advanced"));
}
async function runClose(): Promise<void> {
  if (!round.value) return;
  const unpublished = round.value.progress.people - round.value.progress.published;
  const answer = await confirm({
    title: t("lifecycle.reviews.round.closeTitle"),
    message: unpublished ? t("lifecycle.reviews.round.closeUnpublished", { count: unpublished }, unpublished) : t("lifecycle.reviews.round.closeBody"),
    confirmLabel: t("lifecycle.reviews.round.close"),
    tone: unpublished ? "danger" : "primary",
    icon: Lock,
  });
  if (!answer) return;
  await close.mutateAsync(round.value.id);
  toast.success(t("lifecycle.reviews.round.closed"));
}
async function runRemind(): Promise<void> {
  if (!round.value) return;
  const done = await remind.mutateAsync(round.value.id);
  toast.success(t("lifecycle.reviews.round.reminded", { count: done.people + done.reviewers }, done.people + done.reviewers));
}
async function runDelete(): Promise<void> {
  if (!round.value) return;
  const answer = await confirm({ title: t("lifecycle.reviews.round.deleteTitle"), message: t("lifecycle.reviews.round.deleteBody"), confirmLabel: t("lifecycle.reviews.round.delete"), tone: "danger", icon: Trash2 });
  if (!answer) return;
  await remove.mutateAsync(round.value.id);
  toast.success(t("lifecycle.reviews.round.deleted"));
  void router.push(back.value);
}
const behind = computed(() => {
  const value = round.value;
  if (!value) return 0;
  return value.status === "self" ? value.progress.people - value.progress.self_sent : value.progress.people - value.progress.published;
});

// One person's row
function openReview(row: ReviewRow): void {
  if (!row.can_open) return;
  void router.push({ path: `/c/${company.currentId}/lifecycle/reviews/${roundId.value}/${row.id}` });
}
const reassigning = ref<ReviewRow | null>(null);
const newReviewer = ref<number | null>(null);
const reassign = useReviewMutation((cid, input: { id: number; reviewer: number }) => reviewsApi.reassign(cid, input.id, input.reviewer));
function startReassign(row: ReviewRow): void {
  reassigning.value = row;
  newReviewer.value = row.reviewer?.id ?? null;
}
async function saveReassign(): Promise<void> {
  if (!reassigning.value || !newReviewer.value) return;
  try {
    const row = await reassign.mutateAsync({ id: reassigning.value.id, reviewer: newReviewer.value });
    toast.success(t("lifecycle.reviews.round.reassigned", { name: row.member.name, reviewer: row.reviewer?.name ?? "" }));
    reassigning.value = null;
  } catch {
    // The server said why (they don't run reviews, they don't see the branch).
  }
}
const takeOut = useReviewMutation((cid, id: number) => reviewsApi.remove(cid, id));
async function runTakeOut(row: ReviewRow): Promise<void> {
  const answer = await confirm({ title: t("lifecycle.reviews.round.removeTitle", { name: row.member.name }), message: t("lifecycle.reviews.round.removeBody"), confirmLabel: t("lifecycle.reviews.round.remove"), tone: "danger", icon: UserMinus });
  if (!answer) return;
  await takeOut.mutateAsync(row.id);
  toast.success(t("lifecycle.reviews.round.removed", { name: row.member.name }));
}
function rowMenu(row: ReviewRow): MenuEntry[] {
  return [
    { label: t("lifecycle.reviews.round.reassign"), icon: UserRoundPen, onSelect: () => startReassign(row) },
    { label: t("lifecycle.reviews.round.remove"), icon: UserMinus, danger: true, onSelect: () => void runTakeOut(row) },
  ];
}
const canManageRows = computed(() => !!round.value?.can.run && round.value.status !== "closed" && round.value.status !== "draft");

function selfLabel(row: ReviewRow): string {
  if (row.self_state === "sent") return t("lifecycle.reviews.selfState.sent");
  if (row.late.includes("self")) return t("lifecycle.reviews.selfState.late");
  return t(`lifecycle.reviews.selfState.${row.self_state}`);
}
function selfTone(row: ReviewRow) {
  if (row.self_state === "sent") return "success" as const;
  if (row.late.includes("self")) return "danger" as const;
  return row.self_state === "draft" ? ("info" as const) : ("neutral" as const);
}
function managerLabel(row: ReviewRow): string {
  if (row.manager_state === "published") return t("lifecycle.reviews.managerState.published");
  if (row.late.includes("manager")) return t("lifecycle.reviews.managerState.late");
  return t(`lifecycle.reviews.managerState.${row.manager_state}`);
}
function managerTone(row: ReviewRow) {
  if (row.manager_state === "published") return "success" as const;
  if (row.late.includes("manager")) return "danger" as const;
  return row.manager_state === "draft" ? ("info" as const) : ("neutral" as const);
}
const audienceLine = computed(() => {
  const value = round.value;
  if (!value) return "";
  const parts = [...value.audience.positions, ...value.audience.branches].map((item) => item.name);
  return parts.length ? parts.join(", ") : t("lifecycle.reviews.everyone");
});
</script>

<template>
  <div class="flex flex-col gap-5">
    <div v-if="query.isPending.value" class="flex flex-col gap-4">
      <SkeletonBlock height="64px" radius="14px" />
      <SkeletonBlock height="120px" radius="16px" />
      <SkeletonBlock height="360px" radius="16px" />
    </div>
    <ErrorState v-else-if="query.isError.value || !round" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <PageHeader
        :title="round.name"
        :description="`${fmt.day(round.period_start, 'medium')} – ${fmt.day(round.period_end, 'medium')} · ${audienceLine}`"
        :back="back"
        :back-label="t('lifecycle.nav.reviews')"
      >
        <template #meta><StatusPill size="sm" :tone="ROUND_TONES[round.status]" :label="t(`lifecycle.reviews.status.${round.status}`)" /></template>
        <template #actions>
          <template v-if="round.can.run">
            <UiButton v-if="round.can.edit && round.status === 'draft'" :icon="Pencil" @click="editing = true">{{ t("lifecycle.reviews.round.edit") }}</UiButton>
            <UiButton v-if="round.can.remind && behind > 0" :icon="BellRing" :loading="remind.isPending.value" @click="runRemind">{{ t("lifecycle.reviews.round.remind") }}</UiButton>
            <UiButton v-if="round.can.open" variant="primary" :icon="Send" :loading="openRound.isPending.value" @click="runOpen">{{ t("lifecycle.reviews.round.open") }}</UiButton>
            <UiButton v-if="round.can.advance" variant="primary" :icon="Play" :loading="advance.isPending.value" @click="runAdvance">{{ t("lifecycle.reviews.round.advance") }}</UiButton>
            <UiButton v-if="round.status === 'manager' && round.can.close" variant="primary" :icon="Lock" :loading="close.isPending.value" @click="runClose">{{ t("lifecycle.reviews.round.close") }}</UiButton>
            <IconButton v-if="round.can.delete" :icon="Trash2" :label="t('lifecycle.reviews.round.delete')" variant="secondary" @click="runDelete" />
          </template>
          <ExportButton v-if="round.status !== 'draft'" kind="lifecycle.reviews" :params="{ round: round.id }" sensitive />
        </template>
      </PageHeader>

      <!-- Where the round is -->
      <section class="ui-card p-4 sm:p-5" data-stages>
        <ol class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <li v-for="(item, index) in stages" :key="item.stage" class="relative flex items-start gap-2.5">
            <span
              :class="[
                'grid size-8 shrink-0 place-items-center rounded-full text-xs font-semibold',
                item.state === 'done' ? 'bg-success text-white' : item.state === 'current' ? 'bg-primary text-white ring-4 ring-[color-mix(in_srgb,var(--c-primary)_18%,transparent)]' : 'border border-line bg-surface text-muted',
              ]"
            >
              <CircleCheck v-if="item.state === 'done'" :size="15" aria-hidden="true" />
              <template v-else>{{ index + 1 }}</template>
            </span>
            <div class="min-w-0">
              <p :class="['text-sm font-medium', item.state === 'next' ? 'text-muted' : 'text-fg']">{{ t(`lifecycle.reviews.stage.${item.stage}`) }}</p>
              <p class="text-xs text-muted">{{ stageDay(item.stage, item.day) }}</p>
            </div>
          </li>
        </ol>
        <p v-if="round.status === 'self' && round.reviewers_begin_on" class="mt-3 text-xs text-muted" data-auto-advance>
          {{ round.self_due_on < today ? t("lifecycle.reviews.round.graceLine", { date: fmt.day(round.reviewers_begin_on, "weekday") }) : t("lifecycle.reviews.round.autoLine", { date: fmt.day(round.reviewers_begin_on, "weekday") }) }}
        </p>
      </section>

      <!-- How far everyone has got -->
      <div v-if="round.status !== 'draft' && progress" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-progress>
        <div class="ui-card p-4">
          <p class="text-xs font-medium text-muted">{{ t("lifecycle.reviews.round.selfSent") }}</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-fg">{{ progress.self_sent }}<span class="text-sm font-normal text-muted"> / {{ progress.people }}</span></p>
          <ProgressBar class="mt-2" :value="share(progress.self_sent)" size="sm" tone="info" :label="t('lifecycle.reviews.round.selfSent')" />
        </div>
        <div class="ui-card p-4">
          <p class="text-xs font-medium text-muted">{{ t("lifecycle.reviews.round.published") }}</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-fg">{{ progress.published }}<span class="text-sm font-normal text-muted"> / {{ progress.people }}</span></p>
          <ProgressBar class="mt-2" :value="share(progress.published)" size="sm" tone="success" :label="t('lifecycle.reviews.round.published')" />
        </div>
        <div class="ui-card p-4">
          <p class="text-xs font-medium text-muted">{{ t("lifecycle.reviews.round.late") }}</p>
          <p :class="['mt-1 text-2xl font-semibold tabular-nums', progress.late ? 'text-danger' : 'text-fg']">{{ progress.late }}</p>
          <p class="mt-1 text-xs text-muted">{{ t("lifecycle.reviews.round.lateLine", { self: progress.self_late, manager: progress.manager_late }) }}</p>
        </div>
        <div class="ui-card p-4">
          <p class="text-xs font-medium text-muted">{{ round.mine ? t("lifecycle.reviews.round.mine") : t("lifecycle.reviews.round.acknowledged") }}</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-fg">{{ round.mine || progress.acknowledged }}</p>
          <p class="mt-1 text-xs text-muted">{{ round.mine ? t("lifecycle.reviews.round.mineLine") : t("lifecycle.reviews.round.acknowledgedLine", { count: progress.published }, progress.published) }}</p>
        </div>
      </div>

      <div class="no-scrollbar max-w-full self-start overflow-x-auto">
        <SegmentedControl v-model="tab" :options="tabs" :aria-label="round.name" />
      </div>

      <!-- People -->
      <section v-if="tab === 'people'" class="ui-card overflow-hidden" data-people>
        <EmptyState v-if="round.status === 'draft'" :icon="Users" tone="neutral" :title="t('lifecycle.reviews.round.draftTitle')" :description="t('lifecycle.reviews.round.draftBody')" class="py-10">
          <UiButton v-if="round.can.open" variant="primary" :icon="Send" @click="runOpen">{{ t("lifecycle.reviews.round.open") }}</UiButton>
        </EmptyState>
        <template v-else>
          <div class="flex flex-wrap items-center gap-2 border-b border-line p-3 sm:px-4">
            <TextInput v-model="q" class="w-full sm:w-64" :icon="Search" size="sm" clearable :debounce="250" :placeholder="t('lifecycle.reviews.round.search')" />
            <div class="no-scrollbar max-w-full overflow-x-auto">
              <SegmentedControl v-model="state" :options="STATE_OPTIONS" size="sm" :aria-label="t('lifecycle.reviews.round.filter')" />
            </div>
            <label class="ml-auto flex items-center gap-2 text-sm text-muted">
              <ToggleSwitch v-model="mine" :aria-label="t('lifecycle.reviews.round.onlyMine')" />{{ t("lifecycle.reviews.round.onlyMine") }}
            </label>
          </div>
          <div v-if="rows.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 5" :key="n" height="56px" radius="12px" /></div>
          <ErrorState v-else-if="rows.isError.value" :error="rows.error.value" :retry="() => rows.refetch()" compact />
          <EmptyState v-else-if="!rows.data.value?.length" :icon="Users" tone="neutral" size="sm" :title="t('lifecycle.reviews.round.noRows')" :description="t('lifecycle.reviews.round.noRowsBody')" class="py-10" />
          <ul v-else class="divide-y divide-line" data-rows>
            <li
              v-for="row in rows.data.value"
              :key="row.id"
              :class="['group flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-3 sm:flex-nowrap sm:px-4', row.can_open ? 'cursor-pointer hover:bg-surface-2/50' : '']"
              :data-row="row.id"
              @click="openReview(row)"
            >
              <div class="flex min-w-0 flex-1 items-center gap-3 sm:basis-1/3">
                <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-fg">{{ row.member.name }}</p>
                  <p class="truncate text-xs text-muted">{{ [row.position, row.home_branch?.name].filter(Boolean).join(" · ") }}</p>
                </div>
              </div>
              <div class="flex min-w-0 items-center gap-1.5 text-xs text-muted sm:w-44">
                <UserRoundPen :size="13" class="shrink-0" aria-hidden="true" />
                <span class="truncate">{{ row.reviewer?.name ?? "—" }}</span>
              </div>
              <div class="flex flex-wrap items-center gap-1.5 sm:w-64">
                <StatusPill size="sm" variant="outline" :tone="selfTone(row)" :label="selfLabel(row)" />
                <StatusPill size="sm" variant="outline" :tone="managerTone(row)" :label="managerLabel(row)" />
              </div>
              <div class="flex items-center gap-1.5 sm:w-56 sm:justify-end">
                <template v-if="row.published_at && row.can_open">
                  <StatusPill size="sm" :tone="ratingTone(row.rating)" :icon="Star" :label="row.rating ? `${row.rating}/5` : '—'" />
                  <StatusPill v-if="row.outcome && row.outcome !== 'none'" size="sm" variant="outline" :tone="row.outcome_state ? OUTCOME_STATE_TONES[row.outcome_state] : OUTCOME_TONES[row.outcome]" :label="t(`lifecycle.reviews.outcome.${row.outcome}`)" />
                </template>
                <Lock v-else-if="!row.can_open" :size="14" class="text-subtle" :aria-label="t('lifecycle.reviews.round.private')" />
              </div>
              <div class="w-8 shrink-0" @click.stop>
                <DropdownMenu v-if="canManageRows && !row.published_at" :items="rowMenu(row)" align="end">
                  <template #trigger><IconButton :icon="MoreHorizontal" size="sm" :label="t('lifecycle.reviews.round.rowMenu')" /></template>
                </DropdownMenu>
              </div>
            </li>
          </ul>
        </template>
      </section>

      <RoundResults v-else-if="tab === 'results'" :round-id="round.id" />

      <section v-else class="ui-card p-4 sm:p-5" data-questions-tab>
        <ol class="flex flex-col gap-2">
          <li v-for="(question, index) in round.questions" :key="question.id" class="flex items-start gap-3 rounded-[12px] border border-line px-3.5 py-3">
            <span class="grid size-6 shrink-0 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary">{{ index + 1 }}</span>
            <p class="min-w-0 flex-1 text-sm text-fg">{{ question.text }}</p>
            <StatusPill size="sm" variant="outline" tone="neutral" :label="t(`lifecycle.reviews.kind.${question.kind}`)" />
          </li>
        </ol>
      </section>

      <RoundWizard v-model:open="editing" :round="round" />
      <UiDialog :open="!!reassigning" size="sm" :title="t('lifecycle.reviews.round.reassignTitle', { name: reassigning?.member.name ?? '' })" :description="t('lifecycle.reviews.round.reassignBody')" @update:open="(value) => !value && (reassigning = null)">
        <PersonPicker v-model="newReviewer" :exclude="reassigning ? [reassigning.member.id] : []" :clearable="false" />
        <template #footer>
          <UiButton variant="ghost" @click="reassigning = null">{{ t("common.cancel") }}</UiButton>
          <UiButton variant="primary" :loading="reassign.isPending.value" :disabled="!newReviewer" @click="saveReassign">{{ t("lifecycle.reviews.round.reassignSave") }}</UiButton>
        </template>
      </UiDialog>
    </template>
  </div>
</template>
