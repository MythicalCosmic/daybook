<script setup lang="ts">
/**
 * AI › Ask AI: questions about the company in plain words, answered from its own data with the
 * read-only tools, within the asker's permissions. While an answer is worked out its steps tick
 * off live ("Vazifalarni ko‘rib chiqyapman…"); the answer names people and tasks as chips that open
 * them. Conversations sit beside the chat on wide screens and in a sheet on phones. Without
 * Claude the page says what it will do once Claude is connected.
 */
import { ArrowUp, CircleAlert, History, KeyRound, MessageSquarePlus, MessagesSquare, RotateCcw, Sparkles, Square } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import BottomSheet from "@/components/BottomSheet.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MarkdownView from "@/components/MarkdownView.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { aiApi, aiKeys, useAiStatus, useCompanyId, useConversations, useMessages, useTurn } from "../api";
import AiHeader from "../components/AiHeader.vue";
import TurnSteps from "../components/TurnSteps.vue";
import { aiVisibility, turnIsLive } from "../lib";
import type { Conversation } from "../types";

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const fmt = useFormat();
const client = useQueryClient();
const cid = useCompanyId();
const company = useCompanyStore();
const session = useSessionStore();
const { isPhone } = useBreakpoints();

const status = useAiStatus();
const show = computed(() => aiVisibility(status.data.value));
const conversationId = useRouteState("c", rs.optionalNumber());
const conversations = useConversations(() => show.value.chat);
const messages = useMessages(conversationId);
const turnId = ref<number | null>(null);
const turn = useTurn(turnId);
const live = computed(() => turnId.value !== null && (turnIsLive(turn.data.value?.status) || !turn.data.value));
/** The question being answered, shown until the saved messages include it. */
const pending = ref<string | null>(null);
const failed = ref<{ text: string; error: string } | null>(null);
const text = ref("");
const sending = ref(false);
const listOpen = ref(false);
const lastEl = ref<HTMLElement | null>(null);

const SUGGESTIONS = ["late", "best", "fridge", "review", "off"] as const;
const myName = computed(() => session.me?.user.full_name ?? "");

function scrollDown(): void {
  void nextTick(() => lastEl.value?.scrollIntoView({ block: "end", behavior: "smooth" }));
}

async function ask(question: string): Promise<void> {
  const value = question.trim();
  if (!value || live.value || sending.value) return;
  sending.value = true;
  failed.value = null;
  pending.value = value;
  text.value = "";
  scrollDown();
  try {
    let id = conversationId.value;
    if (!id) {
      const created = await aiApi.newConversation(cid.value);
      client.setQueryData<Conversation[]>(aiKeys.conversations(cid.value), (list) => [created, ...(list ?? [])]);
      id = created.id;
      conversationId.value = id;
    }
    const answer = await aiApi.sendTurn(cid.value, id, { text: value });
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
    void client.invalidateQueries({ queryKey: aiKeys.conversations(cid.value) });
    const code = `ai.chat.error.${outcome?.error_code || "generic"}`;
    if (value === "failed") failed.value = { text: question, error: te(code) ? t(code) : t("ai.chat.error.generic") };
    turnId.value = null;
    pending.value = null;
    scrollDown();
  },
);
watch(() => turn.data.value?.text, scrollDown);

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
  listOpen.value = false;
}

function pick(conversation: Conversation): void {
  if (live.value) return;
  conversationId.value = conversation.id;
  failed.value = null;
  listOpen.value = false;
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void ask(text.value);
  }
}

// "Ask AI: …" from the palette or the top bar arrives as ?q=: asked at once.
onMounted(() => {
  const question = typeof route.query.q === "string" ? route.query.q : "";
  if (!question) return;
  patchQuery(router, { q: undefined });
  const stopWaiting = watch(
    () => show.value.chat,
    (ready) => {
      if (!ready) return;
      void ask(question);
      stopWaiting();
    },
    { immediate: true },
  );
});

watch(conversationId, () => scrollDown());
watch(() => messages.data.value?.length, scrollDown);

