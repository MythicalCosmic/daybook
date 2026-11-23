<script setup lang="ts">
/**
 * The four big live numbers (docs/KOZ.md §6.2): came in today (with how many bought), in the queue
 * and at the counter across the branch's counter cameras, and the longest wait, ticking every
 * second between reports. Each number glides to its new value; a tile turns amber past the rule
 * and red when customers wait with nobody at the counter. A new visitor pops a small "+1".
 */
import { DoorOpen, Hourglass, UserRound, UsersRound } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";
import { useTween } from "@/lib/useTween";

import { useSecondClock } from "../lib/clock";
import { formatClock, tickingWait, waitLevel } from "../lib/tracks";
import type { Live } from "../types";

const props = withDefaults(
  defineProps<{
    live: Live | null;
    /** When `live` arrived (Date.now()). */
    liveAt: number;
    queuePeople: number;
    queueWaitS: number;
    loading?: boolean;
    /** Bigger type for the TV. */
    size?: "page" | "tv";
    /** Tiles shown elsewhere (the TV has its own "today"). */
    omit?: string[];
  }>(),
  { loading: false, size: "page", omit: () => [] },
);

const { t } = useI18n();
const fmt = useFormat();
const clock = useSecondClock();

const counters = computed(() => (props.live?.cameras ?? []).filter((camera) => camera.role === "counter" && camera.online && !camera.stale));
const hasCounter = computed(() => counters.value.length > 0);
const queue = computed(() => (hasCounter.value ? counters.value.reduce((sum, camera) => sum + (camera.queue ?? 0), 0) : null));
const staff = computed(() => (hasCounter.value ? counters.value.reduce((sum, camera) => sum + (camera.staff ?? 0), 0) : null));
const longest = computed(() => {
  const waits = counters.value.map((camera) => camera.wait_s).filter((value): value is number => typeof value === "number");
  return waits.length ? Math.max(...waits) : hasCounter.value ? 0 : null;
});
const wait = computed(() => (longest.value === null ? null : longest.value > 0 ? tickingWait(longest.value, props.liveAt, clock.value) : 0));
const level = computed(() => waitLevel(wait.value, props.queueWaitS));
const visitors = computed(() => props.live?.today.visitors ?? null);
const receipts = computed(() => props.live?.today.receipts ?? null);
const unattended = computed(() => (queue.value ?? 0) > 0 && staff.value === 0);

const visitorsTween = useTween(visitors);
const queueTween = useTween(queue, 300);
const staffTween = useTween(staff, 300);

// "+1" when someone comes in.
const bump = ref<{ n: number; key: number } | null>(null);
let bumpTimer: ReturnType<typeof setTimeout> | undefined;
watch(visitors, (next, before) => {
  if (next === null || before === null || before === undefined || next <= before) return;
  bump.value = { n: next - before, key: Date.now() };
  clearTimeout(bumpTimer);
  bumpTimer = setTimeout(() => (bump.value = null), 1600);
});
onBeforeUnmount(() => clearTimeout(bumpTimer));

const show = (value: number | null) => (value === null ? "—" : fmt.number(Math.round(value)));
const conversion = computed(() => (visitors.value && receipts.value !== null && visitors.value >= receipts.value ? (receipts.value / visitors.value) * 100 : null));

const tiles = computed(() => allTiles.value.filter((tile) => !props.omit.includes(tile.id)));
const allTiles = computed(() => [
  {
    id: "visitors",
    icon: DoorOpen,
    label: t("vision.counter.cameIn"),
    value: show(visitorsTween.value.value),
    sub:
      visitors.value === null
        ? t("vision.missing.no_entrance")
        : receipts.value !== null
          ? conversion.value !== null
            ? t("vision.counter.boughtShare", { n: fmt.number(receipts.value), share: fmt.percent(conversion.value) })
            : t("vision.counter.bought", { n: fmt.number(receipts.value) })
          : t("vision.missing.no_sales"),
    tone: "neutral",
  },
  {
    id: "queue",
    icon: UsersRound,
    label: t("vision.counter.queue"),
    value: show(queueTween.value.value),
    sub: !hasCounter.value ? t("vision.missing.no_counter") : t("vision.counter.queueRule", { n: props.queuePeople }),
    tone: unattended.value ? "danger" : (queue.value ?? 0) >= props.queuePeople ? "warning" : "neutral",
  },
  {
    id: "staff",
    icon: UserRound,
    label: t("vision.counter.atCounter"),
    value: show(staffTween.value.value),
    sub: !hasCounter.value ? t("vision.missing.no_counter") : unattended.value ? t("vision.counter.nobodyWaiting") : t("vision.counter.atCounterHint"),
    tone: unattended.value ? "danger" : "neutral",
  },
  {
    id: "wait",
    icon: Hourglass,
    label: t("vision.counter.wait"),
    value: wait.value === null ? "—" : formatClock(wait.value),
    sub: !hasCounter.value ? t("vision.missing.no_counter") : t("vision.counter.waitRule", { wait: formatClock(props.queueWaitS) }),
    tone: level.value === "over" ? "danger" : level.value === "long" ? "warning" : "neutral",
  },
]);
</script>

