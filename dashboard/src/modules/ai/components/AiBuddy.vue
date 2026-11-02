<script setup lang="ts">
/**
 * The AI's little helpers, drawn: a pixel creature (no image file) in five looks — Claude itself
 * (orange) and one chibi per agent: voice tasks (violet, headphones and a mic), morning plan
 * (yellow, a rising sun on its head), deadline watcher (red, an alarm clock on its head) and photo
 * checker (teal, round glasses). Expressions: open eyes, a blink, a look around, ^ ^ when happy,
 * heart eyes, closed eyes asleep. Moves: breathing, hop, wave, dance, typing, a poke, walking,
 * sitting, listening (sound waves), ringing (the prop shakes, red "!"), cheering (arms up); it lets
 * out hearts, sparkles, or a z now and then while asleep. AiBuddyStage.vue and
 * AgentChibi.vue decide what it does; this only draws it. Hearts, sparkles and z's are drawn
 * pixels, never emoji characters; with reduced motion nothing moves or floats.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { reducedMotion } from "@/components/chartOptions";

import { BUDDY_PARTICLES, type BuddyAction, type BuddyMood, type BuddyParticle, type BuddyVariant } from "../lib";

const props = withDefaults(
  defineProps<{
    mood: BuddyMood;
    variant?: BuddyVariant;
    action?: BuddyAction;
    /** Goes up with every new action, so the same action twice in a row still lets out its hearts. */
    beat?: number;
    size?: number;
    walking?: boolean;
    facing?: "left" | "right";
    sitting?: boolean;
    asleep?: boolean;
    /** What a screen reader says for it (Claude's own words by default). */
    label?: string;
  }>(),
  { variant: "claude", action: "idle", beat: 0, size: 88, walking: false, facing: "right", sitting: false, asleep: false, label: "" },
);
const emit = defineEmits<{ tap: [] }>();

const { t } = useI18n();
type Particle = { id: number; kind: BuddyParticle; x: number; delay: number };
const particles = ref<Particle[]>([]);
const lookRight = ref(false);
const reduced = reducedMotion();
const timers = new Set<ReturnType<typeof setTimeout>>();
let nextId = 0;

function later(fn: () => void, ms: number): void {
  const timer = setTimeout(() => {
    timers.delete(timer);
    fn();
  }, ms);
  timers.add(timer);
}

const eyes = computed(() => {
  switch (props.action) {
    case "blink":
      return "blink";
    case "hearts":
    case "tap":
    case "listen":
    case "cheer":
      return "happy";
    case "love":
      return "love";
    case "look":
      return lookRight.value ? "right" : "left";
    default:
      return props.asleep ? "asleep" : "open";
  }
});
const eyeShift = computed(() => (eyes.value === "left" ? -2 : eyes.value === "right" ? 2 : 0));
const blush = computed(() => eyes.value === "happy" || eyes.value === "love");
const height = computed(() => Math.round((props.size * 34) / 36));

function spawn(kind: Particle["kind"], count: number): void {
  if (reduced) return;
  for (let index = 0; index < count; index += 1) {
    const particle = { id: (nextId += 1), kind, x: kind === "z" ? 10 + index * 6 : Math.round((Math.random() - 0.5) * 56), delay: index * 140 };
    particles.value = [...particles.value, particle];
    later(() => (particles.value = particles.value.filter((item) => item.id !== particle.id)), 1700 + particle.delay);
  }
}

watch(
  () => props.beat,
  () => {
    if (props.action === "look") {
      lookRight.value = false;
      later(() => (lookRight.value = true), 700);
    }
    const burst = BUDDY_PARTICLES[props.action];
    if (burst) spawn(burst.kind, burst.count);
  },
);

/** Asleep, it breathes out a z every few seconds. */
function snore(): void {
  if (!props.asleep) return;
  if (!document.hidden) spawn("z", 1);
  later(snore, 2800);
}
watch(
  () => props.asleep,
  (asleep) => {
    if (asleep && !reduced) later(snore, 900);
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  for (const timer of timers) clearTimeout(timer);
  timers.clear();
});
</script>

