<script setup lang="ts">
/**
 * "Ask the tutor": an Ask AI conversation with the tutor (it reads training, the knowledge base,
 * recognition and people, as the asker may see them). A window of fixed height: the messages
 * scroll inside it and the composer stays at its foot. It follows the newest message unless the
 * reader scrolled up; then a "new messages" pill takes them down. The question goes as a turn,
 * polled until answered. For managers of learning the tutor also drafts questions and tests: they
 * show as cards under its answer (TutorDraftCard), "being written" while it works, and nothing is
 * used until the person approves it there.
 */
import { ArrowDown, CircleAlert, GraduationCap, MessageSquarePlus, RotateCcw, Send, Sparkles, X } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import MarkdownView from "@/components/MarkdownView.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { quizKeys, quizzesApi, useConversations, useTutorDrafts } from "../api";
import type { ChatMessage, Question, Turn, TutorDraftCard } from "../types";
import QuestionEditor from "./QuestionEditor.vue";
import TutorDraftCardView from "./TutorDraftCard.vue";

const { t, te } = useI18n();
const cid = useCompanyId();
const company = useCompanyStore();
const canDraft = computed(() => company.can("learning.manage"));
const conversations = useConversations();
const current = ref<number | null>(null);
watch(
  () => conversations.data.value,
  (rows) => {
    if (current.value === null && rows?.length) current.value = rows[0]!.id;
  },
  { immediate: true },
);

const messages = useQuery({
  queryKey: computed(() => quizKeys.of(cid.value, "messages", { conversation: current.value })),
  queryFn: () => quizzesApi.messages(cid.value, current.value ?? 0),
  enabled: computed(() => cid.value > 0 && current.value !== null),
  staleTime: 5_000,
});
const drafts = useTutorDrafts(current, canDraft);

const text = ref("");
const turn = ref<Turn | null>(null);
const failure = ref<{ error: string; question: string } | null>(null);
const asking = ref(false);
const editing = ref<Question | null>(null);
const editorOpen = ref(false);
const working = computed(() => asking.value || turn.value?.status === "queued" || turn.value?.status === "running");

const SUGGESTED = computed(() => (canDraft.value ? ["quizzes.chat.try1", "quizzes.chat.try4", "quizzes.chat.try2"] : ["quizzes.chat.try1", "quizzes.chat.try2", "quizzes.chat.try3"]));

// The thread: each message with the cards of its turn under it; a card whose answer isn't
// written (yet) goes where it falls in time, and while a turn works, at the foot.
interface Entry {
  key: string;
  message: ChatMessage | null;
  cards: TutorDraftCard[];
}
const cards = computed(() => drafts.data.value ?? []);
const thread = computed<Entry[]>(() => {
  const rows = messages.data.value ?? [];
  const ids = new Set(rows.map((row) => row.id));
  const entries: Entry[] = rows.map((message) => ({ key: `m${message.id}`, message, cards: cards.value.filter((card) => card.message_id === message.id) }));
  for (const card of cards.value) {
    if (card.message_id !== null && ids.has(card.message_id)) continue;
    if (working.value && card.message_id === null) continue; // the live turn's: shown below
    const made = Date.parse(card.created_at);
    const at = entries.findLastIndex((entry) => entry.message !== null && Date.parse(entry.message.created_at) <= made);
    entries.splice(at + 1, 0, { key: `c${card.id}`, message: null, cards: [card] });
  }
  return entries;
});
const liveCards = computed(() => (working.value ? cards.value.filter((card) => card.message_id === null) : []));
const writing = computed(() => liveCards.value.some((card) => card.state === "running"));
const empty = computed(() => !messages.data.value?.length && !working.value && !failure.value);
const stepLabel = computed(() => {
  const steps = turn.value?.steps ?? [];
  return steps.length ? steps[steps.length - 1]!.label : t("quizzes.chat.thinking");
});

// Following the newest message --------------------------------------------------------------

const box = ref<HTMLElement | null>(null);
const inner = ref<HTMLElement | null>(null);
/** Whether the window follows what comes in: the reader is at the foot. */
const follow = ref(true);
const unseen = ref(false);
const NEAR = 48;

