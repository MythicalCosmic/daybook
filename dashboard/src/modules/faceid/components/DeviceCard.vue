<script setup lang="ts">
/**
 * One terminal: a status ring (online, quiet, never connected, switched off), its model, branch
 * and direction, the last scan, today's scans and a small per-hour chart, a clock warning when the
 * terminal's time is off, and for managers the setup values, a new code and the switch.
 */
import { Clock, DoorOpen, KeyRound, Power, Settings2, TriangleAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";

import { clockOf, directionKey, peak, STATUS_TONES } from "../lib";
import type { Device } from "../types";

const props = defineProps<{ device: Device; canManage: boolean; busy?: boolean }>();
defineEmits<{ setup: [device: Device]; regenerate: [device: Device]; toggle: [device: Device] }>();

const { t } = useI18n();
const top = computed(() => peak(props.device.hourly));
const offMinutes = computed(() => Math.round(Math.abs(props.device.clock_offset_s ?? 0) / 60));
const now = new Date().getHours();
</script>

<template>
  <article :class="['ui-card flex min-w-0 flex-col gap-4 p-4 sm:p-5', !device.enabled && 'opacity-75']">
    <header class="flex items-start gap-3">
      <span :class="['faceid-ring relative grid size-11 shrink-0 place-items-center rounded-full', `faceid-ring--${device.status}`]" aria-hidden="true">
        <span class="size-3 rounded-full bg-current" />
      </span>
      <div class="min-w-0 flex-1">
        <h3 class="truncate text-base font-semibold text-fg">{{ device.name }}</h3>
        <p class="truncate text-xs text-muted">{{ device.model || t("faceid.terminals.hikvision") }} · {{ device.branch.name }}</p>
        <p class="mt-0.5 inline-flex items-center gap-1 text-xs text-subtle"><DoorOpen :size="12" aria-hidden="true" />{{ t(directionKey(device.direction)) }}</p>
      </div>
      <StatusPill size="sm" :tone="STATUS_TONES[device.status]" :live="device.status === 'online'" :label="t(`faceid.status.${device.status}`)" />
    </header>

    <div class="grid grid-cols-2 gap-3">
      <div class="min-w-0 rounded-[10px] bg-surface-2/70 px-3 py-2.5">
        <p class="text-[11px] font-medium uppercase tracking-wide text-subtle">{{ t("faceid.terminals.lastScan") }}</p>
        <p v-if="device.last_scan" class="mt-0.5 truncate text-sm font-semibold text-fg">{{ device.last_scan.name || "—" }}</p>
        <p v-if="device.last_scan" class="truncate text-xs tabular-nums text-muted">{{ clockOf(device.last_scan.at) }} · <RelativeTime :value="device.last_scan.at" /></p>
        <p v-else-if="device.last_event_at" class="mt-0.5 text-sm text-muted"><RelativeTime :value="device.last_event_at" /></p>
        <p v-else class="mt-0.5 text-sm text-muted">{{ t("faceid.terminals.noScanYet") }}</p>
      </div>
      <div class="min-w-0 rounded-[10px] bg-surface-2/70 px-3 py-2.5">
        <p class="text-[11px] font-medium uppercase tracking-wide text-subtle">{{ t("faceid.terminals.todayShort") }}</p>
        <p class="mt-0.5 text-xl font-semibold tabular-nums leading-7 text-fg">{{ device.scans_today }}</p>
        <div class="mt-1 flex h-8 items-end gap-[2px]" :aria-label="t('faceid.terminals.perHour')" role="img">
          <span
            v-for="(count, hour) in device.hourly"
            :key="hour"
            :class="['w-full min-w-[2px] rounded-[2px] transition-[height] duration-300', count ? 'bg-[var(--c-chart-2)]' : 'bg-line', hour === now && 'outline outline-1 outline-[var(--c-chart-2)]']"
            :style="{ height: `${count ? Math.max(18, (count / top) * 100) : 12}%` }"
            :title="t('faceid.terminals.hour', { hour: String(hour).padStart(2, '0'), n: count })"
          />
        </div>
      </div>
    </div>

    <p v-if="device.clock_off" class="flex items-start gap-2 rounded-[10px] bg-warning-soft px-3 py-2 text-sm text-warning">
      <TriangleAlert :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{{ (device.clock_offset_s ?? 0) < 0 ? t("faceid.terminals.clockBehind", { n: offMinutes }) : t("faceid.terminals.clockAhead", { n: offMinutes }) }}</span>
    </p>
    <p v-else-if="device.status === 'never'" class="flex items-start gap-2 rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-muted">
      <Clock :size="15" class="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{{ t("faceid.terminals.neverHint") }}</span>
    </p>

    <footer v-if="canManage" class="flex flex-wrap items-center gap-2 border-t border-line pt-3">
      <UiButton size="sm" variant="primary" :icon="Settings2" @click="$emit('setup', device)">{{ t("faceid.terminals.setup") }}</UiButton>
      <UiButton size="sm" variant="ghost" :icon="KeyRound" @click="$emit('regenerate', device)">{{ t("faceid.terminals.newCode") }}</UiButton>
      <span class="flex-1" />
      <UiButton size="sm" variant="ghost" :icon="Power" :loading="busy" @click="$emit('toggle', device)">{{ device.enabled ? t("faceid.terminals.switchOff") : t("faceid.terminals.switchOn") }}</UiButton>
    </footer>
  </article>
</template>

<style scoped>
.faceid-ring {
  color: var(--c-subtle);
  background: color-mix(in srgb, currentColor 12%, transparent);
}
.faceid-ring--online {
  color: var(--c-success);
}
.faceid-ring--quiet {
  color: var(--c-warning);
}
.faceid-ring--online::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 999px;
  border: 2px solid currentColor;
  opacity: 0;
  animation: faceid-pulse 2.4s var(--ease-out, ease-out) infinite;
}
@keyframes faceid-pulse {
  0% {
    transform: scale(0.7);
    opacity: 0.55;
  }
  100% {
    transform: scale(1.25);
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .faceid-ring--online::after {
    animation: none;
  }
}
</style>
