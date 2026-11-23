<script setup lang="ts">
/**
 * TV mode: the live view for a screen on the pharmacy's wall or the owner's office. Full screen,
 * always dark, huge type: the clock and the branch, the counter cameras one after another every
 * 20 s (a bar shows when the next comes), today's visitors against receipts, the queue, who is at
 * the counter and the longest wait, the latest insight, and an open alert across the top. Esc or F
 * leaves; the pointer hides when it rests.
 */
import { Cctv, Lightbulb, Maximize, Minimize, X } from "@lucide/vue";
import { useEventListener } from "@vueuse/core";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useSecondClock } from "../lib/clock";
import type { Alert, Insight, Live, LiveCamera, Zone } from "../types";
import AlertBanner from "./AlertBanner.vue";
import LiveCounters from "./LiveCounters.vue";
import LiveFrame from "./LiveFrame.vue";

const props = defineProps<{
  branchName: string;
  live: Live | null;
  liveAt: number;
  zonesOf: (id: number) => Zone[];
  queuePeople: number;
  queueWaitS: number;
  canVideo: boolean;
  insight: Insight | null;
  /** Opened by a click or F: ask the browser for the whole screen. */
  fullscreen?: boolean;
}>();

const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const clock = useSecondClock();

const ROTATE_MS = 20_000;
const root = ref<HTMLElement | null>(null);

const cameras = computed<LiveCamera[]>(() => {
  const all = props.live?.cameras ?? [];
  const counters = all.filter((camera) => camera.role === "counter");
  return counters.length ? counters : all.filter((camera) => camera.online);
});
const index = ref(0);
const cycle = ref(0);
let rotate: ReturnType<typeof setInterval> | undefined;
function restart(): void {
  clearInterval(rotate);
  cycle.value++;
  rotate = setInterval(() => {
    if (cameras.value.length > 1) index.value = (index.value + 1) % cameras.value.length;
    cycle.value++;
  }, ROTATE_MS);
}
watch(
  () => cameras.value.length,
  (n) => {
    if (index.value >= n) index.value = 0;
  },
);
const current = computed(() => cameras.value[index.value] ?? null);
const next = computed(() => (cameras.value.length > 1 ? cameras.value[(index.value + 1) % cameras.value.length] : null));

const time = computed(() => new Intl.DateTimeFormat("en-GB", { timeZone: company.timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(clock.value));
const seconds = computed(() => new Intl.DateTimeFormat("en-GB", { timeZone: company.timezone, second: "2-digit" }).format(clock.value).padStart(2, "0"));
const date = computed(() => fmt.day(today.value, "weekday"));

const visitors = computed(() => props.live?.today.visitors ?? null);
const receipts = computed(() => props.live?.today.receipts ?? null);
const share = computed(() => (visitors.value && receipts.value !== null && visitors.value >= receipts.value ? (receipts.value / visitors.value) * 100 : null));
const alerts = computed<Alert[]>(() => props.live?.open_alerts ?? []);

// The pointer hides after three quiet seconds.
const idle = ref(false);
let idleTimer: ReturnType<typeof setTimeout> | undefined;
function wake(): void {
  idle.value = false;
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => (idle.value = true), 3000);
}
useEventListener("pointermove", wake, { passive: true });

const full = ref(false);
function syncFull(): void {
  full.value = !!document.fullscreenElement;
}
useEventListener(document, "fullscreenchange", syncFull);
async function toggleFull(): Promise<void> {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await root.value?.requestFullscreen?.();
  } catch {
    // The browser said no (not from a click): the overlay still fills the window.
  }
}

useEventListener("keydown", (event: KeyboardEvent) => {
  if (event.key === "Escape" && !document.fullscreenElement) {
    event.preventDefault();
    emit("close");
  } else if ((event.key === "f" || event.key === "F" || event.code === "KeyF") && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    emit("close");
  }
});

let before: Element | null = null;
onMounted(() => {
  before = document.activeElement;
  root.value?.focus({ preventScroll: true });
  restart();
  wake();
  if (props.fullscreen) void toggleFull();
});
onBeforeUnmount(() => {
  clearInterval(rotate);
  clearTimeout(idleTimer);
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
  (before as HTMLElement | null)?.focus?.({ preventScroll: true });
});
</script>

