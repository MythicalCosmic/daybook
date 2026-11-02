<script setup lang="ts">
/**
 * Claude's helper on every page of the dashboard while AI is on (mounted in the shell's
 * `shell.panel` slot; AI › Agents has its own, so it stays away there). It lives on the floor — the
 * phone's tab bar, else the bottom of the window — and every few seconds it acts in place (blinks,
 * winks, star eyes, thinks, little dances), strolls or moonwalks along the floor, or climbs onto a
 * card it can see, pokes it or sits on it, dances and comes back down. A new page: it walks in from
 * the side to join you. Nothing happening for 90 s: it dozes off, and wakes up surprised when you
 * are back. A late task makes it sweat; a finished one, cheer and dance. A mouse pointer coming
 * close sends it shyly aside; while it walks every tap goes through it. A tap: hearts (five quick
 * taps: dizzy); a long press: it waves goodbye and hides (buddyPrefs; the toast brings it back).
 * The page scrolling under it while it stands on a card: it jumps down. Still with reduced motion.
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
  floorY,
  planCompanion,
  shyStep,
  standPoint,
  type BuddyAction,
} from "../lib";
import AiBuddy from "./AiBuddy.vue";
import { buddyCue } from "./buddyBus";
import { useBuddyCues } from "./buddyCues";
import { buddyEverywhere } from "./buddyPrefs";

const { t } = useI18n();
const route = useRoute();
const status = useAiStatus();
const { isPhone } = useBreakpoints();
const reduced = reducedMotion();

const size = computed(() => (isPhone.value ? 52 : 60));
const height = computed(() => buddyBox(size.value).height);
const shown = computed(() => buddyEverywhere.value && status.data.value?.enabled === true && route.name !== "ai.agents");
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

const timers = new Set<ReturnType<typeof setTimeout>>();
let alive = true;
let trip = 0; // goes up when a walk starts or is called off; an old walk stops at its next step
let travelling = false;
const onCard = ref(false); // up on a card: taps go through it, as while it walks
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

/** The stretch of floor it walks on: the page's content, above the phone's tab bar. */
function lane(): { min: number; max: number; floor: number } {
  const rect = document.querySelector("main")?.getBoundingClientRect();
  const left = rect ? Math.max(rect.left, 0) : 0;
  const right = rect && rect.width > 0 ? Math.min(rect.right, window.innerWidth) : window.innerWidth;
  const bar = isPhone.value ? (document.querySelector("nav.fixed.bottom-0")?.getBoundingClientRect().top ?? null) : null;
  return {
    min: Math.round(left + 8),
    max: Math.round(Math.max(left + 8, right - size.value - 8)),
    floor: floorY(window.innerHeight, bar, size.value),
  };
}

function randomX(): number {
  const { min, max } = lane();
  return Math.round(min + Math.random() * (max - min));
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
  travelling = true;
  onCard.value = false;
  asleep.value = false;
  const { min, floor } = lane();
  moveMs.value = 0;
  position.value = { x: min - size.value - 24, y: floor };
  await nextTick();
  await wait(30); // the start is painted before the walk, so the walk animates
  if (await walkTo({ x: randomX(), y: floor }, id)) act(Math.random() < 0.5 ? "wave" : "look");
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
    if (card.closest('[role="dialog"]')) return false;
    const rect = card.getBoundingClientRect();
    return rect.width > size.value + 40 && rect.height >= 56 && rect.top - feet > 64 && rect.top < floor - 40 && rect.left >= 0 && rect.right <= window.innerWidth;
  });
}

async function down(id: number): Promise<void> {
  if (await walkTo({ x: randomX(), y: lane().floor }, id)) onCard.value = false;
  if (id === trip) travelling = false;
}

async function visit(card: HTMLElement): Promise<void> {
  const id = (trip += 1);
  travelling = true;
  const rect = card.getBoundingClientRect();
  const sit = Math.random() < 0.35;
  const screen = { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  const spot = standPoint({ left: rect.left, top: rect.top, width: rect.width, height: rect.height }, screen, size.value, Math.random(), sit);
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
  const id = (trip += 1);
  travelling = true;
  const { min, max, floor } = lane();
  let x = randomX();
  if (moonwalk && Math.abs(x - position.value.x) < 120) x = position.value.x - min > max - position.value.x ? min : max;
  if (await walkTo({ x, y: floor }, id, moonwalk)) act(moonwalk ? "star" : (["wave", "look", "wink", "hearts"] as const)[Math.floor(Math.random() * 4)]!);
  if (id === trip) travelling = false;
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
  const id = (trip += 1);
  travelling = true;
  act("shy");
  const { min, max, floor } = lane();
  void walkTo({ x: shyStep(position.value.x, event.clientX, min, max), y: floor }, id).then(() => {
    if (id === trip) travelling = false;
  });
}

/** The page scrolled under it while it stood on a card: it jumps back down. */
function onScroll(): void {
  noteActivity();
  if (!onCard.value) return;
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
  moveMs.value = 0;
  const { min, max, floor } = lane();
  position.value = { x: Math.min(max, Math.max(min, position.value.x)), y: floor };
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
  await walkTo({ x: window.innerWidth + 24, y: lane().floor }, id);
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
  if (reduced) {
    const { max, floor } = lane();
    position.value = { x: max, y: floor };
  } else void enter();
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
    if (reduced) {
      const { max, floor } = lane();
      position.value = { x: max, y: floor };
    } else void enter();
  }
  if (!reduced) later(tick, 2500);
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
  <div v-if="shown" class="pointer-events-none fixed inset-0 z-[35]" data-testid="ai-buddy-companion">
    <div
      :class="['buddy-walker absolute left-0 top-0 will-change-transform', walking || onCard ? 'pointer-events-none' : 'pointer-events-auto']"
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
</style>
