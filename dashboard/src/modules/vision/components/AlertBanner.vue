<script setup lang="ts">
/**
 * Open alerts, sliding in at the top of the live view (docs/KOZ.md §5.8, §7): amber for a queue,
 * red for customers waiting with nobody at the counter, each with its timer running, the people
 * waiting and the longest wait right now, who said "Men boraman", and buttons to look at the camera
 * or open the video. Nobody at the counter comes first.
 */
import { Check, Hand, Play, ScanEye, UsersRound } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";

import { useSecondClock } from "../lib/clock";
import { alertWeight } from "../lib/look";
import { formatClock, tickingWait } from "../lib/tracks";
import type { Alert, LiveCamera } from "../types";

const props = withDefaults(
  defineProps<{
    alerts: Alert[];
    cameras?: LiveCamera[];
    liveAt?: number;
    canVideo?: boolean;
    size?: "page" | "tv";
    /** Show the camera button (not on the TV). */
    actions?: boolean;
  }>(),
  { cameras: () => [], liveAt: 0, canVideo: false, size: "page", actions: true },
);

const emit = defineEmits<{ look: [cameraId: number]; video: [alert: Alert] }>();

const { t } = useI18n();
const clock = useSecondClock();

const shown = computed(() =>
  props.alerts
    .filter((alert) => alert.state === "open" && alert.kind !== "agent_offline")
    .sort((a, b) => alertWeight(a.kind) - alertWeight(b.kind) || a.started_at.localeCompare(b.started_at))
    .slice(0, 3)
    .map((alert) => {
      const camera = props.cameras.find((c) => c.id === alert.camera?.id);
      const waiting = camera?.queue ?? alert.peak_queue ?? 0;
      const wait = camera?.wait_s ? tickingWait(camera.wait_s, props.liveAt, clock.value) : alert.peak_wait_s;
      const since = Math.max(0, Math.floor((clock.value - new Date(alert.started_at).getTime()) / 1000));
      const where = alert.camera ? `${alert.camera.name} (${alert.branch.name})` : alert.branch.name;
      return {
        alert,
        title: `${t(`vision.alert.kind.${alert.kind}`)} · ${where}`,
        body:
          alert.kind === "unattended"
            ? t("vision.banner.unattendedBody", { n: waiting, wait: formatClock(wait ?? 0) })
            : t("vision.banner.queueBody", { n: waiting, wait: formatClock(wait ?? 0) }),
        since: formatClock(since),
      };
    }),
);
</script>

<template>
  <TransitionGroup tag="div" name="koz-banner" :class="['flex flex-col', size === 'tv' ? 'gap-3' : 'gap-2']" role="status" aria-live="polite">
    <article
      v-for="item in shown"
      :key="item.alert.id"
      class="koz-banner relative flex flex-wrap items-center gap-x-4 gap-y-2 overflow-hidden rounded-[16px] px-4 py-3"
      :data-kind="item.alert.kind"
      :data-size="size"
      :data-alert="item.alert.id"
    >
      <span class="koz-banner-sweep pointer-events-none absolute inset-0" aria-hidden="true" />
      <span class="koz-banner-icon relative grid shrink-0 place-items-center rounded-full" aria-hidden="true">
        <Hand v-if="item.alert.kind === 'unattended'" :size="size === 'tv' ? 26 : 18" />
        <UsersRound v-else :size="size === 'tv' ? 26 : 18" />
      </span>
      <div class="relative min-w-0 flex-1">
        <h3 class="koz-banner-title truncate font-semibold">{{ item.title }}</h3>
        <p class="koz-banner-body truncate">{{ item.body }}</p>
      </div>
      <div class="relative flex shrink-0 flex-wrap items-center gap-2">
        <span v-if="item.alert.acknowledged_by" class="koz-banner-chip inline-flex max-w-[16rem] items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold">
          <Check :size="13" class="shrink-0" /><span class="truncate">{{ t("vision.banner.going", { name: item.alert.acknowledged_by.name }) }}</span>
        </span>
        <span class="koz-banner-timer inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold tabular-nums" :aria-label="t('vision.banner.since', { time: item.since })">
          <span class="koz-banner-dot size-1.5 rounded-full" aria-hidden="true" />{{ item.since }}
        </span>
        <template v-if="actions && size !== 'tv'">
          <UiButton v-if="item.alert.camera" size="sm" variant="secondary" :icon="ScanEye" @click="emit('look', item.alert.camera.id)">{{ t("vision.banner.look") }}</UiButton>
          <UiButton v-if="canVideo && item.alert.camera" size="sm" variant="secondary" :icon="Play" @click="emit('video', item.alert)">{{ t("vision.video") }}</UiButton>
        </template>
      </div>
    </article>
  </TransitionGroup>