const empty = computed(() => !conversationId.value && !pending.value && !failed.value);
const conversationTitle = (conversation: Conversation) => conversation.title || t("ai.chat.untitled");
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <AiHeader :title="t('ai.chat.title')" :description="t('ai.chat.description')" :status="status.data.value">
      <template v-if="show.chat" #actions>
        <UiButton class="lg:hidden max-sm:flex-1" :size="isPhone ? 'lg' : 'md'" :icon="History" @click="listOpen = true">{{ t("ai.chat.history") }}</UiButton>
        <UiButton :size="isPhone ? 'lg' : 'md'" :icon="MessageSquarePlus" class="max-sm:flex-1" :disabled="live" data-testid="ai-new-chat" @click="newChat">{{ t("ai.chat.new") }}</UiButton>
      </template>
    </AiHeader>

    <div v-if="status.isPending.value" aria-hidden="true"><SkeletonBlock height="320px" radius="12px" /></div>
    <ErrorState v-else-if="status.isError.value" :error="status.error.value" :retry="() => status.refetch()" />

    <!-- Not here yet: what it will do, for whoever can connect it. -->
    <section v-else-if="!show.chat && show.chatTeaser" class="ai-teaser relative overflow-hidden rounded-card border border-line p-5 md:p-8" data-testid="ai-chat-teaser">
      <div class="relative flex max-w-[720px] flex-col gap-4">
        <span class="grid size-12 place-items-center rounded-full bg-primary text-on-primary shadow-raised" aria-hidden="true"><Sparkles :size="24" /></span>
        <h2 class="font-display text-xl text-fg md:text-2xl">{{ t("ai.chat.teaserTitle") }}</h2>
        <p class="text-base text-muted">{{ t("ai.chat.teaserBody") }}</p>
        <ul class="flex flex-wrap gap-2" :aria-label="t('ai.chat.examples')">
          <li v-for="key in SUGGESTIONS.slice(0, 3)" :key="key" class="inline-flex min-h-9 items-center gap-1.5 rounded-full bg-surface/80 px-3 text-sm text-fg ring-1 ring-line">
            <MessagesSquare :size="14" class="shrink-0 text-accent-fg" aria-hidden="true" />{{ t(`ai.chat.suggest.${key}`) }}
          </li>
        </ul>
        <p class="flex items-start gap-2 rounded-[10px] bg-surface/80 px-3 py-2.5 text-sm text-fg ring-1 ring-line">
          <KeyRound :size="15" class="mt-0.5 shrink-0 text-accent-fg" aria-hidden="true" />
          <span>{{ !status.data.value?.enabled ? t("ai.chat.teaserOff") : status.data.value.claude === "not_configured" ? t("ai.chat.teaserKey") : t("ai.chat.teaserSoon") }}</span>
        </p>
        <div v-if="!status.data.value?.enabled">
          <UiButton variant="primary" :size="isPhone ? 'lg' : 'md'" :icon="Sparkles" :to="{ name: 'ai.agents', params: { companyId: company.currentId } }">{{ t("ai.turnOn.button") }}</UiButton>
        </div>
      </div>
    </section>
    <EmptyState v-else-if="!show.chat" class="py-12" :icon="MessagesSquare" :title="t('ai.chat.unavailable')" :description="t('ai.chat.unavailableBody')" />

    <div v-else class="ui-card grid min-w-0 lg:h-[calc(100dvh-264px)] lg:min-h-[480px] lg:grid-cols-[264px_minmax(0,1fr)] lg:overflow-hidden" data-testid="ai-chat">
      <aside class="hidden min-h-0 flex-col border-r border-line lg:flex" :aria-label="t('ai.chat.history')">
        <div class="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
          <span class="px-1 text-sm font-semibold text-fg">{{ t("ai.chat.history") }}</span>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto p-2">
          <div v-if="conversations.isPending.value" class="flex flex-col gap-1.5" aria-hidden="true"><SkeletonBlock v-for="n in 4" :key="n" height="44px" radius="8px" /></div>
          <p v-else-if="!conversations.data.value?.length" class="px-2 py-3 text-sm text-muted">{{ t("ai.chat.noHistory") }}</p>
          <ul v-else class="flex flex-col gap-0.5">
            <li v-for="conversation in conversations.data.value" :key="conversation.id">
              <button
                type="button"
                :aria-current="conversation.id === conversationId ? 'true' : undefined"
                :class="['pressable flex w-full flex-col rounded-[8px] px-2.5 py-2 text-left', conversation.id === conversationId ? 'bg-accent-soft text-accent-fg' : 'text-fg hover:bg-highlight']"
                @click="pick(conversation)"
              >
                <span class="truncate text-sm font-medium">{{ conversationTitle(conversation) }}</span>
                <span class="num text-xs text-muted">{{ fmt.relative(conversation.created_at) }}</span>
              </button>
            </li>
          </ul>
        </div>
      </aside>

      <section class="flex min-h-[60dvh] min-w-0 flex-col lg:min-h-0">
        <div class="min-h-0 flex-1 px-4 py-5 md:px-6 lg:overflow-y-auto" role="log" aria-live="polite" :aria-label="t('ai.chat.thread')">
          <!-- A new conversation: what to ask. -->
          <div v-if="empty" class="mx-auto flex max-w-[560px] flex-col items-center gap-4 py-6 text-center">
            <span class="grid size-12 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><Sparkles :size="22" /></span>
            <div class="flex flex-col gap-1">
              <p class="font-display text-xl text-fg">{{ t("ai.chat.hello") }}</p>
              <p class="text-base text-muted">{{ t("ai.chat.helloBody") }}</p>
            </div>
            <div class="flex w-full flex-col gap-2 sm:items-center">
              <button
                v-for="key in SUGGESTIONS"
                :key="key"
                type="button"
                class="pressable inline-flex min-h-11 w-full items-center gap-2 rounded-[12px] border border-line bg-surface px-3.5 py-2 text-left text-base text-fg hover:border-line-strong hover:bg-surface-2 sm:w-auto sm:rounded-full"
                :data-suggestion="key"
                @click="ask(t(`ai.chat.suggest.${key}`))"
              >
                <MessagesSquare :size="15" class="shrink-0 text-accent-fg" aria-hidden="true" />{{ t(`ai.chat.suggest.${key}`) }}
              </button>
            </div>
          </div>

          <div v-else class="mx-auto flex max-w-[760px] flex-col gap-5">
            <div v-if="messages.isPending.value && conversationId" class="flex flex-col gap-3" aria-hidden="true">
              <SkeletonBlock height="44px" width="60%" radius="14px" class="self-end" />
              <SkeletonBlock height="96px" width="85%" radius="14px" />
            </div>
            <ErrorState v-else-if="messages.isError.value" compact :error="messages.error.value" :retry="() => messages.refetch()" />
            <template v-for="message in messages.data.value ?? []" :key="message.id">
              <div v-if="message.role === 'user'" class="flex justify-end scroll-mb-40" :data-message="message.id">
                <p class="max-w-[85%] whitespace-pre-line rounded-[16px] rounded-br-[6px] bg-primary px-3.5 py-2.5 text-base text-on-primary">{{ message.text }}</p>
              </div>
              <div v-else class="flex gap-3 scroll-mb-40" :data-message="message.id">
                <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><Sparkles :size="15" /></span>
                <div class="flex min-w-0 flex-1 flex-col gap-2">
                  <TurnSteps :steps="message.steps" />
                  <MarkdownView :source="message.text" />
                </div>
              </div>
            </template>

            <!-- The question in flight and its answer as it forms. -->
            <template v-if="pending">
              <div class="flex justify-end">
                <p class="max-w-[85%] whitespace-pre-line rounded-[16px] rounded-br-[6px] bg-primary px-3.5 py-2.5 text-base text-on-primary">{{ pending }}</p>
              </div>
              <div class="flex gap-3" data-testid="ai-live-answer">
                <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg" aria-hidden="true"><Sparkles :size="15" class="animate-pulse" /></span>
                <div class="flex min-w-0 flex-1 flex-col gap-2">
                  <TurnSteps :steps="turn.data.value?.steps ?? []" live />
                  <MarkdownView v-if="turn.data.value?.text" :source="turn.data.value.text" />
                </div>
              </div>
            </template>

            <div v-if="failed" class="flex gap-3" role="alert">
              <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-danger-soft text-danger" aria-hidden="true"><CircleAlert :size="15" /></span>
              <div class="flex min-w-0 flex-1 flex-col items-start gap-2 pt-1">
                <p class="text-base text-fg">{{ failed.error }}</p>
                <UiButton size="sm" :icon="RotateCcw" @click="failed && ask(failed.text)">{{ t("ai.chat.retry") }}</UiButton>
              </div>
            </div>
            <span ref="lastEl" class="block h-px scroll-mb-40" aria-hidden="true" />
          </div>
        </div>

        <form
          class="sticky bottom-0 z-[2] border-t border-line bg-surface px-3 py-3 max-md:bottom-[calc(var(--tabbar-h)+var(--safe-bottom))] max-lg:rounded-b-[12px] md:px-4"
          @submit.prevent="ask(text)"
        >
          <div class="flex items-end gap-2 rounded-[14px] border border-line bg-canvas px-2 py-1.5 focus-within:border-line-strong focus-within:ring-2 focus-within:ring-ring/30">
            <UserAvatar :name="myName || '?'" :size="28" class="mb-1 hidden md:block" />
            <textarea
              v-model="text"
              rows="1"
              :maxlength="2000"
              class="ai-composer max-h-[160px] min-h-10 flex-1 resize-none bg-transparent px-1.5 py-2 text-base text-fg outline-none placeholder:text-subtle"
              :placeholder="t('ai.chat.placeholder')"
              :aria-label="t('ai.chat.placeholder')"
              :disabled="sending"
              data-testid="ai-composer"
              @keydown="onKeydown"
            />
            <UiButton v-if="live" variant="secondary" class="!size-10 shrink-0 !rounded-full !px-0" :aria-label="t('ai.chat.stop')" data-testid="ai-stop" @click="stop">
              <Square :size="14" class="fill-current" aria-hidden="true" />
            </UiButton>
            <UiButton v-else type="submit" variant="primary" class="!size-10 shrink-0 !rounded-full !px-0" :disabled="!text.trim()" :loading="sending" :aria-label="t('ai.chat.send')" data-testid="ai-send">
              <ArrowUp v-if="!sending" :size="18" aria-hidden="true" />
            </UiButton>
          </div>
          <p class="mt-1.5 px-1 text-xs text-subtle max-sm:hidden">{{ t("ai.chat.disclaimer") }}</p>
        </form>
      </section>
    </div>

    <BottomSheet v-model:open="listOpen" :title="t('ai.chat.history')" tall>
      <div class="flex flex-col gap-2 pb-2">
        <UiButton variant="primary" size="lg" block :icon="MessageSquarePlus" :disabled="live" @click="newChat">{{ t("ai.chat.new") }}</UiButton>
        <p v-if="!conversations.data.value?.length" class="px-1 py-3 text-base text-muted">{{ t("ai.chat.noHistory") }}</p>
        <ul v-else class="flex flex-col gap-1">
          <li v-for="conversation in conversations.data.value" :key="conversation.id">
            <button
              type="button"
              :class="['pressable flex min-h-12 w-full flex-col justify-center rounded-[10px] px-3 py-2 text-left', conversation.id === conversationId ? 'bg-accent-soft text-accent-fg' : 'text-fg hover:bg-highlight']"
              @click="pick(conversation)"
            >
              <span class="truncate text-base font-medium">{{ conversationTitle(conversation) }}</span>
              <span class="num text-sm text-muted">{{ fmt.relative(conversation.created_at) }}</span>
            </button>
          </li>
        </ul>
      </div>
    </BottomSheet>
  </div>
</template>

<style scoped>
.ai-teaser {
  background:
    radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--c-primary) 14%, transparent) 0%, transparent 55%),
    radial-gradient(90% 120% at 100% 100%, color-mix(in srgb, var(--c-info) 12%, transparent) 0%, transparent 60%),
    var(--c-surface);
}
.ai-composer {
  field-sizing: content;
}
</style>
