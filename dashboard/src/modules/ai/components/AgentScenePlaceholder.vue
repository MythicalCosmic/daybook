<script setup lang="ts">
/**
 * Where an agent's big scene goes (the lead's AgentScene.vue, with the same props) until it lands:
 * the agent's chibi beside its computer, the screen showing what it did lately (newest last), the
 * room dark at night. It types while the agent works, blinks and looks about while it waits, and
 * sleeps while it is off. Still with reduced motion.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { reducedMotion } from "@/components/chartOptions";
import { useBreakpoints } from "@/lib/useBreakpoints";

import { BUDDY_DURATION, pickChibiAction, type BuddyAction, type BuddyVariant } from "../lib";
import type { SceneState } from "../types";
import AiBuddy from "./AiBuddy.vue";

const props = withDefaults(defineProps<{ variant: BuddyVariant; state: SceneState; lines?: string[]; night?: boolean; label?: string }>(), {
  lines: () => [],
  night: false,
  label: "",
});

const { isPhone } = useBreakpoints();
const reduced = reducedMotion();
const action = ref<BuddyAction>("idle");
const beat = ref(0);
let timer: ReturnType<typeof setTimeout> | undefined;

function act(): void {
  if (props.state !== "asleep" && !document.hidden) {
    action.value = pickChibiAction(props.state === "working", Math.random());
    beat.value += 1;
  }
  timer = setTimeout(act, props.state === "working" ? BUDDY_DURATION.type + 200 : 3500 + Math.random() * 3500);
}
function restart(): void {
  clearTimeout(timer);
  action.value = "idle";
  if (!reduced) timer = setTimeout(act, 600);
}
watch(() => props.state, restart);
onMounted(restart);
onBeforeUnmount(() => clearTimeout(timer));

const size = computed(() => (isPhone.value ? 104 : 168));
const shown = computed(() => (props.state === "asleep" ? [] : props.lines.slice(-6)));
</script>

<template>
  <figure
    :class="['agent-scene relative isolate h-[240px] overflow-hidden rounded-card border border-line md:h-[380px]', night ? 'is-night' : 'is-day']"
    :data-state="state"
    :aria-label="label || undefined"
    role="img"
    data-testid="agent-scene"
  >
    <span class="agent-scene-sky absolute inset-0 -z-10" aria-hidden="true" />
    <span v-if="night" class="absolute right-[12%] top-[14%] size-8 rounded-full bg-[#f4efd9] shadow-[0_0_24px_6px_rgba(244,239,217,0.35)] md:size-12" aria-hidden="true" />
    <span class="agent-scene-floor absolute inset-x-0 bottom-0 -z-10 h-[22%]" aria-hidden="true" />
    <div class="flex h-full items-end justify-center gap-4 px-4 pb-[9%] md:gap-10" aria-hidden="true">
      <AiBuddy :variant="variant" :mood="state === 'working' ? 'busy' : 'on'" :asleep="state === 'asleep'" :action="action" :beat="beat" :size="size" sitting />
      <div class="flex w-[min(56%,460px)] flex-col items-center">
        <div :class="['agent-scene-screen w-full rounded-[10px] p-2.5 md:p-4', state === 'asleep' && 'is-off']">
          <ol class="flex h-[96px] flex-col justify-end gap-0.5 overflow-hidden font-mono text-[10px] leading-[14px] md:h-[188px] md:gap-1 md:text-xs md:leading-[18px]">
            <li v-for="(line, index) in shown" :key="`${index}:${line}`" class="truncate" :class="index === shown.length - 1 ? 'text-[#c8f7d4]' : 'text-[#c8f7d4]/60'">› {{ line }}</li>
            <li v-if="state === 'working'" class="agent-scene-cursor h-3 w-2 bg-[#c8f7d4] md:h-4" />
          </ol>
        </div>
        <span class="h-3 w-6 bg-[color-mix(in_srgb,var(--c-text)_30%,transparent)] md:h-5 md:w-10" />
        <span class="h-1.5 w-20 rounded-full bg-[color-mix(in_srgb,var(--c-text)_30%,transparent)] md:w-32" />
      </div>
    </div>
  </figure>
</template>

<style scoped>
.agent-scene.is-day .agent-scene-sky {
  background: linear-gradient(180deg, color-mix(in srgb, var(--c-info) 16%, var(--c-surface)) 0%, var(--c-surface) 80%);
}
.agent-scene.is-night .agent-scene-sky {
  background: linear-gradient(180deg, #121a33 0%, #1d2747 70%);
}
.agent-scene-floor {
  background: color-mix(in srgb, var(--c-text) 6%, transparent);
  border-top: 1px solid var(--c-border);
}
.agent-scene.is-night .agent-scene-floor {
  background: #161d36;
  border-color: #2a3560;
}
.agent-scene-screen {
  background: #0f1a14;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-text) 28%, transparent), 0 0 28px 2px rgba(120, 230, 160, 0.18);
}
.agent-scene-screen.is-off {
  background: #10131a;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-text) 28%, transparent);
}
.agent-scene-cursor {
  animation: agent-scene-blink 1s steps(1) infinite;
}
@keyframes agent-scene-blink {
  50% {
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .agent-scene-cursor {
    animation: none;
  }
}
</style>