function atFoot(): boolean {
  const el = box.value;
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR;
}
function onScroll(): void {
  follow.value = atFoot();
  if (follow.value) unseen.value = false;
}
function toFoot(smooth = false): void {
  const el = box.value;
  if (!el) return;
  if (typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  else el.scrollTop = el.scrollHeight;
}
function seeNew(): void {
  follow.value = true;
  unseen.value = false;
  toFoot(true);
}
/** Something new came in: stay at the foot if the reader is there, else show the pill. */
async function arrived(): Promise<void> {
  await nextTick();
  if (follow.value) toFoot();
  else unseen.value = true;
}

const signature = computed(() =>
  [
    messages.data.value?.length ?? 0,
    messages.data.value?.at(-1)?.id ?? 0,
    working.value,
    turn.value?.steps.length ?? 0,
    cards.value.map((card) => `${card.id}:${card.state}:${card.questions.length}`).join(","),
    failure.value ? 1 : 0,
  ].join("|"),
);
watch(signature, () => void arrived());
watch(current, () => {
  follow.value = true;
  unseen.value = false;
  void nextTick(() => toFoot());
});

// A card or an answer that grows after it is shown (markdown, a picture) keeps the foot in view.
let observer: ResizeObserver | null = null;
onMounted(() => {
  if (typeof ResizeObserver === "undefined" || !inner.value) return;
  observer = new ResizeObserver(() => {
    if (follow.value) toFoot();
  });
  observer.observe(inner.value);
});
onBeforeUnmount(() => observer?.disconnect());

// Asking ------------------------------------------------------------------------------------

async function startNew(): Promise<void> {
  const made = await quizzesApi.startConversation(cid.value);
  current.value = made.id;
  failure.value = null;
  void conversations.refetch();
}

async function poll(id: number): Promise<void> {
  for (let tries = 0; tries < 120; tries += 1) {
    const found = await quizzesApi.turn(cid.value, id);
    turn.value = found;
    if (found.status === "done" || found.status === "failed" || found.status === "cancelled") break;
    if (canDraft.value) void drafts.refetch(); // a card appears while its tool runs
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  const ended = turn.value;
  await Promise.all([messages.refetch(), canDraft.value ? drafts.refetch() : Promise.resolve()]);
  turn.value = null;
  if (ended?.status === "failed") {
    const code = `quizzes.chat.error.${ended.error_code || "generic"}`;
    failure.value = { error: te(code) ? t(code) : t("quizzes.chat.error.generic"), question: "" };
  }
}

async function ask(question?: string): Promise<void> {
  const value = (question ?? text.value).trim();
  if (!value || working.value) return;
  failure.value = null;
  asking.value = true;
  follow.value = true;
  try {
    if (current.value === null) await startNew();
    const { turn_id } = await quizzesApi.ask(cid.value, current.value ?? 0, value, "learning/tutor");
    text.value = "";
    await messages.refetch();
    asking.value = false;
    await poll(turn_id);
  } catch (error) {
    failure.value = {
      error: isApiError(error) ? (error.detail ?? t("quizzes.chat.error.generic")) : t("quizzes.chat.error.generic"),
      question: value,
    };
  } finally {
    asking.value = false;
  }
}

function retry(): void {
  const again = failure.value?.question;
  failure.value = null;
  if (again) void ask(again);
}

function edit(question: Question): void {
  editing.value = question;
  editorOpen.value = true;
}
</script>

<template>
  <section class="relative flex h-full min-h-0 flex-col overflow-hidden" :aria-label="t('quizzes.tutor.ask')" data-testid="tutor-chat">
    <header class="flex shrink-0 items-center gap-3 border-b border-line px-4 py-3">
      <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-fg"><GraduationCap :size="18" aria-hidden="true" /></span>
      <div class="min-w-0 flex-1">
        <h2 class="truncate text-sm font-semibold text-fg">{{ t("quizzes.tutor.ask") }}</h2>
        <p class="line-clamp-2 text-xs text-muted">{{ canDraft ? t("quizzes.chat.draftsHint") : t("quizzes.chat.hint") }}</p>
      </div>
      <UiButton size="sm" variant="ghost" class="shrink-0" :icon="MessageSquarePlus" :disabled="working" :title="t('quizzes.chat.new')" data-testid="tutor-new-chat" @click="startNew">
        <span class="max-sm:sr-only">{{ t("quizzes.chat.new") }}</span>
      </UiButton>
    </header>

    <div ref="box" class="min-h-0 flex-1 overflow-y-auto overscroll-contain" role="log" aria-live="polite" :aria-label="t('quizzes.chat.thread')" data-testid="tutor-thread" @scroll.passive="onScroll">
      <div ref="inner" class="flex min-h-full flex-col gap-4 px-4 py-4">
        <div v-if="messages.isPending.value && current !== null" class="flex flex-col gap-3" aria-hidden="true">
          <SkeletonBlock height="40px" width="60%" radius="14px" class="self-end" />
          <SkeletonBlock height="96px" width="88%" radius="14px" />
        </div>

        <div v-else-if="empty" class="flex flex-1 flex-col items-center justify-center gap-4 py-6 text-center" data-testid="tutor-chat-empty">
          <span class="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent-fg"><Sparkles :size="22" aria-hidden="true" /></span>
          <div class="flex max-w-xs flex-col gap-1">
            <p class="text-sm font-semibold text-fg">{{ t("quizzes.chat.empty") }}</p>
            <p class="text-xs text-muted">{{ canDraft ? t("quizzes.chat.emptyDrafts") : t("quizzes.chat.hint") }}</p>
          </div>
          <div class="flex w-full max-w-sm flex-col gap-2">
            <button
              v-for="key in SUGGESTED"
              :key="key"
              type="button"
              class="pressable inline-flex min-h-11 w-full items-center gap-2 rounded-[12px] border border-line bg-surface px-3 py-2 text-left text-sm text-fg hover:border-line-strong hover:bg-surface-2"
              @click="ask(t(key))"
            >
              <Sparkles :size="15" class="shrink-0 text-accent-fg" aria-hidden="true" />{{ t(key) }}
            </button>
          </div>
        </div>

        <template v-else>
          <template v-for="entry in thread" :key="entry.key">
            <div v-if="entry.message?.role === 'user'" class="flex justify-end" :data-message="entry.message.id">
              <p class="max-w-[85%] whitespace-pre-line break-words rounded-[16px] rounded-br-[6px] bg-primary px-3 py-2 text-sm text-on-primary">{{ entry.message.text }}</p>
            </div>
            <div v-else class="flex flex-col gap-2" :data-message="entry.message?.id">
              <ul v-if="entry.message?.steps.length" class="flex flex-wrap gap-1" :aria-label="t('quizzes.chat.steps')">
                <li v-for="(step, index) in entry.message.steps" :key="index" class="inline-flex max-w-full items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted dark:bg-surface-3">
                  <X v-if="step.status === 'error'" :size="11" class="shrink-0 text-danger" aria-hidden="true" />
                  <span class="truncate">{{ step.label }}</span>
                </li>
              </ul>
              <div v-if="entry.message" class="max-w-[92%] rounded-[16px] rounded-tl-[6px] bg-surface-2 px-3 py-2 text-fg dark:bg-surface-3">
                <MarkdownView :source="entry.message.text" size="sm" />
              </div>
              <TutorDraftCardView v-for="card in entry.cards" :key="card.id" :card="card" @edit="edit" />
            </div>
          </template>

          <div v-if="working" class="flex flex-col gap-2" data-testid="tutor-working">
            <TutorDraftCardView v-for="card in liveCards" :key="card.id" :card="card" @edit="edit" />
            <p v-if="!writing" class="flex items-center gap-2 px-1 text-xs text-muted">
              <span class="tutor-dots" aria-hidden="true"><i /><i /><i /></span>{{ stepLabel }}
            </p>
          </div>

          <div v-if="failure" class="flex gap-2.5" role="alert" data-testid="tutor-failure">
            <span class="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-danger-soft text-danger" aria-hidden="true"><CircleAlert :size="14" /></span>
            <div class="flex min-w-0 flex-1 flex-col items-start gap-2 pt-0.5">
              <p class="text-sm text-fg">{{ failure.error }}</p>
              <UiButton v-if="failure.question" size="sm" :icon="RotateCcw" @click="retry">{{ t("quizzes.chat.retry") }}</UiButton>
            </div>
          </div>
        </template>
      </div>
    </div>

    <button
      v-if="unseen"
      type="button"
      class="pressable absolute bottom-[84px] left-1/2 z-[2] inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-on-primary shadow-raised"
      data-testid="tutor-new-messages"
      @click="seeNew"
    >
      <ArrowDown :size="13" aria-hidden="true" />{{ t("quizzes.chat.newMessages") }}
    </button>

    <form class="flex shrink-0 items-end gap-2 border-t border-line bg-surface px-3 py-3" data-testid="tutor-composer" @submit.prevent="ask()">
      <TextArea
        v-model="text"
        class="flex-1"
        :rows="1"
        autosize
        :max-rows="5"
        :maxlength="2000"
        :placeholder="t('quizzes.chat.placeholder')"
        :aria-label="t('quizzes.chat.placeholder')"
        @keydown.enter.exact.prevent="ask()"
      />
      <UiButton type="submit" variant="primary" :icon="Send" :loading="working" :disabled="!text.trim()" :aria-label="t('quizzes.chat.send')" />
    </form>

    <QuestionEditor v-model:open="editorOpen" :question="editing" @saved="() => drafts.refetch()" />
  </section>
</template>

<style scoped>
.tutor-dots {
  display: inline-flex;
  gap: 3px;
}
.tutor-dots i {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.35;
  animation: tutor-dot 1.2s infinite ease-in-out;
}
.tutor-dots i:nth-child(2) {
  animation-delay: 0.15s;
}
.tutor-dots i:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes tutor-dot {
  0%,
  80%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-2px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .tutor-dots i {
    animation: none;
  }
}
</style>
