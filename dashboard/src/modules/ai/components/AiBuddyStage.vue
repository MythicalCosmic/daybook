<script setup lang="ts">
/**
 * Where the AI's helper lives on the Agents page while AI is on: a strip with its home spot and a
 * line on what the AI is doing (the default slot), and an invisible layer over the whole page it
 * walks on. Every few seconds it acts in place, strolls along its strip, or walks to an agent card
 * it can see, stands or sits on its top edge and pokes it (the card bounces), then walks home.
 * While an agent runs it prefers that card and types there. Away from home every tap goes through
 * it (it never covers a button); at home a tap makes it hop with hearts. Pauses while the tab is hidden, goes home when
 * the window resizes, and stays home and still with reduced motion.
 *
 * The page's root must be `position: relative` (the layer is `absolute inset-0` in it), and its
 * agent cards carry the class `ai-agent-card` (`is-running` while they run).
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import { reducedMotion } from "@/components/chartOptions";

import AiBuddy from "./AiBuddy.vue";
import { greet } from "./buddyBus";
import { BUDDY_DURATION, buddyBox, buddyWalkMs, planBuddy, standPoint, type Box, type BuddyAction, type BuddyMood } from "../lib";

const props = withDefaults(defineProps<{ mood: BuddyMood; size?: number }>(), { size: 76 });

const home = ref<HTMLElement | null>(null);
const strip = ref<HTMLElement | null>(null);
const layer = ref<HTMLElement | null>(null);

const action = ref<BuddyAction>("idle");
const beat = ref(0);
const away = ref(false);
const walking = ref(false);
const sitting = ref(false);
const facing = ref<"left" | "right">("right");
const position = ref({ x: 0, y: 0 });
const moveMs = ref(0);

const reduced = reducedMotion();
const timers = new Set<ReturnType<typeof setTimeout>>();
let trip = 0; // goes up when a trip starts or is called off; an old trip stops at its next step
let travelling = false;
let alive = true;

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

function box(element: Element): Box {
  const rect = element.getBoundingClientRect();
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

function root(): HTMLElement | null {
  return layer.value?.parentElement ?? null;
}

function homePoint(): { x: number; y: number } {
  const page = root();
  if (!home.value || !page) return { x: 0, y: 0 };
  const spot = box(home.value);
  const base = box(page);
  return { x: Math.round(spot.left - base.left), y: Math.round(spot.top - base.top) };
}

/** The agent cards it can see whole enough to stand on: on screen, below the top bar, wide enough. */
function visibleCards(): HTMLElement[] {
  const page = root();
  if (!page) return [];
  const { feet } = buddyBox(props.size);
  return Array.from(page.querySelectorAll<HTMLElement>(".ai-agent-card")).filter((card) => {
    const rect = card.getBoundingClientRect();
    return rect.width > props.size + 32 && rect.top - feet > 56 && rect.top < window.innerHeight - 48;
  });
}

async function leaveHome(): Promise<void> {
  moveMs.value = 0;
  position.value = homePoint();
  facing.value = "right";
  away.value = true;
  await nextTick();
  await wait(30); // the start is painted before the walk begins, so the move animates
}

async function walkTo(point: { x: number; y: number }, id: number): Promise<boolean> {
  if (id !== trip || !alive) return false;
  const from = position.value;
  if (point.x !== from.x) facing.value = point.x < from.x ? "left" : "right";
  moveMs.value = buddyWalkMs(point.x - from.x, point.y - from.y);
  sitting.value = false;
  walking.value = true;
  position.value = point;
  await wait(moveMs.value);
  walking.value = false;
  return id === trip && alive;
}

async function goHome(id: number): Promise<void> {
  if (await walkTo(homePoint(), id)) {
    away.value = false;
    facing.value = "right";
  }
  travelling = false;
}

function poke(card: HTMLElement): void {
  if (card.dataset.agent) greet(card.dataset.agent);
  card.dataset.buddyPoke = "";
  later(() => delete card.dataset.buddyPoke, 650);
}

