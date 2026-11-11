<script setup lang="ts">
/**
 * Claude's helper on every page of the dashboard while AI is on (mounted in the shell's
 * `shell.panel` slot; AI › Agents has its own, and an agent's page its chibi at its desk, so it
 * stays away from both). It lives on the floor — the
 * phone's tab bar, else the bottom of the window — and every few seconds it acts in place (blinks,
 * winks, star eyes, thinks, little dances), strolls or moonwalks along the floor, or climbs onto a
 * card it can see, pokes it or sits on it, dances and comes back down. A new page: it walks in from
 * the side to join you. Nothing happening for 90 s: it dozes off, and wakes up surprised when you
 * are back. A late task makes it sweat; a finished one, cheer and dance. A mouse pointer coming
 * close sends it shyly aside; while it walks every tap goes through it. A tap: hearts (five quick
 * taps: dizzy); a long press: it waves goodbye and hides (buddyPrefs; the toast brings it back).
 * The page scrolling under it while it stands on a card: it jumps down. Still with reduced motion.
 *
 * It never covers what people press (buddySpace.ts): it only stands where nothing pressable, no
 * docked bar and no dialog is under its drawing, hopping up onto a save bar, a selection bar or a
 * chat's composer instead of standing in front of it; when the floor has no such place it peeks in
 * from the window's right edge, and when even that is taken it hides until there is room. Every
 * 0.7 s it looks again (a save bar slid up, a list scrolled under it) and steps aside, and it
 * hides while a dialog, sheet or drawer is open. Only its drawn pixels take taps, and only on a
 * spot it checked; it is drawn under docked bars, menus and dialogs, never over them.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { reducedMotion } from "@/components/chartOptions";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { useAiStatus } from "../api";
import {
  BUDDY_DANCES,
  BUDDY_DIZZY_TAPS,
  BUDDY_DIZZY_WINDOW_MS,
  BUDDY_DURATION,
  BUDDY_HOLD_MS,
  BUDDY_IDLE_SLEEP_MS,
  buddyBox,
  buddyWalkMs,
  figureBox,
  floorAt,
  planCompanion,
  shyStep,
  spotsFrom,
  standPoint,
  type Box,
  type BuddyAction,
} from "../lib";
import AiBuddy from "./AiBuddy.vue";
import { buddyCue } from "./buddyBus";
import { useBuddyCues } from "./buddyCues";
import { buddyEverywhere } from "./buddyPrefs";
import { dockedBars, overlayOpen, PRESSABLE, pressableBoxes, spotClear } from "./buddySpace";

const { t } = useI18n();
const route = useRoute();
const status = useAiStatus();
const { isPhone } = useBreakpoints();
const reduced = reducedMotion();

const size = computed(() => (isPhone.value ? 52 : 60));
const height = computed(() => buddyBox(size.value).height);
const OWN_CHIBI = new Set(["ai.agents", "ai.agent"]);
const shown = computed(() => buddyEverywhere.value && status.data.value?.enabled === true && !OWN_CHIBI.has(String(route.name)));
// Away from the Agents page it listens to the pulse only (late and finished tasks).
useBuddyCues(shown, { drafts: false, activity: false });

const action = ref<BuddyAction>("idle");
const beat = ref(0);
const position = ref({ x: -200, y: 0 });
const moveMs = ref(0);
const walking = ref(false);
const sitting = ref(false);
const asleep = ref(false);
const facing = ref<"left" | "right">("right");
/** Out of the way: a dialog is open, or there is nowhere clear to stand. */
const hidden = ref(false);
/** The spot it stands on was checked: nothing to press under it, so it may take taps. */
const clearHere = ref(false);
const layer = ref<HTMLElement | null>(null);
const GUARD_MS = 700;
const TOP_GAP = 64; // below the top bar

const timers = new Set<ReturnType<typeof setTimeout>>();
let alive = true;
let trip = 0; // goes up when a walk starts or is called off; an old walk stops at its next step
let travelling = false;
const onCard = ref(false); // up on a card: taps go through it, as while it walks
const tappable = computed(() => !walking.value && !onCard.value && clearHere.value && !hidden.value);
let lastActivity = Date.now();
let lastNoted = 0;
let lastShy = 0;
let taps: number[] = [];
let holdTimer: ReturnType<typeof setTimeout> | null = null;
let held = false;

function later(fn: () => void, ms: number): void {
  const timer = setTimeout(() => {
    timers.delete(timer);
    fn();
  }, ms);
  timers.add(timer);
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => later(resolve, ms));
}

