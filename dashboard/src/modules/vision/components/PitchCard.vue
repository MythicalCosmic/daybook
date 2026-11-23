<script setup lang="ts">
/**
 * The overview of a company without Ko‘z boxes: what Ko‘z does, in three promises, with a drawn
 * counter scene (boxes on stylised figures, the numbers and an alert around it), the privacy
 * promise, and the way in: pairing a box (or, for someone who can't, who to ask).
 */
import { BellRing, ChartColumnBig, Plus, ShieldCheck, Play } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import { useCompanyStore } from "@/stores/company";

defineProps<{ canManage: boolean }>();

const { t } = useI18n();
const company = useCompanyStore();

const POINTS = [
  { key: "point1", icon: ChartColumnBig },
  { key: "point2", icon: BellRing },
  { key: "point3", icon: Play },
] as const;
</script>

<template>
  <section class="koz-pitch ui-card relative overflow-hidden" data-pitch>
    <div class="grid gap-8 p-5 md:p-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:items-center lg:gap-10 lg:p-10">
      <div class="order-2 min-w-0 lg:order-1">
        <p class="text-xs font-semibold uppercase tracking-[0.12em] text-accent-fg">{{ t("vision.pitch.eyebrow") }}</p>
        <h2 class="font-display mt-2 text-[1.6rem] leading-[1.15] text-fg md:text-[2.1rem]">{{ t("vision.pitch.title") }}</h2>
        <p class="mt-3 max-w-xl text-md leading-relaxed text-muted">{{ t("vision.pitch.body") }}</p>
        <ul class="mt-6 flex flex-col gap-4">
          <li v-for="point in POINTS" :key="point.key" class="flex gap-3.5">
            <span class="grid size-10 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent-fg"><component :is="point.icon" :size="19" /></span>
            <span class="min-w-0">
              <span class="block text-base font-semibold text-fg">{{ t(`vision.pitch.${point.key}.title`) }}</span>
              <span class="block text-sm leading-5 text-muted">{{ t(`vision.pitch.${point.key}.body`) }}</span>
            </span>
          </li>
        </ul>
        <div class="mt-7 flex flex-wrap items-center gap-x-4 gap-y-2">
          <UiButton v-if="canManage" variant="primary" size="lg" :icon="Plus" :to="`/c/${company.currentId}/vision/cameras?pair=1`">{{ t("vision.pitch.cta") }}</UiButton>
          <span class="text-sm text-muted">{{ canManage ? t("vision.pitch.ctaHint") : t("vision.pitch.ask") }}</span>
        </div>
        <p class="mt-6 flex items-start gap-2 text-sm text-muted"><ShieldCheck :size="16" class="mt-0.5 shrink-0 text-success" />{{ t("vision.pitch.privacy") }}</p>
      </div>

      <!-- A drawn counter: stylised people, their boxes, and what Ko‘z makes of them. -->
      <div class="relative order-1 lg:order-2" aria-hidden="true">
        <div class="koz-pitch-scene relative overflow-hidden rounded-[18px]">
          <svg viewBox="0 0 480 300" class="block w-full">
            <defs>
              <linearGradient id="koz-wall" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#efe7da" /><stop offset="1" stop-color="#dfd3c1" /></linearGradient>
              <linearGradient id="koz-floor" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#d2c7b6" /><stop offset="1" stop-color="#bcae9a" /></linearGradient>
            </defs>
            <rect width="480" height="300" fill="url(#koz-wall)" />
            <g>
              <rect x="24" y="26" width="432" height="118" rx="4" fill="#d8ccb9" />
              <g v-for="row in 3" :key="row">
                <rect x="28" :y="22 + row * 38" width="424" height="4" fill="#f8f4ec" />
                <rect v-for="n in 17" :key="n" :x="30 + (n - 1) * 25" :y="22 + row * 38 - 22" :width="18 + (n % 3) * 2" :height="18 + (n % 4) * 1" rx="2" fill="#fbfaf6" />
                <rect v-for="n in 17" :key="`s${n}`" :x="30 + (n - 1) * 25" :y="22 + row * 38 - 17" :width="18 + (n % 3) * 2" height="5" :fill="['#2a9d8f', '#3a6ea5', '#c8553d', '#6a994e', '#e09f3e', '#7b6d8d'][(n + row) % 6]" />
              </g>
            </g>
            <!-- A pharmacist behind the counter. -->
            <g>
              <circle cx="196" cy="98" r="13" fill="#e3b48f" />
              <path d="M183 92 a13 13 0 0 1 26 0 z" fill="#2b2420" />
              <path d="M174 152 q2 -36 22 -38 q20 2 22 38 z" fill="#fafaf7" />
              <path d="M190 114 l6 12 l6 -12 z" fill="#2a9d8f" />
              <rect x="166" y="80" width="60" height="78" rx="9" fill="none" stroke="#7fd6aa" stroke-width="2.5" />
            </g>
            <rect x="0" y="146" width="480" height="20" fill="#d9b88f" />
            <rect x="0" y="166" width="480" height="26" fill="#f3ede3" />
            <rect x="0" y="166" width="480" height="4" fill="#2a9d8f" />
            <rect x="0" y="192" width="480" height="108" fill="url(#koz-floor)" />
            <!-- Customers in line, seen from behind. -->
            <g v-for="(p, i) in [{ x: 170, y: 214, s: 1, c: '#5b6c8f' }, { x: 236, y: 236, s: 1.12, c: '#8c4a3b' }, { x: 176, y: 262, s: 1.24, c: '#3f5e4b' }]" :key="i">
              <ellipse :cx="p.x" :cy="p.y + 52 * p.s" :rx="18 * p.s" :ry="4 * p.s" fill="rgba(30,20,10,0.18)" />
              <rect :x="p.x - 16 * p.s" :y="p.y" :width="32 * p.s" :height="40 * p.s" :rx="10 * p.s" :fill="p.c" />
              <circle :cx="p.x" :cy="p.y - 9 * p.s" :r="11 * p.s" :fill="i === 1 ? '#c77d8e' : '#2b2420'" />
              <rect :x="p.x - 24 * p.s" :y="p.y - 26 * p.s" :width="48 * p.s" :height="80 * p.s" :rx="9 * p.s" fill="none" :stroke="i === 0 ? '#ff8466' : '#ffc58a'" stroke-width="2.5" />
            </g>
            <polygon points="110,198 370,198 420,300 60,300" fill="#ffb46e" fill-opacity="0.12" stroke="#ffb46e" stroke-dasharray="7 6" stroke-width="1.6" />
          </svg>
          <span class="koz-pitch-pill absolute left-[29%] top-[22%]"><i class="bg-[#7fd6aa]" />{{ t("vision.person.staff") }}</span>
          <span class="koz-pitch-pill absolute left-[26%] top-[60%]"><i class="bg-[#ffc58a]" />{{ t("vision.person.customer") }} · <b class="text-[#ff8466]">2:41</b></span>
        </div>
        <div class="koz-pitch-chip absolute -right-1 -top-3 md:-right-4">
          <span class="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">18:00–19:00</span>
          <span class="mt-0.5 flex items-baseline gap-3 tabular-nums"><b class="text-xl text-fg">61</b><span class="text-xs text-muted">{{ t("vision.tv.cameIn") }}</span><b class="text-xl text-success">34</b><span class="text-xs text-muted">{{ t("vision.tv.bought") }}</span></span>
        </div>
        <div class="koz-pitch-chip koz-pitch-alert absolute -bottom-4 -left-1 md:-left-5">
          <span class="flex items-center gap-2 text-sm font-semibold text-fg"><span class="size-2 rounded-full bg-warning" />{{ t("vision.alert.kind.queue") }} · Kassa 1</span>
          <span class="mt-0.5 text-xs text-muted">{{ t("vision.banner.queueBody", { n: 4, wait: "2:41" }) }}</span>
        </div>
      </div>
    </div>
    <ol class="flex flex-wrap gap-x-8 gap-y-2 border-t border-line bg-canvas/50 px-5 py-4 text-sm md:px-10" :aria-label="t('vision.pitch.cta')">
      <li v-for="n in 3" :key="n" class="flex items-center gap-2.5">
        <span class="grid size-6 place-items-center rounded-full bg-primary text-xs font-bold text-on-primary">{{ n }}</span>
        <span class="font-medium text-fg">{{ t(`vision.pitch.step${n}`) }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.koz-pitch {
  background:
    radial-gradient(70% 90% at 100% 0%, color-mix(in srgb, var(--c-primary) 9%, transparent), transparent 60%),
    var(--c-surface);
}
.koz-pitch-scene {
  box-shadow:
    0 0 0 1px var(--c-border),
    0 30px 60px -30px rgb(40 24 10 / 0.45);
}
.koz-pitch-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  background: rgb(16 13 10 / 0.72);
  padding: 3px 9px;
  color: #fbf6ee;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.koz-pitch-pill i {
  width: 6px;
  height: 6px;
  border-radius: 999px;
}
.koz-pitch-chip {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  border: 1px solid var(--c-border);
  background: var(--c-surface);
  padding: 10px 14px;
  box-shadow: var(--sh-pop);
}
.koz-pitch-alert {
  border-color: color-mix(in srgb, var(--c-warning) 40%, var(--c-border));
  max-width: 17rem;
}
</style>
