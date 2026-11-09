<script setup lang="ts">
/**
 * The sign-in page's picture of the product: a small, calm live board (the share of people in,
 * and arrivals sliding in with their status). Decorative only: no names, no real data, hidden
 * from screen readers; it stands still when motion is reduced.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

const { t } = useI18n();

type Tone = "success" | "warning" | "primary";
interface Row {
  id: number;
  hue: number;
  width: number;
  time: string;
  tone: Tone;
  label: string;
}

const SAMPLES: Array<Omit<Row, "id" | "label"> & { kind: "onTime" | "late" | "in" }> = [
  { hue: 238, width: 62, time: "08:52", tone: "success", kind: "onTime" },
  { hue: 172, width: 48, time: "08:55", tone: "success", kind: "onTime" },
  { hue: 24, width: 56, time: "09:07", tone: "warning", kind: "late" },
  { hue: 205, width: 70, time: "09:12", tone: "primary", kind: "in" },
  { hue: 300, width: 52, time: "09:14", tone: "success", kind: "onTime" },
];

function label(kind: "onTime" | "late" | "in"): string {
  if (kind === "late") return t("davomat.overview.chip.late", { n: 7 });
  if (kind === "in") return t("davomat.overview.chip.in");
  return t("davomat.overview.chip.onTime");
}

let next = 0;
const make = (index: number): Row => {
  const sample = SAMPLES[index % SAMPLES.length]!;
  return { id: next++, hue: sample.hue, width: sample.width, time: sample.time, tone: sample.tone, label: label(sample.kind) };
};
const rows = ref<Row[]>([make(2), make(1), make(0)]);
const inside = ref(42);
let cursor = 3;
let timer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  timer = setInterval(() => {
    rows.value = [make(cursor++), ...rows.value].slice(0, 3);
    inside.value = inside.value >= 47 ? 42 : inside.value + 1;
  }, 3600);
});
onBeforeUnmount(() => timer && clearInterval(timer));

const ring = computed(() => {
  const r = 22;
  const length = 2 * Math.PI * r;
  return { r, length, dash: (inside.value / 48) * length };
});
const toneClass: Record<Tone, string> = {
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  primary: "bg-accent-soft text-accent-fg",
};
</script>

<template>
  <div class="preview relative w-full max-w-[420px] select-none" aria-hidden="true">
    <div class="rounded-[18px] border border-line bg-surface/80 p-4 shadow-pop backdrop-blur-md">
      <div class="flex items-center gap-4">
        <svg width="56" height="56" viewBox="0 0 56 56" class="shrink-0 -rotate-90">
          <circle cx="28" cy="28" :r="ring.r" fill="none" stroke="var(--c-surface-3)" stroke-width="6" />
          <circle
            cx="28"
            cy="28"
            :r="ring.r"
            fill="none"
            stroke="var(--c-success)"
            stroke-width="6"
            stroke-linecap="round"
            :stroke-dasharray="`${ring.dash} ${ring.length}`"
            class="transition-[stroke-dasharray] duration-500 ease-out"
          />
        </svg>
        <div class="min-w-0">
          <p class="text-xs font-medium text-muted">{{ t("davomat.overview.kpi.inside") }}</p>
          <p class="mt-0.5 text-[28px] font-bold leading-none tracking-[-0.02em] tabular-nums text-fg">
            {{ inside }}<span class="text-lg font-semibold text-subtle">/48</span>
          </p>
        </div>
        <span class="ml-auto inline-flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-1 text-xs font-semibold text-success">
          <span class="relative flex size-2">
            <span class="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60 motion-reduce:hidden" />
            <span class="relative inline-flex size-2 rounded-full bg-success" />
          </span>
          {{ t("davomat.overview.feed.live") }}
        </span>
      </div>
      <TransitionGroup tag="ul" name="row" class="mt-4 flex flex-col gap-2">
        <li v-for="row in rows" :key="row.id" class="flex items-center gap-3 rounded-[12px] bg-surface-2/70 px-3 py-2.5">
          <span class="size-8 shrink-0 rounded-full" :style="{ background: `linear-gradient(135deg, hsl(${row.hue} 70% 72%), hsl(${row.hue + 30} 60% 52%))` }" />
          <span class="flex min-w-0 flex-1 flex-col gap-1.5">
            <span class="h-2.5 rounded-full bg-fg/15" :style="{ width: `${row.width}%` }" />
            <span class="h-2 w-1/3 rounded-full bg-fg/8" />
          </span>
          <span class="text-xs tabular-nums text-muted">{{ row.time }}</span>
          <span :class="['rounded-full px-2 py-0.5 text-[11px] font-semibold', toneClass[row.tone]]">{{ row.label }}</span>
        </li>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.row-enter-active {
  transition:
    opacity 260ms var(--ease-out),
    transform 260ms var(--ease-out);
}
.row-leave-active {
  transition: opacity 180ms var(--ease-out);
  position: absolute;
  opacity: 0;
}
.row-move {
  transition: transform 260ms var(--ease-out);
}
.row-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}
@media (prefers-reduced-motion: reduce) {
  .row-enter-active,
  .row-move {
    transition: none;
  }
}
</style>
