<script setup lang="ts">
/**
 * The big picture on an agent's own page: its chibi in a little room, sitting at its desk. While
 * the agent works it types and its screen fills with what it does, and a finished job gets a cheer
 * and a sparkle over the monitor; while it waits it watches the screen, pulls faces, does its own
 * move now and then (the voice chibi listens, the deadline one rings its clock…) and thinks of
 * little things in a bubble; switched off it sleeps on the desk with the screen dark and Zzz above.
 *
 * The room lives too: the wall clock and the calendar show the company's time and day, a cat sits
 * on the windowsill (curled up asleep at night or while the agent sleeps), birds cross the day sky
 * and stars shoot through the night, dust floats in the sunbeam, the plants sway, and each agent's
 * desk has its own thing (a microphone, an alarm clock, an hourglass, a camera, folders, a pile of
 * books with chalk on top, a little bar chart on an easel, a Claude plush). A tap on the chibi makes it say what it does, what it did today and when it runs next;
 * the cat purrs, the window sends a bird (or a shooting star), the lamp switches, the mug steams
 * and the desk thing does its trick. Those are a pointer's fun only: the picture has one name for
 * screen readers.
 *
 * Pixel art in the chibis' style (no image files), drawn in room units (scene.ts) and layered: the
 * room, the chibi on its chair, the desk in front of it, the night's shade and the screen's glow,
 * then the screen itself and the bubbles. A pointer over it tilts the room a little, like looking in
 * through a window; with reduced motion nothing moves and nothing appears by itself.
 */
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { reducedMotion } from "@/components/chartOptions";

import { buddyVariant, type BuddyAction } from "../lib";
import {
  clockHands,
  pickSceneAction,
  pickThought,
  ROOM,
  SCENE_BEAT_MS,
  sceneActionMs,
  sceneBuddy,
  sceneSayings,
  screenLines,
  seatBox,
  SIGNATURE_MOVE,
  stagePoint,
  type SceneState,
  type ThoughtIcon,
} from "../scene";
import AiBuddy from "./AiBuddy.vue";

const props = withDefaults(
  defineProps<{
    /** The agent's key ("hr_assistant") or a chibi variant ("hr"). */
    variant: string;
    state: SceneState;
    /** What it did lately, oldest first: the newest show on its screen. */
    lines?: readonly string[];
    night?: boolean;
    /** What a screen reader says for the whole picture. */
    label: string;
    /** The company's time and day of the month, for the wall clock and the calendar. */
    clock?: { hours: number; minutes: number; day: number } | null;
    /** When it runs next, as words ("14:30", "Ertaga, 09:00"), for what it says when tapped. */
    nextRun?: string | null;
    /** How many things it did today, for what it says when tapped. */
    doneToday?: number | null;
    /** An agent an owner made: its chibi's colour. */
    color?: string | null;
  }>(),
  { lines: () => [], night: false, clock: null, nextRun: null, doneToday: null, color: null },
);

const { t } = useI18n();
const VARIANTS = new Set(["claude", "voice", "morning", "deadline", "photo", "hr", "tutor", "advisor", "custom"]);
const chibi = computed(() => (VARIANTS.has(props.variant) ? (props.variant as ReturnType<typeof buddyVariant>) : buddyVariant(props.variant)));
const buddy = computed(() => sceneBuddy(props.state));
const reduced = reducedMotion();
const glowId = `scene-glow-${useId()}`;
const lampId = `scene-lamp-${useId()}`;
const glassId = `scene-glass-${useId()}`;

// Size: the room covers the box; the chibi and the bubbles (HTML) are placed with the same units.
const root = ref<HTMLElement | null>(null);
const box = ref({ width: 0, height: 0 });
let observer: ResizeObserver | null = null;
const seat = computed(() => seatBox(box.value.width, box.value.height, props.state === "asleep"));
// A bubble is at most BUBBLE_MAX wide: on a narrow phone it moves left to stay in the picture.
const BUBBLE_MAX = 190;
const chatAt = computed(() => {
  const point = stagePoint(176, 60, box.value.width, box.value.height);
  return { left: Math.max(8, Math.min(point.left, box.value.width - BUBBLE_MAX - 8)), top: point.top };
});
const catAt = computed(() => stagePoint(88, 61, box.value.width, box.value.height));
const zzzAt = computed(() => stagePoint(168, 70, box.value.width, box.value.height));

// What it does: a new face every few seconds, settling back to watching the screen.
const action = ref<BuddyAction>("idle");
const beat = ref(0);
const glance = ref<"left" | null>(null);
let actionTimer: ReturnType<typeof setTimeout> | null = null;
let settleTimer: ReturnType<typeof setTimeout> | null = null;
let glanceTimer: ReturnType<typeof setTimeout> | null = null;

function clearTimers(): void {
  if (actionTimer) clearTimeout(actionTimer);
  if (settleTimer) clearTimeout(settleTimer);
  actionTimer = settleTimer = null;
}

function act(next: BuddyAction): void {
  action.value = next;
  beat.value += 1;
  if (settleTimer) clearTimeout(settleTimer);
  const lasts = sceneActionMs(next);
  if (Number.isFinite(lasts)) settleTimer = setTimeout(() => (action.value = props.state === "working" ? "type" : "idle"), lasts);
}

/** It turns to the window for a moment (the cat, a bird), then back to its screen. */
function glanceLeft(ms = 1600): void {
  if (reduced || props.state === "asleep") return;
  glance.value = "left";
  if (glanceTimer) clearTimeout(glanceTimer);
  glanceTimer = setTimeout(() => (glance.value = null), ms);
}

function loop(): void {
  clearTimers();
  if (props.state === "asleep") {
    action.value = "idle";
    return;
  }
  if (reduced) {
    action.value = props.state === "working" ? "type" : "idle";
    return;
  }
  act(pickSceneAction(props.state, action.value, Math.random, SIGNATURE_MOVE[chibi.value]));
  maybeThink();
  actionTimer = setTimeout(loop, SCENE_BEAT_MS[props.state] * (0.75 + Math.random() * 0.5));
}

// Now and then a little thought in a bubble (a picture, no words); never over what it says.
const thought = ref<ThoughtIcon | null>(null);
let lastThought: ThoughtIcon | null = null;
let thoughtTimer: ReturnType<typeof setTimeout> | null = null;
function maybeThink(): void {
  if (speech.value || thought.value || Math.random() > (props.state === "working" ? 0.16 : 0.28)) return;
  const next = pickThought(props.state, lastThought);
  if (!next) return;
  lastThought = thought.value = next;
  if (thoughtTimer) clearTimeout(thoughtTimer);
  thoughtTimer = setTimeout(() => (thought.value = null), 2600);
}

// A tap on the chibi: it says the next of its lines, with hearts, a wave, a star or love.
const speech = ref<string | null>(null);
let speechTimer: ReturnType<typeof setTimeout> | null = null;
let said = 0;
let taps = 0;
const TAP_MOVES: readonly BuddyAction[] = ["hearts", "wave", "star", "love"];
const sayings = computed(() => sceneSayings(props.state, chibi.value, props.nextRun, props.doneToday));
function say(text: string, ms = 3200): void {
  speech.value = text;
  thought.value = null;
  if (speechTimer) clearTimeout(speechTimer);
  speechTimer = setTimeout(() => (speech.value = null), ms);
}
function poke(): void {
  const list = sayings.value;
  const saying = list[said % list.length];
  said += 1;
  if (saying) say(t(saying.key, saying.params ?? {}));
  if (reduced) return;
  act(props.state === "asleep" ? "wide" : TAP_MOVES[taps++ % TAP_MOVES.length]!);
}

// The cat on the windowsill: awake by day, curled up at night or while the agent sleeps.
const catAsleep = computed(() => props.state === "asleep" || props.night);
const catTalks = ref(false);
const catStretch = ref(false);
let catTimer: ReturnType<typeof setTimeout> | null = null;
function petCat(): void {
  catTalks.value = true;
  catStretch.value = !reduced && !catAsleep.value;
  if (catTimer) clearTimeout(catTimer);
  catTimer = setTimeout(() => (catTalks.value = catStretch.value = false), 1700);
  glanceLeft();
}

// The window sends one more bird by day, a shooting star by night; the lamp switches; the mug steams.
const sky = ref(0);
function skyTap(): void {
  if (reduced) return;
  sky.value += 1;
  glanceLeft(2200);
}
const lampOn = ref(true);
const steam = ref(false);
let steamTimer: ReturnType<typeof setTimeout> | null = null;
function sip(): void {
  if (reduced) return;
  steam.value = true;
  if (steamTimer) clearTimeout(steamTimer);
  steamTimer = setTimeout(() => (steam.value = false), 1500);
  if (props.state !== "asleep") act("love");
}
// Its desk thing does its trick: the camera flashes, the others start the chibi's own move.
const flash = ref(0);
function propTap(): void {
  if (reduced) return;
  if (chibi.value === "photo") flash.value += 1;
  if (props.state !== "asleep") act(SIGNATURE_MOVE[chibi.value]);
}