function act(name: BuddyAction): void {
  action.value = name;
  beat.value += 1;
  const current = beat.value;
  later(() => {
    if (beat.value === current) action.value = "idle";
  }, BUDDY_DURATION[name]);
}

function randomDance(): BuddyAction {
  return BUDDY_DANCES[Math.floor(Math.random() * BUDDY_DANCES.length)]!;
}

/** The stretch of floor it walks on: the page's content, above the phone's tab bar. `feet` is
 * the floor's line, `floor` where its top is when it stands there. */
function lane(): { min: number; max: number; floor: number; feet: number } {
  const rect = document.querySelector("main")?.getBoundingClientRect();
  const left = rect ? Math.max(rect.left, 0) : 0;
  const right = rect && rect.width > 0 ? Math.min(rect.right, window.innerWidth) : window.innerWidth;
  const bar = isPhone.value ? (document.querySelector("nav.fixed.bottom-0")?.getBoundingClientRect().top ?? null) : null;
  const feet = Math.round(bar ?? window.innerHeight - 10);
  return {
    min: Math.round(left + 8),
    max: Math.round(Math.max(left + 8, right - size.value - 8)),
    floor: feet - buddyBox(size.value).feet,
    feet,
  };
}

function randomX(): number {
  const { min, max } = lane();
  return Math.round(min + Math.random() * (max - min));
}

type Spot = { x: number; y: number; peek?: boolean };

/** What its drawing would cover at a spot (a peek only shows its part inside the window). */
function figureAt(spot: Spot): Box {
  const figure = figureBox(spot.x, spot.y, size.value);
  if (!spot.peek) return figure;
  return { ...figure, width: Math.max(0, window.innerWidth - 1 - figure.left) };
}

function clearAt(spot: Spot, pressable?: readonly Box[]): boolean {
  return spot.y >= TOP_GAP && spotClear(figureAt(spot), layer.value, pressable ?? pressableBoxes(layer.value));
}

/** The nearest clear place on the floor to `x` (up on a docked bar where one is), else a peek in
 * from the window's right edge, else none. */
function findSpot(x: number): Spot | null {
  const { min, max, feet } = lane();
  const bars = dockedBars(feet, min, max + size.value, layer.value);
  const pressable = pressableBoxes(layer.value);
  const tall = buddyBox(size.value).feet;
  for (const left of spotsFrom(x, min, max)) {
    const spot = { x: left, y: floorAt(feet, bars, left, size.value) - tall };
    if (clearAt(spot, pressable)) return spot;
  }
  const edge = window.innerWidth - Math.round(size.value * 0.45);
  const peek = { x: edge, y: floorAt(feet, bars, edge, size.value) - tall, peek: true };
  return clearAt(peek, pressable) ? peek : null;
}

/** Straight to a spot (reduced motion, or a new window size). */
function place(spot: Spot): void {
  moveMs.value = 0;
  walking.value = false;
  position.value = { x: spot.x, y: spot.y };
}

/** Where it settles: it looks once more before it takes taps. */
function settle(spot: Spot): void {
  if (spot.peek) facing.value = "left";
  clearHere.value = clearAt({ ...position.value, peek: spot.peek });
}

/** Out of the way until there is room (or the dialog closes). */
function hide(): void {
  trip += 1;
  travelling = false;
  walking.value = false;
  onCard.value = false;
  sitting.value = false;
  clearHere.value = false;
  hidden.value = true;
}

/** Reduced motion: it stands still at the right end of the floor, or the nearest clear place. */
function stayStill(): void {
  const spot = overlayOpen() ? null : findSpot(lane().max);
  if (!spot) return hide();
  hidden.value = false;
  place(spot);
  settle(spot);
}

async function walkTo(point: { x: number; y: number }, id: number, backwards = false): Promise<boolean> {
  if (id !== trip || !alive) return false;
  const from = position.value;
  if (point.x !== from.x) {
    const right = point.x > from.x;
    facing.value = right !== backwards ? "right" : "left";
  }
  moveMs.value = Math.round(buddyWalkMs(point.x - from.x, point.y - from.y) * (backwards ? 1.4 : 1));
  sitting.value = false;
  walking.value = true;
  position.value = point;
  await wait(moveMs.value);
  walking.value = false;
  return id === trip && alive;
}

