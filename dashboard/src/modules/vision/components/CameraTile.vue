<script setup lang="ts">
/**
 * A camera on the live wall or the focus rail: the live picture with its overlay, the name and
 * role on glass in a corner, the live mark, and its numbers at the bottom (people, queue, the
 * longest wait ticking). Pictures are asked for only while the tile is on screen. Clicking a tile
 * opens it in focus.
 */
import { Hourglass, UserRound, Users } from "@lucide/vue";
import { useIntersectionObserver } from "@vueuse/core";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { fromInnerControl } from "@/core/hotkeys";
import { useFormat } from "@/lib/useFormat";

import { useSecondClock } from "../lib/clock";
import { formatClock, tickingWait, waitLevel } from "../lib/tracks";
import type { LiveCamera, Zone } from "../types";
import LiveFrame from "./LiveFrame.vue";

const props = withDefaults(
  defineProps<{
    camera: LiveCamera;
    zones: Zone[];
    canVideo: boolean;
    queueWaitS: number;
    queuePeople: number;
    /** When the live numbers arrived (Date.now()), for the ticking wait. */
    liveAt: number;
    size?: "wall" | "rail" | "focus";
    selected?: boolean;
    enabled?: boolean;
  }>(),
  { size: "wall", selected: false, enabled: true },
);

const emit = defineEmits<{ open: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const clock = useSecondClock();

const root = ref<HTMLElement | null>(null);
const visible = ref(true);
useIntersectionObserver(root, (entries) => (visible.value = entries.some((entry) => entry.isIntersecting)), { rootMargin: "80px" });

const clickable = computed(() => props.size !== "focus");
const wait = computed(() => tickingWait(props.camera.wait_s, props.liveAt, clock.value));
const level = computed(() => waitLevel(wait.value, props.queueWaitS));
const counter = computed(() => props.camera.role === "counter");
const busy = computed(() => counter.value && (props.camera.queue ?? 0) >= props.queuePeople);
const unattended = computed(() => counter.value && (props.camera.queue ?? 0) > 0 && props.camera.staff === 0);
const label = computed(() => {
  const parts = [props.camera.name, t(`vision.role.${props.camera.role}`)];
  if (!props.camera.online) parts.push(t("vision.camera.offline"));
  else {
    if (props.camera.people !== null) parts.push(t("vision.camera.people", { n: props.camera.people }));
    if (counter.value && props.camera.queue !== null) parts.push(t("vision.counter.queueOf", { n: props.camera.queue }));
    if (wait.value !== null && wait.value > 0) parts.push(t("vision.counter.waitOf", { wait: formatClock(wait.value) }));
  }
  return parts.join(", ");
});

function open(event?: Event): void {
  if (!clickable.value || (event && fromInnerControl(event))) return;
  emit("open", props.camera.id);
}
</script>

<template>
  <div
    ref="root"
    :class="[
      'koz-tile group relative min-w-0 rounded-[16px] transition-[box-shadow,transform] duration-200',
      clickable && 'cursor-pointer focus-visible:outline-none',
      selected ? 'koz-tile-selected' : clickable && 'hover:-translate-y-px',
      unattended ? 'koz-tile-red' : busy ? 'koz-tile-amber' : '',
    ]"
    :role="clickable ? 'button' : undefined"
    :tabindex="clickable ? 0 : undefined"
    :aria-label="clickable ? t('vision.camera.open', { name: camera.name }) : undefined"
    :aria-pressed="clickable ? selected : undefined"
    :data-camera="camera.id"
    @click="open"
    @keydown.enter.prevent="open"
    @keydown.space.prevent="open"
  >
    <LiveFrame
      :camera-id="camera.id"
      :zones="zones"
      :online="camera.online"
      :can-video="canVideo"
      :active="visible && enabled"
      :interval="size === 'rail' ? 1500 : 500"
      :queue-wait-s="queueWaitS"
      :labels="size !== 'rail'"
      :zones-visible="size !== 'rail'"
      :compact="size !== 'focus'"
      :label="label"
      :rounded="size === 'rail' ? '12px' : '16px'"
    >
      <!-- On-screen display: name and role, the live mark, the numbers. -->
      <div class="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 p-2.5" :class="size === 'focus' && 'p-3.5'">
        <span class="koz-glass inline-flex min-w-0 items-center gap-2 rounded-full py-1 pl-2.5 pr-3">
          <span :class="['truncate font-semibold text-white', size === 'focus' ? 'text-sm' : 'text-xs']">{{ camera.name }}</span>
          <span v-if="size !== 'rail'" class="shrink-0 text-[11px] font-medium text-white/60">{{ t(`vision.role.${camera.role}`) }}</span>
        </span>
        <span v-if="camera.online && !camera.stale && canVideo" class="koz-glass inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-1 text-[10.5px] font-bold uppercase tracking-[0.06em] text-white">
          <span class="koz-rec size-1.5 rounded-full bg-[#ff5a4e]" />{{ t("vision.live.onAir") }}
        </span>
      </div>
      <div v-if="camera.online && size !== 'rail' && camera.people !== null" class="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap items-end gap-1.5 p-2.5" :class="size === 'focus' && 'p-3.5'">
        <span class="koz-glass inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums text-white">
          <Users :size="13" class="text-white/70" />{{ fmt.number(camera.people) }}
        </span>
        <template v-if="counter">
          <span :class="['koz-glass inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums', busy ? 'text-[#ffd36b]' : 'text-white']">
            <UserRound :size="13" class="opacity-70" />{{ t("vision.counter.queueOf", { n: camera.queue ?? 0 }) }}
          </span>
          <span
            v-if="wait !== null && wait > 0"
            :class="['koz-glass inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums', level === 'over' ? 'text-[#ff8466]' : level === 'long' ? 'text-[#ffd36b]' : 'text-white']"
          >
            <Hourglass :size="13" class="opacity-70" />{{ formatClock(wait) }}
          </span>
        </template>
      </div>
    </LiveFrame>
  </div>
</template>

<style scoped>
.koz-tile {
  box-shadow: 0 1px 2px rgb(20 14 8 / 0.12);
}
.koz-tile:focus-visible {
  box-shadow:
    0 0 0 2px var(--c-canvas),
    0 0 0 4px var(--c-ring);
}
.koz-tile-selected {
  box-shadow:
    0 0 0 2px var(--c-canvas),
    0 0 0 4px var(--c-primary);
}
.koz-tile-amber {
  box-shadow:
    0 0 0 2px color-mix(in srgb, #f0a43a 70%, transparent),
    0 8px 24px -10px rgb(240 164 58 / 0.55);
}
.koz-tile-red {
  box-shadow:
    0 0 0 2px color-mix(in srgb, #f0604a 75%, transparent),
    0 8px 26px -10px rgb(240 96 74 / 0.6);
}
.koz-glass {
  background: rgb(14 11 9 / 0.58);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.06);
}
.koz-rec {
  box-shadow: 0 0 0 0 rgb(255 90 78 / 0.7);
  animation: koz-rec 1.6s ease-out infinite;
}
@keyframes koz-rec {
  70% {
    box-shadow: 0 0 0 6px rgb(255 90 78 / 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgb(255 90 78 / 0);
  }
}
:root[data-motion="reduced"] .koz-rec {
  animation: none;
}
</style>
