<script setup lang="ts">
/**
 * A slim bar across the top of the page while something the person is waiting for loads: a page's
 * code (router navigation) or data that isn't on screen yet (a query's first load, also after a
 * filter changes). Live refreshes of data already shown never count. It appears after 150 ms, so a
 * quick answer never shows it, creeps towards the end while it waits, then fills and fades.
 */
import { useIsFetching } from "@tanstack/vue-query";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";

const DELAY = 150;
const FADE = 420;

const router = useRouter();
const navigating = ref(false);
const stopBefore = router.beforeEach((to, from) => {
  if (to.path !== from.path) navigating.value = true;
});
const stopAfter = router.afterEach(() => (navigating.value = false));
const stopError = router.onError(() => (navigating.value = false));

const firstLoads = useIsFetching({ predicate: (query) => query.state.data === undefined });
const busy = computed(() => navigating.value || firstLoads.value > 0);

type Phase = "idle" | "running" | "finishing";
const phase = ref<Phase>("idle");
const width = ref(0);
let startTimer: ReturnType<typeof setTimeout> | undefined;
let finishTimer: ReturnType<typeof setTimeout> | undefined;

function run(from: number): void {
  phase.value = "running";
  width.value = from;
  // Two frames: the start width paints first, then the long creep towards 90 % begins.
  requestAnimationFrame(() => requestAnimationFrame(() => phase.value === "running" && (width.value = 90)));
}

watch(
  busy,
  (isBusy) => {
    if (isBusy) {
      if (phase.value === "finishing") {
        clearTimeout(finishTimer);
        run(Math.min(width.value, 60));
        return;
      }
      if (phase.value === "running" || startTimer !== undefined) return;
      startTimer = setTimeout(() => {
        startTimer = undefined;
        if (busy.value) run(0);
      }, DELAY);
      return;
    }
    clearTimeout(startTimer);
    startTimer = undefined;
    if (phase.value !== "running") return;
    phase.value = "finishing";
    width.value = 100;
    finishTimer = setTimeout(() => {
      phase.value = "idle";
      width.value = 0;
    }, FADE);
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  clearTimeout(startTimer);
  clearTimeout(finishTimer);
  stopBefore();
  stopAfter();
  stopError();
});

defineExpose({ phase });
</script>

<template>
  <div class="pointer-events-none absolute inset-x-0 top-0 z-40 h-[2px] overflow-hidden" aria-hidden="true">
    <div v-if="phase !== 'idle'" :class="['top-loading-bar h-full', phase]" :style="{ width: `${width}%` }" data-testid="top-loading-bar" />
  </div>
</template>

<style scoped>
.top-loading-bar {
  background: linear-gradient(90deg, color-mix(in srgb, var(--c-primary) 55%, transparent), var(--c-primary));
  box-shadow: 0 0 10px color-mix(in srgb, var(--c-primary) 55%, transparent);
  border-radius: 0 2px 2px 0;
}
.top-loading-bar.running {
  /* Quick at first, then a long crawl: it never reaches the end on its own. */
  transition: width 9s cubic-bezier(0.08, 0.7, 0.15, 1);
}
.top-loading-bar.finishing {
  transition:
    width 200ms var(--ease-standard),
    opacity 220ms var(--ease-standard) 200ms;
  opacity: 0;
}
</style>