/** It comes onto the page from the left edge: a new page, and it came along. */
async function enter(): Promise<void> {
  const id = (trip += 1);
  onCard.value = false;
  asleep.value = false;
  clearHere.value = false;
  const spot = overlayOpen() ? null : findSpot(randomX());
  if (!spot) return hide();
  hidden.value = false;
  travelling = true;
  moveMs.value = 0;
  position.value = { x: lane().min - size.value - 24, y: spot.y };
  await nextTick();
  await wait(30); // the start is painted before the walk, so the walk animates
  if (await walkTo(spot, id)) {
    settle(spot);
    act(spot.peek || Math.random() < 0.5 ? "look" : "wave");
  }
  if (id === trip) travelling = false;
}

/** What counts as a card: the shared card component, and any bordered, rounded surface. */
const LANDMARKS = ".ui-card, .rounded-card, [class*='rounded-'][class*='bg-surface'][class*='border']";

/** Cards on the page it can climb: on screen, clear of the top bar and the floor, big enough. */
function visibleCards(): HTMLElement[] {
  const main = document.querySelector("main");
  if (!main) return [];
  const { floor } = lane();
  const { feet } = buddyBox(size.value);
  return Array.from(main.querySelectorAll<HTMLElement>(LANDMARKS)).filter((card) => {
    // A dialog's card, or a button dressed as a card (a suggestion chip): not something to climb.
    if (card.closest('[role="dialog"]') || card.closest(PRESSABLE)) return false;
    const rect = card.getBoundingClientRect();
    return rect.width > size.value + 40 && rect.height >= 56 && rect.top - feet > 64 && rect.top < floor - 40 && rect.left >= 0 && rect.right <= window.innerWidth;
  });
}

async function down(id: number): Promise<void> {
  const spot = findSpot(randomX());
  if (!spot) {
    if (id === trip) hide();
    return;
  }
  if (await walkTo(spot, id)) {
    onCard.value = false;
    settle(spot);
  }
  if (id === trip) travelling = false;
}

/** A clear place on a card's top edge (a few tries along it), or none. */
function cardSpot(card: HTMLElement, sit: boolean): Spot | null {
  const rect = card.getBoundingClientRect();
  const screen = { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  const pressable = pressableBoxes(layer.value);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const spot = standPoint({ left: rect.left, top: rect.top, width: rect.width, height: rect.height }, screen, size.value, Math.random(), sit);
    if (clearAt(spot, pressable)) return spot;
  }
  return null;
}

async function visit(card: HTMLElement): Promise<void> {
  const sit = Math.random() < 0.35;
  const spot = cardSpot(card, sit);
  if (!spot) return; // something to press above it: not this card
  const id = (trip += 1);
  travelling = true;
  clearHere.value = false;
  if (!(await walkTo(spot, id))) {
    if (id === trip) travelling = false;
    return;
  }
  onCard.value = true;
  sitting.value = sit;
  card.dataset.buddyPoke = "";
  later(() => delete card.dataset.buddyPoke, 650);
  act(sit ? "love" : "touch");
  await wait(1100);
  if (id !== trip) return;
  act(sit ? "wink" : randomDance());
  await wait(1800);
  if (id !== trip) return;
  await down(id);
}

async function stroll(moonwalk = false): Promise<void> {
  const { min, max } = lane();
  let x = randomX();
  if (moonwalk && Math.abs(x - position.value.x) < 120) x = position.value.x - min > max - position.value.x ? min : max;
  const spot = findSpot(x);
  if (!spot || (spot.x === position.value.x && spot.y === position.value.y)) return;
  const id = (trip += 1);
  travelling = true;
  clearHere.value = false;
  if (await walkTo(spot, id, moonwalk)) {
    settle(spot);
    act(moonwalk ? "star" : (["wave", "look", "wink", "hearts"] as const)[Math.floor(Math.random() * 4)]!);
  }
  if (id === trip) travelling = false;
}

/** Something came under it (a save bar slid up, a list scrolled, a menu opened): it steps to the
 * nearest clear place, or hides. */
async function stepAside(): Promise<void> {
  const spot = findSpot(position.value.x);
  if (!spot) return hide();
  const id = (trip += 1);
  onCard.value = false;
  asleep.value = false;
  clearHere.value = false;
  if (reduced) {
    place(spot);
    settle(spot);
    return;
  }
  travelling = true;
  act("shy");
  if (await walkTo(spot, id)) settle(spot);
  if (id === trip) travelling = false;
}

