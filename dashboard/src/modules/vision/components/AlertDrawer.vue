<script setup lang="ts">
/**
 * One alert (docs/KOZ.md §6.5), opened from `?alert=<id>`: the photo the box sent (tap for full
 * size), what happened in order (it started with so many waiting → who said "Men boraman" → it
 * was over, and how long it lasted), the peaks, and the video of it for those who may watch.
 */
import { BellRing, CircleCheck, Hand, ImageOff, Play, UsersRound, WifiOff } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DescriptionList from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TimelineEvent } from "@/components/TimelineList.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useAlert } from "../api";
import { useSecondClock } from "../lib/clock";
import { formatSeconds } from "../lib/format";
import { ALERT_TONE } from "../lib/look";
import type { Alert, ClipRequest } from "../types";
import ClipPlayer from "./ClipPlayer.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const clock = useSecondClock();

const id = useRouteState("alert", rs.optionalNumber(), { push: true });
const query = useAlert(id);
const alert = computed<Alert | null>(() => query.data.value ?? null);
const canVideo = computed(() => company.can("vision.video"));

const duration = computed(() => {
  const a = alert.value;
  if (!a) return null;
  if (a.state === "open") return Math.max(0, (clock.value - new Date(a.started_at).getTime()) / 1000);
  return a.duration_s;
});
const title = computed(() => (alert.value ? t(`vision.alert.kind.${alert.value.kind}`) : t("vision.alert.title")));
const subtitle = computed(() => (alert.value ? [alert.value.camera?.name, alert.value.branch.name, fmt.instant(alert.value.started_at, "datetime")].filter(Boolean).join(" · ") : undefined));

const facts = computed(() => {
  const a = alert.value;
  if (!a) return [];
  const items = [
    { key: "duration", label: t("vision.alert.duration"), value: duration.value === null ? null : formatSeconds(duration.value, fmt.lang.value) },
    { key: "branch", label: t("vision.alert.branch"), value: a.branch.name },
  ];
  if (a.kind !== "agent_offline") {
    items.splice(1, 0, { key: "peakQueue", label: t("vision.alert.peakQueue"), value: a.peak_queue === null ? null : t("vision.alert.people", { n: a.peak_queue }, a.peak_queue) });
    items.splice(2, 0, { key: "peakWait", label: t("vision.alert.peakWait"), value: a.peak_wait_s === null ? null : formatSeconds(a.peak_wait_s, fmt.lang.value) });
    items.push({ key: "camera", label: t("vision.alert.camera"), value: a.camera?.name ?? null });
  }
  return items;
});

const events = computed<TimelineEvent[]>(() => {
  const a = alert.value;
  if (!a) return [];
  const out: TimelineEvent[] = [
    {
      key: "started",
      at: a.started_at,
      title: t("vision.alert.started"),
      body: a.kind === "agent_offline" ? t("vision.alert.offlineBody") : t("vision.alert.startedBody", { n: a.peak_queue ?? 0, wait: formatSeconds(a.peak_wait_s ?? 0, fmt.lang.value) }),
      icon: a.kind === "unattended" ? Hand : a.kind === "agent_offline" ? WifiOff : UsersRound,
      tone: ALERT_TONE[a.kind] === "neutral" ? "neutral" : ALERT_TONE[a.kind],
    },
  ];
  if (a.acknowledged_by && a.acknowledged_at) {
    out.push({ key: "ack", at: a.acknowledged_at, title: t("vision.alert.acknowledged", { name: a.acknowledged_by.name }), icon: BellRing, tone: "primary", actor: { name: a.acknowledged_by.name } });
  }
  if (a.resolved_at) {
    out.push({ key: "resolved", at: a.resolved_at, title: t("vision.alert.resolved"), body: a.duration_s !== null ? t("vision.alert.resolvedBody", { time: formatSeconds(a.duration_s, fmt.lang.value) }) : undefined, icon: CircleCheck, tone: "success" });
  }
  return out;
});

const TONES = {
  neutral: "bg-surface-2 text-muted dark:bg-surface-3",
  primary: "bg-accent-soft text-accent-fg",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
} as const;

