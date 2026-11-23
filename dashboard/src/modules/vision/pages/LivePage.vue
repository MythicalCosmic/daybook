<script setup lang="ts">
/**
 * Ko‘z › Live: what the cameras see right now (docs/KOZ.md §6.2, §6.3). Big live numbers (came
 * in today, in the queue, at the counter, the longest wait ticking), open alerts sliding in with
 * their timers, and the cameras: a wall of every camera of the branch, or one in focus with the
 * rest on a rail. Numbers every 5 s, pictures every 500 ms only for the cameras on screen and only
 * while the tab is visible. TV mode (the button, F, or `?tv=1`) fills the screen for a wall TV.
 * Branch, view, camera and TV live in the URL.
 */
import { Cctv, Focus, LayoutGrid, Plus, Tv } from "@lucide/vue";
import { useMediaQuery, useResizeObserver } from "@vueuse/core";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useHotkey } from "@/core/hotkeys";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCameras, useLive, useOverview, useSettings } from "../api";
import AlertBanner from "../components/AlertBanner.vue";
import CameraTile from "../components/CameraTile.vue";
import ClipPlayer from "../components/ClipPlayer.vue";
import LiveCounters from "../components/LiveCounters.vue";
import TvMode from "../components/TvMode.vue";
import { bySeverity } from "../lib/overview";
import { DEFAULT_RULES, ROLE_ORDER } from "../lib/rules";
import type { Alert, CameraRole, ClipRequest, LiveCamera, Zone } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();
const { isPhone } = useBreakpoints();

const canVideo = computed(() => company.can("vision.video"));
const canManage = computed(() => company.can("vision.manage"));

const allCameras = useCameras(null);
const settings = useSettings();
const rules = computed(() => ({ ...DEFAULT_RULES, ...(settings.data.value ?? {}) }));

const branchParam = useRouteState("branch", rs.optionalNumber());
const branches = computed(() => company.current?.branches ?? []);
/** Branches that have cameras, the first of them by default. */
const withCameras = computed(() => branches.value.filter((branch) => (allCameras.data.value ?? []).some((camera) => camera.branch.id === branch.id)));
const branch = computed<number | null>(() => branchParam.value ?? withCameras.value[0]?.id ?? branches.value[0]?.id ?? null);
const branchName = computed(() => branches.value.find((b) => b.id === branch.value)?.name ?? "");
const branchOptions = computed(() => (withCameras.value.length ? withCameras.value : branches.value).map((b) => ({ value: b.id, label: b.name })));

const live = useLive(branch, computed(() => branch.value !== null));
const liveAt = computed(() => live.dataUpdatedAt.value || Date.now());

const view = useRouteState("view", rs.enum(["wall", "focus"] as const, "wall"));
const focusId = useRouteState("camera", rs.optionalNumber());
const tv = useRouteState("tv", rs.boolean(), { push: true });
const tvFullscreen = ref(false);

const zonesOf = (id: number): Zone[] => (allCameras.data.value ?? []).find((camera) => camera.id === id)?.zones ?? [];
const enabledOf = (id: number): boolean => (allCameras.data.value ?? []).find((camera) => camera.id === id)?.enabled ?? true;

const cameras = computed<LiveCamera[]>(() =>
  [...(live.data.value?.cameras ?? [])]
    .filter((camera) => camera.branch_id === branch.value || branch.value === null)
    .sort(
      (a, b) =>
        Number(b.online) - Number(a.online) ||
        Number(enabledOf(b.id)) - Number(enabledOf(a.id)) ||
        ROLE_ORDER.indexOf(a.role as CameraRole) - ROLE_ORDER.indexOf(b.role as CameraRole) ||
        a.name.localeCompare(b.name),
    ),
);
const focused = computed(() => cameras.value.find((camera) => camera.id === focusId.value) ?? cameras.value.find((camera) => camera.role === "counter") ?? cameras.value[0] ?? null);
const rail = computed(() => cameras.value.filter((camera) => camera.id !== focused.value?.id));
const alerts = computed<Alert[]>(() => live.data.value?.open_alerts ?? []);
const streaming = computed(() => live.isSuccess.value && !live.isError.value && cameras.value.some((camera) => camera.online && !camera.stale));