/** No room on the floor (a page full of things to press): now and then it pops up on a card's
 * clear top edge, waves and dances, and goes again. */
async function popIn(): Promise<void> {
  const cards = visibleCards();
  if (!cards.length) return;
  const sit = Math.random() < 0.35;
  const spot = cardSpot(cards[Math.floor(Math.random() * cards.length)]!, sit);
  if (!spot) return;
  const id = (trip += 1);
  travelling = true;
  place(spot);
  facing.value = "right";
  sitting.value = sit;
  onCard.value = true;
  await nextTick();
  hidden.value = false; // it fades in where it stands, without crossing the page
  act("wave");
  await wait(1600);
  if (id !== trip) return;
  act(sit ? "wink" : randomDance());
  await wait(1800);
  if (id !== trip) return;
  await down(id);
}

/** It looks under itself every GUARD_MS: out of the way of dialogs, aside from what came under
 * it, back once there is room again (looking for room is the costly part: every third round),
 * or popping up on a card now and then (every 18th) while there is none. */
let rounds = 0;
function guard(): void {
  rounds += 1;
  if (alive && shown.value && !document.hidden) {
    if (overlayOpen()) {
      if (!hidden.value) hide();
    } else if (hidden.value) {
      if (rounds % 3 === 0 && reduced) stayStill();
      else if (rounds % 3 === 0 && !travelling && findSpot(randomX())) void enter();
      else if (rounds % 18 === 0 && !travelling && !reduced) void popIn();
    } else if (!walking.value && !travelling) {
      const clear = clearAt({ ...position.value, peek: position.value.x > window.innerWidth - size.value });
      clearHere.value = clear && !onCard.value;
      if (!clear) void stepAside();
    }
  }
  later(guard, GUARD_MS);
}

function tick(): void {
  if (alive && shown.value && !document.hidden && !travelling) {
    if (Date.now() - lastActivity > BUDDY_IDLE_SLEEP_MS) {
      if (onCard.value) void down((trip += 1));
      else if (!asleep.value) asleep.value = true;
    } else if (!asleep.value) {
      const cards = visibleCards();
      const plan = planCompanion(cards.length, Math.random);
      if (plan.kind === "visit") void visit(cards[plan.card]!);
      else if (plan.kind === "stroll") void stroll();
      else if (plan.kind === "moonwalk") void stroll(true);
      else act(plan.action);
    }
  }
  later(tick, 3000 + Math.random() * 3500);
}

/** Someone is here: a sleeping helper wakes up surprised, then glad. */
function noteActivity(): void {
  const now = Date.now();
  if (now - lastNoted < 500) return;
  lastNoted = now;
  lastActivity = now;
  if (asleep.value) {
    asleep.value = false;
    act("wide");
    later(() => act("hearts"), BUDDY_DURATION.wide + 100);
  }
}

function onPointerMove(event: PointerEvent): void {
  noteActivity();
  if (event.pointerType !== "mouse" || travelling || onCard.value || asleep.value || !shown.value || reduced) return;
  const now = Date.now();
  if (now - lastShy < 2500) return;
  const middleX = position.value.x + size.value / 2;
  const middleY = position.value.y + height.value / 2;
  if (Math.hypot(event.clientX - middleX, event.clientY - middleY) > 70) return;
  lastShy = now;
  const { min, max } = lane();
  const spot = findSpot(shyStep(position.value.x, event.clientX, min, max));
  if (!spot) return;
  const id = (trip += 1);
  travelling = true;
  clearHere.value = false;
  act("shy");
  void walkTo(spot, id).then((arrived) => {
    if (arrived) settle(spot);
    if (id === trip) travelling = false;
  });
}

/** The page scrolled under it while it stood on a card: it jumps back down. */
function onScroll(): void {
  noteActivity();
  if (!onCard.value) {
    clearHere.value = false; // the page moved under it: no taps until it has looked again
    return;
  }
  onCard.value = false;
  act("wide");
  travelling = true;
  void down((trip += 1));
}

function onResize(): void {
  trip += 1;
  travelling = false;
  onCard.value = false;
  walking.value = false;
  if (hidden.value) return;
  const spot = findSpot(position.value.x);
  if (!spot) return hide();
  place(spot);
  settle(spot);
}

function onTap(): void {
  if (held) {
    held = false;
    return;
  }
  const now = Date.now();
  taps = [...taps.filter((time) => now - time < BUDDY_DIZZY_WINDOW_MS), now];
  if (taps.length >= BUDDY_DIZZY_TAPS) {
    taps = [];
    act("dizzy");
  } else act("tap");
  window.Telegram?.WebApp?.HapticFeedback?.impactOccurred("light");
}