</template>

<style scoped>
.koz-banner {
  --tone: #d98a1c;
  --tone-soft: #fff2d9;
  --tone-ink: #7a4a05;
  background: color-mix(in srgb, var(--tone-soft) 92%, var(--c-surface));
  border: 1px solid color-mix(in srgb, var(--tone) 45%, transparent);
  color: var(--tone-ink);
  box-shadow: 0 10px 28px -16px color-mix(in srgb, var(--tone) 70%, transparent);
}
.koz-banner[data-kind="unattended"] {
  --tone: #d9452e;
  --tone-soft: #ffe7e1;
  --tone-ink: #7c1f10;
}
[data-theme="dark"] .koz-banner {
  --tone-soft: #3a2a0f;
  --tone-ink: #ffd99a;
}
[data-theme="dark"] .koz-banner[data-kind="unattended"] {
  --tone-soft: #3d1711;
  --tone-ink: #ffc2b5;
}
.koz-banner-sweep {
  background: linear-gradient(105deg, transparent 20%, color-mix(in srgb, var(--tone) 14%, transparent) 45%, transparent 70%);
  background-size: 250% 100%;
  animation: koz-sweep 3.2s ease-in-out infinite;
}
@keyframes koz-sweep {
  from {
    background-position: 130% 0;
  }
  to {
    background-position: -130% 0;
  }
}
.koz-banner-icon {
  width: 2.25rem;
  height: 2.25rem;
  background: var(--tone);
  color: #fff;
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--tone) 55%, transparent);
  animation: koz-ping 1.8s ease-out infinite;
}
@keyframes koz-ping {
  70% {
    box-shadow: 0 0 0 10px color-mix(in srgb, var(--tone) 0%, transparent);
  }
}
.koz-banner-title {
  font-size: var(--text-base);
  line-height: 1.3;
}
.koz-banner-body {
  font-size: var(--text-sm);
  opacity: 0.85;
}
.koz-banner-chip {
  background: color-mix(in srgb, var(--c-success) 16%, var(--c-surface));
  color: var(--c-success);
}
.koz-banner-timer {
  background: color-mix(in srgb, var(--tone) 16%, transparent);
  font-size: var(--text-sm);
}
.koz-banner-dot {
  background: var(--tone);
}
.koz-banner[data-size="tv"] {
  padding: 1.25rem 1.5rem;
  border-radius: 22px;
}
.koz-banner[data-size="tv"] .koz-banner-icon {
  width: 3.5rem;
  height: 3.5rem;
}
.koz-banner[data-size="tv"] .koz-banner-title {
  font-size: 1.75rem;
}
.koz-banner[data-size="tv"] .koz-banner-body {
  font-size: 1.25rem;
}
.koz-banner[data-size="tv"] .koz-banner-timer {
  font-size: 1.5rem;
  padding: 0.4rem 1rem;
}
.koz-banner-enter-active,
.koz-banner-leave-active {
  transition:
    opacity 0.32s var(--ease-out),
    transform 0.42s var(--ease-out);
}
.koz-banner-enter-from,
.koz-banner-leave-to {
  opacity: 0;
  transform: translateY(-12px) scale(0.985);
}
:root[data-motion="reduced"] .koz-banner-sweep,
:root[data-motion="reduced"] .koz-banner-icon {
  animation: none;
}
:root[data-motion="reduced"] .koz-banner-enter-active,
:root[data-motion="reduced"] .koz-banner-leave-active {
  transition: opacity 80ms linear;
}
</style>