// The screen: the newest lines, the newest typed out letter by letter while it works.
const shown = computed(() => screenLines(props.lines, 5, 26));
const typed = ref(0);
let typeTimer: ReturnType<typeof setInterval> | null = null;
function typeNewest(): void {
  if (typeTimer) clearInterval(typeTimer);
  const newest = shown.value.at(-1) ?? "";
  if (reduced || props.state !== "working" || !newest) {
    typed.value = newest.length;
    return;
  }
  typed.value = 0;
  typeTimer = setInterval(() => {
    typed.value += 1;
    if (typed.value >= newest.length && typeTimer) {
      clearInterval(typeTimer);
      typeTimer = null;
    }
  }, 45);
}
const screenText = computed(() =>
  shown.value.map((line, index) => (index === shown.value.length - 1 ? line.slice(0, typed.value) : line)),
);
// Without lines yet: a few code-like bars, so the screen never looks broken.
const bars = [34, 52, 26, 44, 18];
// Something new it did: a sparkle over the monitor and a cheer.
const burst = ref(0);

// The wall clock and the calendar (10:10 and no day before the page knows the time).
const hands = computed(() => clockHands(props.clock?.hours ?? 10, props.clock?.minutes ?? 10));
const day = computed(() => (props.clock ? String(props.clock.day) : ""));

// The tilt: where the pointer is, from -1 to 1.
const tilt = ref({ x: 0, y: 0 });
function onPointer(event: PointerEvent): void {
  if (reduced || event.pointerType === "touch" || !root.value) return;
  const rect = root.value.getBoundingClientRect();
  tilt.value = { x: ((event.clientX - rect.left) / rect.width) * 2 - 1, y: ((event.clientY - rect.top) / rect.height) * 2 - 1 };
}
function onLeave(): void {
  tilt.value = { x: 0, y: 0 };
}

// Floor boards and wallpaper stripes across the whole width.
const stripes = Array.from({ length: Math.ceil(ROOM.width / 24) }, (_, index) => index * 24);
const BOARD_ROWS = [
  { y: 119, h: 8, step: 28, shift: 0 },
  { y: 128, h: 9, step: 34, shift: 14 },
  { y: 138, h: 12, step: 42, shift: 6 },
  { y: 151, h: 15, step: 52, shift: 26 },
  { y: 167, h: 13, step: 64, shift: 10 },
];
const boardSeams = BOARD_ROWS.flatMap((row) =>
  Array.from({ length: Math.ceil(ROOM.width / row.step) + 1 }, (_, index) => ({ x: row.shift + index * row.step, y: row.y, h: row.h })),
);
const rowSeams = BOARD_ROWS.slice(1).map((row) => row.y - 1);
const stars = [
  [36, 28, 0],
  [47, 37, 1.1],
  [58, 26, 2.3],
  [76, 33, 0.6],
  [41, 45, 1.7],
  [69, 44, 2.9],
  [95, 45, 0.3],
  [53, 59, 1.4],
  [88, 62, 2.1],
] as const;
const keys = Array.from({ length: 9 }, (_, index) => index);
// Dust in the sunbeam: [x, y, delay s].
const motes = [
  [60, 98, 0],
  [76, 112, 1.6],
  [94, 126, 3.1],
  [110, 141, 0.8],
  [68, 133, 2.4],
  [124, 156, 4.2],
] as const;
// The bookcase out of the window's way (wide screens): [x, y, width, height, colour].
const SHELF_BOOKS = [
  [-74, 52, 5, 14, "#e8625a"],
  [-68, 55, 4, 11, "#6a8fe0"],
  [-63, 50, 6, 16, "#f2b544"],
  [-56, 54, 4, 12, "#36b1a4"],
  [-51, 57, 7, 9, "#b07ad9"],
  [-74, 74, 6, 12, "#36b1a4"],
  [-67, 77, 5, 9, "#e8625a"],
  [-61, 73, 4, 13, "#6a8fe0"],
  [-56, 76, 6, 10, "#f2b544"],
  [-74, 95, 5, 11, "#f2b544"],
  [-68, 93, 6, 13, "#b07ad9"],
  [-61, 96, 4, 10, "#e8625a"],
] as const;

watch(
  () => props.state,
  () => {
    loop();
    typeNewest();
  },
);
watch(
  () => shown.value.at(-1),
  (line, before) => {
    typeNewest();
    if (!reduced && line && before !== undefined && line !== before && props.state !== "asleep") {
      burst.value += 1;
      act("cheer");
    }
  },
);

onMounted(() => {
  if (root.value) {
    box.value = { width: root.value.clientWidth, height: root.value.clientHeight };
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(([entry]) => {
        if (entry) box.value = { width: entry.contentRect.width, height: entry.contentRect.height };
      });
      observer.observe(root.value);
    }
  }
  loop();
  typeNewest();
});

onBeforeUnmount(() => {
  clearTimers();
  for (const timer of [glanceTimer, thoughtTimer, speechTimer, catTimer, steamTimer]) if (timer) clearTimeout(timer);
  if (typeTimer) clearInterval(typeTimer);
  observer?.disconnect();
});
</script>

