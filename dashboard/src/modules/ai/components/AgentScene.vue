<script setup lang="ts">
/**
 * The big picture on an agent's own page: its chibi in a little room, sitting at its desk. While
 * the agent works it types and its screen fills with what it does; while it waits it watches the
 * screen and pulls faces; switched off it sleeps on the desk with the screen dark. The window shows
 * day or night by the company's clock. Pixel art in the chibis' style (no image files), drawn in
 * room units (scene.ts) and layered: the room, the chibi on its chair, the desk in front of it, the
 * night's shade and the screen's glow, then the screen itself. A pointer over it tilts the room a
 * little, like looking in through a window; with reduced motion nothing moves.
 */
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";

import { reducedMotion } from "@/components/chartOptions";

import { buddyVariant, type BuddyAction } from "../lib";
import { pickSceneAction, ROOM, SCENE_BEAT_MS, sceneActionMs, sceneBuddy, screenLines, seatBox, type SceneState } from "../scene";
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
  }>(),
  { lines: () => [], night: false },
);

const VARIANTS = new Set(["claude", "voice", "morning", "deadline", "photo", "hr"]);
const chibi = computed(() => (VARIANTS.has(props.variant) ? (props.variant as ReturnType<typeof buddyVariant>) : buddyVariant(props.variant)));
const buddy = computed(() => sceneBuddy(props.state));
const reduced = reducedMotion();
const glowId = `scene-glow-${useId()}`;
const lampId = `scene-lamp-${useId()}`;

// Size: the room covers the box; the chibi (HTML) is placed with the same units.
const root = ref<HTMLElement | null>(null);
const box = ref({ width: 0, height: 0 });
let observer: ResizeObserver | null = null;
const seat = computed(() => seatBox(box.value.width, box.value.height, props.state === "asleep"));

// What it does: a new face every few seconds, settling back to watching the screen.
const action = ref<BuddyAction>("idle");
const beat = ref(0);
let actionTimer: ReturnType<typeof setTimeout> | null = null;
let settleTimer: ReturnType<typeof setTimeout> | null = null;

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
  act(pickSceneAction(props.state, action.value));
  actionTimer = setTimeout(loop, SCENE_BEAT_MS[props.state] * (0.75 + Math.random() * 0.5));
}