<template>
  <button
    type="button"
    class="ai-buddy relative block shrink-0 rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-accent"
    :style="{ width: `${size}px`, height: `${height}px` }"
    :data-variant="variant"
    :data-mood="mood"
    :data-action="action"
    :data-walking="walking || undefined"
    :data-sitting="sitting || undefined"
    :data-asleep="asleep || undefined"
    :aria-label="label || t('ai.buddy.label')"
    data-testid="ai-buddy"
    @click="emit('tap')"
  >
    <svg viewBox="0 -6 36 34" shape-rendering="crispEdges" class="block h-full w-full overflow-visible" :style="facing === 'left' ? { transform: 'scaleX(-1)' } : undefined" aria-hidden="true">
      <rect class="buddy-shadow" x="7" y="25" width="22" height="2" />
      <g class="buddy-figure">
        <rect class="buddy-limb buddy-arm-left" x="2" y="9" width="4" height="5" />
        <rect class="buddy-limb buddy-arm-right" x="30" y="9" width="4" height="5" />
        <rect class="buddy-limb buddy-leg buddy-leg-a" x="8" y="18" width="3" height="6" />
        <rect class="buddy-limb buddy-leg buddy-leg-b" x="13" y="18" width="3" height="6" />
        <rect class="buddy-limb buddy-leg buddy-leg-a" x="20" y="18" width="3" height="6" />
        <rect class="buddy-limb buddy-leg buddy-leg-b" x="25" y="18" width="3" height="6" />
        <rect class="buddy-body" x="6" y="2" width="24" height="16" />
        <rect class="buddy-light" x="6" y="2" width="24" height="1" />
        <rect class="buddy-shade" x="6" y="16" width="24" height="2" />

        <g v-if="eyes === 'open' || eyes === 'left' || eyes === 'right'" class="buddy-eyes" :transform="`translate(${eyeShift} 0)`" data-eyes="open">
          <rect x="11" y="7" width="3" height="5" />
          <rect x="22" y="7" width="3" height="5" />
        </g>
        <g v-else-if="eyes === 'blink'" class="buddy-eyes" data-eyes="blink">
          <rect x="11" y="10" width="3" height="1" />
          <rect x="22" y="10" width="3" height="1" />
        </g>
        <g v-else-if="eyes === 'asleep'" class="buddy-eyes" data-eyes="asleep">
          <rect x="10" y="10" width="5" height="1" />
          <rect x="21" y="10" width="5" height="1" />
        </g>
        <g v-else-if="eyes === 'happy'" class="buddy-eyes" data-eyes="happy">
          <template v-for="left in [10, 21]" :key="left">
            <rect :x="left" y="10" width="1" height="1" />
            <rect :x="left + 1" y="9" width="1" height="1" />
            <rect :x="left + 2" y="8" width="1" height="1" />
            <rect :x="left + 3" y="9" width="1" height="1" />
            <rect :x="left + 4" y="10" width="1" height="1" />
          </template>
        </g>
        <g v-else class="buddy-heart-eyes" data-eyes="love">
          <template v-for="left in [10, 21]" :key="left">
            <rect :x="left" y="7" width="2" height="1" />
            <rect :x="left + 3" y="7" width="2" height="1" />
            <rect :x="left" y="8" width="5" height="1" />
            <rect :x="left + 1" y="9" width="3" height="1" />
            <rect :x="left + 2" y="10" width="1" height="1" />
          </template>
        </g>
        <g v-if="blush" class="buddy-blush">
          <rect x="8" y="13" width="3" height="1" />
          <rect x="25" y="13" width="3" height="1" />
        </g>

        <!-- The agents' props. -->
        <g v-if="variant === 'voice'" data-prop="headphones">
          <rect class="buddy-gear" x="10" y="-2" width="16" height="2" />
          <rect class="buddy-gear" x="8" y="-1" width="2" height="5" />
          <rect class="buddy-gear" x="26" y="-1" width="2" height="5" />
          <rect class="buddy-cup" x="5" y="4" width="4" height="6" />
          <rect class="buddy-cup" x="27" y="4" width="4" height="6" />
          <rect class="buddy-gear" x="24" y="13" width="5" height="1" />
          <rect class="buddy-gear" x="22" y="12" width="2" height="3" />
        </g>
        <g v-else-if="variant === 'morning'" data-prop="sun">
          <rect class="buddy-sun" x="15" y="-3" width="6" height="1" />
          <rect class="buddy-sun" x="14" y="-2" width="8" height="1" />
          <rect class="buddy-sun" x="13" y="-1" width="10" height="3" />
          <rect class="buddy-ray" x="11" y="-4" width="1" height="1" />
          <rect class="buddy-ray" x="17" y="-6" width="2" height="1" />
          <rect class="buddy-ray" x="24" y="-4" width="1" height="1" />
          <rect class="buddy-ray" x="10" y="0" width="1" height="1" />
          <rect class="buddy-ray" x="25" y="0" width="1" height="1" />
        </g>
        <g v-else-if="variant === 'deadline'" data-prop="clock">
          <rect class="buddy-bell" x="12" y="-6" width="3" height="2" />
          <rect class="buddy-bell" x="21" y="-6" width="3" height="2" />
          <rect class="buddy-gear" x="13" y="-5" width="10" height="7" />
          <rect class="buddy-face" x="14" y="-4" width="8" height="5" />
          <rect class="buddy-gear" x="17" y="-3" width="1" height="2" />
          <rect class="buddy-gear" x="18" y="-2" width="2" height="1" />
        </g>
        <g v-else-if="variant === 'photo'" data-prop="glasses">
          <rect class="buddy-gear" x="9" y="6" width="7" height="1" />
          <rect class="buddy-gear" x="9" y="12" width="7" height="1" />
          <rect class="buddy-gear" x="9" y="6" width="1" height="7" />
          <rect class="buddy-gear" x="15" y="6" width="1" height="7" />
          <rect class="buddy-gear" x="20" y="6" width="7" height="1" />
          <rect class="buddy-gear" x="20" y="12" width="7" height="1" />
          <rect class="buddy-gear" x="20" y="6" width="1" height="7" />
          <rect class="buddy-gear" x="26" y="6" width="1" height="7" />
          <rect class="buddy-gear" x="16" y="8" width="4" height="1" />
          <rect class="buddy-glint" x="10" y="7" width="1" height="1" />
          <rect class="buddy-glint" x="21" y="7" width="1" height="1" />
        </g>
      </g>
    </svg>

    <span
      v-for="particle in particles"
      :key="particle.id"
      class="buddy-particle pointer-events-none absolute left-1/2 top-0"
      :style="{ '--x': `${particle.x}px`, animationDelay: `${particle.delay}ms` }"
      :data-kind="particle.kind"
      aria-hidden="true"
    >
      <svg v-if="particle.kind === 'heart'" viewBox="0 0 7 6" shape-rendering="crispEdges" class="block h-3.5 w-4">
        <rect class="buddy-heart" x="1" y="0" width="2" height="1" />
        <rect class="buddy-heart" x="4" y="0" width="2" height="1" />
        <rect class="buddy-heart" x="0" y="1" width="7" height="2" />
        <rect class="buddy-heart" x="1" y="3" width="5" height="1" />
        <rect class="buddy-heart" x="2" y="4" width="3" height="1" />
        <rect class="buddy-heart" x="3" y="5" width="1" height="1" />
        <rect class="buddy-glint" x="1" y="1" width="1" height="1" />
      </svg>
      <svg v-else-if="particle.kind === 'spark'" viewBox="0 0 5 5" shape-rendering="crispEdges" class="block h-3 w-3">
        <rect class="buddy-spark" x="2" y="0" width="1" height="5" />
        <rect class="buddy-spark" x="0" y="2" width="5" height="1" />
      </svg>
      <svg v-else-if="particle.kind === 'wave'" viewBox="0 0 5 5" shape-rendering="crispEdges" class="block h-3 w-3">
        <rect class="buddy-wave" x="0" y="2" width="1" height="3" />
        <rect class="buddy-wave" x="2" y="0" width="1" height="5" />
        <rect class="buddy-wave" x="4" y="1" width="1" height="4" />
      </svg>
      <svg v-else-if="particle.kind === 'alert'" viewBox="0 0 3 5" shape-rendering="crispEdges" class="block h-3.5 w-2">
        <rect class="buddy-alert" x="1" y="0" width="1" height="3" />
        <rect class="buddy-alert" x="1" y="4" width="1" height="1" />
      </svg>
      <svg v-else viewBox="0 0 5 5" shape-rendering="crispEdges" class="block h-2.5 w-2.5">
        <rect class="buddy-z" x="0" y="0" width="5" height="1" />
        <rect class="buddy-z" x="3" y="1" width="1" height="1" />
        <rect class="buddy-z" x="2" y="2" width="1" height="1" />
        <rect class="buddy-z" x="1" y="3" width="1" height="1" />
        <rect class="buddy-z" x="0" y="4" width="5" height="1" />
      </svg>
    </span>
  </button>
