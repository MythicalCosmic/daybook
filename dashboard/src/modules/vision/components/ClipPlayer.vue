<script setup lang="ts">
/**
 * The video receipt (docs/KOZ.md §6.6), the same player everywhere (an alert, a moment worth a
 * look, a sale): asking for it, the Ko‘z box finding and sending it (step by step, polled every
 * 2 s), then a dark player with the camera, the time and its own controls, or a clear reason why
 * there is no video. Space plays and pauses, the arrows skip 5 s, F fills the screen.
 */
import { Check, CircleAlert, Download, Maximize, Pause, Play, RotateCcw, Volume2, VolumeX, X } from "@lucide/vue";
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from "reka-ui";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";

import { failureKey, refusalKey, waitingStep } from "../lib/clip";
import { formatSeconds } from "../lib/format";
import { formatClock } from "../lib/tracks";
import { useClip } from "../lib/useClip";
import type { ClipRequest } from "../types";

const open = defineModel<boolean>("open", { default: false });

const props = defineProps<{
  request: ClipRequest | null;
  /** What the video is about ("Voided sale · 186 000 so‘m"), under the camera's name. */
  context?: string;
}>();

const { t } = useI18n();
const fmt = useFormat();

const asked = computed(() => (open.value ? props.request : null));
const { clip, error, phase, retry } = useClip(asked);

const title = computed(() => clip.value?.camera?.name ?? t("vision.clip.title"));
const when = computed(() => (clip.value ? fmt.instant(clip.value.start, "datetime") : ""));
const waiting = computed(() => phase.value === "requesting" || phase.value === "pending" || phase.value === "fetching");
const step = computed(() => waitingStep(phase.value));
const steps = computed(() => [t("vision.clip.step.asked"), t("vision.clip.step.cutting"), t("vision.clip.step.sending")]);
const reason = computed(() => {
  if (phase.value === "refused") return t(refusalKey(error.value));
  if (phase.value === "failed") return clip.value?.failure_text || t(failureKey(clip.value?.failure));
  return "";
});

// ─── The player ──────────────────────────────────────────────────────────────

const video = ref<HTMLVideoElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const playing = ref(false);
const muted = ref(true);
const current = ref(0);
const duration = ref(0);
const rate = ref(1);
const scrubbing = ref(false);

watch(phase, async (value) => {
  if (value !== "ready") return;
  await nextTick();
  // Starts by itself, muted (browsers allow that), as a receipt you glance at.
  video.value?.play().catch(() => undefined);
});
watch(open, (value) => {
  if (!value) {
    playing.value = false;
    current.value = 0;
    duration.value = 0;
  }
});

function toggle(): void {
  const el = video.value;
  if (!el) return;
  if (el.paused) void el.play().catch(() => undefined);
  else el.pause();
}

function seek(seconds: number): void {
  const el = video.value;
  if (!el || !Number.isFinite(el.duration)) return;
  el.currentTime = Math.min(Math.max(0, seconds), el.duration);
}

function setRate(value: number): void {
  rate.value = value;
  if (video.value) video.value.playbackRate = value;
}

function toggleMute(): void {
  muted.value = !muted.value;
  if (video.value) video.value.muted = muted.value;
}

function fullscreen(): void {
  const el = stage.value;
  if (!el) return;
  if (document.fullscreenElement) void document.exitFullscreen();
  else void el.requestFullscreen?.().catch(() => undefined);
}

function onKeydown(event: KeyboardEvent): void {
  if (phase.value !== "ready") return;
  if (event.key === " " || event.key === "k") {
    event.preventDefault();
    toggle();
  } else if (event.key === "ArrowRight") seek(current.value + 5);
  else if (event.key === "ArrowLeft") seek(current.value - 5);
  else if (event.key === "f") fullscreen();
  else if (event.key === "m") toggleMute();
}