async function visit(card: HTMLElement): Promise<void> {
  const id = (trip += 1);
  travelling = true;
  await leaveHome();
  const page = root();
  if (!page) return void (travelling = false);
  const sit = Math.random() < 0.35;
  if (!(await walkTo(standPoint(box(card), box(page), props.size, Math.random(), sit), id))) return void (travelling = false);
  sitting.value = sit;
  const working = card.classList.contains("is-running");
  poke(card);
  act(working ? "type" : "touch");
  await wait(working ? BUDDY_DURATION.type : BUDDY_DURATION.touch + 200);
  if (id !== trip) return void (travelling = false);
  act(Math.random() < 0.5 ? "love" : "hearts");
  await wait(1700);
  await goHome(id);
}

async function stroll(): Promise<void> {
  const id = (trip += 1);
  travelling = true;
  await leaveHome();
  const page = root();
  if (!strip.value || !page) return void (travelling = false);
  const lane = box(strip.value);
  const base = box(page);
  const x = Math.round(lane.left - base.left + 8 + Math.random() * Math.max(0, lane.width - props.size - 16));
  if (!(await walkTo({ x, y: homePoint().y }, id))) return void (travelling = false);
  act((["wave", "hearts", "look", "dance"] as const)[Math.floor(Math.random() * 4)]!);
  await wait(1500);
  await goHome(id);
}

function tick(): void {
  if (!travelling && !document.hidden) {
    let cards = visibleCards();
    if (props.mood === "busy") {
      const running = cards.filter((card) => card.classList.contains("is-running"));
      if (running.length) cards = running;
    }
    const plan = planBuddy(props.mood, cards.length, Math.random);
    if (plan.kind === "visit") void visit(cards[plan.card]!);
    else if (plan.kind === "stroll") void stroll();
    else act(plan.action);
  }
  later(tick, 2600 + Math.random() * 2600);
}

/** The window changed size: the places it was heading for moved, so it goes straight home. */
function callOff(): void {
  trip += 1;
  travelling = false;
  walking.value = false;
  sitting.value = false;
  away.value = false;
}

function tap(): void {
  act("tap");
  window.Telegram?.WebApp?.HapticFeedback?.impactOccurred("light");
}

onMounted(() => {
  window.addEventListener("resize", callOff);
  if (!reduced) later(tick, 1500);
});
onBeforeUnmount(() => {
  alive = false;
  window.removeEventListener("resize", callOff);
  for (const timer of timers) clearTimeout(timer);
  timers.clear();
  for (const card of root()?.querySelectorAll<HTMLElement>("[data-buddy-poke]") ?? []) delete card.dataset.buddyPoke;
});

defineExpose({ visit, stroll, act, callOff });
</script>

<template>
  <section ref="strip" class="flex items-center gap-4 rounded-card border border-line bg-surface px-4 py-3 md:px-5" data-testid="ai-buddy-strip">
    <div ref="home" class="shrink-0" :style="{ width: `${size}px`, height: `${buddyBox(size).height}px` }">
      <AiBuddy v-if="!away" :mood="mood" :action="action" :beat="beat" :size="size" @tap="tap" />
    </div>
    <div class="min-w-0 flex-1">
      <slot />
    </div>
  </section>
  <div ref="layer" class="pointer-events-none absolute inset-0 z-[5]" data-testid="ai-buddy-layer">
    <div
      v-if="away"
      class="absolute left-0 top-0 will-change-transform"
      :style="{ transform: `translate(${position.x}px, ${position.y}px)`, transition: moveMs ? `transform ${moveMs}ms linear` : 'none' }"
      data-testid="ai-buddy-traveller"
    >
      <AiBuddy :mood="mood" :action="action" :beat="beat" :size="size" :walking="walking" :facing="facing" :sitting="sitting" @tap="tap" />
    </div>
  </div>
</template>

<style>
/* A card the helper pokes gives a little bounce and a warm glow. */
.ai-agent-card[data-buddy-poke] {
  animation: ai-buddy-poke 0.6s ease-out;
}
@keyframes ai-buddy-poke {
  0% { transform: translateY(0); }
  30% { transform: translateY(2px); box-shadow: 0 0 0 2px rgb(217 119 87 / 0.45); }
  60% { transform: translateY(-1px); }
  100% { transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .ai-agent-card[data-buddy-poke] { animation: none; }
}
</style>