</template>

<style scoped>
.ai-buddy {
  --buddy-main: #d97757;
  --buddy-light: #e8936f;
  --buddy-dark: #b85c3e;
  --buddy-eye: #1c1a19;
  --buddy-pink: #f06b9b;
  --buddy-gold: #f2b544;
  --buddy-gear: #2f2b3a;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.ai-buddy[data-variant="voice"] { --buddy-main: #8b7cf6; --buddy-light: #a99cf8; --buddy-dark: #6a5ad8; }
.ai-buddy[data-variant="morning"] { --buddy-main: #f2b544; --buddy-light: #f7cb72; --buddy-dark: #cf9220; }
.ai-buddy[data-variant="deadline"] { --buddy-main: #e8625a; --buddy-light: #f08883; --buddy-dark: #c2453e; --buddy-gear: #7c2a24; }
.ai-buddy[data-variant="photo"] { --buddy-main: #36b1a4; --buddy-light: #5fc8bc; --buddy-dark: #24897f; --buddy-gear: #1d3b57; }

.buddy-body { fill: var(--buddy-main); }
.buddy-light { fill: var(--buddy-light); }
.buddy-shade, .buddy-limb { fill: var(--buddy-dark); }
.buddy-eyes rect { fill: var(--buddy-eye); }
.buddy-heart-eyes rect, .buddy-heart { fill: var(--buddy-pink); }
.buddy-blush rect { fill: var(--buddy-pink); opacity: 0.55; }
.buddy-glint { fill: #fff; opacity: 0.85; }
.buddy-spark { fill: var(--buddy-gold); }
.buddy-z { fill: currentColor; opacity: 0.55; }
.buddy-wave { fill: #8b7cf6; }
.buddy-alert { fill: #e5484d; }
.buddy-gear { fill: var(--buddy-gear); }
.buddy-cup { fill: #c9c1ff; }
.buddy-sun { fill: #ff8a3d; }
.buddy-ray { fill: #ffb347; }
.buddy-bell { fill: var(--buddy-gold); }
.buddy-face { fill: #fff4e0; }
.buddy-shadow { fill: currentColor; opacity: 0.12; transform-box: fill-box; transform-origin: center; }

.buddy-figure, .buddy-limb { transform-box: fill-box; transform-origin: center bottom; }

/* Alive: a slow breath, in pixel steps; faster while an agent works, slower asleep. */
.buddy-figure { animation: buddy-breathe 2.4s steps(4) infinite; }
.ai-buddy[data-mood="busy"] .buddy-figure { animation-duration: 1.4s; }
.ai-buddy[data-asleep] .buddy-figure { animation-duration: 3.6s; }
.ai-buddy[data-asleep] svg { filter: saturate(0.4); opacity: 0.85; }

.ai-buddy[data-action="hop"] .buddy-figure,
.ai-buddy[data-action="tap"] .buddy-figure { animation: buddy-hop 0.6s ease-out; }
.ai-buddy[data-action="hop"] .buddy-shadow,
.ai-buddy[data-action="tap"] .buddy-shadow { animation: buddy-shadow 0.6s ease-out; }
.ai-buddy[data-action="wave"] .buddy-arm-right { animation: buddy-arm 0.32s steps(1) 4; }
.ai-buddy[data-action="touch"] .buddy-arm-right { animation: buddy-poke 0.3s steps(1) 3; }
.ai-buddy[data-action="dance"] .buddy-figure { animation: buddy-wiggle 0.35s steps(1) 4; }
.ai-buddy[data-action="dance"] .buddy-leg-a,
.ai-buddy[data-action="type"] .buddy-arm-left,
.ai-buddy[data-walking] .buddy-leg-a { animation: buddy-arm 0.2s steps(1) infinite; }
.ai-buddy[data-action="dance"] .buddy-leg-b,
.ai-buddy[data-action="type"] .buddy-arm-right,
.ai-buddy[data-walking] .buddy-leg-b { animation: buddy-arm 0.2s steps(1) infinite 0.1s; }
/* Listening sways to the voice; ringing shakes the prop on its head; cheering hops twice, arms up. */
.ai-buddy[data-action="listen"] .buddy-figure { animation: buddy-wiggle 0.6s steps(1) 4; }
.ai-buddy[data-action="ring"] [data-prop] { transform-box: fill-box; transform-origin: center bottom; animation: buddy-shake 0.12s steps(1) 12; }
.ai-buddy[data-action="ring"] .buddy-figure { animation: buddy-shiver 0.12s steps(1) 12; }
.ai-buddy[data-action="cheer"] .buddy-figure { animation: buddy-hop 0.5s ease-out 2; }
.ai-buddy[data-action="cheer"] .buddy-arm-left,
.ai-buddy[data-action="cheer"] .buddy-arm-right { transform: translateY(-4px); animation: buddy-arm 0.25s steps(1) 6; }
/* Walking leans into the step; sitting lets the legs hang from the edge it sits on. */
.ai-buddy[data-walking] .buddy-figure { animation: buddy-step 0.4s steps(2) infinite; }
.ai-buddy[data-sitting] .buddy-leg { transform: translateY(2px); }
.ai-buddy[data-sitting] .buddy-shadow { opacity: 0; }

.buddy-particle {
  translate: calc(-50% + var(--x)) 0;
  opacity: 0;
  animation: buddy-float 1.6s ease-out forwards;
}
.buddy-particle[data-kind="z"] { animation-duration: 2.4s; }

@keyframes buddy-breathe {
  0%, 100% { transform: translateY(0) scaleY(1); }
  50% { transform: translateY(-0.5px) scaleY(1.02); }
}
@keyframes buddy-hop {
  0% { transform: translateY(0) scale(1.06, 0.9); }
  35% { transform: translateY(-6px) scale(0.96, 1.06); }
  70% { transform: translateY(0) scale(1.06, 0.92); }
  100% { transform: translateY(0) scale(1, 1); }
}
@keyframes buddy-shadow {
  35% { transform: scaleX(0.7); opacity: 0.06; }
}
@keyframes buddy-arm {
  0% { transform: translateY(-3px); }
  50% { transform: translateY(0); }
}
@keyframes buddy-poke {
  0% { transform: translate(1px, 3px); }
  50% { transform: translate(0, 0); }
}
@keyframes buddy-wiggle {
  0% { transform: rotate(-5deg); }
  50% { transform: rotate(5deg); }
}
@keyframes buddy-shake {
  0% { transform: rotate(-12deg); }
  50% { transform: rotate(12deg); }
}
@keyframes buddy-shiver {
  0% { transform: translateX(-0.5px); }
  50% { transform: translateX(0.5px); }
}
@keyframes buddy-step {
  0% { transform: translateY(0) rotate(3deg); }
  50% { transform: translateY(-1px) rotate(3deg); }
}
@keyframes buddy-float {
  0% { opacity: 0; transform: translateY(6px) scale(0.6); }
  15% { opacity: 1; transform: translateY(0) scale(1); }
  100% { opacity: 0; transform: translateY(-38px) scale(0.9); }
}

@media (prefers-reduced-motion: reduce) {
  .buddy-figure, .buddy-limb, .buddy-shadow, .buddy-particle { animation: none !important; }
}
</style>
