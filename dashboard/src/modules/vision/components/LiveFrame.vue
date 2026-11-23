<script setup lang="ts">
/**
 * One camera, live (docs/KOZ.md §6.3): the latest picture every `interval` ms while it is on
 * screen, the zones drawn softly with their names and the entrance line's arrow, and a rounded
 * box on every person in their role's colour. Between pictures the boxes glide (matched by track)
 * and the pictures cross-fade, so twice a second reads as movement; the label pills
 * ("Mijoz · 0:45", "Farmatsevt") keep ticking every second and are laid out so they never cover
 * each other (lib/labels.ts: the longest wait first and in its place, the others moved the least,
 * with a leader, shortened or left out when the queue is too tight). The box draws nothing on the
 * JPEG: everything on top is drawn here.
 */
import { CameraOff, Cctv, Lock, RefreshCw } from "@lucide/vue";
import { useResizeObserver } from "@vueuse/core";
import { computed, onBeforeUnmount, ref, shallowRef, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { useSecondClock } from "../lib/clock";
import { useFrameWaits } from "../lib/frameWaits";
import { insideArrow, labelAnchor } from "../lib/geometry";
import { layoutPills, memoryOf, overlaps, type PillInput, type PillMemory, type Rect } from "../lib/labels";
import { ROLE_COLOR, WAIT_COLOR, ZONE_COLOR } from "../lib/look";
import { formatClock, glideDuration, interpolate, steadyStarts, waitedBy, waitLevel, type DrawnPerson, type WaitStarts } from "../lib/tracks";
import { useFramePoll } from "../lib/useFramePoll";
import type { FramePerson, Zone } from "../types";

const props = withDefaults(
  defineProps<{
    cameraId: number;
    zones?: Zone[];
    /** The camera reports in (live/): without it there is nothing to ask for. */
    online?: boolean;
    /** `vision.video`: live pictures are allowed. */
    canVideo?: boolean;
    /** Poll while true (on screen, in the wall's view). */
    active?: boolean;
    interval?: number;
    /** The queue rule, for the colour of the waits. */
    queueWaitS?: number;
    labels?: boolean;
    zonesVisible?: boolean;
    /** A small tile: thinner lines, no zone names, short states. */
    compact?: boolean;
    /** What a screen reader hears ("Kassa 1: 4 people, 3 in the queue"). */
    label?: string;
    /** Rounded corners of the picture. */
    rounded?: string;
  }>(),
  {
    zones: () => [],
    online: true,
    canVideo: true,
    active: true,
    interval: 500,
    queueWaitS: 120,
    labels: true,
    zonesVisible: true,
    compact: false,
    label: undefined,
    rounded: "14px",
  },
);

const emit = defineEmits<{ status: [status: string] }>();

const { t } = useI18n();
const uid = useId();
const clock = useSecondClock();

const poll = useFramePoll(
  () => props.cameraId,
  { interval: () => props.interval, enabled: () => props.active && props.online && props.canVideo },
);
watch(poll.status, (status) => emit("status", status), { immediate: true });

const VW = 1000;
const aspect = ref(16 / 9);
const VH = computed(() => Math.round((VW / aspect.value) * 10) / 10);

// Two pictures for the cross-fade: the one fading in on top of the last.
const front = ref<string | null>(null);
const back = ref<string | null>(null);
const progress = ref(1);
const drawn = shallowRef<DrawnPerson[]>([]);
/** When each customer's queue wait began, by track: steady across frames (lib/tracks.ts). */
const starts = shallowRef<WaitStarts>(new Map());
/** When the frame those were last read from arrived. */
const startsAt = ref(0);
let from: FramePerson[] = [];
let to: FramePerson[] = [];
let frame = 0;
let started = 0;
let duration = 420;

function animate(now: number): void {
  const t = Math.min(1, (now - started) / duration);
  progress.value = t;
  drawn.value = interpolate(from, to, t);
  if (t < 1) frame = requestAnimationFrame(animate);
  else back.value = null;
}

watch(
  () => poll.frame.value,
  async (next) => {
    if (!next) {
      front.value = back.value = null;
      drawn.value = [];
      starts.value = new Map();
      from = to = [];
      return;
    }
    const url = `data:image/jpeg;base64,${next.image_b64}`;
    // Decode first, so the swap never shows a blank or half-drawn picture.
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
    } catch {
      // A picture the browser can't decode still goes up: its alt text is honest.
    }
    if (poll.frame.value !== next) return;
    if (next.w > 0 && next.h > 0) aspect.value = next.w / next.h;
    starts.value = steadyStarts(
      starts.value,
      next.people.filter((person) => person.role === "customer").map((person) => ({ key: person.track, wait: person.wait_s })),
      poll.receivedAt.value,
    );
    startsAt.value = poll.receivedAt.value;
    cancelAnimationFrame(frame);
    from = drawn.value.filter((person) => person.state !== "left");
    to = next.people;
    back.value = front.value;
    front.value = url;
    duration = glideDuration(poll.interval.value);
    const reduced = typeof document !== "undefined" && document.documentElement.dataset.motion === "reduced";
    if (reduced || typeof requestAnimationFrame !== "function" || !back.value) {
      progress.value = 1;
      back.value = null;
      drawn.value = interpolate(from, to, 1);
      return;
    }
    started = performance.now();
    frame = requestAnimationFrame(animate);
  },
);
onBeforeUnmount(() => cancelAnimationFrame(frame));

