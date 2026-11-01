<script setup lang="ts">
/**
 * Speak the tasks: one big button, then a live level, the time against the limit, Cancel and Done.
 * Where the browser can't record (no microphone API, permission refused), it says so kindly and
 * offers typing instead, or a voice message to the bot in Telegram.
 */
import { Check, Keyboard, Mic, MicOff, RotateCcw, Send, X } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import UiSpinner from "@/components/UiSpinner.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { formatSeconds } from "../lib";
import { useRecorder } from "../recorder";

const props = withDefaults(defineProps<{ maxSeconds: number; botUsername?: string | null }>(), { botUsername: null });
const emit = defineEmits<{ recorded: [audio: { blob: Blob; seconds: number; limit: boolean }]; type: [] }>();

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const recorder = useRecorder({ maxSeconds: () => props.maxSeconds, bars: 28 });
const state = recorder.state;

watch(state, (value) => {
  if (value === "done" && recorder.blob.value) emit("recorded", { blob: recorder.blob.value, seconds: recorder.seconds.value, limit: recorder.hitLimit.value });
});

const remaining = computed(() => Math.max(0, props.maxSeconds - recorder.seconds.value));
const nearLimit = computed(() => state.value === "recording" && remaining.value <= 10);
const pulse = computed(() => 1 + Math.min(1, recorder.level.value) * 0.32);
const botLink = computed(() => (props.botUsername ? `https://t.me/${props.botUsername.replace(/^@/, "")}` : null));

function openBot(): void {
  const link = botLink.value;
  if (!link) return;
  // Inside Telegram the chat opens in Telegram itself; elsewhere in a new tab.
  const webApp = window.Telegram?.WebApp as unknown as { openTelegramLink?: (url: string) => void } | undefined;
  if (webApp?.openTelegramLink) webApp.openTelegramLink(link);
  else window.open(link, "_blank", "noopener");
}

function onKey(event: KeyboardEvent): void {
  if (event.key !== " " && event.key !== "Enter") return;
  event.preventDefault();
  if (state.value === "recording") recorder.stop();
  else if (state.value === "idle" || state.value === "error") void recorder.start();
}

defineExpose({ cancel: recorder.cancel, state });
</script>