/** A tap: hearts while it's awake; asleep, a startled blink and back to sleep. */
function poke(): void {
  if (reduced) return;
  act(props.state === "asleep" ? "wide" : "hearts");
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

watch(
  () => props.state,
  () => {
    loop();
    typeNewest();
  },
);
watch(
  () => shown.value.at(-1),
  () => typeNewest(),
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
        <rect class="sc-wall" x="0" y="0" :width="ROOM.width" height="118" />
        <rect v-for="x in stripes" :key="`s${x}`" class="sc-stripe" :x="x" y="0" width="8" height="116" />
        <rect class="sc-base" x="0" y="115" :width="ROOM.width" height="4" />
        <rect class="sc-floor" x="0" y="119" :width="ROOM.width" height="61" />
        <rect v-for="y in rowSeams" :key="`r${y}`" class="sc-seam" x="0" :y="y" :width="ROOM.width" height="1" />
        <rect v-for="seam in boardSeams" :key="`b${seam.x}-${seam.y}`" class="sc-seam" :x="seam.x" :y="seam.y" width="1" :height="seam.h - 1" />

        <g :transform="`translate(${ROOM.stageX} 0)`">
          <!-- The window: day sky with clouds, or night with the moon and stars. -->
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

          <!-- Sticky notes on the wall. -->
          <rect class="sc-note-1" x="128" y="27" width="12" height="12" />
          <rect class="sc-note-ink" x="130" y="31" width="8" height="1" />
          <rect class="sc-note-ink" x="130" y="34" width="5" height="1" />
          <rect class="sc-note-2" x="144" y="22" width="12" height="12" />
          <rect class="sc-note-ink" x="146" y="26" width="7" height="1" />
          <rect class="sc-note-3" x="160" y="30" width="12" height="12" />
          <rect class="sc-note-ink" x="162" y="34" width="8" height="1" />
          <rect class="sc-note-ink" x="162" y="37" width="6" height="1" />

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
          <rect class="sc-plant" x="263" y="17" width="3" height="10" />
          <rect class="sc-plant-dark" x="258" y="21" width="6" height="3" />
          <rect class="sc-plant" x="266" y="19" width="7" height="3" />
          <rect class="sc-plant-dark" x="261" y="15" width="3" height="5" />
          <rect class="sc-frame" x="279" y="23" width="13" height="13" />
          <rect class="sc-photo" x="281" y="25" width="9" height="9" />
          <rect class="sc-claude" x="282" y="28" width="7" height="5" />
          <rect class="sc-photo" x="284" y="29" width="1" height="2" />
          <rect class="sc-photo" x="287" y="29" width="1" height="2" />
          <rect class="sc-wood" x="211" y="36" width="86" height="4" />
          <rect class="sc-wood-dark" x="211" y="40" width="86" height="1" />
          <rect class="sc-wood-dark" x="219" y="41" width="3" height="6" />
          <rect class="sc-wood-dark" x="286" y="41" width="3" height="6" />

          <!-- A rug, and a plant on the floor by the window. -->
          <rect class="sc-rug-edge" x="72" y="146" width="232" height="26" />
          <rect class="sc-rug" x="76" y="149" width="224" height="20" />
          <rect v-for="index in 13" :key="`rug${index}`" class="sc-rug-edge" :x="80 + index * 16" y="158" width="4" height="2" />
          <rect class="sc-plant" x="30" y="111" width="11" height="6" />
          <rect class="sc-plant-dark" x="43" y="103" width="8" height="15" />
          <rect class="sc-plant" x="52" y="109" width="12" height="6" />
          <rect class="sc-plant-dark" x="33" y="121" width="11" height="5" />
          <rect class="sc-plant" x="49" y="119" width="12" height="5" />
          <rect class="sc-plant-dark" x="45" y="115" width="3" height="24" />
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
          :mood="buddy.mood"
          :action="action"
          :beat="beat"
          :size="seat.size"
          :asleep="buddy.asleep"
          :gaze="buddy.gaze"
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

          <!-- A desk lamp, papers, the keyboard and the mouse. -->
          <rect class="sc-gear" x="95" y="97" width="12" height="3" />
          <rect class="sc-gear" x="99" y="91" width="2" height="6" />
          <rect class="sc-gear" x="99" y="85" width="2" height="6" />
          <rect class="sc-gear" x="101" y="79" width="2" height="6" />
          <rect class="sc-lamp" x="98" y="72" width="16" height="6" />
          <rect class="sc-bulb" x="101" y="78" width="11" height="1" />
          <rect class="sc-paper" x="108" y="98" width="12" height="2" />
          <rect class="sc-paper-shade" x="110" y="97" width="10" height="1" />
          <rect class="sc-gear" x="130" y="101" width="40" height="4" />
          <rect v-for="key in keys" :key="`k${key}`" class="sc-key" :x="132 + key * 4" y="102" width="3" height="1" />
          <rect v-for="key in keys" :key="`l${key}`" class="sc-key" :x="134 + key * 4" y="103" width="2" height="1" />
          <rect class="sc-mouse" x="176" y="101" width="6" height="3" />
          <rect class="sc-mouse-dark" x="178" y="101" width="2" height="1" />

          <!-- The monitor: the screen itself is the top layer. -->
          <rect class="sc-monitor-light" x="214" y="98" width="32" height="3" />
          <rect class="sc-monitor" x="226" y="88" width="8" height="11" />
          <rect class="sc-monitor" x="188" y="40" width="84" height="50" />
          <rect class="sc-monitor-light" x="188" y="40" width="84" height="2" />
          <rect class="sc-monitor-light" x="188" y="86" width="84" height="4" />
          <rect class="sc-led" x="265" y="87" width="3" height="1" />
          <rect class="sc-note-1" x="263" y="37" width="8" height="8" />

          <!-- A mug, steaming unless it sleeps. -->
          <rect class="sc-mug" x="282" y="91" width="9" height="9" />
          <rect class="sc-mug-dark" x="291" y="93" width="3" height="5" />
          <rect class="sc-mug-light" x="282" y="91" width="9" height="1" />
          <g class="sc-steam">
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

      <!-- The screen. -->
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
        </g>
      </svg>
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
.sc-photo { fill: #f6efe2; }
.sc-claude { fill: #d97757; }
.sc-wood { fill: var(--sc-wood); }
.sc-wood-dark { fill: var(--sc-wood-dark); }
.sc-chair { fill: var(--sc-chair); }
.sc-chair-light { fill: var(--sc-chair-light); }
.sc-chair-seam { fill: var(--sc-chair); opacity: 0.5; }
.sc-chair-shine { fill: rgba(255, 255, 255, 0.18); }
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
.agent-scene[data-state="asleep"] .sc-bulb { fill: #b9ab84; }
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
.agent-scene[data-state="asleep"] .sc-steam { display: none; }
.sc-dim { fill: var(--sc-dim); transition: fill 0.8s ease; }
.sc-glow { mix-blend-mode: screen; }
.sc-glow-in { stop-color: var(--sc-glow); transition: stop-color 0.8s ease; }
.sc-glow-out { stop-color: rgba(140, 205, 255, 0); }
.sc-lamp-glow { mix-blend-mode: screen; }
.sc-lamp-in { stop-color: var(--sc-lamp-glow); }
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
}

html[data-motion="reduced"] .agent-scene,
html[data-motion="reduced"] .agent-scene * {
  animation: none !important;
  transition: none !important;
}
html[data-motion="reduced"] .agent-scene .scene-camera {
  transform: none !important;
}
</style>