function pressStart(): void {
  held = false;
  holdTimer = setTimeout(() => {
    held = true;
    void goodbye();
  }, BUDDY_HOLD_MS);
}

function pressEnd(): void {
  if (holdTimer) clearTimeout(holdTimer);
  holdTimer = null;
}

/** A long press: it waves goodbye, walks off, and stays away until switched on again. */
async function goodbye(): Promise<void> {
  const id = (trip += 1);
  travelling = true;
  act("bye");
  await wait(BUDDY_DURATION.bye);
  await walkTo({ x: window.innerWidth + 24, y: position.value.y }, id);
  buddyEverywhere.value = false;
  travelling = false;
  toast.info(t("ai.buddy.hidden"), { action: { label: t("ai.buddy.bringBack"), onClick: () => (buddyEverywhere.value = true) }, duration: 6000 });
}

// What happens in the company: a finished task, a cheer and a dance; a late one, a sweat.
watch(buddyCue, (next) => {
  if (!next || !shown.value || reduced) return;
  if (next.key === "" && next.action === "cheer") {
    act("cheer");
    later(() => act(randomDance()), BUDDY_DURATION.cheer + 100);
  } else if (next.key === "deadline_watcher" && next.action === "ring") act("sweat");
});

// Shown (AI on, switched on, off the Agents page) or a new page: it walks in from the side.
watch(shown, (visible) => {
  if (!visible) {
    trip += 1;
    travelling = false;
    onCard.value = false;
    return;
  }
  if (reduced) stayStill();
  else void enter();
});
watch(
  () => route.path,
  () => {
    if (shown.value && !reduced) void enter();
  },
);

onMounted(() => {
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  window.addEventListener("pointerdown", noteActivity, { passive: true });
  window.addEventListener("keydown", noteActivity);
  window.addEventListener("scroll", onScroll, { capture: true, passive: true });
  window.addEventListener("resize", onResize);
  if (shown.value) {
    if (reduced) stayStill();
    else void enter();
  }
  if (!reduced) later(tick, 2500);
  later(guard, GUARD_MS);
});
onBeforeUnmount(() => {
  alive = false;
  window.removeEventListener("pointermove", onPointerMove);
  window.removeEventListener("pointerdown", noteActivity);
  window.removeEventListener("keydown", noteActivity);
  window.removeEventListener("scroll", onScroll, { capture: true });
  window.removeEventListener("resize", onResize);
  pressEnd();
  for (const timer of timers) clearTimeout(timer);
  timers.clear();
});

defineExpose({ visit, stroll, act, enter, goodbye });
</script>

<template>
  <!-- Drawn under docked bars (z-index 2 and up), menus, sheets and dialogs, over the page itself. -->
  <div
    v-if="shown"
    ref="layer"
    :class="['pointer-events-none fixed inset-0 z-[1] transition-opacity duration-200', hidden && 'opacity-0']"
    :data-hidden="hidden || undefined"
    :aria-hidden="hidden || undefined"
    data-testid="ai-buddy-companion"
  >
    <div
      :class="['buddy-walker absolute left-0 top-0 will-change-transform', tappable ? 'pointer-events-auto' : 'pointer-events-none']"
      :style="{ transform: `translate(${position.x}px, ${position.y}px)`, transition: moveMs ? `transform ${moveMs}ms linear` : 'none' }"
      data-testid="ai-buddy-walker"
      @pointerdown="pressStart"
      @pointerup="pressEnd"
      @pointerleave="pressEnd"
      @pointercancel="pressEnd"
      @contextmenu.prevent
    >
      <AiBuddy
        mood="on"
        :action="action"
        :beat="beat"
        :size="size"
        :walking="walking"
        :facing="facing"
        :sitting="sitting"
        :asleep="asleep && action === 'idle'"
        :label="t('ai.buddy.companionLabel')"
        @tap="onTap"
      />
    </div>
  </div>
</template>

<style scoped>
.buddy-walker {
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  touch-action: manipulation;
}
/* Only its drawn pixels take a tap: the empty corners of its box let it through. */
.buddy-walker.pointer-events-auto :deep(.ai-buddy) {
  pointer-events: none;
}
.buddy-walker.pointer-events-auto :deep(.buddy-figure) {
  pointer-events: visiblePainted;
}
</style>
