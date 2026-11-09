<script setup lang="ts">
/**
 * One scan in the live feed: the snapshot (its ring in the scan's colour), who it was (the Daybook
 * person, or the terminal's name and number), where (branch and terminal), when (the exact time
 * and how long ago) and what it did, as a chip ("On time", "Late 14 min", "Left · 9 h 7 min",
 * "Repeat", "Unknown face", "Not in Daybook").
 */
import { CreditCard, Fingerprint, ScanFace } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";

import { ACTION_TONES, actionChip, clockOf, RING_COLORS, scanName } from "../lib";
import type { Scan } from "../types";
import Snapshot from "./Snapshot.vue";

const props = withDefaults(defineProps<{ scan: Scan; fresh?: boolean; showBranch?: boolean }>(), { fresh: false, showBranch: true });
defineEmits<{ open: [scan: Scan]; photo: [scan: Scan] }>();

const { t } = useI18n();
const fmt = useFormat();

const name = computed(() => (props.scan.kind === "stranger" && !props.scan.name_on_device ? t("faceid.feed.unknown") : scanName(props.scan)));
const subtitle = computed(() => {
  const scan = props.scan;
  if (scan.member) return scan.member.position?.name ?? "";
  if (scan.kind === "stranger") return t("faceid.feed.strangerHint");
  return t("faceid.feed.number", { number: scan.employee_no });
});
const chip = computed(() => {
  const value = actionChip(props.scan);
  return t(value.key, { d: value.minutes ? fmt.duration(value.minutes) : "" });
});
const tone = computed(() => (props.scan.flags.includes("simulated") ? "info" : props.scan.action === "checked_in" && props.scan.record?.is_late ? "warning" : ACTION_TONES[props.scan.action]));
const ring = computed(() => (props.scan.action === "checked_in" && props.scan.record?.is_late ? "var(--c-warning)" : RING_COLORS[props.scan.action]));
const method = computed(() => ({ fingerprint: Fingerprint, card: CreditCard })[props.scan.method as "fingerprint" | "card"] ?? ScanFace);
</script>

<template>
  <li :class="['faceid-row group relative flex items-center gap-3 px-3 py-2.5 sm:px-4', fresh && 'faceid-row--fresh']">
    <button type="button" class="shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--c-primary)]" :aria-label="t('faceid.feed.photo', { name })" @click="$emit('photo', scan)">
      <Snapshot :src="scan.photo_url" :name="name" :size="48" :ring="ring" />
    </button>
    <button type="button" class="flex min-w-0 flex-1 items-center gap-3 text-left" @click="$emit('open', scan)">
      <span class="min-w-0 flex-1">
        <span class="flex min-w-0 items-center gap-1.5">
          <span class="truncate text-sm font-semibold text-fg">{{ name }}</span>
          <component :is="method" :size="13" class="shrink-0 text-subtle" :aria-label="t(`faceid.method.${scan.method || 'face'}`)" />
        </span>
        <span class="block truncate text-xs text-muted">
          {{ subtitle }}<template v-if="showBranch"><template v-if="subtitle"> · </template>{{ scan.branch.name }} · {{ scan.device.name }}</template>
        </span>
      </span>
      <span class="hidden shrink-0 flex-col items-end leading-tight sm:flex">
        <span class="text-sm font-semibold tabular-nums text-fg">{{ clockOf(scan.event_at) }}</span>
        <span class="text-[11px] text-subtle"><RelativeTime :value="scan.event_at" /></span>
      </span>
      <StatusPill class="shrink-0" size="sm" :tone="tone" :label="chip" />
      <span class="w-10 shrink-0 text-right text-sm font-semibold tabular-nums text-fg sm:hidden">{{ clockOf(scan.event_at) }}</span>
    </button>
  </li>
</template>

<style scoped>
.faceid-row--fresh::before {
  content: "";
  position: absolute;
  inset: 0;
  background: var(--c-accent-soft, color-mix(in srgb, var(--c-primary) 10%, transparent));
  animation: faceid-fresh 1600ms var(--ease-out, ease-out) forwards;
  pointer-events: none;
}
@keyframes faceid-fresh {
  from {
    opacity: 1;
  }
  to {
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .faceid-row--fresh::before {
    animation: none;
    opacity: 0;
  }
}
</style>