const lightbox = ref(false);
const clip = ref<ClipRequest | null>(null);
const clipOpen = computed({ get: () => clip.value !== null, set: (value: boolean) => (clip.value = value ? clip.value : null) });
</script>

<template>
  <UiDrawer query-key="alert" size="lg" :title="title" :description="subtitle">
    <template #header-actions>
      <StatusPill v-if="alert" :tone="alert.state === 'open' ? (alert.kind === 'unattended' ? 'danger' : 'warning') : 'success'" :live="alert.state === 'open'" size="sm" :label="t(`vision.state.${alert.state}`)" />
    </template>
    <div v-if="query.isPending.value" class="flex flex-col gap-4 p-5">
      <SkeletonBlock class="aspect-video" height="auto" radius="14px" />
      <SkeletonBlock :lines="3" />
    </div>
    <ErrorState v-else-if="query.isError.value" class="m-5" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="alert" class="flex flex-col gap-6 p-5" :data-alert="alert.id">
      <div v-if="alert.kind !== 'agent_offline'">
        <button v-if="alert.photo_url" type="button" class="group relative block w-full overflow-hidden rounded-[14px] bg-[#0f0d0b]" :aria-label="t('vision.alert.photo', { camera: alert.camera?.name ?? '' })" @click="lightbox = true">
          <img :src="alert.photo_url" :alt="t('vision.alert.photo', { camera: alert.camera?.name ?? '' })" class="aspect-video w-full object-cover transition-transform duration-500 group-hover:scale-[1.015]" />
        </button>
        <div v-else class="grid aspect-video place-items-center rounded-[14px] bg-surface-2 text-sm text-muted dark:bg-surface-3">
          <span class="flex flex-col items-center gap-2"><ImageOff :size="20" />{{ t("vision.alert.noPhoto") }}</span>
        </div>
        <div v-if="canVideo && alert.camera" class="mt-3 flex flex-wrap items-center gap-2">
          <UiButton variant="primary" :icon="Play" @click="clip = { alert_id: alert.id }">{{ t("vision.video") }}</UiButton>
          <span class="text-xs text-muted">{{ t("vision.clip.unmasked") }}</span>
        </div>
      </div>

      <DescriptionList :items="facts" :columns="2" />

      <section>
        <h3 class="mb-3 text-sm font-semibold text-fg">{{ t("vision.alert.timeline") }}</h3>
        <!-- In the order it happened: started, someone said they're going, over. -->
        <ol class="flex flex-col">
          <li v-for="(event, index) in events" :key="event.key" class="flex gap-3" :data-event="event.key">
            <span class="flex flex-col items-center">
              <span :class="['grid size-8 shrink-0 place-items-center rounded-full', TONES[event.tone ?? 'neutral']]"><component :is="event.icon" :size="15" /></span>
              <span v-if="index < events.length - 1 || alert.state === 'open'" class="my-1 w-px flex-1 bg-line" />
            </span>
            <div class="min-w-0 flex-1 pb-4">
              <p class="flex items-baseline justify-between gap-3">
                <span class="text-sm font-semibold text-fg">{{ event.title }}</span>
                <time :datetime="event.at" class="shrink-0 text-xs tabular-nums text-muted">{{ fmt.instant(event.at, "time") }}</time>
              </p>
              <p v-if="event.body" class="mt-0.5 text-sm text-muted">{{ event.body }}</p>
            </div>
          </li>
          <li v-if="alert.state === 'open'" class="flex gap-3">
            <span class="grid size-8 shrink-0 place-items-center"><span class="size-2.5 animate-pulse rounded-full bg-warning" /></span>
            <p class="pt-1.5 text-sm font-medium text-warning">{{ t("vision.alert.stillOpen") }}</p>
          </li>
        </ol>
      </section>
    </div>
  </UiDrawer>
  <ImageLightbox v-if="alert?.photo_url" v-model:open="lightbox" :images="[{ src: alert.photo_url, alt: t('vision.alert.photo', { camera: alert.camera?.name ?? '' }) }]" :title="subtitle" />
  <ClipPlayer v-model:open="clipOpen" :request="clip" :context="title" />
</template>
