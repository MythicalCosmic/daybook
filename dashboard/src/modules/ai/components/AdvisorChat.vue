<script setup lang="ts">
/**
 * "Maslahatchidan so‘rang" (Ask the advisor): an Ask AI conversation with Maslahatchi, which reads
 * the money, sales, stock and people the asker may see, the latest weekly review's facts, and works
 * out "what if" on the cash forecast. A panel of its own height: the messages scroll inside it, the
 * composer stays at its bottom, and a new answer scrolls into view unless the reader scrolled up
 * to read (then "New answer" takes them down). Its newest conversation opens; "New chat" starts
 * another. The question goes as a turn and its answer is polled while it is written.
 */
import { ArrowDown, ArrowUp, CircleAlert, MessageSquarePlus, MessagesSquare, RotateCcw, Square } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import MarkdownView from "@/components/MarkdownView.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";

import { ADVISOR_QUESTIONS, followsNewest } from "../advisor";
import { aiApi, useCompanyId, useMessages, useTurn } from "../api";
import { briefingKeys, briefingsApi, useAdvisorConversations } from "../briefings";
import { turnIsLive } from "../lib";
import type { Conversation } from "../types";
import AgentChibi from "./AgentChibi.vue";
import TurnSteps from "./TurnSteps.vue";

const props = withDefaults(defineProps<{ agentName: string; on?: boolean }>(), { on: true });

const { t, te } = useI18n();
const cid = useCompanyId();
const client = useQueryClient();

const conversations = useAdvisorConversations(true);
const conversationId = ref<number | null>(null);
watch(
  () => conversations.data.value,
  (rows) => {
    if (conversationId.value === null && rows?.length) conversationId.value = rows[0]!.id;
  },
  { immediate: true },
);
const messages = useMessages(conversationId);
const turnId = ref<number | null>(null);
const turn = useTurn(turnId);
const live = computed(() => turnId.value !== null && (turnIsLive(turn.data.value?.status) || !turn.data.value));
const pending = ref<string | null>(null);
const failed = ref<{ text: string; error: string } | null>(null);
const text = ref("");
const sending = ref(false);

