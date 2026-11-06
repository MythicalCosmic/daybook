<script setup lang="ts">
/**
 * An agent's own chibi on its card (AiBuddy.vue draws it in the agent's colours with its prop).
 * Calmer than Claude's helper: while its agent is on it blinks and looks about every few seconds,
 * waves or smiles now and then, and types and sparkles while the agent runs; while the agent is off
 * it sleeps. When Claude's helper pokes its card it greets it back; it reacts to what happens to
 * its agent (buddyCues.ts: listens to a voice note, rings for a late task) and cheers with everyone
 * when a task is finished; a tap makes it happy (it wakes up for a moment if asleep). Pauses while the tab is hidden; still with reduced motion.
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import { reducedMotion } from "@/components/chartOptions";

import { BUDDY_DURATION, buddyVariant, pickChibiAction, type BuddyAction } from "../lib";
import AiBuddy from "./AiBuddy.vue";
import { buddyCue, buddyGreeting } from "./buddyBus";

const props = withDefaults(defineProps<{ agentKey: string; name: string; on: boolean; running?: boolean; size?: number; color?: string | null }>(), {
  running: false,
  size: 46,
  color: null,
});

const action = ref<BuddyAction>("idle");
const beat = ref(0);
const reduced = reducedMotion();
const timers = new Set<ReturnType<typeof setTimeout>>();

function later(fn: () => void, ms: number): void {
  const timer = setTimeout(() => {
    timers.delete(timer);
    fn();
  }, ms);
  timers.add(timer);
}

function act(name: BuddyAction): void {
  action.value = name;
  beat.value += 1;
  const current = beat.value;
  later(() => {
    if (beat.value === current) action.value = "idle";
  }, BUDDY_DURATION[name]);
}

function tick(): void {
  if (props.on && !document.hidden) act(pickChibiAction(props.running, Math.random()));
  later(tick, 3500 + Math.random() * 4500);
}

function tap(): void {
  act("tap");
  window.Telegram?.WebApp?.HapticFeedback?.impactOccurred("light");
}

watch(buddyGreeting, (greeting) => {
  if (greeting?.key === props.agentKey && props.on) later(() => act(Math.random() < 0.5 ? "hearts" : "wave"), 250);
});

watch(buddyCue, (next) => {
  if (next && (next.key === "" || next.key === props.agentKey)) act(next.action);
});

onMounted(() => {
  if (!reduced) later(tick, 1000 + Math.random() * 3000);
});
onBeforeUnmount(() => {
  for (const timer of timers) clearTimeout(timer);
  timers.clear();
});
</script>

<template>
  <AiBuddy
    :variant="buddyVariant(agentKey)"
    :color="color"
    :mood="running ? 'busy' : 'on'"
    :asleep="!on && action === 'idle'"
    :action="action"
    :beat="beat"
    :size="size"
    :label="name"
    :data-agent-chibi="agentKey"
    @tap="tap"
  />
</template>