// The page's numbers read this camera's longest wait from these frames while they arrive
// (lib/frameWaits.ts): the same second as its pill.
const frameWaits = useFrameWaits();
const longestStart = computed<number | null | undefined>(() => {
  if (!front.value || !poll.active.value) return undefined;
  let first: number | null = null;
  for (const entry of starts.value.values()) if (entry.seen === startsAt.value && (first === null || entry.start < first)) first = entry.start;
  return first;
});
if (frameWaits) {
  watch(
    [longestStart, () => props.cameraId],
    ([start, id], previous) => {
      const before = previous?.[1];
      if (before !== undefined && before !== id) frameWaits.delete(before);
      if (start === undefined) frameWaits.delete(id);
      else frameWaits.set(id, start);
    },
    { immediate: true },
  );
  onBeforeUnmount(() => frameWaits.delete(props.cameraId));
}

const people = computed(() =>
  drawn.value.map((person) => {
    const [x, y, w, h] = person.box;
    const wait = person.role === "customer" ? waitedBy(starts.value.get(person.track)?.start, clock.value) : null;
    const level = waitLevel(wait, props.queueWaitS);
    return {
      key: person.track,
      x,
      y,
      w,
      h,
      wait,
      opacity: person.opacity,
      color: ROLE_COLOR[person.role],
      waitColor: wait !== null ? WAIT_COLOR[level] : null,
      staff: person.role === "staff",
    };
  }),
);

const shapes = computed(() =>
  props.zones.map((zone) => {
    const points = zone.points.map(([x, y]) => `${x * VW},${y * VH.value}`).join(" ");
    const tag = zone.kind === "line" ? midpoint(zone) : labelAnchor(zone.points);
    let arrow: { x1: number; y1: number; x2: number; y2: number } | null = null;
    if (zone.kind === "line" && zone.points.length === 2) {
      const { from: a, to: b } = insideArrow(zone.points[0]!, zone.points[1]!, zone.in ?? "left", { w: VW, h: VH.value }, props.compact ? 34 : 46);
      arrow = { x1: a[0] * VW, y1: a[1] * VH.value, x2: b[0] * VW, y2: b[1] * VH.value };
    }
    return { zone, points, color: ZONE_COLOR[zone.kind], tag, arrow };
  }),
);