<template>
  <figure
    ref="root"
    class="agent-scene relative isolate m-0 h-60 w-full overflow-hidden rounded-card md:h-[380px]"
    :data-state="state"
    :data-night="night || undefined"
    :data-variant="chibi"
    :data-lamp="lampOn ? undefined : 'off'"
    :style="{ '--px': tilt.x, '--py': tilt.y }"
    role="img"
    :aria-label="label"
    data-testid="agent-scene"
    @pointermove="onPointer"
    @pointerleave="onLeave"
  >
    <div class="scene-camera absolute inset-0" aria-hidden="true">
      <!-- The room, behind the chibi. -->
      <svg class="scene-layer scene-room" :viewBox="`0 0 ${ROOM.width} ${ROOM.height}`" preserveAspectRatio="xMidYMid slice" shape-rendering="crispEdges">
        <defs>
          <clipPath :id="glassId">
            <rect :x="ROOM.stageX + 30" y="22" width="72" height="54" />
          </clipPath>
        </defs>
        <rect class="sc-wall" x="0" y="0" :width="ROOM.width" height="118" />
        <rect v-for="x in stripes" :key="`s${x}`" class="sc-stripe" :x="x" y="0" width="8" height="116" />
        <rect class="sc-base" x="0" y="115" :width="ROOM.width" height="4" />
        <rect class="sc-floor" x="0" y="119" :width="ROOM.width" height="61" />
        <rect v-for="y in rowSeams" :key="`r${y}`" class="sc-seam" x="0" :y="y" :width="ROOM.width" height="1" />
        <rect v-for="seam in boardSeams" :key="`b${seam.x}-${seam.y}`" class="sc-seam" :x="seam.x" :y="seam.y" width="1" :height="seam.h - 1" />

        <g :transform="`translate(${ROOM.stageX} 0)`">
          <!-- Wide screens: a pharmacy poster over a bookcase on the left… -->
          <rect class="sc-frame-dark" x="-72" y="10" width="26" height="26" />
          <rect class="sc-poster" x="-70" y="12" width="22" height="22" />
          <rect class="sc-cross" x="-62" y="15" width="6" height="16" />
          <rect class="sc-cross" x="-67" y="20" width="16" height="6" />
          <rect class="sc-wood-dark" x="-80" y="44" width="42" height="72" />
          <rect class="sc-wood" x="-78" y="46" width="38" height="68" />
          <rect class="sc-wood-dark" x="-78" y="66" width="38" height="2" />
          <rect class="sc-wood-dark" x="-78" y="86" width="38" height="2" />
          <rect class="sc-wood-dark" x="-78" y="106" width="38" height="2" />
          <rect v-for="([x, y, w, h, colour], index) in SHELF_BOOKS" :key="`sb${index}`" :x="x" :y="y" :width="w" :height="h" :fill="colour" />
          <rect class="sc-trophy" x="-48" y="57" width="6" height="2" />
          <rect class="sc-trophy" x="-47" y="52" width="4" height="5" />
          <rect class="sc-trophy" x="-49" y="50" width="8" height="2" />
          <rect class="sc-trophy-shine" x="-46" y="52" width="1" height="3" />

          <!-- …and a water cooler and a framed star on the right. -->
          <rect class="sc-frame-dark" x="352" y="22" width="22" height="22" />
          <rect class="sc-photo" x="354" y="24" width="18" height="18" />
          <rect class="sc-note-1" x="361" y="27" width="4" height="12" />
          <rect class="sc-note-1" x="357" y="31" width="12" height="4" />
          <rect class="sc-note-1" x="359" y="29" width="8" height="8" />
          <rect class="sc-cooler-bottle" x="338" y="60" width="16" height="18" />
          <rect class="sc-cooler-water" x="339" y="64" width="14" height="13" />
          <rect class="sc-bubble" x="343" y="72" width="2" height="2" />
          <rect class="sc-bubble sc-bubble-2" x="348" y="70" width="1" height="1" />
          <rect class="sc-cooler" x="334" y="78" width="24" height="38" />
          <rect class="sc-cooler-dark" x="334" y="90" width="24" height="2" />
          <rect class="sc-tap-blue" x="339" y="84" width="4" height="3" />
          <rect class="sc-tap-red" x="349" y="84" width="4" height="3" />
          <rect class="sc-cooler-dark" x="336" y="114" width="20" height="3" />

          <!-- The window: day sky with clouds and birds, or night with the moon and stars. -->
          <rect class="sc-rod" x="14" y="12" width="104" height="2" />
          <rect class="sc-rod" x="12" y="11" width="3" height="4" />
          <rect class="sc-rod" x="117" y="11" width="3" height="4" />
          <rect class="sc-sky-top" x="30" y="22" width="72" height="28" />
          <rect class="sc-sky-bottom" x="30" y="50" width="72" height="26" />
          <template v-if="night">
            <rect class="sc-moon" x="85" y="27" width="8" height="8" />
            <rect class="sc-moon" x="84" y="29" width="1" height="4" />
            <rect class="sc-sky-top" x="88" y="26" width="6" height="6" />
            <rect v-for="[x, y, delay] in stars" :key="`st${x}`" class="sc-star" :x="x" :y="y" width="1" height="1" :style="{ animationDelay: `${delay}s` }" />
          </template>
          <template v-else>
            <rect class="sc-sun" x="86" y="27" width="7" height="7" />
            <rect class="sc-sun" x="85" y="28" width="9" height="5" />
            <g class="sc-cloud">
              <rect x="37" y="31" width="16" height="3" />
              <rect x="40" y="28" width="9" height="3" />
              <rect x="35" y="34" width="20" height="2" />
              <rect x="66" y="42" width="12" height="3" />
              <rect x="69" y="40" width="6" height="2" />
            </g>
          </template>
        </g>
        <!-- Birds and shooting stars stay inside the glass. -->
        <g :clip-path="`url(#${glassId})`">
          <g :transform="`translate(${ROOM.stageX} 0)`">
            <template v-if="!night">
              <g class="sc-bird sc-bird-1">
                <rect class="sc-wing" x="0" y="0" width="1" height="1" />
                <rect x="1" y="1" width="1" height="1" />
                <rect class="sc-wing" x="2" y="0" width="1" height="1" />
              </g>
              <g class="sc-bird sc-bird-2">
                <rect class="sc-wing" x="0" y="0" width="1" height="1" />
                <rect x="1" y="1" width="1" height="1" />
                <rect class="sc-wing" x="2" y="0" width="1" height="1" />
              </g>
              <g v-if="sky" :key="`bird${sky}`" class="sc-bird sc-bird-now">
                <rect class="sc-wing" x="0" y="0" width="1" height="1" />
                <rect x="1" y="1" width="1" height="1" />
                <rect class="sc-wing" x="2" y="0" width="1" height="1" />
              </g>
            </template>
            <template v-else>
              <rect class="sc-shoot" x="0" y="0" width="6" height="1" />
              <rect v-if="sky" :key="`shoot${sky}`" class="sc-shoot sc-shoot-now" x="0" y="0" width="6" height="1" />
            </template>
          </g>
        </g>
        <g :transform="`translate(${ROOM.stageX} 0)`">
          <rect class="sc-frame" x="65" y="22" width="2" height="54" />
          <rect class="sc-frame" x="30" y="48" width="72" height="2" />
          <rect class="sc-frame" x="26" y="18" width="80" height="4" />
          <rect class="sc-frame" x="26" y="76" width="80" height="4" />
          <rect class="sc-frame" x="26" y="18" width="4" height="62" />
          <rect class="sc-frame" x="102" y="18" width="4" height="62" />
          <rect class="sc-frame-dark" x="30" y="22" width="72" height="1" />
          <rect class="sc-frame-dark" x="22" y="80" width="88" height="3" />
          <rect class="sc-curtain" x="18" y="14" width="10" height="72" />
          <rect class="sc-curtain-fold" x="21" y="14" width="1" height="72" />
          <rect class="sc-curtain-fold" x="25" y="14" width="1" height="72" />
          <rect class="sc-curtain-fold" x="18" y="54" width="10" height="2" />
          <rect class="sc-curtain" x="104" y="14" width="10" height="72" />
          <rect class="sc-curtain-fold" x="107" y="14" width="1" height="72" />
          <rect class="sc-curtain-fold" x="111" y="14" width="1" height="72" />
          <rect class="sc-curtain-fold" x="104" y="54" width="10" height="2" />
          <polygon class="sc-beam" points="30,83 102,83 176,170 48,170" />
          <template v-if="!night">
            <rect v-for="[x, y, delay] in motes" :key="`m${x}`" class="sc-mote" :x="x" :y="y" width="1" height="1" :style="{ animationDelay: `${delay}s` }" />
          </template>
          <!-- A tap on the glass: one more bird, or a shooting star. -->
          <rect class="sc-hit" x="30" y="22" width="72" height="54" fill="transparent" @click="skyTap" />

          <!-- The cat on the windowsill. -->
          <g class="sc-hit sc-cat" :class="{ 'sc-cat--stretch': catStretch }" data-testid="scene-cat" @click="petCat">
            <g v-if="!catAsleep" transform="translate(76 64)">
              <g class="sc-tail">
                <rect class="sc-fur" x="9" y="9" width="3" height="2" />
                <rect class="sc-fur" x="11" y="6" width="2" height="3" />
                <rect class="sc-fur-dark" x="12" y="4" width="2" height="2" />
              </g>
              <rect class="sc-fur" x="0" y="0" width="2" height="2" />
              <rect class="sc-fur" x="7" y="0" width="2" height="2" />
              <rect class="sc-ear-in" x="1" y="1" width="1" height="1" />
              <rect class="sc-ear-in" x="7" y="1" width="1" height="1" />
              <rect class="sc-fur" x="0" y="2" width="9" height="5" />
              <rect class="sc-fur-dark" x="0" y="3" width="1" height="1" />
              <rect class="sc-fur-dark" x="8" y="3" width="1" height="1" />
              <rect class="sc-fur-dark" x="4" y="2" width="1" height="1" />
              <g class="sc-cat-eyes">
                <rect class="sc-cat-eye" x="2" y="4" width="1" height="1" />
                <rect class="sc-cat-eye" x="6" y="4" width="1" height="1" />
              </g>
              <rect class="sc-ear-in" x="4" y="5" width="1" height="1" />
              <rect class="sc-fur" x="1" y="7" width="8" height="5" />
              <rect class="sc-cream" x="3" y="7" width="3" height="4" />
              <rect class="sc-fur-dark" x="1" y="8" width="1" height="2" />
              <rect class="sc-fur-dark" x="8" y="8" width="1" height="2" />
              <rect class="sc-cream" x="2" y="11" width="2" height="1" />
              <rect class="sc-cream" x="5" y="11" width="2" height="1" />
            </g>
            <!-- Placed by the outer group: a CSS transform (its breathing) replaces an SVG one. -->
            <g v-else transform="translate(74 69)"><g class="sc-cat-sleep">
              <rect class="sc-fur" x="1" y="1" width="12" height="1" />
              <rect class="sc-fur" x="0" y="2" width="14" height="5" />
              <rect class="sc-fur-dark" x="6" y="2" width="1" height="2" />
              <rect class="sc-fur-dark" x="9" y="2" width="1" height="2" />
              <rect class="sc-fur" x="0" y="0" width="2" height="2" />
              <rect class="sc-fur" x="4" y="0" width="2" height="2" />
              <rect class="sc-cat-eye" x="1" y="4" width="2" height="1" />
              <rect class="sc-cat-eye" x="4" y="4" width="2" height="1" />
              <rect class="sc-fur-dark" x="0" y="6" width="12" height="1" />
              <rect class="sc-cream" x="11" y="6" width="2" height="1" />
            </g></g>
          </g>

          <!-- Sticky notes and the wall clock (the company's time). -->
          <rect class="sc-note-1" x="128" y="27" width="12" height="12" />
          <rect class="sc-note-ink" x="130" y="31" width="8" height="1" />
          <rect class="sc-note-ink" x="130" y="34" width="5" height="1" />
          <rect class="sc-note-2" x="144" y="22" width="12" height="12" />
          <rect class="sc-note-ink" x="146" y="26" width="7" height="1" />
          <g class="sc-clock" data-testid="scene-clock">
            <circle class="sc-clock-rim" cx="171" cy="31" r="10" />
            <circle class="sc-clock-face" cx="171" cy="31" r="8" />
            <rect class="sc-clock-tick" x="170.5" y="24" width="1" height="2" />
            <rect class="sc-clock-tick" x="170.5" y="36" width="1" height="2" />
            <rect class="sc-clock-tick" x="164" y="30.5" width="2" height="1" />
            <rect class="sc-clock-tick" x="176" y="30.5" width="2" height="1" />
            <rect class="sc-clock-hand" x="170.3" y="26.5" width="1.4" height="5" :transform="`rotate(${hands.hour} 171 31)`" data-testid="scene-hour" />
            <rect class="sc-clock-minute" x="170.5" y="24" width="1" height="7.5" :transform="`rotate(${hands.minute} 171 31)`" />
            <rect class="sc-clock-pin" x="170" y="30" width="2" height="2" />
          </g>

          <!-- A shelf: books, a little plant and a framed Claude. -->
          <rect class="sc-book-1" x="217" y="21" width="5" height="15" />
          <rect class="sc-book-2" x="223" y="24" width="5" height="12" />
          <rect class="sc-book-3" x="229" y="19" width="4" height="17" />
          <rect class="sc-book-4" x="234" y="26" width="7" height="10" />
          <rect class="sc-spine" x="218" y="23" width="3" height="1" />
          <rect class="sc-spine" x="224" y="26" width="3" height="1" />
          <rect class="sc-spine" x="229" y="21" width="4" height="1" />
          <rect class="sc-pot" x="258" y="28" width="12" height="8" />
          <rect class="sc-pot-dark" x="257" y="27" width="14" height="2" />
          <g class="sc-sway sc-sway-small">
            <rect class="sc-plant" x="263" y="17" width="3" height="10" />
            <rect class="sc-plant-dark" x="258" y="21" width="6" height="3" />
            <rect class="sc-plant" x="266" y="19" width="7" height="3" />
            <rect class="sc-plant-dark" x="261" y="15" width="3" height="5" />
          </g>
          <rect class="sc-frame" x="279" y="23" width="13" height="13" />
          <rect class="sc-photo" x="281" y="25" width="9" height="9" />
          <rect class="sc-claude" x="282" y="28" width="7" height="5" />
          <rect class="sc-photo" x="284" y="29" width="1" height="2" />
          <rect class="sc-photo" x="287" y="29" width="1" height="2" />
          <rect class="sc-wood" x="211" y="36" width="86" height="4" />
          <rect class="sc-wood-dark" x="211" y="40" width="86" height="1" />
          <rect class="sc-wood-dark" x="219" y="41" width="3" height="6" />
          <rect class="sc-wood-dark" x="286" y="41" width="3" height="6" />

          <!-- The calendar: the company's day of the month. -->
          <rect class="sc-cal-ring" x="284" y="50" width="2" height="3" />
          <rect class="sc-cal-ring" x="294" y="50" width="2" height="3" />
          <rect class="sc-cal-head" x="280" y="52" width="20" height="5" />
          <rect class="sc-cal-page" x="280" y="57" width="20" height="14" />
          <rect class="sc-cal-shade" x="280" y="70" width="20" height="1" />
          <text class="sc-cal-day" x="290" y="68" text-anchor="middle" data-testid="scene-day">{{ day }}</text>

          <!-- A rug, and a plant on the floor by the window. -->
          <rect class="sc-rug-edge" x="72" y="146" width="232" height="26" />
          <rect class="sc-rug" x="76" y="149" width="224" height="20" />
          <rect v-for="index in 13" :key="`rug${index}`" class="sc-rug-edge" :x="80 + index * 16" y="158" width="4" height="2" />
          <g class="sc-sway">
            <rect class="sc-plant" x="30" y="111" width="11" height="6" />
            <rect class="sc-plant-dark" x="43" y="103" width="8" height="15" />
            <rect class="sc-plant" x="52" y="109" width="12" height="6" />
            <rect class="sc-plant-dark" x="33" y="121" width="11" height="5" />
            <rect class="sc-plant" x="49" y="119" width="12" height="5" />
            <rect class="sc-plant-dark" x="45" y="115" width="3" height="24" />
          </g>
          <rect class="sc-pot" x="38" y="140" width="17" height="17" />
          <rect class="sc-pot-dark" x="36" y="138" width="21" height="3" />

          <!-- Its chair, behind it: a padded back with a rounded top. -->
          <rect class="sc-chair" x="125" y="64" width="50" height="1" />
          <rect class="sc-chair" x="123" y="65" width="54" height="2" />
          <rect class="sc-chair" x="122" y="67" width="56" height="33" />
          <rect class="sc-chair-light" x="127" y="68" width="46" height="28" />
          <rect class="sc-chair-seam" x="149" y="69" width="2" height="26" />
          <rect class="sc-chair-shine" x="128" y="69" width="10" height="1" />
        </g>
      </svg>

      <!-- The chibi on its chair. -->
      <div
        class="scene-seat absolute"
        :style="{ left: `${seat.left}px`, top: `${seat.top}px`, width: `${seat.size}px` }"
        @click="poke"
      >
        <AiBuddy
          :variant="chibi"
          :color="color"
          :mood="buddy.mood"
          :action="action"
          :beat="beat"
          :size="seat.size"
          :asleep="buddy.asleep"
          :gaze="glance ?? buddy.gaze"
          sitting
          tabindex="-1"
          aria-hidden="true"
        />
      </div>

      <!-- The desk in front of it. -->
      <svg class="scene-layer scene-desk" :viewBox="`0 0 ${ROOM.width} ${ROOM.height}`" preserveAspectRatio="xMidYMid slice" shape-rendering="crispEdges">
        <g :transform="`translate(${ROOM.stageX} 0)`">
          <rect class="sc-floor-shadow" x="96" y="160" width="206" height="3" />
          <rect class="sc-desk-shade" x="98" y="116" width="7" height="46" />
          <rect class="sc-desk-shade" x="292" y="116" width="7" height="46" />
          <rect class="sc-desk-front" x="236" y="116" width="52" height="41" />
          <rect class="sc-desk-shade" x="236" y="129" width="52" height="1" />
          <rect class="sc-desk-shade" x="236" y="142" width="52" height="1" />
          <rect class="sc-knob" x="260" y="122" width="4" height="2" />
          <rect class="sc-knob" x="260" y="135" width="4" height="2" />
          <rect class="sc-knob" x="260" y="148" width="4" height="2" />
          <rect class="sc-desk-top" x="92" y="100" width="212" height="6" />
          <rect class="sc-desk-light" x="92" y="100" width="212" height="1" />
          <rect class="sc-desk-front" x="92" y="106" width="212" height="10" />
          <rect class="sc-desk-shade" x="92" y="114" width="212" height="2" />

          <!-- A desk lamp (a tap switches it), papers, the keyboard and the mouse. -->
          <g class="sc-hit sc-lamp-set" data-testid="scene-lamp" @click="lampOn = !lampOn">
            <rect class="sc-gear" x="95" y="97" width="12" height="3" />
            <rect class="sc-gear" x="99" y="91" width="2" height="6" />
            <rect class="sc-gear" x="99" y="85" width="2" height="6" />
            <rect class="sc-gear" x="101" y="79" width="2" height="6" />
            <rect class="sc-lamp" x="98" y="72" width="16" height="6" />
            <rect class="sc-bulb" x="101" y="78" width="11" height="1" />
          </g>
          <rect class="sc-paper" x="108" y="98" width="12" height="2" />
          <rect class="sc-paper-shade" x="110" y="97" width="10" height="1" />
          <rect class="sc-gear" x="130" y="101" width="40" height="4" />
          <rect v-for="key in keys" :key="`k${key}`" class="sc-key" :x="132 + key * 4" y="102" width="3" height="1" />
          <rect v-for="key in keys" :key="`l${key}`" class="sc-key" :x="134 + key * 4" y="103" width="2" height="1" />
          <rect class="sc-mouse" x="176" y="101" width="6" height="3" />
          <rect class="sc-mouse-dark" x="178" y="101" width="2" height="1" />

          <!-- Its own thing on the desk; a tap starts its trick. -->
          <g class="sc-hit sc-prop" :data-prop="chibi" data-testid="scene-prop" @click="propTap">
            <template v-if="chibi === 'voice'">
              <rect class="sc-gear" x="114" y="98" width="10" height="2" />
              <rect class="sc-gear" x="118" y="93" width="2" height="5" />
              <rect class="sc-mic" x="116" y="85" width="6" height="8" />
              <rect class="sc-mic-grille" x="117" y="86" width="1" height="1" />
              <rect class="sc-mic-grille" x="120" y="86" width="1" height="1" />
              <rect class="sc-mic-grille" x="117" y="88" width="1" height="1" />
              <rect class="sc-mic-grille" x="120" y="88" width="1" height="1" />
              <rect class="sc-mic-grille" x="117" y="90" width="1" height="1" />
              <rect class="sc-mic-grille" x="120" y="90" width="1" height="1" />
              <rect class="sc-rec" x="118" y="83" width="2" height="1" />
            </template>
            <template v-else-if="chibi === 'morning'">
              <rect class="sc-bell" x="113" y="86" width="4" height="3" />
              <rect class="sc-bell" x="123" y="86" width="4" height="3" />
              <rect class="sc-alarm" x="114" y="88" width="12" height="11" />
              <rect class="sc-alarm-face" x="116" y="90" width="8" height="7" />
              <rect class="sc-gear" x="120" y="91" width="1" height="3" />
              <rect class="sc-gear" x="120" y="93" width="3" height="1" />
              <rect class="sc-gear" x="115" y="99" width="2" height="1" />
              <rect class="sc-gear" x="123" y="99" width="2" height="1" />
            </template>
            <template v-else-if="chibi === 'deadline'">
              <rect class="sc-wood" x="114" y="86" width="12" height="2" />
              <rect class="sc-wood" x="114" y="98" width="12" height="2" />
              <rect class="sc-glass" x="115" y="88" width="10" height="10" />
              <rect class="sc-sand sc-sand-top" x="116" y="89" width="8" height="3" />
              <rect class="sc-sand sc-sand-stream" x="119" y="92" width="2" height="2" />
              <rect class="sc-sand sc-sand-bottom" x="116" y="94" width="8" height="3" />
              <rect class="sc-wood-dark" x="114" y="88" width="1" height="10" />
              <rect class="sc-wood-dark" x="125" y="88" width="1" height="10" />
            </template>
            <template v-else-if="chibi === 'photo'">
              <rect class="sc-gear" x="115" y="88" width="5" height="2" />
              <rect class="sc-gear" x="113" y="90" width="14" height="10" />
              <rect class="sc-lens-ring" x="116" y="91" width="7" height="7" />
              <rect class="sc-lens" x="117" y="92" width="5" height="5" />
              <rect class="sc-lens-glint" x="118" y="93" width="1" height="1" />
              <rect class="sc-flash-bulb" x="124" y="91" width="2" height="1" />
            </template>
            <template v-else-if="chibi === 'hr'">
              <rect class="sc-folder-1" x="112" y="96" width="15" height="4" />
              <rect class="sc-folder-2" x="113" y="93" width="14" height="3" />
              <rect class="sc-folder-3" x="112" y="90" width="15" height="3" />
              <rect class="sc-folder-3" x="114" y="89" width="5" height="1" />
              <rect class="sc-paper" x="114" y="91" width="9" height="1" />
              <rect class="sc-pen" x="125" y="84" width="1" height="8" />
              <rect class="sc-gear" x="125" y="84" width="1" height="1" />
            </template>
            <template v-else-if="chibi === 'tutor'">
              <!-- A pile of books with a stick of chalk on top. -->
              <rect class="sc-book-1" x="111" y="94" width="17" height="6" />
              <rect class="sc-book-band" x="113" y="96" width="13" height="1" />
              <rect class="sc-book-2" x="113" y="90" width="14" height="4" />
              <rect class="sc-paper" x="113" y="91" width="13" height="2" />
              <rect class="sc-book-3" x="112" y="87" width="13" height="3" />
              <rect class="sc-book-band-3" x="114" y="88" width="9" height="1" />
              <rect class="sc-chalk" x="116" y="85" width="6" height="2" />
              <rect class="sc-chalk-shade" x="116" y="86" width="6" height="1" />
            </template>
            <template v-else-if="chibi === 'advisor'">
              <!-- A little bar chart on an easel; its bars rise and fall while the advisor works. -->
              <rect class="sc-wood-dark" x="114" y="96" width="1" height="4" />
              <rect class="sc-wood-dark" x="125" y="96" width="1" height="4" />
              <rect class="sc-gear" x="111" y="83" width="18" height="14" />
              <rect class="sc-paper" x="112" y="84" width="16" height="12" />
              <g class="sc-bars">
                <rect class="sc-bar-1" x="114" y="91" width="2" height="4" />
                <rect class="sc-bar-2" x="117" y="89" width="2" height="6" />
                <rect class="sc-bar-1" x="120" y="88" width="2" height="7" />
                <rect class="sc-bar-3" x="123" y="86" width="2" height="9" />
              </g>
              <rect class="sc-paper-shade" x="112" y="95" width="16" height="1" />
            </template>
            <template v-else-if="chibi === 'custom'">
              <!-- The report it is about to send: an envelope with a heart seal. -->
              <rect class="sc-paper" x="113" y="90" width="14" height="10" />
              <rect class="sc-paper-shade" x="113" y="99" width="14" height="1" />
              <rect class="sc-envelope-flap" x="113" y="90" width="2" height="1" />
              <rect class="sc-envelope-flap" x="115" y="91" width="2" height="1" />
              <rect class="sc-envelope-flap" x="117" y="92" width="2" height="1" />
              <rect class="sc-envelope-flap" x="121" y="92" width="2" height="1" />
              <rect class="sc-envelope-flap" x="123" y="91" width="2" height="1" />
              <rect class="sc-envelope-flap" x="125" y="90" width="2" height="1" />
              <rect class="sc-seal" x="119" y="92" width="2" height="1" />
              <rect class="sc-seal" x="118" y="93" width="4" height="1" />
              <rect class="sc-seal" x="119" y="94" width="2" height="1" />
            </template>
            <template v-else>
              <rect class="sc-claude" x="115" y="89" width="10" height="11" />
              <rect class="sc-claude" x="114" y="91" width="12" height="7" />
              <rect class="sc-plush-eye" x="117" y="92" width="1" height="2" />
              <rect class="sc-plush-eye" x="122" y="92" width="1" height="2" />
              <rect class="sc-plush-cheek" x="116" y="95" width="2" height="1" />
              <rect class="sc-plush-cheek" x="122" y="95" width="2" height="1" />
            </template>
          </g>

          <!-- The monitor: the screen itself is the top layer. -->
          <rect class="sc-monitor-light" x="214" y="98" width="32" height="3" />
          <rect class="sc-monitor" x="226" y="88" width="8" height="11" />
          <rect class="sc-monitor" x="188" y="40" width="84" height="50" />
          <rect class="sc-monitor-light" x="188" y="40" width="84" height="2" />
          <rect class="sc-monitor-light" x="188" y="86" width="84" height="4" />
          <rect class="sc-led" x="265" y="87" width="3" height="1" />
          <rect class="sc-note-1" x="263" y="37" width="8" height="8" />

          <!-- A mug, steaming unless it sleeps; a tap for a sip. -->
          <g class="sc-hit" data-testid="scene-mug" @click="sip">
            <rect class="sc-mug" x="282" y="91" width="9" height="9" />
            <rect class="sc-mug-dark" x="291" y="93" width="3" height="5" />
            <rect class="sc-mug-light" x="282" y="91" width="9" height="1" />
          </g>
          <g class="sc-steam" :class="{ 'sc-steam--puff': steam }">
            <rect x="284" y="84" width="1" height="3" />
            <rect x="285" y="81" width="1" height="3" />
            <rect x="288" y="85" width="1" height="2" />
            <rect x="287" y="82" width="1" height="3" />
          </g>
        </g>
      </svg>

      <!-- Night or sleep dims the room; the screen and the lamp glow through it. -->
      <svg class="scene-layer scene-shade" :viewBox="`0 0 ${ROOM.width} ${ROOM.height}`" preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient :id="glowId">
            <stop offset="0" class="sc-glow-in" />
            <stop offset="1" class="sc-glow-out" />
          </radialGradient>
          <radialGradient :id="lampId">
            <stop offset="0" class="sc-lamp-in" />
            <stop offset="1" class="sc-lamp-out" />
          </radialGradient>
        </defs>
        <rect class="sc-dim" x="0" y="0" :width="ROOM.width" :height="ROOM.height" />
        <g :transform="`translate(${ROOM.stageX} 0)`">
          <ellipse class="sc-glow" cx="230" cy="64" rx="96" ry="70" :fill="`url(#${glowId})`" />
          <ellipse class="sc-lamp-glow" cx="108" cy="96" rx="44" ry="20" :fill="`url(#${lampId})`" />
        </g>
      </svg>

      <!-- The screen, and a sparkle over the monitor when it has done something new. -->
      <svg class="scene-layer scene-screen" :viewBox="`0 0 ${ROOM.width} ${ROOM.height}`" preserveAspectRatio="xMidYMid slice">
        <g :transform="`translate(${ROOM.stageX} 0)`">
          <rect class="sc-screen" x="192" y="44" width="76" height="42" shape-rendering="crispEdges" />
          <template v-if="state !== 'asleep'">
            <rect class="sc-titlebar" x="192" y="44" width="76" height="5" shape-rendering="crispEdges" />
            <rect class="sc-dot-red" x="195" y="46" width="2" height="2" shape-rendering="crispEdges" />
            <rect class="sc-dot-yellow" x="199" y="46" width="2" height="2" shape-rendering="crispEdges" />
            <rect class="sc-dot-green" x="203" y="46" width="2" height="2" shape-rendering="crispEdges" />
            <template v-if="screenText.length">
              <text
                v-for="(line, index) in screenText"
                :key="`${index}-${shown[index]}`"
                :class="index === screenText.length - 1 ? 'sc-ink-new' : 'sc-ink'"
                x="195"
                :y="56 + index * 6"
                data-testid="scene-line"
              >{{ line }}</text>
            </template>
            <template v-else>
              <rect v-for="(width, index) in bars" :key="`bar${index}`" class="sc-bar" x="195" :y="53 + index * 6" :width="width" height="2" shape-rendering="crispEdges" />
            </template>
            <rect
              class="sc-cursor"
              :x="195 + Math.min(26, (screenText.at(-1) ?? '').length) * 2.52 + 1"
              :y="screenText.length ? 52 + (screenText.length - 1) * 6 : 77"
              width="2"
              height="5"
              shape-rendering="crispEdges"
            />
            <g v-if="state === 'working'" class="sc-progress">
              <rect class="sc-track" x="195" y="82" width="70" height="2" shape-rendering="crispEdges" />
              <rect class="sc-fill" x="195" y="82" width="70" height="2" shape-rendering="crispEdges" />
            </g>
          </template>
          <g v-else class="sc-saver">
            <text x="226" y="68">z</text>
            <text x="234" y="62" class="sc-saver-small">z</text>
          </g>
          <rect class="sc-glare" x="192" y="44" width="76" height="42" />
          <g v-if="burst" :key="`burst${burst}`" class="sc-burst" shape-rendering="crispEdges" data-testid="scene-burst">
            <rect class="sc-burst-ok" x="226" y="30" width="2" height="2" />
            <rect class="sc-burst-ok" x="228" y="32" width="2" height="2" />
            <rect class="sc-burst-ok" x="230" y="30" width="2" height="2" />
            <rect class="sc-burst-ok" x="232" y="28" width="2" height="2" />
            <rect class="sc-burst-ok" x="234" y="26" width="2" height="2" />
            <rect class="sc-burst-spark" x="218" y="28" width="1" height="3" />
            <rect class="sc-burst-spark" x="217" y="29" width="3" height="1" />
            <rect class="sc-burst-spark" x="242" y="24" width="1" height="3" />
            <rect class="sc-burst-spark" x="241" y="25" width="3" height="1" />
          </g>
        </g>
      </svg>

      <!-- What it thinks, says and dreams, over everything. -->
      <div v-if="thought && !speech" class="scene-thought absolute" :style="{ left: `${chatAt.left}px`, top: `${chatAt.top}px` }" :data-icon="thought" data-testid="scene-thought">
        <span class="scene-thought-box">
          <svg viewBox="0 0 7 6" shape-rendering="crispEdges" class="block h-4 w-5" aria-hidden="true">
            <template v-if="thought === 'heart'">
              <rect x="1" y="0" width="2" height="1" fill="#ff6b8a" /><rect x="4" y="0" width="2" height="1" fill="#ff6b8a" />
              <rect x="0" y="1" width="7" height="2" fill="#ff6b8a" /><rect x="1" y="3" width="5" height="1" fill="#ff6b8a" />
              <rect x="2" y="4" width="3" height="1" fill="#ff6b8a" /><rect x="3" y="5" width="1" height="1" fill="#ff6b8a" />
            </template>
            <template v-else-if="thought === 'star'">
              <rect x="3" y="0" width="1" height="2" fill="#f2b544" /><rect x="0" y="2" width="7" height="1" fill="#f2b544" />
              <rect x="1" y="3" width="5" height="1" fill="#f2b544" /><rect x="1" y="4" width="2" height="1" fill="#f2b544" />
              <rect x="4" y="4" width="2" height="1" fill="#f2b544" /><rect x="0" y="5" width="2" height="1" fill="#f2b544" /><rect x="5" y="5" width="2" height="1" fill="#f2b544" />
            </template>
            <template v-else-if="thought === 'coffee'">
              <rect x="2" y="0" width="1" height="1" fill="#b9b3a6" /><rect x="4" y="0" width="1" height="1" fill="#b9b3a6" />
              <rect x="1" y="2" width="4" height="4" fill="#e86f5a" /><rect x="5" y="3" width="1" height="2" fill="#e86f5a" /><rect x="1" y="2" width="4" height="1" fill="#7a4a2c" />
            </template>
            <template v-else-if="thought === 'note'">
              <rect x="0" y="0" width="6" height="6" fill="#ffd866" /><rect x="1" y="2" width="4" height="1" fill="#8a7a50" /><rect x="1" y="4" width="3" height="1" fill="#8a7a50" />
            </template>
            <template v-else>
              <rect x="2" y="0" width="3" height="1" fill="#ffd866" /><rect x="1" y="1" width="5" height="2" fill="#ffd866" />
              <rect x="2" y="3" width="3" height="1" fill="#ffd866" /><rect x="2" y="4" width="3" height="1" fill="#9aa3b5" /><rect x="3" y="5" width="1" height="1" fill="#9aa3b5" />
            </template>
          </svg>
        </span>
        <span class="scene-thought-dot scene-thought-dot--big" /><span class="scene-thought-dot" />
      </div>
      <div v-if="speech" class="scene-bubble absolute" :style="{ left: `${chatAt.left}px`, top: `${chatAt.top}px` }" data-testid="scene-speech">{{ speech }}</div>
      <div v-if="catTalks" class="scene-bubble scene-bubble--cat absolute" :style="{ left: `${catAt.left}px`, top: `${catAt.top}px` }" data-testid="scene-cat-says">{{ t("ai.agent.scene.say.cat") }}</div>
      <div v-if="state === 'asleep'" class="scene-zzz absolute" :style="{ left: `${zzzAt.left}px`, top: `${zzzAt.top}px` }">
        <span>z</span><span>z</span><span>Z</span>
      </div>
      <div v-if="flash" :key="`flash${flash}`" class="scene-flash absolute inset-0" />
    </div>
  </figure>
</template>

<style scoped>
.agent-scene {
  --sc-wall: #f1e7d8;
  --sc-stripe: rgba(120, 90, 50, 0.045);
  --sc-base: #cdb38f;
  --sc-floor: #dbbc92;
  --sc-seam: #c8a678;
  --sc-rug: #e9d4ad;
  --sc-rug-edge: #c49a66;
  --sc-frame: #fbf7ee;
  --sc-frame-dark: #d9cdb6;
  --sc-rod: #9a6a3c;
  --sc-curtain: #86bfac;
  --sc-curtain-fold: #6da895;
  --sc-sky-top: #9fd6f2;
  --sc-sky-bottom: #c9ecfb;
  --sc-wood: #b98552;
  --sc-wood-dark: #94643a;
  --sc-desk-top: #dcab6f;
  --sc-desk-light: #ecc48e;
  --sc-desk-front: #bc874f;
  --sc-desk-shade: #a1703f;
  --sc-chair: #5b6f86;
  --sc-chair-light: #7489a2;
  --sc-monitor: #2d3340;
  --sc-monitor-light: #3e4657;
  --sc-gear: #3a3f4b;
  --sc-screen: #0f1b2d;
  --sc-ink: #7fd8a8;
  --sc-ink-new: #c4ffdf;
  --sc-dim: rgba(14, 18, 44, 0);
  --sc-glow: rgba(140, 205, 255, 0.16);
  --sc-lamp-glow: rgba(255, 214, 128, 0);
  --sc-bubble-bg: #fffdf8;
  --sc-bubble-ink: #2d2a26;

  background: var(--sc-wall);
  touch-action: pan-y;
}


.agent-scene[data-night] {
  --sc-sky-top: #1a2246;
  --sc-sky-bottom: #29315c;
  --sc-dim: rgba(14, 18, 44, 0.36);
  --sc-glow: rgba(140, 205, 255, 0.34);
  --sc-lamp-glow: rgba(255, 210, 120, 0.42);
}

.agent-scene[data-state="asleep"] {
  --sc-screen: #07090c;
  --sc-dim: rgba(18, 20, 30, 0.26);
  --sc-glow: rgba(140, 205, 255, 0);
  --sc-lamp-glow: rgba(255, 210, 120, 0);
}

.agent-scene[data-state="asleep"][data-night] {
  --sc-dim: rgba(10, 12, 28, 0.48);
}

.agent-scene[data-state="working"] {
  --sc-glow: rgba(140, 205, 255, 0.26);
}

.agent-scene[data-state="working"][data-night] {
  --sc-glow: rgba(140, 205, 255, 0.46);
}

.agent-scene[data-lamp="off"] {
  --sc-lamp-glow: rgba(255, 210, 120, 0);
}

.scene-camera {
  transform: perspective(1400px) rotateY(calc(var(--px, 0) * 2.4deg)) rotateX(calc(var(--py, 0) * -1.6deg)) scale(1.035);
  transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1);
}

