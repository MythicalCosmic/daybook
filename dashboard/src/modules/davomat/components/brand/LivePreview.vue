<script setup lang="ts">
/**
 * The sign-in page's picture of the product, on its dark panel: a small, calm live board (the share
 * of people in, and arrivals sliding in with their status). Decorative only: no names, no real
 * data, hidden from screen readers; it stands still when motion is reduced. Its colors are its own
 * (the panel is dark in both themes): one indigo family for people, and the three status colors.
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
  { hue: 236, width: 62, time: "08:52", tone: "success", kind: "onTime" },
  { hue: 252, width: 48, time: "08:55", tone: "success", kind: "onTime" },
  { hue: 224, width: 56, time: "09:07", tone: "warning", kind: "late" },
  { hue: 264, width: 70, time: "09:12", tone: "primary", kind: "in" },
  { hue: 244, width: 52, time: "09:14", tone: "success", kind: "onTime" },
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
</script>

<template>
  <div class="relative w-full max-w-[440px] select-none" aria-hidden="true">
    <div class="card rounded-[20px] p-4">
      <div class="flex items-center gap-4">
        <svg width="56" height="56" viewBox="0 0 56 56" class="shrink-0 -rotate-90">
          <circle cx="28" cy="28" :r="ring.r" fill="none" stroke="rgb(255 255 255 / 0.1)" stroke-width="6" />
          <circle
            cx="28"
            cy="28"
            :r="ring.r"
            fill="none"
            stroke="#34d399"
            stroke-width="6"
            stroke-linecap="round"
            :stroke-dasharray="`${ring.dash} ${ring.length}`"
            class="transition-[stroke-dasharray] duration-500 ease-out"
          />
        </svg>
        <div class="min-w-0">
          <p class="text-xs font-medium text-white/55">{{ t("davomat.overview.kpi.inside") }}</p>
          <p class="mt-1 text-[28px] font-bold leading-none tracking-[-0.02em] tabular-nums text-white">
            {{ inside }}<span class="text-lg font-semibold text-white/35">/48</span>
          </p>
        </div>
        <span class="chip chip-success ml-auto inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold">
          <span class="relative flex size-2">
            <span class="dot absolute inline-flex size-full animate-ping rounded-full opacity-60 motion-reduce:hidden" />
            <span class="dot relative inline-flex size-2 rounded-full" />
          </span>
          {{ t("davomat.overview.feed.live") }}
        </span>
      </div>
      <TransitionGroup tag="ul" name="row" class="mt-4 flex flex-col gap-2">
        <li v-for="row in rows" :key="row.id" class="row flex items-center gap-3 rounded-[12px] px-3 py-2.5">
          <span class="size-8 shrink-0 rounded-full" :style="{ background: `linear-gradient(135deg, hsl(${row.hue} 90% 80%), hsl(${row.hue + 14} 62% 58%))` }" />
          <span class="flex min-w-0 flex-1 flex-col gap-1.5">
            <span class="h-2.5 rounded-full bg-white/25" :style="{ width: `${row.width}%` }" />
            <span class="h-2 w-1/3 rounded-full bg-white/10" />
          </span>
          <span class="text-xs tabular-nums text-white/55">{{ row.time }}</span>
          <span :class="['chip rounded-full px-2 py-0.5 text-[11px] font-semibold', `chip-${row.tone}`]">{{ row.label }}</span>
        </li>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.card {
  background: linear-gradient(180deg, rgb(255 255 255 / 0.085), rgb(255 255 255 / 0.045));
  border: 1px solid rgb(255 255 255 / 0.1);
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 0.07),
    0 30px 80px -28px rgb(0 0 0 / 0.7);
  backdrop-filter: blur(14px);
}
.row {
  background: rgb(255 255 255 / 0.05);
}
.chip-success {
  background: rgb(52 211 153 / 0.14);
  color: #6ee7b7;
}
.chip-success .dot {
  background: #34d399;
}
.chip-warning {
  background: rgb(251 191 36 / 0.14);
  color: #fcd34d;
}
.chip-primary {
  background: rgb(129 140 248 / 0.2);
  color: #c7d2fe;
}
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
