<script setup lang="ts">
/**
 * Waiting for my check (plan §6.2): finished one-off work with large proof photos, oldest first.
 * Routine work is confirmed on its own page (Routines → To confirm), linked from here. `A`
 * accepts the focused card, `R` sends it back (asks why, with ready reasons), `J`/`K` move between
 * cards. Accepting waits 5 seconds with "Undo" before it reaches the server, so a slip costs nothing.
 *
 * Above the queue, what waits for an answer: "Need more time" (Approve / Decline right here,
 * contract 8) and "Can't do it" (opens the task with its three ways out, contract 7). Work without
 * a photo gets a compact card below the photo cards instead of an empty picture frame.
 */
import { Ban, Check, ChevronRight, ClipboardCheck, FileText, Hourglass, Repeat, RotateCcw, X } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KbdKey from "@/components/KbdKey.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { returnReasonFields } from "@/components/returnReasons";
import { useConfirm } from "@/components/useConfirm";
import { dismissToast, toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { usePulseCount } from "@/core/pulse";
import { todayIn, zonedDay } from "@/lib/dates";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { patchQuery } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { tasksApi, useRefreshTasks, useReviews, useTaskList, useTasksSettings } from "../api";
import TaskDrawer from "../components/TaskDrawer.vue";
import { BLOCKED_PARAMS, EXTENSION_PARAMS } from "../filters";
import { cardKey, lateness, minutesBetween } from "../meta";
import type { TaskReview, TaskRow } from "../types";

const UNDO_MS = 5000;

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
// Accept and send back are finger-sized on phones.
const { isPhone } = useBreakpoints();
const tap = computed(() => (isPhone.value ? "lg" : "sm"));
const refresh = useRefreshTasks();

const query = useReviews();
// "All checked" with the company's rule for finished work (§15.3): with "accept automatically", only
// work whose giver asked for a check comes here, which an owner should not have to guess.
const finishRule = useTasksSettings();
const ruleNote = computed(() => {
  const rule = finishRule.data.value?.on_finish;
  return rule ? t(`tasks.reviews.rule.${rule}`) : "";
});
/** The company's wait: what nobody checks in time is accepted on its own. */
const waitNote = computed(() => {
  const hours = finishRule.data.value?.auto_accept_after_hours;
  return hours ? t("tasks.reviews.ruleWait", { n: hours }) : "";
});
const routineChecks = usePulseCount("tasks.routine_review");
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const hidden = ref<Set<number>>(new Set());
const visible = computed(() => (query.data.value?.results ?? []).filter((task) => !hidden.value.has(task.id)));
/** Photo cards first (the big pictures to look at), then the compact ones; each oldest first. */
const photoCards = computed(() => visible.value.filter((task) => !!task.proof_photo));
const plainCards = computed(() => visible.value.filter((task) => !task.proof_photo));
/** The cards in the order they stand on the page: what J/K walk through. */
const cards = computed(() => [...photoCards.value, ...plainCards.value]);
const total = computed(() => cards.value.length);

// Waiting for an answer ------------------------------------------------------------------------
// The list needs tasks.view_all: without it (or on a backend without these filters) the queries
// fail or find nothing, and the section stays away.
const extensionList = useTaskList({ ...EXTENSION_PARAMS, page_size: 50 });
const blockedList = useTaskList({ ...BLOCKED_PARAMS, page_size: 50 });
const answers = computed(() => {
  const rows: Array<{ kind: "extension" | "blocked"; task: TaskRow }> = [];
  for (const task of extensionList.data.value?.results ?? []) if (task.extension) rows.push({ kind: "extension", task });
  for (const task of blockedList.data.value?.results ?? []) if (task.blocker) rows.push({ kind: "blocked", task });
  return rows;
});
/** The asked-for deadline on its button: the time when it's today, else the day too. */
const untilLabel = (iso: string) => (zonedDay(iso, company.timezone) === todayIn(company.timezone) ? fmt.instant(iso, "time") : fmt.instant(iso, "short"));
const deciding = ref<Set<string>>(new Set());
async function decide(task: TaskRow, approve: boolean): Promise<void> {
  const key = `${task.id}:${approve}`;
  deciding.value = new Set(deciding.value).add(key);
  try {
    await tasksApi.decideExtension(company.currentId!, task.id, approve);
    toast.success(t(approve ? "tasks.extension.approvedToast" : "tasks.extension.declinedToast"), { description: task.title });
  } catch {
    // the HTTP layer showed why
  } finally {
    const next = new Set(deciding.value);
    next.delete(key);
    deciding.value = next;
    void refresh();
  }
}

const pending = new Map<number, { timer: ReturnType<typeof setTimeout>; toastId: string }>();

function hide(id: number, value: boolean): void {
  const next = new Set(hidden.value);
  if (value) next.add(id);
  else next.delete(id);
  hidden.value = next;
}

async function send(task: TaskReview): Promise<void> {
  pending.delete(task.id);
  try {
    await tasksApi.confirm(company.currentId!, task.id, { toast: false });
    void refresh();
  } catch (error) {
    // Several people may check the same work (audit X-11): when someone else decided it meanwhile,
    // it just leaves the queue. Only work still waiting comes back, with the reason it failed.
    await refresh();
    if (stillWaiting(task.id)) {
      hide(task.id, false);
      toast.error(isApiError(error) && error.detail ? error.detail : t("common.error.generic"), { description: task.title });
    } else {
      toast.info(t("tasks.reviews.decidedElsewhere"), { description: task.title });
    }
  }
}

/** Whether the queue (as the server has it now) still holds this task. */
function stillWaiting(id: number): boolean {
  return (query.data.value?.results ?? []).some((item) => item.id === id);
}

function accept(task: TaskReview): void {
  const index = cards.value.findIndex((card) => card.id === task.id);
  hide(task.id, true);
  const toastId = `tasks.review.${task.id}`;
  const timer = setTimeout(() => void send(task), UNDO_MS);
  pending.set(task.id, { timer, toastId });
  toast.success(t("tasks.reviews.accepted"), {
    id: toastId,
    description: task.title,
    duration: UNDO_MS,
    action: {
      label: t("common.undo"),
      onClick: () => {
        const entry = pending.get(task.id);
        if (entry) clearTimeout(entry.timer);
        pending.delete(task.id);
        hide(task.id, false);
      },
    },
  });
  void focusIndex(index);
}

async function sendBack(task: TaskReview): Promise<void> {
  const answer = await confirm({
    title: t("tasks.sendBack.title"),
    message: task.title,
    ...returnReasonFields(t),
    reasonLabel: t("tasks.sendBack.reason"),
    reasonPlaceholder: t("tasks.sendBack.placeholder"),
    confirmLabel: t("tasks.action.return"),
    tone: "danger",
  });
  if (!answer) return;
  const index = cards.value.findIndex((card) => card.id === task.id);
  hide(task.id, true);
  try {
    await tasksApi.sendBack(company.currentId!, task.id, answer.reason);
    toast.success(t("tasks.toast.returned"), { description: task.title });
  } catch {
    hide(task.id, false);
  } finally {
    void refresh();
  }
  void focusIndex(index);
}

onBeforeUnmount(() => {
  // Leaving the page doesn't undo anything: send what is waiting now.
  for (const [id, entry] of pending) {
    clearTimeout(entry.timer);
    dismissToast(entry.toastId);
    const task = (query.data.value?.results ?? []).find((item) => item.id === id);
    if (task) void send(task);
  }
});

// Keyboard ----------------------------------------------------------------------------------
const grid = ref<HTMLElement | null>(null);
const focusedId = ref<number | null>(null);
function cardElements(): HTMLElement[] {
  return [...(grid.value?.querySelectorAll<HTMLElement>("[data-review-card]") ?? [])];
}
async function focusIndex(index: number): Promise<void> {
  await nextTick();
  const elements = cardElements();
  elements[Math.min(Math.max(0, index), elements.length - 1)]?.focus();
}
function focused(): TaskReview | null {
  const id = focusedId.value ?? cards.value[0]?.id;
  return cards.value.find((card) => card.id === id) ?? null;
}
function step(direction: 1 | -1): void {
  const index = cards.value.findIndex((card) => card.id === focused()?.id);
  void focusIndex(index + direction);
}
useHotkey("a", () => {
  const task = focused();
  if (task) accept(task);
}, { description: "tasks.keys.accept", group: "page" });
useHotkey("r", () => {
  const task = focused();
  if (task) void sendBack(task);
}, { description: "tasks.keys.sendBack", group: "page" });
useHotkey("j", () => step(1), { description: "tasks.keys.next", group: "page" });
useHotkey("k", () => step(-1), { description: "tasks.keys.previous", group: "page" });

function open(task: { id: number }): void {
  patchQuery(router, { task: String(task.id) }, true);
}

/** How late the work came in (R2 T29), or null when it was on time or had no deadline. */
function lateBy(task: TaskReview): string | null {
  if (!task.due_at || !task.completed_at) return null;
  const minutes = minutesBetween(task.due_at, task.completed_at);
  if (minutes <= 0) return null;
  return t("tasks.due.lateBy", { time: lateness(minutes, { min: t("tasks.unit.min"), h: t("tasks.unit.h"), d: t("tasks.unit.d") }) });
}

/** Nothing was reported: fine when nothing was asked, worth a look when a photo or note was. */
const missing = (task: TaskReview) => (task.proof === "none" ? { text: t("tasks.reviews.noProof"), warn: false } : { text: t("tasks.reviews.noPhoto"), warn: true });
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <PageHeader :title="t('tasks.reviews.title')" :description="t('tasks.reviews.description')">
      <template #actions>
        <p class="hidden items-center gap-1.5 text-sm text-muted md:flex">
          <KbdKey keys="a" />{{ t("tasks.reviews.keyAccept") }}<span class="mx-1 text-subtle">·</span><KbdKey keys="r" />{{ t("tasks.reviews.keyReturn") }}<span class="mx-1 text-subtle">·</span><KbdKey :keys="['j', 'k']" />{{ t("tasks.reviews.keyMove") }}
        </p>
      </template>
    </PageHeader>

    <p v-if="routineChecks > 0" class="-mt-2 flex flex-wrap items-center gap-1.5 text-sm text-muted" data-testid="routine-checks">
      <Repeat :size="15" class="text-subtle" aria-hidden="true" />{{ t("tasks.reviews.routines", { n: routineChecks }, routineChecks) }}
      <RouterLink :to="`/c/${company.currentId}/routines/confirm`" class="inline-flex items-center font-medium text-accent-fg hover:underline">{{ t("tasks.reviews.toRoutines") }}<ChevronRight :size="14" /></RouterLink>
    </p>

    <!-- The company's rule above the work too, not only on the empty page: why these and not all. -->
    <p v-if="ruleNote && query.data.value && total" class="-mt-2 max-w-[860px] text-sm text-muted" data-testid="reviews-rule-top">
      {{ ruleNote }}<template v-if="waitNote"> {{ waitNote }}</template>
      <RouterLink v-if="company.can('company.settings')" :to="`/c/${company.currentId}/settings/tasks`" class="ml-1 font-medium text-primary hover:underline">{{ t("tasks.reviews.ruleLink") }}</RouterLink>
    </p>

    <!-- Waiting for your answer: more time asked, "can't do it". -->
    <section v-if="answers.length" class="ui-card overflow-hidden" :aria-label="t('tasks.answers.title')" data-testid="answers">
      <h2 class="flex items-center gap-2 border-b border-line px-4 py-2.5 text-sm font-semibold text-fg">
        {{ t("tasks.answers.title") }}<span class="rounded-full bg-surface-2 px-1.5 text-xs font-semibold tabular-nums text-muted">{{ answers.length }}</span>
      </h2>
      <ul class="divide-y divide-line">
        <li v-for="item in answers" :key="`${item.kind}:${item.task.id}`" class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3" :data-answer="item.kind">
          <span :class="['grid size-8 shrink-0 place-items-center rounded-full', item.kind === 'extension' ? 'bg-warning-soft text-warning' : 'bg-danger-soft text-danger']" aria-hidden="true">
            <component :is="item.kind === 'extension' ? Hourglass : Ban" :size="15" />
          </span>
          <div class="min-w-0 flex-1 basis-[240px]">
            <button type="button" class="line-clamp-1 text-left text-sm font-semibold text-fg hover:underline" @click="open(item.task)">{{ item.task.title }}</button>
            <p class="mt-0.5 text-sm text-muted">
              <span class="font-medium text-fg">{{ item.task.assignee.name }}</span>
              <template v-if="item.kind === 'extension' && item.task.extension">
                · {{ t("tasks.extension.until", { time: fmt.instant(item.task.extension.until, "short") }) }}<template v-if="item.task.extension.note"> · {{ t("tasks.quoted", { text: item.task.extension.note }) }}</template>
              </template>
              <template v-else-if="item.task.blocker">
                · {{ t(`tasks.blocker.reason.${item.task.blocker.reason_code}`) }}<template v-if="item.task.blocker.note"> · {{ t("tasks.quoted", { text: item.task.blocker.note }) }}</template>
              </template>
            </p>
          </div>
          <div class="flex shrink-0 gap-2 max-sm:w-full max-sm:flex-col">
            <template v-if="item.kind === 'extension' && item.task.extension">
              <UiButton :size="tap" variant="primary" :icon="Check" class="max-sm:w-full" :loading="deciding.has(`${item.task.id}:true`)" data-testid="answer-approve" @click="decide(item.task, true)">
                {{ t("tasks.extension.approve", { time: untilLabel(item.task.extension.until) }) }}
              </UiButton>
              <UiButton :size="tap" :icon="X" class="max-sm:w-full" :loading="deciding.has(`${item.task.id}:false`)" data-testid="answer-decline" @click="decide(item.task, false)">{{ t("tasks.extension.decline") }}</UiButton>
            </template>
            <UiButton v-else :size="tap" :icon-right="ChevronRight" class="max-sm:w-full" @click="open(item.task)">{{ t("tasks.answers.open") }}</UiButton>
          </div>
        </li>
      </ul>
    </section>

    <div v-if="skeleton" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <div v-for="n in 6" :key="n" class="ui-card flex flex-col gap-3 p-3">
        <SkeletonBlock height="220px" radius="10px" />
        <SkeletonBlock width="70%" />
        <SkeletonBlock width="45%" height="12px" />
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !total" class="ui-card">
      <EmptyState tone="success" size="lg" :icon="ClipboardCheck" :title="t('tasks.reviews.emptyTitle')" :description="t('tasks.reviews.emptyBody')">
        <p v-if="ruleNote" class="max-w-[440px] text-balance text-sm text-muted" data-testid="reviews-rule">
          {{ ruleNote }}
          <RouterLink v-if="company.can('company.settings')" :to="`/c/${company.currentId}/settings/tasks`" class="font-medium text-primary hover:underline">{{ t("tasks.reviews.ruleLink") }}</RouterLink>
        </p>
        <UiButton :to="`/c/${company.currentId}/tasks`" :icon-right="ChevronRight">{{ t("tasks.reviews.toTasks") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else ref="grid" class="flex flex-col gap-4">
      <h2 v-if="photoCards.length && plainCards.length" class="-mb-1 text-sm font-semibold text-muted">{{ t("tasks.reviews.withPhoto") }} · {{ photoCards.length }}</h2>
      <TransitionGroup v-if="photoCards.length" name="list" tag="div" class="relative grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <article
          v-for="task in photoCards"
          :key="task.id"
          data-review-card
          tabindex="0"
          class="ui-card group/card flex min-w-0 flex-col overflow-hidden outline-offset-2 transition-[border-color,box-shadow] hover:border-line-strong focus-visible:border-primary focus-visible:shadow-raised"
          @focus="focusedId = task.id"
        >
          <div class="relative aspect-[4/3] w-full overflow-hidden bg-surface-2">
            <ProofThumb :src="task.proof_photo!" :images="[{ src: task.proof_photo!, caption: task.title }]" size="fill" class="!rounded-none" />
            <span v-if="task.reward" class="absolute left-2 top-2 rounded-full bg-surface/90 px-2 py-0.5 text-xs font-semibold text-success shadow-xs">{{ t("tasks.reward.short") }}</span>
          </div>
          <div class="flex flex-1 flex-col gap-2 p-3.5">
            <button type="button" class="line-clamp-2 text-left text-base font-semibold leading-5 text-fg hover:underline" :title="task.project?.name" @click="open(task)">
              <span v-if="task.project" class="mr-1 font-mono text-xs font-semibold text-subtle">{{ cardKey(task.project) }}</span>{{ task.title }}
            </button>
            <div class="flex min-w-0 items-center gap-2 text-sm text-muted">
              <UserAvatar :name="task.assignee.name" :src="task.assignee.photo_url" :size="22" />
              <span class="min-w-0 truncate"><span class="font-medium text-fg">{{ task.assignee.name }}</span><template v-if="task.branch"> · {{ task.branch.name }}</template></span>
              <span class="flex-1" />
              <span class="flex shrink-0 items-center gap-1 text-xs"><RelativeTime :value="task.completed_at" /><span v-if="lateBy(task)" class="font-semibold text-danger" data-testid="late-by">· {{ lateBy(task) }}</span></span>
            </div>
            <p v-if="task.checklist.total" class="text-xs text-muted">{{ t("tasks.reviews.checklist", { done: task.checklist.done, total: task.checklist.total }) }}</p>
            <p v-if="task.proof_text" class="line-clamp-2 rounded-[8px] bg-surface-2 px-2.5 py-1.5 text-sm text-fg">{{ task.proof_text }}</p>
            <div class="mt-auto flex gap-2 pt-1">
              <UiButton variant="primary" :size="tap" :icon="Check" class="flex-1" @click="accept(task)">{{ t("tasks.action.confirm") }}</UiButton>
              <UiButton :size="tap" :icon="RotateCcw" class="flex-1" @click="sendBack(task)">{{ t("tasks.action.return") }}</UiButton>
            </div>
          </div>
        </article>
      </TransitionGroup>

      <!-- No photo: what was reported (else what was asked), on a compact card. -->
      <h2 v-if="photoCards.length && plainCards.length" class="-mb-1 mt-2 text-sm font-semibold text-muted">{{ t("tasks.reviews.withoutPhoto") }} · {{ plainCards.length }}</h2>
      <TransitionGroup v-if="plainCards.length" name="list" tag="div" class="relative grid gap-3 xl:grid-cols-2">
        <article
          v-for="task in plainCards"
          :key="task.id"
          data-review-card
          data-compact
          tabindex="0"
          class="ui-card flex min-w-0 flex-col gap-3 p-3.5 outline-offset-2 transition-[border-color,box-shadow] hover:border-line-strong focus-visible:border-primary focus-visible:shadow-raised sm:flex-row sm:items-center"
          @focus="focusedId = task.id"
        >
          <div class="flex min-w-0 flex-1 flex-col gap-1.5">
            <button type="button" class="line-clamp-2 text-left text-base font-semibold leading-5 text-fg hover:underline" :title="task.project?.name" @click="open(task)">
              <span v-if="task.project" class="mr-1 font-mono text-xs font-semibold text-subtle">{{ cardKey(task.project) }}</span>{{ task.title }}
            </button>
            <div class="flex min-w-0 items-center gap-2 text-sm text-muted">
              <UserAvatar :name="task.assignee.name" :src="task.assignee.photo_url" :size="20" />
              <span class="min-w-0"><span class="font-medium text-fg">{{ task.assignee.name }}</span><template v-if="task.branch"> · {{ task.branch.name }}</template> · <RelativeTime :value="task.completed_at" /><span v-if="lateBy(task)" class="font-semibold text-danger" data-testid="late-by"> · {{ lateBy(task) }}</span></span>
            </div>
            <blockquote v-if="task.proof_text" class="line-clamp-3 rounded-[8px] border-l-[3px] border-primary bg-surface-2 px-2.5 py-1.5 text-sm text-fg">{{ task.proof_text }}</blockquote>
            <p v-else-if="task.description" class="line-clamp-2 text-sm text-muted">
              <span class="text-xs font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("tasks.reviews.asked") }}:</span> {{ task.description }}
            </p>
            <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span v-if="!task.proof_text" :class="['inline-flex items-center gap-1', missing(task).warn ? 'font-medium text-warning' : 'text-subtle']"><FileText :size="12" aria-hidden="true" />{{ missing(task).text }}</span>
              <span v-if="task.checklist.total" class="text-muted">{{ t("tasks.reviews.checklist", { done: task.checklist.done, total: task.checklist.total }) }}</span>
              <span v-if="task.reward" class="font-semibold text-success">{{ t("tasks.reward.short") }}</span>
            </p>
          </div>
          <div class="flex shrink-0 gap-2 sm:w-[260px]">
            <UiButton variant="primary" :size="tap" :icon="Check" class="flex-1" @click="accept(task)">{{ t("tasks.action.confirm") }}</UiButton>
            <UiButton :size="tap" :icon="RotateCcw" class="flex-1" @click="sendBack(task)">{{ t("tasks.action.return") }}</UiButton>
          </div>
        </article>
      </TransitionGroup>
    </div>

    <TaskDrawer />
  </div>
</template>
