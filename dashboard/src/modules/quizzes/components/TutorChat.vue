<script setup lang="ts">
/**
 * "Ask the tutor": an Ask AI conversation with the tutor (it reads training, the knowledge base,
 * recognition and people, as the asker may see them). The question goes as a turn; the answer is
 * polled until it is written.
 */
import { MessageSquarePlus, Send } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import MarkdownView from "@/components/MarkdownView.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import { useCompanyId } from "@/stores/company";

import { quizKeys, quizzesApi, useConversations } from "../api";
import type { Turn } from "../types";

const { t, te } = useI18n();
const cid = useCompanyId();
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

const text = ref("");
const turn = ref<Turn | null>(null);
const failure = ref("");
const asking = ref(false);
const list = ref<HTMLElement | null>(null);
const working = computed(() => asking.value || turn.value?.status === "queued" || turn.value?.status === "running");

const SUGGESTED = ["quizzes.chat.try1", "quizzes.chat.try2", "quizzes.chat.try3"];

async function scrollDown(): Promise<void> {
  await nextTick();
  list.value?.scrollTo({ top: list.value.scrollHeight, behavior: "smooth" });
}

async function startNew(): Promise<void> {
  const made = await quizzesApi.startConversation(cid.value);
  current.value = made.id;
  void conversations.refetch();
}

async function poll(id: number): Promise<void> {
  for (let tries = 0; tries < 90; tries += 1) {
    const found = await quizzesApi.turn(cid.value, id);
    turn.value = found;
    if (found.status === "done" || found.status === "failed" || found.status === "cancelled") break;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  if (turn.value?.status === "failed") {
    const code = `quizzes.chat.error.${turn.value.error_code || "generic"}`;
    failure.value = te(code) ? t(code) : t("quizzes.chat.error.generic");
  }
  await messages.refetch();
  turn.value = null;
  void scrollDown();
}

async function ask(question?: string): Promise<void> {
  const value = (question ?? text.value).trim();
  if (!value || working.value) return;
  failure.value = "";
  asking.value = true;
  try {
    if (current.value === null) await startNew();
    const { turn_id } = await quizzesApi.ask(cid.value, current.value ?? 0, value, "learning/tutor");
    text.value = "";
    await messages.refetch();
    void scrollDown();
    asking.value = false;
    await poll(turn_id);
  } catch (error) {
    failure.value = isApiError(error) ? (error.detail ?? t("quizzes.chat.error.generic")) : t("quizzes.chat.error.generic");
  } finally {
    asking.value = false;
  }
}
</script>

<template>
  <div class="flex h-full min-h-[420px] flex-col" data-testid="tutor-chat">
    <div class="mb-2 flex items-center gap-2">
      <p class="flex-1 text-xs text-muted">{{ t("quizzes.chat.hint") }}</p>
      <UiButton size="sm" variant="ghost" :icon="MessageSquarePlus" @click="startNew">{{ t("quizzes.chat.new") }}</UiButton>
    </div>
    <div ref="list" class="flex flex-1 flex-col gap-3 overflow-y-auto rounded-xl border border-line bg-surface-2/40 p-3">
      <div v-if="messages.isPending.value && current !== null" class="grid gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="48px" radius="12px" /></div>
      <template v-else-if="messages.data.value?.length">
        <div v-for="message in messages.data.value" :key="message.id" class="flex" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
          <div class="max-w-[85%] rounded-2xl px-3 py-2 text-sm" :class="message.role === 'user' ? 'bg-primary text-on-primary' : 'bg-surface text-fg shadow-sm'">
            <MarkdownView v-if="message.role === 'assistant'" :source="message.text" size="sm" />
            <p v-else class="whitespace-pre-line">{{ message.text }}</p>
          </div>
        </div>
      </template>
      <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center">
        <p class="text-sm text-muted">{{ t("quizzes.chat.empty") }}</p>
        <div class="flex flex-wrap justify-center gap-2">
          <UiButton v-for="key in SUGGESTED" :key="key" size="sm" variant="secondary" @click="ask(t(key))">{{ t(key) }}</UiButton>
        </div>
      </div>
      <div v-if="working" class="flex items-center gap-2 text-sm text-muted">
        <UiSpinner :size="14" />
        <span>{{ turn?.steps.length ? turn.steps[turn.steps.length - 1]!.label : t("quizzes.chat.thinking") }}</span>
      </div>
    </div>
    <p v-if="failure" class="mt-2 text-sm text-danger">{{ failure }}</p>
    <form class="mt-2 flex items-end gap-2" @submit.prevent="ask()">
      <TextArea v-model="text" class="flex-1" :rows="1" autosize :max-rows="5" :maxlength="2000" :placeholder="t('quizzes.chat.placeholder')" @keydown.enter.exact.prevent="ask()" />
      <UiButton type="submit" variant="primary" :icon="Send" :loading="working" :disabled="!text.trim()" :aria-label="t('quizzes.chat.send')" />
    </form>
  </div>
</template>