// Following the newest message: unless the reader scrolled up.
const box = ref<HTMLElement | null>(null);
const following = ref(true);
const unseen = ref(false);
function onScroll(): void {
  following.value = followsNewest(box.value);
  if (following.value) unseen.value = false;
}
function toBottom(smooth = true): void {
  void nextTick(() => {
    box.value?.scrollTo({ top: box.value.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    unseen.value = false;
    following.value = true;
  });
}
function arrived(): void {
  if (following.value) toBottom();
  else unseen.value = true;
}

async function ask(question: string): Promise<void> {
  const value = question.trim();
  if (!value || live.value || sending.value) return;
  sending.value = true;
  failed.value = null;
  pending.value = value;
  text.value = "";
  toBottom();
  try {
    let id = conversationId.value;
    if (!id) {
      const created = await briefingsApi.newConversation(cid.value);
      client.setQueryData<Conversation[]>(briefingKeys.conversations(cid.value), (list) => [created, ...(list ?? [])]);
      id = created.id;
      conversationId.value = id;
    }
    const answer = await aiApi.sendTurn(cid.value, id, { text: value, page: "ai/advisor" });
    turnId.value = answer.turn_id;
  } catch (error) {
    failed.value = { text: value, error: isApiError(error) && error.detail ? error.detail : t("ai.chat.error.generic") };
    pending.value = null;
  } finally {
    sending.value = false;
  }
}

// The answer is in: the saved conversation takes over from the live bubble.
watch(
  () => turn.data.value?.status,
  async (value) => {
    if (!value || turnIsLive(value) || turnId.value === null) return;
    const question = pending.value ?? "";
    const outcome = turn.data.value;
    await messages.refetch();
    void client.invalidateQueries({ queryKey: briefingKeys.conversations(cid.value) });
    const code = `ai.chat.error.${outcome?.error_code || "generic"}`;
    if (value === "failed") failed.value = { text: question, error: te(code) ? t(code) : t("ai.chat.error.generic") };
    turnId.value = null;
    pending.value = null;
    arrived();
  },
);
watch(() => turn.data.value?.text, arrived);
watch(() => turn.data.value?.steps.length, arrived);
watch(conversationId, () => toBottom(false));
watch(() => messages.data.value?.length, () => toBottom(false));

async function stop(): Promise<void> {
  if (turnId.value === null) return;
  try {
    await aiApi.cancelTurn(cid.value, turnId.value);
  } catch {
    // Already finished: the next poll shows the answer.
  }
}

function newChat(): void {
  if (live.value) return;
  conversationId.value = null;
  failed.value = null;
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void ask(text.value);
  }
}

const empty = computed(() => !conversationId.value && !pending.value && !failed.value);
const hasMessages = computed(() => (messages.data.value?.length ?? 0) > 0);
</script>

<template>
  <section class="advisor-chat ui-card relative flex min-h-0 flex-col overflow-hidden" :aria-label="t('ai.advisor.chat.title')" data-testid="advisor-chat">
    <header class="flex shrink-0 items-center gap-2.5 border-b border-line px-3.5 py-2.5">
      <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-[color-mix(in_srgb,#6b8fd6_14%,var(--c-surface))]" aria-hidden="true">
        <AgentChibi agent-key="advisor" :name="props.agentName" :on="props.on" :running="live" :size="32" />
      </span>
      <div class="min-w-0 flex-1">
        <h2 class="truncate text-sm font-semibold text-fg">{{ t("ai.advisor.chat.title") }}</h2>
        <p class="truncate text-xs text-muted">{{ t("ai.advisor.chat.subtitle") }}</p>
      </div>
      <UiButton size="sm" variant="ghost" :icon="MessageSquarePlus" :disabled="live || empty" data-testid="advisor-new-chat" @click="newChat">{{ t("ai.chat.new") }}</UiButton>
    </header>

    <div ref="box" class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3.5 py-4" role="log" aria-live="polite" :aria-label="t('ai.chat.thread')" data-testid="advisor-thread" @scroll.passive="onScroll">
      <div v-if="empty" class="flex min-h-full flex-col items-center justify-center gap-4 py-4 text-center" data-testid="advisor-chat-empty">
        <div class="flex flex-col gap-1">
          <p class="font-display text-lg text-fg">{{ t("ai.advisor.chat.hello") }}</p>
          <p class="text-sm text-muted">{{ t("ai.advisor.chat.helloBody") }}</p>
        </div>
        <div class="flex w-full flex-col gap-2">
          <button
            v-for="key in ADVISOR_QUESTIONS"
            :key="key"
            type="button"
            class="pressable inline-flex min-h-11 w-full items-center gap-2 rounded-[12px] border border-line bg-surface px-3 py-2 text-left text-sm text-fg hover:border-line-strong hover:bg-surface-2"
            :data-question="key"
            @click="ask(t(key))"
          >
            <MessagesSquare :size="15" class="shrink-0 text-accent-fg" aria-hidden="true" />{{ t(key) }}
          </button>
        </div>
      </div>

      <div v-else class="flex flex-col gap-4">
        <div v-if="messages.isPending.value && conversationId && !pending" class="flex flex-col gap-3" aria-hidden="true">
          <SkeletonBlock height="40px" width="65%" radius="14px" class="self-end" />
          <SkeletonBlock height="88px" width="90%" radius="14px" />
        </div>
        <template v-for="message in messages.data.value ?? []" :key="message.id">
          <div v-if="message.role === 'user'" class="flex justify-end" :data-message="message.id">
            <p class="max-w-[88%] whitespace-pre-line rounded-[16px] rounded-br-[6px] bg-primary px-3 py-2 text-sm text-on-primary">{{ message.text }}</p>
          </div>
          <div v-else class="flex flex-col gap-1.5" :data-message="message.id">
            <TurnSteps :steps="message.steps" />
            <div class="rounded-[16px] rounded-tl-[6px] bg-surface-2 px-3 py-2 dark:bg-surface-3">
              <MarkdownView :source="message.text" size="sm" />
            </div>
          </div>
        </template>

        <template v-if="pending">
          <div class="flex justify-end">
            <p class="max-w-[88%] whitespace-pre-line rounded-[16px] rounded-br-[6px] bg-primary px-3 py-2 text-sm text-on-primary">{{ pending }}</p>
          </div>
          <div class="flex flex-col gap-1.5" data-testid="advisor-live-answer">
            <TurnSteps :steps="turn.data.value?.steps ?? []" live />
            <div v-if="turn.data.value?.text" class="rounded-[16px] rounded-tl-[6px] bg-surface-2 px-3 py-2 dark:bg-surface-3">
              <MarkdownView :source="turn.data.value.text" size="sm" />
            </div>
            <p v-else class="flex items-center gap-1.5 px-1 text-xs text-muted">
              <span class="advisor-dots" aria-hidden="true"><i /><i /><i /></span>{{ t("ai.advisor.chat.thinking") }}
            </p>
          </div>
        </template>

        <div v-if="failed" class="flex gap-2.5" role="alert">
          <span class="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-danger-soft text-danger" aria-hidden="true"><CircleAlert :size="14" /></span>
          <div class="flex min-w-0 flex-1 flex-col items-start gap-2 pt-0.5">
            <p class="text-sm text-fg">{{ failed.error }}</p>
            <UiButton size="sm" :icon="RotateCcw" @click="failed && ask(failed.text)">{{ t("ai.chat.retry") }}</UiButton>
          </div>
        </div>
        <p v-if="!hasMessages && !pending && !failed && !messages.isPending.value" class="text-center text-sm text-muted">{{ t("ai.advisor.chat.helloBody") }}</p>
      </div>
    </div>

    <button
      v-if="unseen"
      type="button"
      class="pressable absolute bottom-[86px] left-1/2 z-[2] inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-on-primary shadow-raised"
      data-testid="advisor-new-answer"
      @click="toBottom()"
    >
      <ArrowDown :size="13" aria-hidden="true" />{{ t("ai.advisor.chat.newAnswer") }}
    </button>

    <form class="shrink-0 border-t border-line bg-surface px-3 py-2.5" data-testid="advisor-composer-bar" @submit.prevent="ask(text)">
      <div class="flex items-end gap-2 rounded-[14px] border border-line bg-canvas px-2 py-1.5 focus-within:border-line-strong focus-within:ring-2 focus-within:ring-ring/30">
        <textarea
          v-model="text"
          rows="1"
          :maxlength="2000"
          class="advisor-composer max-h-[140px] min-h-10 flex-1 resize-none bg-transparent px-1.5 py-2 text-base text-fg outline-none placeholder:text-subtle pointer-coarse:text-md"
          :placeholder="t('ai.advisor.chat.placeholder')"
          :aria-label="t('ai.advisor.chat.placeholder')"
          :disabled="sending"
          data-testid="advisor-composer"
          @keydown="onKeydown"
        />
        <UiButton v-if="live" variant="secondary" class="!size-10 shrink-0 !rounded-full !px-0" :aria-label="t('ai.chat.stop')" data-testid="advisor-stop" @click="stop">
          <Square :size="14" class="fill-current" aria-hidden="true" />
        </UiButton>
        <UiButton v-else type="submit" variant="primary" class="!size-10 shrink-0 !rounded-full !px-0" :disabled="!text.trim()" :loading="sending" :aria-label="t('ai.chat.send')" data-testid="advisor-send">
          <ArrowUp v-if="!sending" :size="18" aria-hidden="true" />
        </UiButton>
      </div>
      <p class="mt-1.5 px-1 text-[11px] text-subtle max-sm:hidden">{{ t("ai.advisor.chat.disclaimer") }}</p>
    </form>
  </section>
</template>

<style scoped>
.advisor-composer {
  field-sizing: content;
}
.advisor-dots {
  display: inline-flex;
  gap: 3px;
}
.advisor-dots i {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.4;
  animation: advisor-dot 1.2s ease-in-out infinite;
}
.advisor-dots i:nth-child(2) {
  animation-delay: 0.15s;
}
.advisor-dots i:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes advisor-dot {
  0%,
  100% {
    opacity: 0.3;
    transform: translateY(0);
  }
  50% {
    opacity: 0.9;
    transform: translateY(-2px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .advisor-dots i {
    animation: none;
  }
}
</style>