function openCamera(id: number): void {
  focusId.value = id;
  view.value = "focus";
}

function openTv(fullscreen: boolean): void {
  tvFullscreen.value = fullscreen;
  tv.value = true;
}

useHotkey("f", () => (tv.value ? (tv.value = false) : openTv(true)), { group: "page", description: "vision.hotkey.tv" });

// TV mode shows the day's most important insight.
const day = useOverview(
  computed(() => ({ branch: branch.value, day: today.value })),
  computed(() => tv.value),
);
const insight = computed(() => (tv.value ? (bySeverity(day.data.value?.insights ?? [])[0] ?? null) : null));

const clip = ref<ClipRequest | null>(null);
const clipOpen = computed({ get: () => clip.value !== null, set: (value: boolean) => (clip.value = value ? clip.value : null) });
function video(alert: Alert): void {
  clip.value = { alert_id: alert.id };
}

const viewOptions = computed(() => [
  { value: "wall" as const, label: t("vision.live.wall"), icon: LayoutGrid },
  { value: "focus" as const, label: t("vision.live.focus"), icon: Focus },
]);

watch(branch, () => (focusId.value = null));

// The rail beside the focused camera is as tall as its picture, and scrolls.
const focusTile = ref<InstanceType<typeof CameraTile> | null>(null);
const focusHeight = ref(0);
const isDesktopWide = useMediaQuery("(min-width: 1280px)");
useResizeObserver(
  () => (focusTile.value?.$el as HTMLElement | undefined) ?? null,
  (entries) => (focusHeight.value = Math.round(entries[0]?.contentRect.height ?? 0)),
);
const loading = computed(() => live.isPending.value || allCameras.isPending.value);
const empty = computed(() => !loading.value && !live.isError.value && !(allCameras.data.value ?? []).length);
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('vision.live.title')" :description="t('vision.live.description')">
      <template #actions>
        <SelectBox v-if="branchOptions.length > 1" :model-value="branch" size="sm" class="w-48 max-sm:w-full" :options="branchOptions" :aria-label="t('vision.filter.branch')" @update:model-value="branchParam = $event" />
        <SegmentedControl v-model="view" size="sm" :options="viewOptions" :aria-label="t('vision.live.layout')" />
        <UiButton variant="primary" size="sm" :icon="Tv" kbd="F" @click="openTv(true)">{{ t("vision.live.tv") }}</UiButton>
      </template>
      <template #meta>
        <StatusPill v-if="streaming" tone="success" live size="sm" :label="t('vision.live.live')" />
        <StatusPill v-else-if="live.isError.value" tone="warning" size="sm" :label="t('vision.live.reconnecting')" />
      </template>
    </PageHeader>

    <EmptyState v-if="empty" class="ui-card py-14" :icon="Cctv" :title="t('vision.camera.none')" :description="canManage ? t('vision.camera.noneBody') : t('vision.pitch.ask')">
      <UiButton v-if="canManage" variant="primary" :icon="Plus" :to="`/c/${company.currentId}/vision/cameras?pair=1`">{{ t("vision.pitch.cta") }}</UiButton>
    </EmptyState>
    <ErrorState v-else-if="live.isError.value && !live.data.value" class="ui-card" :error="live.error.value" :retry="() => live.refetch()" />

    <template v-else>
      <AlertBanner :alerts="alerts" :cameras="cameras" :live-at="liveAt" :can-video="canVideo" @look="openCamera" @video="video" />

      <LiveCounters :live="live.data.value ?? null" :live-at="liveAt" :queue-people="rules.queue_people" :queue-wait-s="rules.queue_wait_s" :loading="loading" />

      <!-- First load: the wall's own shape. -->
      <div v-if="loading" class="grid gap-3 md:grid-cols-2">
        <SkeletonBlock v-for="n in 4" :key="n" class="aspect-video" height="auto" radius="16px" />
      </div>

      <section v-else-if="view === 'wall'" class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3" :aria-label="t('vision.live.wall')" data-view="wall">
        <CameraTile
          v-for="camera in cameras"
          :key="camera.id"
          :camera="camera"
          :zones="zonesOf(camera.id)"
          :analysed="enabledOf(camera.id)"
          :enabled="!tv"
          :can-video="canVideo"
          :queue-people="rules.queue_people"
          :queue-wait-s="rules.queue_wait_s"
          :live-at="liveAt"
          size="wall"
          @open="openCamera"
        />
      </section>

      <section v-else-if="focused" class="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_280px]" :aria-label="focused.name" data-view="focus">
        <CameraTile
          ref="focusTile"
          :key="focused.id"
          :camera="focused"
          :zones="zonesOf(focused.id)"
          :analysed="enabledOf(focused.id)"
          :enabled="!tv"
          :can-video="canVideo"
          :queue-people="rules.queue_people"
          :queue-wait-s="rules.queue_wait_s"
          :live-at="liveAt"
          size="focus"
        />
        <div
          v-if="rail.length"
          :class="['flex gap-3', isPhone ? 'no-scrollbar -mx-4 overflow-x-auto px-4 pb-1' : 'max-xl:grid max-xl:grid-cols-3 xl:flex-col xl:overflow-y-auto xl:pr-1']"
          :style="isDesktopWide && focusHeight ? { maxHeight: `${focusHeight}px` } : undefined"
          role="list"
          :aria-label="t('vision.live.others')"
        >
          <div v-for="camera in rail" :key="camera.id" role="listitem" :class="isPhone ? 'w-44 shrink-0' : 'min-w-0'">
            <CameraTile
              :camera="camera"
              :zones="zonesOf(camera.id)"
          :analysed="enabledOf(camera.id)"
              :enabled="!tv"
              :can-video="canVideo"
              :queue-people="rules.queue_people"
              :queue-wait-s="rules.queue_wait_s"
              :live-at="liveAt"
              size="rail"
              @open="openCamera"
            />
          </div>
        </div>
      </section>

      <ul class="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-xs text-muted" :aria-label="t('vision.live.legend')">
        <li class="inline-flex items-center gap-2"><span class="koz-key rounded-[4px] border-2 border-[#e8a35d]" />{{ t("vision.person.customer") }}</li>
        <li class="inline-flex items-center gap-2"><span class="koz-key rounded-[4px] border-2 border-[#4fb986]" />{{ t("vision.person.staff") }}</li>
        <li class="inline-flex items-center gap-2"><span class="koz-key rounded-[4px] border border-dashed border-[#e8a35d] bg-[#ffb46e]/15" />{{ t("vision.zone.queue") }}</li>
        <li class="inline-flex items-center gap-2"><span class="koz-key rounded-[4px] border border-dashed border-[#4fb986] bg-[#74d4a3]/15" />{{ t("vision.zone.staff") }}</li>
        <li class="inline-flex items-center gap-2"><span class="koz-key koz-key-mask rounded-[4px]" />{{ t("vision.zone.mask") }}</li>
        <li class="ml-auto max-sm:ml-0">{{ t("vision.live.privacy") }}</li>
      </ul>
    </template>

    <TvMode
      v-if="tv"
      :branch-name="branchName"
      :live="live.data.value ?? null"
      :live-at="liveAt"
      :zones-of="zonesOf"
      :queue-people="rules.queue_people"
      :queue-wait-s="rules.queue_wait_s"
      :can-video="canVideo"
      :insight="insight"
      :fullscreen="tvFullscreen"
      @close="tv = false"
    />
    <ClipPlayer v-model:open="clipOpen" :request="clip" />
  </div>
</template>

<style scoped>
.koz-key {
  width: 14px;
  height: 11px;
}
.koz-key-mask {
  background: repeating-linear-gradient(45deg, #1a1a1a 0 3px, #3a3a3a 3px 5px);
}
</style>