<template>
  <Teleport to="body">
    <div
      ref="root"
      class="koz-tv fixed inset-0 z-[78] flex flex-col overflow-y-auto bg-canvas text-fg outline-none"
      data-theme="dark"
      role="dialog"
      aria-modal="true"
      :aria-label="t('vision.live.tv')"
      tabindex="-1"
      :data-idle="idle || undefined"
    >
      <header class="flex shrink-0 items-center gap-4 px-5 pb-3 pt-4 md:px-10 md:pt-7">
        <span class="grid size-11 shrink-0 place-items-center rounded-[14px] bg-primary text-on-primary md:size-14"><Cctv :size="26" /></span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold uppercase tracking-[0.14em] text-muted md:text-md">{{ t("vision.title") }} · {{ t("vision.subtitle") }}</p>
          <h1 class="koz-tv-branch truncate font-semibold">{{ branchName }}</h1>
        </div>
        <div class="text-right">
          <p class="koz-tv-clock font-semibold tabular-nums">{{ time }}<span class="koz-tv-seconds text-muted">:{{ seconds }}</span></p>
          <p class="text-sm text-muted md:text-lg">{{ date }}</p>
        </div>
        <div class="koz-tv-tools flex shrink-0 flex-col gap-2">
          <button type="button" class="koz-tv-btn" :aria-label="full ? t('vision.tv.windowed') : t('vision.tv.fullscreen')" @click="toggleFull">
            <Minimize v-if="full" :size="18" /><Maximize v-else :size="18" />
          </button>
          <button type="button" class="koz-tv-btn" :aria-label="t('vision.tv.exit')" @click="emit('close')"><X :size="18" /></button>
        </div>
      </header>

      <div class="px-5 md:px-10"><AlertBanner :alerts="alerts" :cameras="live?.cameras ?? []" :live-at="liveAt" size="tv" :actions="false" /></div>

      <main class="grid min-h-0 flex-1 gap-5 px-5 pb-6 pt-4 md:gap-7 md:px-10 md:pb-10 xl:grid-cols-[minmax(0,1fr)_minmax(360px,30vw)]">
        <section class="flex min-w-0 flex-col gap-3" :aria-label="current?.name ?? t('vision.tv.noCamera')">
          <div class="relative min-h-0">
            <Transition name="koz-tv-cam" mode="out-in">
              <LiveFrame
                v-if="current"
                :key="current.id"
                :camera-id="current.id"
                :zones="zonesOf(current.id)"
                :online="current.online"
                :can-video="canVideo"
                :queue-wait-s="queueWaitS"
                :interval="500"
                rounded="22px"
                class="koz-tv-frame"
              >
                <div class="pointer-events-none absolute left-0 top-0 p-4">
                  <span class="koz-tv-glass inline-flex items-center gap-2.5 rounded-full px-4 py-2 text-lg font-semibold text-white">
                    <span class="koz-tv-rec size-2.5 rounded-full bg-[#ff5a4e]" />{{ current.name }}
                  </span>
                </div>
              </LiveFrame>
              <div v-else class="grid aspect-video place-items-center rounded-[22px] border border-line bg-surface text-xl text-muted">{{ t("vision.tv.noCamera") }}</div>
            </Transition>
          </div>
          <div v-if="next" class="flex items-center gap-3">
            <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
              <div :key="cycle" class="koz-tv-bar h-full rounded-full bg-primary" :style="{ animationDuration: `${ROTATE_MS}ms` }" />
            </div>
            <span class="shrink-0 text-base text-muted md:text-lg">{{ t("vision.tv.next", { name: next.name }) }}</span>
          </div>
        </section>

        <aside class="flex min-w-0 flex-col gap-4 md:gap-5">
          <div class="koz-tv-today rounded-[22px] border border-line bg-surface p-5 md:p-7">
            <p class="text-lg font-semibold text-muted">{{ t("vision.tv.today") }}</p>
            <div class="mt-3 grid grid-cols-2 gap-4">
              <div>
                <p class="koz-tv-big font-semibold tabular-nums">{{ visitors === null ? "—" : fmt.number(visitors) }}</p>
                <p class="text-lg text-muted">{{ t("vision.tv.cameIn") }}</p>
              </div>
              <div>
                <p class="koz-tv-big font-semibold tabular-nums text-success">{{ receipts === null ? "—" : fmt.number(receipts) }}</p>
                <p class="text-lg text-muted">{{ t("vision.tv.bought") }}</p>
              </div>
            </div>
            <div v-if="share !== null" class="mt-5">
              <div class="flex h-3 overflow-hidden rounded-full bg-surface-3">
                <div class="koz-tv-share h-full rounded-full bg-success" :style="{ width: `${share}%` }" />
              </div>
              <p class="mt-2 text-lg text-muted">{{ t("vision.tv.share", { share: fmt.percent(share) }) }}</p>
            </div>
          </div>
          <LiveCounters :live="live" :live-at="liveAt" :queue-people="queuePeople" :queue-wait-s="queueWaitS" size="tv" :omit="['visitors']" class="koz-tv-counters" />
          <div v-if="insight" class="koz-tv-insight flex gap-4 rounded-[22px] border border-line bg-surface p-5 md:p-6" :data-severity="insight.severity">
            <span class="grid size-11 shrink-0 place-items-center rounded-[13px] bg-accent-soft text-accent-fg"><Lightbulb :size="22" /></span>
            <div class="min-w-0">
              <p class="text-sm font-semibold uppercase tracking-[0.1em] text-muted">{{ t("vision.tv.latest") }}</p>
              <p class="koz-tv-clamp mt-1 text-lg leading-snug text-fg md:text-xl">{{ insight.text }}</p>
            </div>
          </div>
        </aside>
      </main>
      <p class="koz-tv-hint pointer-events-none fixed bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-surface/80 px-3 py-1 text-xs text-muted backdrop-blur">{{ t("vision.tv.hint") }}</p>
    </div>
  </Teleport>
