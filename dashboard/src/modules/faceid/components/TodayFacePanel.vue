<script setup lang="ts">
/**
 * Face ID on Attendance › Today (when the company runs both): who is in the building now, as
 * faces (each person's latest scan of the day says in; a check-out or none says gone), and the
 * latest scans at the terminals, with how the terminals are doing. A face opens the person's
 * attendance (`?person=` on the Today page); the feed is one tap away. Live through the pulse.
 */
import { ArrowRight, ScanFace } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { findModule } from "@/core/modules";
import { ensureModuleMessages } from "@/i18n";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useScans, useStatus } from "../api";
import { ACTION_TONES, actionChip, clockOf, RING_COLORS, scanName } from "../lib";
import type { Scan } from "../types";
import Snapshot from "./Snapshot.vue";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const personId = useRouteState("person", rs.optionalNumber(), { push: true });

// Face ID's own words load with the panel (the attendance page doesn't carry them).
const ready = ref(false);
const faceid = findModule("faceid");
if (faceid) void ensureModuleMessages(faceid).then(() => (ready.value = true));

const scans = useScans(() => ({ date: today.value, page_size: 300 }));
const status = useStatus();

/** Each person's latest scan of the day: in (came, checked in) or gone (checked out). */
const hereNow = computed(() => {
  const latest = new Map<string, Scan>();
  for (const scan of scans.data.value?.results ?? []) {
    if (scan.kind !== "person" || !["checked_in", "checked_out", "seen"].includes(scan.action)) continue;
    const key = scan.member ? `m${scan.member.id}` : `n${scan.employee_no}`;
    if (!latest.has(key)) latest.set(key, scan); // the list is newest first
  }
  return [...latest.values()].filter((scan) => scan.action !== "checked_out").sort((a, b) => a.event_at.localeCompare(b.event_at));
});
const recent = computed(() => (scans.data.value?.results ?? []).filter((scan) => scan.kind !== "other").slice(0, 5));
const terminals = computed(() => status.data.value);

function open(scan: Scan): void {
  if (scan.member) personId.value = scan.member.id;
}
</script>

<template>
  <section v-if="ready" class="ui-card flex min-w-0 flex-col gap-4 p-4" :aria-label="t('faceid.today.title')">
    <header class="flex flex-wrap items-center gap-2">
      <ScanFace :size="16" class="text-subtle" aria-hidden="true" />
      <h2 class="text-sm font-semibold text-fg">{{ t("faceid.today.title") }}</h2>
      <StatusPill v-if="terminals" size="sm" :tone="terminals.quiet ? 'warning' : terminals.total ? 'success' : 'neutral'" :live="!!terminals.online && !terminals.quiet" :label="t('faceid.today.terminals', { online: terminals.online, total: terminals.total })" />
      <span class="flex-1" />
      <UiButton size="sm" variant="ghost" class="whitespace-nowrap" :icon-right="ArrowRight" :to="`/c/${company.currentId}/faceid`">{{ t("faceid.today.feed") }}</UiButton>
    </header>

    <div class="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div class="min-w-0">
        <p class="mb-2 text-[11px] font-medium uppercase tracking-wide text-subtle">{{ t("faceid.today.hereNow", { n: hereNow.length }) }}</p>
        <ul v-if="hereNow.length" class="grid grid-cols-[repeat(auto-fill,minmax(76px,1fr))] gap-x-2 gap-y-3">
          <li v-for="scan in hereNow" :key="scan.id">
            <button type="button" class="flex w-full flex-col items-center gap-1 rounded-[10px] p-1 text-center hover:bg-highlight" :disabled="!scan.member" @click="open(scan)">
              <Snapshot :src="scan.photo_url" :name="scanName(scan)" :size="52" :ring="scan.record?.is_late ? 'var(--c-warning)' : RING_COLORS[scan.action]" />
              <span class="w-full truncate text-xs font-medium text-fg">{{ (scan.member?.name || scan.name_on_device || scan.employee_no).split(" ")[0] }}</span>
              <span class="text-[11px] tabular-nums text-muted">{{ clockOf(scan.event_at) }}</span>
            </button>
          </li>
        </ul>
        <p v-else class="py-3 text-sm text-muted">{{ t("faceid.today.nobody") }}</p>
      </div>
      <div class="min-w-0">
        <p class="mb-2 text-[11px] font-medium uppercase tracking-wide text-subtle">{{ t("faceid.today.latest") }}</p>
        <ul v-if="recent.length" class="flex flex-col gap-1.5">
          <li v-for="scan in recent" :key="scan.id" class="flex items-center gap-2.5">
            <Snapshot :src="scan.photo_url" :name="scanName(scan)" :size="30" :ring="RING_COLORS[scan.action]" />
            <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ scan.kind === "stranger" && !scan.name_on_device ? t("faceid.feed.unknown") : scanName(scan) }}</span>
            <span class="text-xs tabular-nums text-muted">{{ clockOf(scan.event_at) }}</span>
            <StatusPill size="sm" variant="plain" :tone="ACTION_TONES[scan.action]" :label="t(actionChip(scan).key, { d: actionChip(scan).minutes ? fmt.duration(actionChip(scan).minutes!) : '' })" />
          </li>
        </ul>
        <p v-else class="py-3 text-sm text-muted">{{ t("faceid.live.emptyBody") }}</p>
      </div>
    </div>
  </section>
</template>