function midpoint(zone: Zone): [number, number] {
  const [a, b] = zone.points;
  if (!a || !b) return [0.5, 0.5];
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

// ─── Label pills, laid out in pixels so they never overlap ─────────────────

const root = ref<HTMLElement | null>(null);
const size = ref({ w: 960, h: 540 });
/** The chips the slot puts on the picture (name, live mark, numbers): pills keep clear of them. */
const reserved = shallowRef<Rect[]>([]);
function measureReserved(): void {
  const el = root.value;
  if (!el) return;
  const origin = el.getBoundingClientRect();
  const nodes = [...el.querySelectorAll<HTMLElement>("[data-reserve]"), ...[...el.querySelectorAll<HTMLElement>("[data-reserve-children]")].flatMap((node) => [...node.children] as HTMLElement[])];
  const next = nodes
    .map((node) => node.getBoundingClientRect())
    .filter((box) => box.width > 0 && box.height > 0)
    .map((box) => ({ x: Math.round(box.left - origin.left - 2), y: Math.round(box.top - origin.top - 2), w: Math.round(box.width + 4), h: Math.round(box.height + 4) }));
  const same = next.length === reserved.value.length && next.every((r, i) => {
    const before = reserved.value[i]!;
    return r.x === before.x && r.y === before.y && r.w === before.w && r.h === before.h;
  });
  if (!same) reserved.value = next;
}
useResizeObserver(root, (entries) => {
  const box = entries[0]?.contentRect;
  if (box && box.width > 0 && box.height > 0) size.value = { w: box.width, h: box.height };
  measureReserved();
});
// The chips' words change with the numbers (a queue of 3, then 12): measure again now and then.
let reserveTimer: ReturnType<typeof setInterval> | undefined;
watch(
  () => !!front.value,
  (shown) => {
    clearInterval(reserveTimer);
    if (!shown) return;
    requestAnimationFrame(measureReserved);
    reserveTimer = setInterval(measureReserved, 2000);
  },
  { immediate: true },
);
onBeforeUnmount(() => clearInterval(reserveTimer));

const font = computed(() => (props.compact ? 10 : 11.5));
const pillHeight = computed(() => (props.compact ? 16 : 21));
/** Padding, the role dot and the space after it. */
const chrome = computed(() => (props.compact ? 12 + 6 + 5 : 16 + 6 + 6));

let measure: CanvasRenderingContext2D | null | undefined;
const measured = new Map<string, number>();
// Widths measured before Figtree arrived were the fallback font's: measure again once it has.
void (typeof document !== "undefined" ? document.fonts?.ready : undefined)?.then(() => measured.clear());
/** A text's width; digits all count as "0" (they are tabular), so a ticking wait never resizes its pill. */
function textWidth(text: string): number {
  const shape = text.replace(/[0-9]/g, "0");
  const key = `${font.value}|${shape}`;
  let width = measured.get(key);
  if (width === undefined) {
    if (measure === undefined) {
      try {
        measure = document.createElement("canvas").getContext("2d");
      } catch {
        measure = null;
      }
    }
    if (measure) {
      measure.font = `600 ${font.value}px "Figtree Variable", Figtree, system-ui, sans-serif`;
      width = measure.measureText(shape).width;
    } else width = shape.length * font.value * 0.56;
    measured.set(key, width);
  }
  return Math.ceil(width + 3);
}

/**
 * Zone name tags, in pixels: at the zone's top left (a line's middle), hanging leftwards near the
 * right edge so they stay inside the picture, and left out where a chip of the slot sits. Pills
 * keep clear of them.
 */
const tags = computed(() => {
  if (!props.zonesVisible || props.compact) return [];
  return shapes.value
    .filter((shape) => shape.zone.kind !== "mask")
    .map((shape) => {
      const w = textWidth(t(`vision.zone.${shape.zone.kind}`)) + 22;
      const ax = shape.tag[0] * size.value.w;
      const ay = shape.tag[1] * size.value.h;
      let rect: Rect = shape.zone.kind === "line" ? { x: ax - w / 2, y: ay + 10, w, h: 20 } : { x: ax + 6, y: ay + 6, w, h: 20 };
      if (rect.x + rect.w > size.value.w - 6) rect = { ...rect, x: size.value.w - 6 - rect.w };
      if (rect.x < 6) rect = { ...rect, x: 6 };
      return { key: shape.zone.id, kind: shape.zone.kind, color: shape.color, rect };
    })
    .filter((tag) => !reserved.value.some((chip) => overlaps(tag.rect, chip)));
});
const tagRects = computed<Rect[]>(() => tags.value.map((tag) => tag.rect));

interface PillLook {
  full: string;
  short: string;
  color: string;
  waitColor: string | null;
  opacity: number;
  wait: number | null;
}

let memory: Map<number, PillMemory> = new Map();
const pills = computed(() => {
  if (!props.labels || !front.value) return [];
  const { w: W, h: H } = size.value;
  const items: PillInput[] = [];
  const looks = new Map<number, PillLook>();
  for (const person of people.value) {
    // A person fading out no longer claims room.
    if (person.opacity < 0.35) continue;
    const full = person.staff ? t("vision.person.staff") : person.wait !== null ? `${t("vision.person.customer")} · ${formatClock(person.wait)}` : t("vision.person.customer");
    const short = person.wait !== null ? formatClock(person.wait) : full;
    looks.set(person.key, { full, short, color: person.color, waitColor: person.waitColor, opacity: person.opacity, wait: person.wait });
    items.push({
      key: person.key,
      box: { x: person.x * W, y: person.y * H, w: person.w * W, h: person.h * H },
      width: textWidth(full) + chrome.value,
      shortWidth: textWidth(short) + chrome.value,
      height: pillHeight.value,
      // The longest wait first, then the other waits, then customers, then pharmacists.
      priority: person.wait !== null ? 10_000 + person.wait : person.staff ? 10 : 100,
    });
  }
  const placements = layoutPills(items, size.value, memory, { obstacles: [...reserved.value, ...tagRects.value], gap: props.compact ? 2 : 3 });
  memory = memoryOf(placements);
  const longest = Math.max(-1, ...[...looks.values()].map((look) => look.wait ?? -1));
  return placements.map((placement) => {
    const look = looks.get(placement.key)!;
    return { ...placement, ...look, text: placement.form === "full" ? look.full : look.short, longest: look.wait !== null && look.wait === longest && longest > 0 };
  });
});

const state = computed<"offline" | "denied" | "connecting" | "waiting" | "error" | null>(() => {
  if (!props.online) return "offline";
  if (!props.canVideo || poll.status.value === "denied") return "denied";
  if (front.value) return null;
  if (poll.status.value === "waiting") return "waiting";
  if (poll.status.value === "error") return "error";
  return "connecting";
});
</script>

<template>
  <div
    ref="root"
    class="koz-frame relative isolate overflow-hidden bg-[#0f0d0b] text-[#f6efe4]"
    :style="{ aspectRatio: aspect, borderRadius: rounded }"
    role="img"
    :aria-label="label"
    :data-state="state ?? 'live'"
  >
    <img v-if="back" :src="back" alt="" aria-hidden="true" draggable="false" class="absolute inset-0 size-full select-none object-fill" />
    <img
      v-if="front"
      :src="front"
      alt=""
      aria-hidden="true"
      draggable="false"
      class="absolute inset-0 size-full select-none object-fill"
      :style="{ opacity: back ? progress : 1 }"
    />

    <svg v-if="front" class="absolute inset-0 size-full" :viewBox="`0 0 ${VW} ${VH}`" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <pattern :id="`hatch-${uid}`" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="14" height="14" fill="#090909" />
          <line x1="0" y1="0" x2="0" y2="14" stroke="rgba(255,255,255,0.09)" stroke-width="5" />
        </pattern>
        <marker :id="`arrow-${uid}`" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#ffffff" />
        </marker>
      </defs>
      <g v-if="zonesVisible">
        <template v-for="shape in shapes" :key="shape.zone.id">
          <polygon
            v-if="shape.zone.kind === 'mask'"
            :points="shape.points"
            :fill="`url(#hatch-${uid})`"
            stroke="rgba(255,255,255,0.4)"
            stroke-dasharray="6 5"
            stroke-width="1.25"
            vector-effect="non-scaling-stroke"
          />
          <template v-else-if="shape.zone.kind === 'line'">
            <polyline :points="shape.points" fill="none" stroke="rgba(0,0,0,0.45)" stroke-width="5" stroke-linecap="round" vector-effect="non-scaling-stroke" />
            <polyline :points="shape.points" fill="none" stroke="#ffffff" stroke-width="2.25" stroke-dasharray="10 7" stroke-linecap="round" vector-effect="non-scaling-stroke" />
            <line
              v-if="shape.arrow"
              :x1="shape.arrow.x1"
              :y1="shape.arrow.y1"
              :x2="shape.arrow.x2"
              :y2="shape.arrow.y2"
              stroke="#ffffff"
              stroke-width="2.5"
              stroke-linecap="round"
              vector-effect="non-scaling-stroke"
              :marker-end="`url(#arrow-${uid})`"
            />
          </template>
          <polygon
            v-else
            :points="shape.points"
            :fill="shape.color"
            fill-opacity="0.1"
            :stroke="shape.color"
            stroke-opacity="0.8"
            stroke-dasharray="7 6"
            stroke-width="1.5"
            vector-effect="non-scaling-stroke"
          />
        </template>
      </g>
      <g>
        <g v-for="person in people" :key="person.key" :opacity="person.opacity">
          <rect
            :x="person.x * VW"
            :y="person.y * VH"
            :width="person.w * VW"
            :height="person.h * VH"
            :rx="Math.min(compact ? 8 : 12, person.w * VW * 0.14)"
            fill="none"
            stroke="rgba(0,0,0,0.38)"
            :stroke-width="compact ? 3.5 : 5"
            vector-effect="non-scaling-stroke"
          />
          <rect
            :x="person.x * VW"
            :y="person.y * VH"
            :width="person.w * VW"
            :height="person.h * VH"
            :rx="Math.min(compact ? 8 : 12, person.w * VW * 0.14)"
            :fill="person.color"
            fill-opacity="0.08"
            :stroke="person.waitColor === WAIT_COLOR.over ? WAIT_COLOR.over : person.color"
            :stroke-width="compact ? 1.5 : 2.25"
            vector-effect="non-scaling-stroke"
          />
        </g>
      </g>
    </svg>

    <!-- Zone names: HTML, so they stay crisp at any size. -->
    <div v-if="front && tags.length" class="pointer-events-none absolute inset-0" aria-hidden="true">
      <span
        v-for="tag in tags"
        :key="tag.key"
        class="koz-tag absolute inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-[11px] font-semibold"
        :style="{ left: `${tag.rect.x}px`, top: `${tag.rect.y}px`, height: `${tag.rect.h}px`, '--tag': tag.color }"
        :data-line="tag.kind === 'line' || undefined"
      >
        <span class="size-1.5 rounded-full" :style="{ background: tag.color }" />{{ t(`vision.zone.${tag.kind}`) }}
      </span>
    </div>

    <!-- The label pills, never on each other, with a leader when moved away from their box. -->
    <div v-if="front && labels" class="pointer-events-none absolute inset-0" aria-hidden="true">
      <svg class="absolute inset-0 size-full" :viewBox="`0 0 ${size.w} ${size.h}`" preserveAspectRatio="none">
        <template v-for="pill in pills" :key="`leader-${pill.key}`">
          <g v-if="pill.leader" :opacity="pill.opacity" data-leader>
            <line :x1="pill.leader.x1" :y1="pill.leader.y1" :x2="pill.leader.x2" :y2="pill.leader.y2" stroke="rgba(10,8,6,0.6)" stroke-width="3.5" stroke-linecap="round" />
            <line :x1="pill.leader.x1" :y1="pill.leader.y1" :x2="pill.leader.x2" :y2="pill.leader.y2" stroke="rgba(255,255,255,0.92)" stroke-width="1.5" stroke-linecap="round" />
            <circle :cx="pill.leader.x2" :cy="pill.leader.y2" r="3.25" :fill="pill.waitColor ?? pill.color" stroke="rgba(10,8,6,0.7)" stroke-width="1.5" />
          </g>
        </template>
      </svg>
      <span
        v-for="pill in pills"
        :key="pill.key"
        :class="['koz-pill absolute inline-flex items-center justify-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full font-semibold tabular-nums', compact ? 'text-[10px]' : 'text-[11.5px]']"
        :style="{ left: `${pill.x}px`, top: `${pill.y}px`, width: `${pill.w}px`, height: `${pill.h}px`, opacity: pill.opacity, '--ring': pill.waitColor ?? pill.color }"
        :data-longest="pill.longest || undefined"
        :data-form="pill.form"
      >
        <span class="size-1.5 shrink-0 rounded-full" :style="{ background: pill.color }" />
        <span :style="pill.waitColor ? { color: pill.waitColor } : undefined">{{ pill.text }}</span>
      </span>
    </div>

    <!-- What stands in for the picture: never a spinner on black without words. -->
    <div v-if="state" class="koz-state absolute inset-0 grid place-items-center p-3 text-center" :data-kind="state">
      <div class="flex max-w-[22rem] flex-col items-center gap-2">
        <span :class="['grid place-items-center rounded-full bg-white/8 text-white/80', compact ? 'size-8' : 'size-11']">
          <CameraOff v-if="state === 'offline'" :size="compact ? 16 : 20" />
          <Lock v-else-if="state === 'denied'" :size="compact ? 16 : 20" />
          <RefreshCw v-else-if="state === 'error'" :size="compact ? 16 : 20" />
          <Cctv v-else :size="compact ? 16 : 20" class="koz-breathe" />
        </span>
        <p :class="['font-medium text-white/85', compact ? 'text-xs' : 'text-sm']">{{ t(`vision.camera.${state}`) }}</p>
      </div>
    </div>

    <slot />
  </div>
</template>

<style scoped>
.koz-frame {
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.04);
}
.koz-pill,
.koz-tag {
  background: rgb(16 13 10 / 0.72);
  color: #fbf6ee;
  -webkit-backdrop-filter: blur(6px);
  backdrop-filter: blur(6px);
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.35);
  will-change: left, top;
}
/* The longest wait reads first: a thin ring in its colour. */
.koz-pill[data-longest] {
  background: rgb(16 13 10 / 0.86);
  box-shadow:
    0 0 0 1.5px var(--ring),
    0 2px 8px rgb(0 0 0 / 0.45);
}
.koz-tag {
  background: rgb(16 13 10 / 0.55);
  color: color-mix(in srgb, var(--tag) 70%, #ffffff);
}
.koz-tag[data-line] {
  color: #ffffff;
}
.koz-state {
  background:
    radial-gradient(120% 90% at 50% 40%, rgb(255 255 255 / 0.05), transparent 60%),
    linear-gradient(180deg, #1a1714, #0f0d0b);
}
.koz-state[data-kind="connecting"]::after,
.koz-state[data-kind="waiting"]::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 30%, rgb(255 255 255 / 0.05) 50%, transparent 70%);
  background-size: 220% 100%;
  animation: koz-shine 1.8s linear infinite;
}
@keyframes koz-shine {
  from {
    background-position: 120% 0;
  }
  to {
    background-position: -120% 0;
  }
}
.koz-breathe {
  animation: koz-breathe 1.8s ease-in-out infinite;
}
@keyframes koz-breathe {
  50% {
    opacity: 0.45;
  }
}
:root[data-motion="reduced"] .koz-state::after,
:root[data-motion="reduced"] .koz-breathe {
  animation: none;
}
</style>