<template>
  <!-- The TV: one row per number, the label on the left and the number large on the right. -->
  <div v-if="size === 'tv'" class="koz-counters flex flex-col gap-3" data-size="tv" aria-live="off">
    <div v-for="tile in tiles" :key="tile.id" class="koz-counter flex items-center gap-4 rounded-[20px] border px-5 py-3.5" :data-tone="tile.tone" :data-counter="tile.id">
      <span class="koz-counter-icon grid size-11 shrink-0 place-items-center rounded-[13px]"><component :is="tile.icon" :size="22" /></span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-lg font-semibold text-fg">{{ tile.label }}</span>
        <span class="block truncate text-sm text-muted">{{ tile.sub }}</span>
      </span>
      <span class="koz-counter-value shrink-0 font-semibold tabular-nums">{{ tile.value }}</span>
    </div>
  </div>
  <div v-else class="koz-counters grid grid-cols-2 gap-2.5 lg:grid-cols-4" data-size="page" aria-live="off">
    <div
      v-for="tile in tiles"
      :key="tile.id"
      class="koz-counter relative flex min-w-0 flex-col overflow-hidden rounded-[16px] border p-4 transition-[background-color,border-color] duration-500 @container"
      :data-tone="tile.tone"
      :data-counter="tile.id"
    >
      <div class="flex items-center gap-2">
        <span class="koz-counter-icon grid size-7 shrink-0 place-items-center rounded-[9px]"><component :is="tile.icon" :size="15" /></span>
        <span class="kpi-label">{{ tile.label }}</span>
      </div>
      <SkeletonBlock v-if="loading" class="mt-3" width="55%" height="40px" radius="10px" />
      <p v-else class="koz-counter-value relative mt-2 font-semibold tabular-nums">
        {{ tile.value }}
        <Transition name="koz-bump">
          <span v-if="tile.id === 'visitors' && bump" :key="bump.key" class="koz-bump absolute -top-1 ml-1.5 text-sm font-bold text-success">+{{ bump.n }}</span>
        </Transition>
      </p>
      <p class="mt-1 truncate text-xs text-muted" :title="tile.sub">{{ tile.sub }}</p>
    </div>
  </div>
</template>

<style scoped>
.koz-counter {
  border-color: var(--c-border);
  background: var(--c-surface);
}
.koz-counter-icon {
  background: var(--c-surface-2);
  color: var(--c-muted);
}
.koz-counter[data-tone="warning"] {
  border-color: color-mix(in srgb, var(--c-warning) 45%, var(--c-border));
  background: color-mix(in srgb, var(--c-warning-soft) 75%, var(--c-surface));
}
.koz-counter[data-tone="warning"] .koz-counter-icon {
  background: var(--c-warning-soft);
  color: var(--c-warning);
}
.koz-counter[data-tone="warning"] .koz-counter-value {
  color: var(--c-warning);
}
.koz-counter[data-tone="danger"] {
  border-color: color-mix(in srgb, var(--c-danger) 50%, var(--c-border));
  background: color-mix(in srgb, var(--c-danger-soft) 80%, var(--c-surface));
}
.koz-counter[data-tone="danger"] .koz-counter-icon {
  background: var(--c-danger-soft);
  color: var(--c-danger);
}
.koz-counter[data-tone="danger"] .koz-counter-value {
  color: var(--c-danger);
}
.koz-counter-value {
  font-size: clamp(1.75rem, 16cqi, 2.5rem);
  line-height: 1.1;
  letter-spacing: -0.03em;
  color: var(--c-text);
}
[data-size="tv"] .koz-counter-value {
  font-size: clamp(2.25rem, 3.6vw, 3.5rem);
  line-height: 1;
}
.koz-bump-enter-active {
  transition:
    opacity 0.25s var(--ease-out),
    transform 0.6s var(--ease-out);
}
.koz-bump-leave-active {
  transition:
    opacity 0.6s ease,
    transform 0.6s ease;
}
.koz-bump-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.8);
}
.koz-bump-leave-to {
  opacity: 0;
  transform: translateY(-14px);
}
</style>
