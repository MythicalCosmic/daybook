<script setup lang="ts">
/**
 * Waiting for my check (plan §6.2): finished work with large proof photos, oldest first. `A`
 * accepts the focused card, `R` sends it back (asks why), `J`/`K` move between cards. Accepting
 * waits 5 seconds with "Undo" before it reaches the server, so a slip costs nothing.
 */
import { Check, ChevronRight, ClipboardCheck, FileText, RotateCcw } from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KbdKey from "@/components/KbdKey.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { dismissToast, toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { patchQuery } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { tasksApi, useRefreshTasks, useReviews } from "../api";
import TaskDrawer from "../components/TaskDrawer.vue";
import { cardKey } from "../meta";
import type { TaskReview } from "../types";

const UNDO_MS = 5000;

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefreshTasks();

const query = useReviews();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const hidden = ref<Set<number>>(new Set());
const cards = computed(() => (query.data.value?.results ?? []).filter((task) => !hidden.value.has(task.id)));
const total = computed(() => cards.value.length);

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
    await tasksApi.confirm(company.currentId!, task.id);
  } catch {
    hide(task.id, false); // back in the list; the HTTP layer showed why
  } finally {
    void refresh();
  }
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
    reason: "required",
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

function open(task: TaskReview): void {
  patchQuery(router, { task: String(task.id) }, true);
}
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
        <UiButton :to="`/c/${company.currentId}/tasks`" :icon-right="ChevronRight">{{ t("tasks.reviews.toTasks") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else ref="grid">
    <TransitionGroup name="list" tag="div" class="relative grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="task in cards"
        :key="task.id"
        data-review-card
        tabindex="0"
        class="ui-card group/card flex min-w-0 flex-col overflow-hidden outline-offset-2 transition-[border-color,box-shadow] hover:border-line-strong focus-visible:border-primary focus-visible:shadow-raised"
        @focus="focusedId = task.id"
      >
        <div :class="['relative w-full overflow-hidden bg-surface-2', task.proof_photo ? 'aspect-[4/3]' : 'h-32 sm:h-auto sm:aspect-[4/3]']">
          <ProofThumb v-if="task.proof_photo" :src="task.proof_photo" :images="[{ src: task.proof_photo, caption: task.title }]" size="fill" class="!rounded-none" />
          <!-- No photo: what was reported, else what was asked, so the card still says something. -->
          <div v-else class="flex h-full flex-col justify-center gap-2 p-5">
            <template v-if="task.proof_text">
              <FileText :size="18" class="text-subtle" aria-hidden="true" />
              <p class="line-clamp-5 text-sm text-fg">“{{ task.proof_text }}”</p>
            </template>
            <template v-else-if="task.description">
              <p class="text-[11px] font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("tasks.reviews.asked") }}</p>
              <p class="line-clamp-5 whitespace-pre-line text-sm text-muted">{{ task.description }}</p>
            </template>
            <p v-else class="flex flex-col items-center gap-2 text-center text-sm text-muted">
              <FileText :size="22" class="text-subtle" aria-hidden="true" />{{ task.proof === "none" ? t("tasks.reviews.noProof") : t("tasks.reviews.noPhoto") }}
            </p>
            <p v-if="(task.proof_text || task.description) && !task.proof_photo" class="mt-auto text-xs text-subtle">{{ task.proof === "none" ? t("tasks.reviews.noProof") : t("tasks.reviews.noPhoto") }}</p>
          </div>
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
            <RelativeTime :value="task.completed_at" class="shrink-0 text-xs" />
          </div>
          <p v-if="task.checklist.total" class="text-xs text-muted">{{ t("tasks.reviews.checklist", { done: task.checklist.done, total: task.checklist.total }) }}</p>
          <p v-if="task.proof_photo && task.proof_text" class="line-clamp-2 rounded-[8px] bg-surface-2 px-2.5 py-1.5 text-sm text-fg">{{ task.proof_text }}</p>
          <div class="mt-auto flex gap-2 pt-1">
            <UiButton variant="primary" size="sm" :icon="Check" class="flex-1" @click="accept(task)">{{ t("tasks.action.confirm") }}</UiButton>
            <UiButton size="sm" :icon="RotateCcw" class="flex-1" @click="sendBack(task)">{{ t("tasks.action.return") }}</UiButton>
          </div>
        </div>
      </article>
    </TransitionGroup>
    </div>

    <TaskDrawer />
  </div>
</template>