const progress = computed(() => (duration.value ? (current.value / duration.value) * 100 : 0));
const downloadName = computed(() => (clip.value ? `koz-${clip.value.camera?.name ?? "clip"}-${clip.value.start.slice(0, 19).replace(/[:T]/g, "-")}.webm` : "clip.webm"));
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="anim-overlay fixed inset-0 z-[60] bg-[rgb(10_8_6/0.78)] backdrop-blur-[3px]" />
      <div class="pointer-events-none fixed inset-0 z-[61] grid place-items-center p-2 sm:p-6">
        <DialogContent
          class="koz-player anim-dialog pointer-events-auto relative flex max-h-[calc(100dvh-16px)] w-full max-w-[980px] flex-col overflow-hidden rounded-[20px] text-[#f3ece1] outline-none"
          :aria-describedby="undefined"
          @keydown="onKeydown"
        >
          <header class="flex items-start gap-3 px-4 pb-3 pt-4 sm:px-5">
            <div class="min-w-0 flex-1">
              <DialogTitle class="truncate text-md font-semibold text-white">{{ title }}</DialogTitle>
              <DialogDescription class="mt-0.5 truncate text-sm text-white/60">
                {{ [when, context].filter(Boolean).join(" · ") || t("vision.clip.requesting") }}
              </DialogDescription>
            </div>
            <span v-if="clip?.duration_s" class="mt-0.5 shrink-0 rounded-full bg-white/10 px-2.5 py-1 text-xs font-semibold tabular-nums text-white/80">{{ formatSeconds(clip.duration_s, fmt.lang.value) }}</span>
            <DialogClose class="pressable -mr-1.5 -mt-1 grid size-9 shrink-0 place-items-center rounded-full text-white/70 hover:bg-white/10 hover:text-white" :aria-label="t('shell.overlay.close')">
              <X :size="18" />
            </DialogClose>
          </header>

          <div ref="stage" class="koz-stage relative aspect-video w-full overflow-hidden bg-black" :data-phase="phase">
            <!-- Ready: the video and its controls. -->
            <template v-if="phase === 'ready' && clip?.video_url">
              <video
                ref="video"
                :src="clip.video_url"
                :poster="clip.poster_url ?? undefined"
                class="absolute inset-0 size-full bg-black object-contain"
                playsinline
                :muted="muted"
                preload="auto"
                @play="playing = true"
                @pause="playing = false"
                @ended="playing = false"
                @timeupdate="!scrubbing && (current = ($event.target as HTMLVideoElement).currentTime)"
                @loadedmetadata="duration = Number.isFinite(($event.target as HTMLVideoElement).duration) ? ($event.target as HTMLVideoElement).duration : (clip?.duration_s ?? 0)"
                @durationchange="Number.isFinite(($event.target as HTMLVideoElement).duration) && (duration = ($event.target as HTMLVideoElement).duration)"
                @click="toggle"
              />
              <button
                v-if="!playing"
                type="button"
                class="koz-bigplay absolute left-1/2 top-1/2 grid size-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full text-white"
                :aria-label="t('vision.clip.play')"
                @click="toggle"
              >
                <Play :size="28" class="translate-x-0.5" fill="currentColor" />
              </button>
              <div class="koz-controls absolute inset-x-0 bottom-0 flex flex-col gap-2 px-3 pb-3 pt-10 sm:px-4">
                <input
                  type="range"
                  class="koz-scrub w-full"
                  min="0"
                  :max="duration || 0"
                  step="0.05"
                  :value="current"
                  :style="{ '--fill': `${progress}%` }"
                  :aria-label="t('vision.clip.position')"
                  @pointerdown="scrubbing = true"
                  @pointerup="scrubbing = false"
                  @input="(current = Number(($event.target as HTMLInputElement).value)), seek(current)"
                />
                <div class="flex items-center gap-1.5">
                  <button type="button" class="koz-ctl" :aria-label="playing ? t('vision.clip.pause') : t('vision.clip.play')" @click="toggle">
                    <Pause v-if="playing" :size="18" fill="currentColor" />
                    <Play v-else :size="18" fill="currentColor" />
                  </button>
                  <button type="button" class="koz-ctl" :aria-label="muted ? t('vision.clip.unmute') : t('vision.clip.mute')" @click="toggleMute">
                    <VolumeX v-if="muted" :size="18" />
                    <Volume2 v-else :size="18" />
                  </button>
                  <span class="ml-1 text-xs font-semibold tabular-nums text-white/80">{{ formatClock(current) }} / {{ formatClock(duration) }}</span>
                  <span class="flex-1" />
                  <div class="flex rounded-full bg-white/10 p-0.5" role="group" :aria-label="t('vision.clip.speed')">
                    <button
                      v-for="value in [1, 2]"
                      :key="value"
                      type="button"
                      :class="['rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums transition-colors', rate === value ? 'bg-white text-[#141210]' : 'text-white/75 hover:text-white']"
                      :aria-pressed="rate === value"
                      @click="setRate(value)"
                    >
                      {{ value }}×
                    </button>
                  </div>
                  <a class="koz-ctl" :href="clip.video_url" :download="downloadName" :aria-label="t('vision.clip.download')"><Download :size="18" /></a>
                  <button type="button" class="koz-ctl" :aria-label="t('vision.clip.fullscreen')" @click="fullscreen"><Maximize :size="18" /></button>
                </div>
              </div>
            </template>

            <!-- Waiting for the box: three steps, the current one moving. -->
            <div v-else-if="waiting" class="koz-wait absolute inset-0 flex flex-col items-center justify-center gap-6 p-6 text-center" aria-live="polite">
              <div class="koz-reel" aria-hidden="true"><span /><span /><span /></div>
              <div>
                <p class="text-md font-semibold text-white">{{ phase === "fetching" ? t("vision.clip.fetching") : t("vision.clip.requesting") }}</p>
                <p class="mx-auto mt-1 max-w-md text-sm text-white/60">{{ t("vision.clip.fetchingHint") }}</p>
              </div>
              <ol class="flex flex-wrap items-center justify-center gap-2 text-xs font-semibold">
                <li
                  v-for="(label, index) in steps"
                  :key="label"
                  :class="['inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 transition-colors', index < step ? 'bg-[#7fd6aa]/15 text-[#9fe3c0]' : index === step ? 'bg-white/14 text-white' : 'bg-white/5 text-white/40']"
                  :aria-current="index === step ? 'step' : undefined"
                >
                  <Check v-if="index < step" :size="12" />
                  <span v-else :class="['size-1.5 rounded-full', index === step ? 'koz-step-dot bg-white' : 'bg-white/30']" />
                  {{ label }}
                </li>
              </ol>
            </div>

            <!-- No video: why, and what to do. -->
            <div v-else class="absolute inset-0 flex flex-col items-center justify-center gap-4 p-6 text-center" role="alert">
              <span class="grid size-12 place-items-center rounded-full bg-[#ff8466]/15 text-[#ff9c84]"><CircleAlert :size="22" /></span>
              <div>
                <p class="text-md font-semibold text-white">{{ phase === "refused" ? t("vision.clip.refused.title") : t("vision.clip.failed") }}</p>
                <p class="mx-auto mt-1 max-w-md text-sm text-white/65">{{ reason }}</p>
              </div>
              <button type="button" class="inline-flex items-center gap-2 rounded-full bg-white/12 px-4 py-2 text-sm font-semibold text-white hover:bg-white/20" @click="retry">
                <RotateCcw :size="15" />{{ t("common.retry") }}
              </button>
            </div>
          </div>

          <footer class="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-xs text-white/45 sm:px-5">
            <span>{{ t("vision.clip.unmasked") }}</span>
            <span v-if="phase === 'ready'" class="ml-auto hidden sm:inline">{{ t("vision.clip.keys") }}</span>
          </footer>
        </DialogContent>
      </div>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.koz-player {
  background: linear-gradient(180deg, #1b1815, #121010);
  box-shadow:
    0 0 0 1px rgb(255 255 255 / 0.06),
    0 40px 90px -20px rgb(0 0 0 / 0.75);
}
.koz-bigplay {
  background: rgb(255 255 255 / 0.16);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.25);
  transition: transform 0.15s var(--ease-out), background-color 0.15s;
}
.koz-bigplay:hover {
  background: rgb(255 255 255 / 0.24);
  transform: translate(-50%, -50%) scale(1.05);
}
.koz-controls {
  background: linear-gradient(0deg, rgb(0 0 0 / 0.72), transparent);
  opacity: 1;
  transition: opacity 0.2s;
}
.koz-stage:hover .koz-controls,
.koz-stage:focus-within .koz-controls {
  opacity: 1;
}
.koz-ctl {
  display: grid;
  width: 2rem;
  height: 2rem;
  place-items: center;
  border-radius: 999px;
  color: rgb(255 255 255 / 0.85);
}
.koz-ctl:hover {
  background: rgb(255 255 255 / 0.12);
  color: #fff;
}
.koz-scrub {
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  border-radius: 999px;
  background: linear-gradient(90deg, #ffc58a var(--fill), rgb(255 255 255 / 0.25) var(--fill));
  cursor: pointer;
}
.koz-scrub::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: #fff;
  box-shadow: 0 1px 4px rgb(0 0 0 / 0.5);
}
.koz-scrub::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border: 0;
  border-radius: 999px;
  background: #fff;
}
.koz-wait {
  background:
    radial-gradient(70% 60% at 50% 35%, rgb(255 197 138 / 0.1), transparent 70%),
    #0d0b0a;
}
.koz-reel {
  display: flex;
  gap: 10px;
}
.koz-reel span {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: #ffc58a;
  animation: koz-reel 1.2s ease-in-out infinite;
}
.koz-reel span:nth-child(2) {
  animation-delay: 0.15s;
}
.koz-reel span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes koz-reel {
  0%,
  100% {
    transform: translateY(0);
    opacity: 0.35;
  }
  40% {
    transform: translateY(-9px);
    opacity: 1;
  }
}
.koz-step-dot {
  animation: koz-reel 1.2s ease-in-out infinite;
}
:root[data-motion="reduced"] .koz-reel span,
:root[data-motion="reduced"] .koz-step-dot {
  animation: none;
  opacity: 0.8;
}
</style>