</template>

<style scoped>
.koz-tv {
  background:
    radial-gradient(80% 60% at 70% -10%, color-mix(in srgb, var(--c-primary) 12%, transparent), transparent 60%),
    var(--c-canvas);
}
.koz-tv[data-idle] {
  cursor: none;
}
.koz-tv[data-idle] .koz-tv-tools,
.koz-tv[data-idle] .koz-tv-hint {
  opacity: 0;
}
.koz-tv-tools,
.koz-tv-hint {
  transition: opacity 0.4s ease;
}
.koz-tv-branch {
  font-size: clamp(1.5rem, 3.2vw, 2.75rem);
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.koz-tv-clock {
  font-size: clamp(2rem, 5vw, 4.25rem);
  line-height: 1;
  letter-spacing: -0.03em;
}
.koz-tv-seconds {
  font-size: 0.5em;
  letter-spacing: 0;
}
.koz-tv-big {
  font-size: clamp(2.75rem, 6vw, 5.5rem);
  line-height: 1;
  letter-spacing: -0.04em;
}
.koz-tv-btn {
  display: grid;
  width: 2.5rem;
  height: 2.5rem;
  place-items: center;
  border-radius: 999px;
  background: var(--c-surface-2);
  color: var(--c-muted);
}
.koz-tv-btn:hover {
  color: var(--c-text);
  background: var(--c-surface-3);
}
.koz-tv-frame {
  max-height: calc(100dvh - 15rem);
  margin-inline: auto;
  box-shadow: 0 30px 80px -30px rgb(0 0 0 / 0.8);
}
.koz-tv-glass {
  background: rgb(14 11 9 / 0.6);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}
.koz-tv-rec {
  animation: koz-tv-rec 1.6s ease-in-out infinite;
}
@keyframes koz-tv-rec {
  50% {
    opacity: 0.35;
  }
}
.koz-tv-bar {
  width: 0;
  animation-name: koz-tv-fill;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes koz-tv-fill {
  to {
    width: 100%;
  }
}
.koz-tv-share {
  transition: width 0.8s var(--ease-out);
}
.koz-tv-clamp {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
}
.koz-tv-cam-enter-active,
.koz-tv-cam-leave-active {
  transition:
    opacity 0.45s ease,
    transform 0.6s var(--ease-out);
}
.koz-tv-cam-enter-from {
  opacity: 0;
  transform: scale(1.015);
}
.koz-tv-cam-leave-to {
  opacity: 0;
}
:root[data-motion="reduced"] .koz-tv-rec,
:root[data-motion="reduced"] .koz-tv-bar {
  animation: none;
  width: 100%;
}
</style>