<template>
  <div class="flex flex-col items-center gap-5 py-4 text-center" data-testid="ai-recorder" :data-state="state">
    <!-- Can't record here: say why and what to do instead. -->
    <template v-if="state === 'denied' || state === 'unsupported' || state === 'error'">
      <span class="grid size-16 place-items-center rounded-full bg-surface-2 text-muted dark:bg-surface-3" aria-hidden="true"><MicOff :size="28" /></span>
      <div class="flex max-w-[400px] flex-col gap-1.5">
        <p class="text-md font-semibold text-fg">{{ t(`ai.recorder.${state}.title`) }}</p>
        <p class="text-base text-muted">{{ t(`ai.recorder.${state}.body`) }}</p>
      </div>
      <div class="flex w-full max-w-[400px] flex-col gap-2 sm:flex-row sm:justify-center">
        <UiButton variant="primary" :size="isPhone ? 'lg' : 'md'" :icon="Keyboard" :block="isPhone" data-testid="ai-type-instead" @click="emit('type')">{{ t("ai.recorder.typeInstead") }}</UiButton>
        <UiButton v-if="state !== 'unsupported'" :size="isPhone ? 'lg' : 'md'" :icon="RotateCcw" :block="isPhone" @click="recorder.start()">{{ t("ai.recorder.tryAgain") }}</UiButton>
      </div>
      <button v-if="botLink" type="button" class="inline-flex min-h-10 items-center gap-1.5 text-sm font-medium text-accent-fg hover:underline" @click="openBot">
        <Send :size="14" aria-hidden="true" />{{ t("ai.recorder.useBot", { bot: `@${botUsername}` }) }}
      </button>
      <p v-else class="max-w-[400px] text-sm text-subtle">{{ t("ai.recorder.useBotGeneric") }}</p>
    </template>

    <template v-else>
      <div class="relative grid size-[148px] place-items-center">
        <span
          v-if="state === 'recording'"
          class="ai-halo absolute inset-3 rounded-full"
          :style="{ transform: `scale(${pulse})` }"
          aria-hidden="true"
        />
        <span v-if="state === 'recording'" class="ai-ring absolute inset-3 rounded-full" aria-hidden="true" />
        <button
          type="button"
          :class="[
            'pressable relative grid size-[104px] place-items-center rounded-full text-on-primary shadow-raised outline-offset-4 transition-colors duration-150',
            state === 'recording' ? 'bg-danger' : 'bg-primary hover:bg-primary-hover',
          ]"
          :aria-label="state === 'recording' ? t('ai.recorder.stop') : t('ai.recorder.start')"
          :aria-pressed="state === 'recording'"
          :disabled="state === 'requesting' || state === 'stopping'"
          data-testid="ai-mic"
          @click="state === 'recording' ? recorder.stop() : recorder.start()"
          @keydown="onKey"
        >
          <UiSpinner v-if="state === 'requesting' || state === 'stopping'" :size="30" />
          <span v-else-if="state === 'recording'" class="size-8 rounded-[8px] bg-white" aria-hidden="true" />
          <Mic v-else :size="40" aria-hidden="true" />
        </button>
      </div>

      <div class="flex min-h-[64px] flex-col items-center gap-1.5">
        <template v-if="state === 'recording'">
          <p class="num text-xl font-semibold tracking-[-0.01em] text-fg" aria-live="off">
            {{ formatSeconds(recorder.seconds.value) }}<span class="text-base font-normal text-subtle"> / {{ formatSeconds(maxSeconds) }}</span>
          </p>
          <div class="flex h-7 items-center gap-[3px]" aria-hidden="true">
            <span v-for="(value, index) in recorder.levels.value" :key="index" class="ai-bar w-[3px] rounded-full bg-primary" :style="{ height: `${Math.max(3, Math.round(value * 28))}px`, opacity: 0.35 + value * 0.65 }" />
          </div>
          <p :class="['text-sm', nearLimit ? 'font-medium text-warning' : 'text-muted']" role="status">
            {{ nearLimit ? t("ai.recorder.endsSoon", { n: Math.ceil(remaining) }) : t("ai.recorder.listening") }}
          </p>
        </template>
        <template v-else>
          <p class="text-md font-semibold text-fg">{{ state === "requesting" ? t("ai.recorder.allow") : t("ai.recorder.tap") }}</p>
          <p class="max-w-[380px] text-base text-muted">{{ t("ai.recorder.hint", { max: formatSeconds(maxSeconds) }) }}</p>
        </template>
      </div>

      <figure v-if="state !== 'recording'" class="w-full max-w-[440px] rounded-card bg-surface-2 px-4 py-3 text-left dark:bg-surface-3">
        <figcaption class="text-xs font-semibold text-muted">{{ t("ai.recorder.example") }}</figcaption>
        <blockquote class="mt-1 text-base italic leading-[1.5] text-fg">{{ t("ai.recorder.exampleText") }}</blockquote>
      </figure>

      <div v-if="state === 'recording'" class="grid w-full max-w-[400px] grid-cols-2 gap-2">
        <UiButton :size="isPhone ? 'lg' : 'md'" :icon="X" block data-testid="ai-rec-cancel" @click="recorder.cancel()">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :size="isPhone ? 'lg' : 'md'" :icon="Check" block data-testid="ai-rec-done" @click="recorder.stop()">{{ t("ai.recorder.done") }}</UiButton>
      </div>
      <UiButton v-else variant="ghost" :size="isPhone ? 'lg' : 'md'" :icon="Keyboard" @click="emit('type')">{{ t("ai.recorder.typeInstead") }}</UiButton>
    </template>
  </div>
</template>

<style scoped>
.ai-halo {
  background: color-mix(in srgb, var(--c-danger) 18%, transparent);
  transition: transform 90ms linear;
}
.ai-ring {
  border: 2px solid color-mix(in srgb, var(--c-danger) 45%, transparent);
  animation: ai-pulse 1.6s var(--ease-standard) infinite;
}
@keyframes ai-pulse {
  0% {
    opacity: 0.9;
    transform: scale(0.95);
  }
  100% {
    opacity: 0;
    transform: scale(1.35);
  }
}
.ai-bar {
  transition: height 80ms linear;
}
</style>
