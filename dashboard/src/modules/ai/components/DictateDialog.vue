<script setup lang="ts">
/**
 * Dictate or Smart add, start to finish in one dialog: speak (or type) the instructions, watch the
 * AI listen and understand, check each task it found and change anything, then "Create N tasks".
 * The tasks go through the normal task flow (notifications, reminders); the Tasks lists refresh.
 * Closing midway loses nothing: the draft waits in AI › Voice notes for a day.
 */
import { Hourglass, Keyboard, Mic, RotateCcw, Sparkles, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { useAgents, useAiStatus, useCreateDraft, useDiscardDraft, useDraft } from "../api";
import type { DictationMode } from "../dictation";
import { isWorking, workingPhase } from "../lib";
import { voiceFilename } from "../recorder";
import { failedTitles, useReview } from "../review";
import CreatedTasks from "./CreatedTasks.vue";
import DraftReview from "./DraftReview.vue";
import RecorderPanel from "./RecorderPanel.vue";
import WorkingState from "./WorkingState.vue";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ mode?: DictationMode; initialText?: string }>(), { mode: "voice", initialText: "" });
const emit = defineEmits<{ created: [ids: number[]] }>();

const TEXT_MAX = 2000;

const { t, te, locale } = useI18n();
const { isPhone } = useBreakpoints();
const status = useAiStatus();
const agents = useAgents();
const create = useCreateDraft();
const discard = useDiscardDraft();

const mode = ref<DictationMode>(props.mode);
const text = ref(props.initialText);
const draftId = ref<number | null>(null);
const sendError = ref<string | null>(null);
const watched = useDraft(draftId);
const draft = computed(() => (draftId.value ? (watched.data.value ?? null) : null));
const review = useReview(draft);

const maxSeconds = computed(() => {
  const value = agents.data.value?.find((agent) => agent.key === "voice_tasks")?.config.max_seconds;
  return typeof value === "number" && value > 0 ? value : 120;
});

type Step = "capture" | "sending" | "working" | "slow" | "review" | "done" | "failed";
const step = computed<Step>(() => {
  if (review.result.value) return "done";
  if (create.isPending.value) return "sending";
  if (!draftId.value) return "capture";
  const current = draft.value;
  if (!current || isWorking(current.status)) {
    if (watched.gaveUp.value) return "slow";
    return watched.isError.value && !current ? "failed" : "working";
  }
  if (current.status === "ready") return "review";
  if (current.status === "applied") return "done";
  return "failed";
});

const created = computed(() => review.result.value?.draft.created_tasks ?? draft.value?.created_tasks ?? []);
const failedLines = computed(() => failedTitles(review.edits.value, review.result.value));
const phase = computed(() => (step.value === "sending" ? "upload" : workingPhase(draft.value?.status, mode.value === "voice")));

const title = computed(() => {
  if (step.value === "review") return t("ai.review.title");
  if (step.value === "done") return t("ai.done.dialogTitle");
  return mode.value === "voice" ? t("ai.dictate.title") : t("ai.smartAdd.title");
});
const description = computed(() => {
  if (step.value === "review") return t("ai.review.description");
  if (step.value === "capture") return mode.value === "voice" ? t("ai.dictate.description") : t("ai.smartAdd.description");
  return undefined;
});

/** The server's refusal in words: its own translated sentence first, then ours for the code. */
function refusal(error: unknown): string {
  if (isApiError(error)) {
    if (error.detail) return error.detail;
    if (error.code && te(`ai.refusal.${error.code}`)) return t(`ai.refusal.${error.code}`);
    if (error.isNetwork) return t("ai.refusal.network");
  }
  return t("ai.refusal.generic");
}

const failure = computed(() => {
  const current = draft.value;
  if (current?.error) return current.error;
  const code = current?.status === "expired" ? "expired" : current?.status === "discarded" ? "discarded" : current?.error_code;
  return code && te(`ai.error.${code}`) ? t(`ai.error.${code}`) : t("ai.error.generic");
});

async function send(input: { text: string } | { audio: Blob; seconds: number }): Promise<void> {
  sendError.value = null;
  try {
    const answer = await create.mutateAsync(
      "text" in input ? input : { audio: input.audio, seconds: input.seconds, language: String(locale.value), filename: voiceFilename(input.audio.type) },
    );
    draftId.value = answer.id;
  } catch (error) {
    sendError.value = refusal(error);
  }
}

function onRecorded(audio: { blob: Blob; seconds: number }): void {
  void send({ audio: audio.blob, seconds: audio.seconds });
}

function readText(): void {
  const value = text.value.trim();
  if (!value || value.length > TEXT_MAX) return;
  void send({ text: value });
}

async function createTasks(): Promise<void> {
  const result = await review.create();
  if (result?.created.length) emit("created", result.created);
}

async function throwAway(): Promise<void> {
  if (!draftId.value) return;
  try {
    await discard.mutateAsync(draftId.value);
    toast.info(t("ai.review.discarded"));
    open.value = false;
  } catch {
    // The reason is a toast.
  }
}

function again(next: DictationMode = mode.value): void {
  draftId.value = null;
  review.result.value = null;
  sendError.value = null;
  mode.value = next;
  if (next === "voice") text.value = "";
}

// A fresh start every time the dialog opens again.
watch(open, (value) => {
  if (value) return;
  draftId.value = null;
  review.result.value = null;
});
watch(
  () => props.mode,
  (value) => (mode.value = value),
);