.scene-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.scene-room {
  transform: translate(calc(var(--px, 0) * -6px), calc(var(--py, 0) * -3px));
  transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1);
}

.scene-desk,
.scene-screen {
  transform: translate(calc(var(--px, 0) * 3px), calc(var(--py, 0) * 2px));
  transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1);
}

.scene-seat {
  transform: translate(calc(var(--px, 0) * -1px), 0);
  transition:
    transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1),
    top 0.8s ease;
  cursor: pointer;
}

.agent-scene[data-state="asleep"] .scene-seat {
  transform: translate(calc(var(--px, 0) * -1px), 0) rotate(5deg);
}

/* What a pointer may tap: the layers let everything else through to the chibi. */
.sc-hit {
  pointer-events: all;
  cursor: pointer;
}

.sc-wall { fill: var(--sc-wall); }
.sc-stripe { fill: var(--sc-stripe); }
.sc-base { fill: var(--sc-base); }
.sc-floor { fill: var(--sc-floor); }
.sc-seam { fill: var(--sc-seam); }
.sc-rug { fill: var(--sc-rug); }
.sc-rug-edge { fill: var(--sc-rug-edge); }
.sc-frame { fill: var(--sc-frame); }
.sc-frame-dark { fill: var(--sc-frame-dark); }
.sc-rod { fill: var(--sc-rod); }
.sc-curtain { fill: var(--sc-curtain); }
.sc-curtain-fold { fill: var(--sc-curtain-fold); }
.sc-sky-top { fill: var(--sc-sky-top); }
.sc-sky-bottom { fill: var(--sc-sky-bottom); }
.sc-sun { fill: #ffd766; }
.sc-moon { fill: #f4efcf; }
.sc-star { fill: #fff8d8; animation: sc-twinkle 2.6s steps(2) infinite; }
.sc-cloud rect { fill: #ffffff; opacity: 0.92; }
.sc-cloud { animation: sc-drift 26s linear infinite alternate; }
.sc-beam { fill: #ffffff; opacity: 0.1; }
.agent-scene[data-night] .sc-beam { fill: #b9c8ff; opacity: 0.06; }
.sc-mote { fill: #fffbe8; opacity: 0.5; animation: sc-mote 7s ease-in-out infinite alternate; }
.sc-note-1 { fill: #ffd866; }
.sc-note-2 { fill: #ff9fb7; }
.sc-note-3 { fill: #9be3b5; }
.sc-note-ink { fill: rgba(60, 50, 40, 0.45); }
.sc-book-1 { fill: #e8625a; }
.sc-book-2 { fill: #6a8fe0; }
.sc-book-3 { fill: #f2b544; }
.sc-book-4 { fill: #36b1a4; }
.sc-spine { fill: rgba(255, 255, 255, 0.45); }
.sc-pot { fill: #c8734a; }
.sc-pot-dark { fill: #a95c38; }
.sc-plant { fill: #4fae6a; }
.sc-plant-dark { fill: #3b8d53; }
.sc-sway { transform-box: fill-box; transform-origin: 50% 100%; animation: sc-sway 5.5s ease-in-out infinite alternate; }
.sc-sway-small { animation-duration: 4.2s; animation-delay: -1.3s; }
.sc-photo { fill: #f6efe2; }
.sc-claude { fill: #d97757; }
.sc-poster { fill: #f6efe2; }
.sc-cross { fill: #3fae6a; }
.sc-trophy { fill: #f2c14e; }
.sc-trophy-shine { fill: #fff3c4; }
.sc-cooler { fill: #e8e4dc; }
.sc-cooler-dark { fill: #c9c3b8; }
.sc-cooler-bottle { fill: #b9dff5; }
.sc-cooler-water { fill: #7cc4ec; }
.sc-bubble { fill: #e6f6ff; animation: sc-bubble 3.4s ease-in infinite; }
.sc-bubble-2 { animation-delay: -1.7s; }
.sc-tap-blue { fill: #5b8fd9; }
.sc-tap-red { fill: #e86f5a; }
.sc-wood { fill: var(--sc-wood); }
.sc-wood-dark { fill: var(--sc-wood-dark); }
.sc-chair { fill: var(--sc-chair); }
.sc-chair-light { fill: var(--sc-chair-light); }
.sc-chair-seam { fill: var(--sc-chair); opacity: 0.5; }
.sc-chair-shine { fill: rgba(255, 255, 255, 0.18); }

/* The wall clock and the calendar. */
.sc-clock-rim { fill: var(--sc-wood-dark); }
.sc-clock-face { fill: #fffaf0; }
.sc-clock-tick { fill: #9a8c76; }
.sc-clock-hand { fill: #3a3f4b; }
.sc-clock-minute { fill: #e86f5a; }
.sc-clock-pin { fill: #3a3f4b; }
.sc-cal-ring { fill: #6b6f7a; }
.sc-cal-head { fill: #e8625a; }
.sc-cal-page { fill: #fffaf0; }
.sc-cal-shade { fill: #e3dccd; }
.sc-cal-day {
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 9px;
  font-weight: 700;
  fill: #3a3f4b;
}

/* The cat. */
.sc-fur { fill: #f0a050; }
.sc-fur-dark { fill: #c97a34; }
.sc-cream { fill: #fde6c8; }
.sc-ear-in { fill: #f4a3ac; }
.sc-cat-eye { fill: #2b2622; }
.sc-cat-eyes { transform-box: fill-box; transform-origin: center; animation: sc-cat-blink 5.2s steps(1) infinite; }
.sc-tail { transform-box: fill-box; transform-origin: 0% 100%; animation: sc-tail 2.6s ease-in-out infinite alternate; }
.sc-cat { transform-box: fill-box; transform-origin: 50% 100%; }
.sc-cat--stretch { animation: sc-cat-stretch 0.9s ease-in-out; }
.sc-cat-sleep { transform-box: fill-box; transform-origin: 50% 100%; animation: sc-breathe 3.4s ease-in-out infinite; }

/* Birds by day, shooting stars by night (hidden until their moment, so a still room shows none). */
.sc-bird rect { fill: #3a3f4b; }
.sc-bird { opacity: 0; animation: sc-bird 24s linear infinite; }
.sc-bird-2 { animation-duration: 33s; animation-delay: -14s; }
.sc-bird-now { animation: sc-bird-now 5s linear 1 forwards; }
.sc-wing { animation: sc-flap 0.5s steps(2) infinite; }
.sc-shoot { fill: #fff8d8; opacity: 0; animation: sc-shoot 19s linear infinite; }
.sc-shoot-now { animation: sc-shoot-now 1.3s ease-out 1 forwards; }

/* Its own things on the desk. */
.sc-mic { fill: #4a5060; }
.sc-mic-grille { fill: #8b93a6; }
.sc-rec { fill: #ff6b6b; }
.agent-scene[data-state="working"] .sc-rec { animation: sc-blink 1.2s steps(2) infinite; }
.sc-bell { fill: #e0a93a; }
.sc-alarm { fill: #f2c94c; }
.sc-alarm-face { fill: #fffaf0; }
.sc-glass { fill: rgba(190, 225, 245, 0.55); }
.sc-sand { fill: #e9c27a; }
.sc-sand-top { transform-box: fill-box; transform-origin: 50% 100%; animation: sc-sand-top 8s linear infinite; }
.sc-sand-bottom { transform-box: fill-box; transform-origin: 50% 100%; animation: sc-sand-bottom 8s linear infinite; }
.sc-sand-stream { animation: sc-blink 0.6s steps(2) infinite; }
.sc-lens-ring { fill: #8b93a6; }
.sc-lens { fill: #1f2a3c; }
.sc-lens-glint { fill: #cfe6ff; }
.sc-flash-bulb { fill: #fff3c4; }
.sc-folder-1 { fill: #4fb36f; }
.sc-folder-2 { fill: #6a8fe0; }
.sc-folder-3 { fill: #f2b544; }
.sc-pen { fill: #2d6fd2; }
.sc-plush-eye { fill: #2b2622; }
.sc-plush-cheek { fill: #f39a88; }
.sc-envelope-flap { fill: #d8cfbd; }
.sc-seal { fill: #f06b9b; }
.sc-book-1 { fill: #2f6f8f; }
.sc-book-2 { fill: #c4523f; }
.sc-book-3 { fill: #4fb36f; }
.sc-book-band { fill: #f2b544; }
.sc-book-band-3 { fill: #9ad8a8; }
.sc-chalk { fill: #f7f3e8; }
.sc-chalk-shade { fill: #d9d2c2; }
.sc-bar-1 { fill: #4fb36f; }
.sc-bar-2 { fill: #6b8fd6; }
.sc-bar-3 { fill: #f2b544; }
/* At work, the advisor's chart is being drawn: its bars rise and fall one after another. */
.sc-bars rect { transform-box: fill-box; transform-origin: 50% 100%; }
.agent-scene[data-state="working"] .sc-bars rect { animation: sc-bar 1.8s ease-in-out infinite; }
.agent-scene[data-state="working"] .sc-bars rect:nth-child(2) { animation-delay: 0.2s; }
.agent-scene[data-state="working"] .sc-bars rect:nth-child(3) { animation-delay: 0.4s; }
.agent-scene[data-state="working"] .sc-bars rect:nth-child(4) { animation-delay: 0.6s; }
/* At work, the envelope lifts a little: the report is on its way. */
.agent-scene[data-state="working"] .sc-prop[data-prop="custom"] { animation: sc-wobble 2.4s ease-in-out infinite; transform-box: fill-box; transform-origin: 50% 100%; }
.agent-scene[data-state="working"] .sc-prop[data-prop="morning"] { animation: sc-wobble 2.4s ease-in-out infinite; transform-box: fill-box; transform-origin: 50% 100%; }

/* Its legs and floor shadow are under the desk: never drawn, so a slump can't show them. */
.scene-seat :deep(.buddy-leg),
.scene-seat :deep(.buddy-shadow) { display: none; }
.sc-floor-shadow { fill: rgba(0, 0, 0, 0.09); }
.sc-desk-top { fill: var(--sc-desk-top); }
.sc-desk-light { fill: var(--sc-desk-light); }
.sc-desk-front { fill: var(--sc-desk-front); }
.sc-desk-shade { fill: var(--sc-desk-shade); }
.sc-knob { fill: var(--sc-desk-light); }
.sc-gear { fill: var(--sc-gear); }
.sc-lamp { fill: #e8a33d; }
.sc-bulb { fill: #fff3c4; }
.agent-scene[data-state="asleep"] .sc-bulb,
.agent-scene[data-lamp="off"] .sc-bulb { fill: #b9ab84; }
.sc-paper { fill: #fbf7ee; }
.sc-paper-shade { fill: #e3dccd; }
.sc-key { fill: #8b93a6; }
.sc-mouse { fill: #ebe6dc; }
.sc-mouse-dark { fill: #b9b3a6; }
.sc-monitor { fill: var(--sc-monitor); }
.sc-monitor-light { fill: var(--sc-monitor-light); }
.sc-led { fill: #5be08a; }
.agent-scene[data-state="asleep"] .sc-led { fill: #f2b544; animation: sc-blink 2.4s steps(2) infinite; }
.sc-mug { fill: #e86f5a; }
.sc-mug-dark { fill: #c4523f; }
.sc-mug-light { fill: #f39a88; }
.sc-steam rect { fill: rgba(255, 255, 255, 0.75); }
.sc-steam { animation: sc-steam 2.4s ease-in-out infinite; }
.sc-steam--puff { animation: sc-puff 0.75s ease-out 2; }
.agent-scene[data-state="asleep"] .sc-steam { display: none; }
.sc-dim { fill: var(--sc-dim); transition: fill 0.8s ease; }
.sc-glow { mix-blend-mode: screen; }
.sc-glow-in { stop-color: var(--sc-glow); transition: stop-color 0.8s ease; }
.sc-glow-out { stop-color: rgba(140, 205, 255, 0); }
.sc-lamp-glow { mix-blend-mode: screen; }
.sc-lamp-in { stop-color: var(--sc-lamp-glow); transition: stop-color 0.4s ease; }
.sc-lamp-out { stop-color: rgba(255, 210, 120, 0); }
.agent-scene[data-state="working"] .sc-glow { animation: sc-pulse 2.2s ease-in-out infinite; }
.sc-screen { fill: var(--sc-screen); transition: fill 0.6s ease; }
.sc-titlebar { fill: #1c2a42; }
.sc-dot-red { fill: #ff6b6b; }
.sc-dot-yellow { fill: #ffd166; }
.sc-dot-green { fill: #6bd88a; }
.sc-ink,
.sc-ink-new {
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 4.2px;
  letter-spacing: 0;
  white-space: pre;
}
.sc-ink { fill: var(--sc-ink); opacity: 0.78; }
.sc-ink-new { fill: var(--sc-ink-new); }
.sc-bar { fill: var(--sc-ink); opacity: 0.45; }
.sc-cursor { fill: var(--sc-ink-new); animation: sc-blink 1s steps(2) infinite; }
.sc-track { fill: #1c2a42; }
.sc-fill { fill: var(--sc-ink); transform-box: fill-box; transform-origin: left center; animation: sc-progress 2.8s ease-in-out infinite; }
.sc-saver text {
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 7px;
  fill: #3b4a63;
}
.sc-saver .sc-saver-small { font-size: 5px; }
.sc-saver { animation: sc-float 5s ease-in-out infinite; }
.sc-glare { fill: rgba(255, 255, 255, 0.04); pointer-events: none; }
.sc-burst { opacity: 0; animation: sc-burst 1.3s ease-out 1 forwards; }
.sc-burst-ok { fill: #6bd88a; }
.sc-burst-spark { fill: #ffd766; }

/* Bubbles: what it says (words), what it thinks (a picture), its Zzz and the camera's flash. */
.scene-bubble {
  z-index: 2;
  max-width: 190px;
  transform: translate(-6px, -100%);
  padding: 5px 9px;
  border: 2px solid var(--sc-bubble-ink);
  border-radius: 3px;
  background: var(--sc-bubble-bg);
  color: var(--sc-bubble-ink);
  box-shadow: 3px 3px 0 rgba(0, 0, 0, 0.16);
  font: 600 12px/1.3 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  pointer-events: none;
  animation: scene-pop 0.22s steps(3) both;
}
.scene-bubble::after {
  content: "";
  position: absolute;
  left: 8px;
  bottom: -8px;
  width: 8px;
  height: 8px;
  background: var(--sc-bubble-bg);
  border-right: 2px solid var(--sc-bubble-ink);
  border-bottom: 2px solid var(--sc-bubble-ink);
  clip-path: polygon(0 0, 100% 0, 100% 100%);
}
.scene-bubble--cat { padding: 3px 7px; font-size: 11px; }
.scene-thought {
  z-index: 2;
  transform: translate(-2px, -100%);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  pointer-events: none;
  animation: scene-pop 0.22s steps(3) both;
}
.scene-thought-box {
  display: block;
  padding: 4px 6px;
  border: 2px solid var(--sc-bubble-ink);
  border-radius: 8px;
  background: var(--sc-bubble-bg);
  box-shadow: 2px 2px 0 rgba(0, 0, 0, 0.14);
}
.scene-thought-dot {
  display: block;
  width: 5px;
  height: 5px;
  margin-left: 4px;
  border: 2px solid var(--sc-bubble-ink);
  border-radius: 50%;
  background: var(--sc-bubble-bg);
}
.scene-thought-dot--big { width: 7px; height: 7px; margin-left: 8px; }
.scene-zzz {
  z-index: 2;
  pointer-events: none;
  font: 700 13px/1 ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  color: #8fa3c8;
}
.scene-zzz span {
  position: absolute;
  opacity: 0;
  animation: scene-zzz 3.6s ease-out infinite;
}
.scene-zzz span:nth-child(2) { animation-delay: 1.2s; font-size: 15px; }
.scene-zzz span:nth-child(3) { animation-delay: 2.4s; font-size: 18px; }
.scene-flash {
  z-index: 3;
  background: #ffffff;
  pointer-events: none;
  animation: scene-flash 0.45s ease-out 1 forwards;
}

@keyframes sc-twinkle {
  50% { opacity: 0.25; }
}
@keyframes sc-drift {
  from { transform: translateX(-4px); }
  to { transform: translateX(10px); }
}
@keyframes sc-blink {
  50% { opacity: 0; }
}
@keyframes sc-steam {
  0% { transform: translateY(2px); opacity: 0; }
  40% { opacity: 0.9; }
  100% { transform: translateY(-4px); opacity: 0; }
}
@keyframes sc-puff {
  0% { transform: translateY(1px) scale(1); opacity: 0.4; }
  50% { opacity: 1; }
  100% { transform: translateY(-7px) scale(1.25); opacity: 0; }
}
@keyframes sc-pulse {
  50% { opacity: 0.7; }
}
@keyframes sc-progress {
  0% { transform: scaleX(0.05); }
  70% { transform: scaleX(0.95); }
  100% { transform: scaleX(1); opacity: 0.3; }
}
@keyframes sc-float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(4px, -3px); }
}
@keyframes sc-mote {
  0% { transform: translate(0, 0); opacity: 0.15; }
  50% { opacity: 0.75; }
  100% { transform: translate(4px, -7px); opacity: 0.2; }
}
@keyframes sc-sway {
  from { transform: rotate(-1.6deg); }
  to { transform: rotate(1.6deg); }
}
@keyframes sc-bubble {
  0% { transform: translateY(0); opacity: 0; }
  20% { opacity: 1; }
  100% { transform: translateY(-11px); opacity: 0; }
}
@keyframes sc-cat-blink {
  0%, 92%, 100% { transform: scaleY(1); }
  94%, 97% { transform: scaleY(0.15); }
}
@keyframes sc-tail {
  from { transform: rotate(-14deg); }
  to { transform: rotate(10deg); }
}
@keyframes sc-cat-stretch {
  0%, 100% { transform: scale(1, 1); }
  35% { transform: scale(1.12, 0.86); }
  70% { transform: scale(0.94, 1.08); }
}
@keyframes sc-breathe {
  0%, 100% { transform: scaleY(1); }
  50% { transform: scaleY(1.07); }
}
@keyframes sc-bird {
  0% { transform: translate(24px, 36px); opacity: 1; }
  34% { transform: translate(108px, 27px); opacity: 1; }
  34.1%, 100% { transform: translate(108px, 27px); opacity: 0; }
}
@keyframes sc-bird-now {
  0% { transform: translate(104px, 30px) scaleX(-1); opacity: 1; }
  99% { transform: translate(22px, 40px) scaleX(-1); opacity: 1; }
  100% { opacity: 0; }
}
@keyframes sc-flap {
  50% { transform: translateY(1px); }
}
@keyframes sc-shoot {
  0%, 82% { transform: translate(44px, 24px) rotate(24deg); opacity: 0; }
  84% { opacity: 1; }
  88% { transform: translate(84px, 42px) rotate(24deg); opacity: 0; }
  100% { opacity: 0; }
}
@keyframes sc-shoot-now {
  0% { transform: translate(40px, 26px) rotate(24deg); opacity: 0; }
  15% { opacity: 1; }
  100% { transform: translate(90px, 48px) rotate(24deg); opacity: 0; }
}
@keyframes sc-sand-top {
  0% { transform: scaleY(1); }
  95% { transform: scaleY(0.1); }
  100% { transform: scaleY(1); }
}
@keyframes sc-sand-bottom {
  0% { transform: scaleY(0.15); }
  95% { transform: scaleY(1); }
  100% { transform: scaleY(0.15); }
}
@keyframes sc-bar {
  0%, 100% { transform: scaleY(1); }
  50% { transform: scaleY(0.55); }
}
@keyframes sc-wobble {
  0%, 100% { transform: rotate(0); }
  10% { transform: rotate(-4deg); }
  20% { transform: rotate(4deg); }
  30% { transform: rotate(0); }
}
@keyframes sc-burst {
  0% { transform: translateY(4px); opacity: 0; }
  25% { transform: translateY(0); opacity: 1; }
  80% { opacity: 1; }
  100% { transform: translateY(-5px); opacity: 0; }
}
@keyframes scene-pop {
  0% { transform: translate(-6px, -100%) scale(0.6); opacity: 0; }
  100% { transform: translate(-6px, -100%) scale(1); opacity: 1; }
}
@keyframes scene-zzz {
  0% { transform: translate(0, 0); opacity: 0; }
  20% { opacity: 1; }
  100% { transform: translate(14px, -26px); opacity: 0; }
}
@keyframes scene-flash {
  from { opacity: 0.85; }
  to { opacity: 0; }
}

</style>

<style>
/* Unscoped on purpose: in a scoped block `:global(X) .agent-scene` compiles to just `X` (Vue drops
 * the rest), so the dark palette and reduced motion live here, keyed by the scene's own class. */
html[data-theme="dark"] .agent-scene {
  --sc-wall: #2c2720;
  --sc-stripe: rgba(255, 255, 255, 0.022);
  --sc-base: #4b3e2f;
  --sc-floor: #4d3b2a;
  --sc-seam: #3f3022;
  --sc-rug: #5d4934;
  --sc-rug-edge: #725a3d;
  --sc-frame: #d8d0c0;
  --sc-frame-dark: #a69d8b;
  --sc-curtain: #4f8170;
  --sc-curtain-fold: #426d5e;
  --sc-wood: #80593a;
  --sc-wood-dark: #634329;
  --sc-desk-top: #a07549;
  --sc-desk-light: #b98b5b;
  --sc-desk-front: #7f5a36;
  --sc-desk-shade: #67472a;
  --sc-chair: #43526a;
  --sc-chair-light: #55667f;
  --sc-bubble-bg: #f5efe4;
  --sc-bubble-ink: #1f1c18;
}

html[data-motion="reduced"] .agent-scene,
html[data-motion="reduced"] .agent-scene * {
  animation: none !important;
  transition: none !important;
}
html[data-motion="reduced"] .agent-scene .scene-camera {
  transform: none !important;
}
/* Still: the bubbles keep their place without their pop. */
html[data-motion="reduced"] .agent-scene .scene-bubble { transform: translate(-6px, -100%); }
html[data-motion="reduced"] .agent-scene .scene-thought { transform: translate(-2px, -100%); }
</style>