/** Speech isn't set up on this server: typing still works, so the dialog starts there. */
const voiceMissing = ref(false);
watch(
  () => status.data.value,
  (value) => {
    if (!value?.enabled || value.features.voice || mode.value !== "voice" || draftId.value) return;
    voiceMissing.value = true;
    mode.value = "text";
  },
  { immediate: true },
);
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="description" size="lg" :dismissable="step !== 'review' || !review.applying.value">
    <div class="flex flex-col gap-4" :data-step="step" data-testid="ai-dictate-dialog">
      <InlineAlert v-if="sendError" tone="danger" :description="sendError" dismissible @dismiss="sendError = null" />
      <InlineAlert
        v-if="step === 'capture' && status.data.value && !status.data.value.enabled"
        tone="warning"
        :title="t('ai.off.title')"
        :description="status.data.value.can_configure ? t('ai.dictate.offOwner') : t('ai.off.body')"
      />
      <InlineAlert v-else-if="step === 'capture' && voiceMissing" tone="info" :description="t('ai.dictate.noVoice')" />

      <template v-if="step === 'capture'">
        <RecorderPanel v-if="mode === 'voice'" :max-seconds="maxSeconds" :bot-username="status.data.value?.bot_username ?? null" @recorded="onRecorded" @type="mode = 'text'" />
        <template v-else>
          <FormField :label="t('ai.smartAdd.label')" :hint="t('ai.smartAdd.hint')" :count="text.length" :max="TEXT_MAX">
            <TextArea
              v-model="text"
              :rows="5"
              :max-rows="12"
              :maxlength="TEXT_MAX"
              :placeholder="t('ai.smartAdd.placeholder')"
              autofocus
              data-testid="ai-smart-text"
              @keydown.meta.enter.prevent="readText"
              @keydown.ctrl.enter.prevent="readText"
            />
          </FormField>
          <button v-if="status.data.value?.features.voice" type="button" class="inline-flex min-h-10 w-fit items-center gap-1.5 text-sm font-medium text-accent-fg hover:underline" @click="mode = 'voice'">
            <Mic :size="15" aria-hidden="true" />{{ t("ai.smartAdd.speakInstead") }}
          </button>
        </template>
      </template>

      <WorkingState v-else-if="step === 'sending' || step === 'working'" :phase="phase" :voice="mode === 'voice'" />

      <div v-else-if="step === 'slow'" class="flex flex-col items-center gap-3 py-6 text-center" role="status">
        <span class="grid size-14 place-items-center rounded-full bg-warning-soft text-warning" aria-hidden="true"><Hourglass :size="26" /></span>
        <p class="text-md font-semibold text-fg">{{ t("ai.slow.title") }}</p>
        <p class="max-w-[380px] text-base text-muted">{{ t("ai.slow.body") }}</p>
      </div>

      <ErrorState v-else-if="step === 'failed'" :title="t('ai.error.title')" :description="failure" />

      <DraftReview v-else-if="step === 'review' && draft" :draft="draft" :review="review" :disabled="review.applying.value" />

      <CreatedTasks v-else-if="step === 'done'" :tasks="created" :failed="failedLines" celebrate @navigate="open = false" />
    </div>

    <template #footer>
      <template v-if="step === 'capture' && mode === 'text'">
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :icon="Sparkles" :disabled="!text.trim()" kbd="mod+enter" data-testid="ai-read" @click="readText">{{ t("ai.smartAdd.read") }}</UiButton>
      </template>
      <template v-else-if="step === 'capture' || step === 'sending' || step === 'working'">
        <span class="mr-auto text-sm text-muted max-sm:hidden">{{ step === "capture" ? t("ai.dictate.privacy") : t("ai.working.later") }}</span>
        <UiButton variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
      </template>
      <template v-else-if="step === 'slow'">
        <UiButton variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
        <UiButton variant="primary" :icon="RotateCcw" @click="watched.retry()">{{ t("ai.slow.retry") }}</UiButton>
      </template>
      <template v-else-if="step === 'failed'">
        <UiButton variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
        <UiButton v-if="mode === 'voice'" :icon="Keyboard" @click="again('text')">{{ t("ai.recorder.typeInstead") }}</UiButton>
        <UiButton variant="primary" :icon="mode === 'voice' ? Mic : RotateCcw" @click="again()">{{ mode === "voice" ? t("ai.error.recordAgain") : t("ai.error.tryAgain") }}</UiButton>
      </template>
      <template v-else-if="step === 'review'">
        <span v-if="review.blockers.value.problems || review.blockers.value.untitled" class="mr-auto text-sm text-warning max-sm:hidden" role="status">
          {{ review.blockers.value.untitled ? t("ai.review.needTitles") : t("ai.review.fixFirst") }}
        </span>
        <UiButton variant="ghost" :icon="isPhone ? undefined : Trash2" :loading="discard.isPending.value" :disabled="review.applying.value" data-testid="ai-discard" @click="throwAway">{{ t("ai.review.discard") }}</UiButton>
        <UiButton
          variant="primary"
          :loading="review.applying.value"
          :disabled="!review.canApply.value"
          kbd="mod+enter"
          data-testid="ai-apply"
          @click="createTasks"
        >
          {{ t("ai.review.create", { n: review.count.value }, review.count.value) }}
        </UiButton>
      </template>
      <template v-else-if="step === 'done'">
        <UiButton :icon="Mic" @click="again('voice')">{{ t("ai.done.more") }}</UiButton>
        <UiButton variant="primary" data-testid="ai-done" @click="open = false">{{ t("ai.done.close") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
