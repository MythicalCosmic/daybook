<script setup lang="ts">
/**
 * Face ID › Live: every scan the terminals send, as it happens, each with its snapshot, linked to a
 * Daybook person or not ("the pictures of whoever comes"). Today's numbers on top (scans, people,
 * numbers not in Daybook, terminals online); filters by terminal and result; any past day via
 * `?date=`. New rows slide in with a short highlight; the list holds still while the pointer is
 * over it. Live through the `faceid.feed` pulse.
 */
import { CircleAlert, Plus, Radio, ScanFace, UserRoundX, Users } from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { connection } from "@/core/pulse";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useScans, useStatus } from "../api";
import ScanDrawer from "../components/ScanDrawer.vue";
import ScanItem from "../components/ScanItem.vue";
import { freshIds, scanName } from "../lib";
import type { Scan, ScanAction } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const RESULTS = ["all", "in", "out", "unlinked", "unknown"] as const;
const ACTIONS: Record<(typeof RESULTS)[number], ScanAction[] | undefined> = {
  all: undefined,
  in: ["checked_in", "seen"],
  out: ["checked_out"],
  unlinked: ["not_linked"],
  unknown: ["stranger"],
};
const day = useRouteState("date", rs.day());
const device = useRouteState("device", rs.optionalNumber());
const result = useRouteState("result", rs.enum(RESULTS, "all"));
const scanId = useRouteState("scan", rs.optionalNumber(), { push: true });

const isToday = computed(() => !day.value || day.value === today.value);
const params = computed(() => ({ date: day.value ?? today.value, device: device.value ?? undefined, action: ACTIONS[result.value], page_size: 100 }));
const scans = useScans(params);
const dayScans = useScans(() => ({ date: day.value ?? today.value, page_size: 500 }));
const status = useStatus();
const skeleton = useDelayedPending(computed(() => scans.isPending.value));

// The list holds still under the pointer; what arrived meanwhile slides in when it leaves.
const hovering = ref(false);
const shown = ref<Scan[]>([]);
const fresh = ref(new Set<number>());
let clearFresh: ReturnType<typeof setTimeout> | undefined;
function apply(rows: Scan[] | undefined): void {
  if (!rows) return;
  const added = shown.value.length ? freshIds(shown.value.map((row) => row.id), rows) : [];
  shown.value = rows;
  if (!added.length) return;
  fresh.value = new Set(added);
  clearTimeout(clearFresh);
  clearFresh = setTimeout(() => (fresh.value = new Set()), 1800);
}
watch(
  () => scans.data.value?.results,
  (rows) => {
    if (!hovering.value) apply(rows);
  },
  { immediate: true },
);
watch(hovering, (value) => {
  if (!value) apply(scans.data.value?.results);
});
watch(params, () => (shown.value = []));
onBeforeUnmount(() => clearTimeout(clearFresh));

const kpis = computed(() => {
  const rows = dayScans.data.value?.results ?? [];
  const people = new Set(rows.filter((row) => row.member).map((row) => row.member!.id));
  const outside = new Set(rows.filter((row) => row.action === "not_linked").map((row) => row.employee_no));
  const strangers = rows.filter((row) => row.action === "stranger").length;
  const terminals = status.data.value;
  return [
    { id: "scans", label: isToday.value ? t("faceid.kpi.scansToday") : t("faceid.kpi.scans"), value: dayScans.data.value?.count ?? null, icon: ScanFace },
    { id: "people", label: t("faceid.kpi.people"), value: people.size, icon: Users, hint: t("faceid.kpi.peopleHint") },
    {
      id: "outside",
      label: t("faceid.kpi.notInDaybook"),
      value: outside.size,
      icon: UserRoundX,
      hint: strangers ? t("faceid.kpi.strangers", { n: strangers }, strangers) : undefined,
      to: company.can("attendance.manage") ? `/c/${company.currentId}/faceid/people?show=unlinked` : undefined,
    },
    {
      id: "terminals",
      label: t("faceid.kpi.terminals"),
      value: terminals?.online ?? null,
      format: (value: number) => `${fmt.number(value)}/${fmt.number(terminals?.total ?? 0)}`,
      icon: Radio,
      hint: !terminals ? undefined : terminals.quiet ? t("faceid.kpi.quiet", { n: terminals.quiet }, terminals.quiet) : terminals.total ? t("faceid.kpi.allOnline") : t("faceid.kpi.noTerminals"),
    },
  ];
});

const deviceOptions = computed(() => (status.data.value?.devices ?? []).map((row) => ({ value: row.id, label: `${row.name} · ${row.branch.name}` })));
const results = computed(() => RESULTS.map((value) => ({ value, label: t(`faceid.filter.${value}`) })));
const filtered = computed(() => result.value !== "all" || device.value !== null);
const live = computed(() => isToday.value && connection.value === "online");
const showBranch = computed(() => new Set((status.data.value?.devices ?? []).map((row) => row.branch.id)).size > 1);

const lightbox = ref<Scan | null>(null);
const lightboxOpen = computed({ get: () => lightbox.value !== null, set: (value: boolean) => (lightbox.value = value ? lightbox.value : null) });
function photo(scan: Scan): void {
  if (scan.photo_url) lightbox.value = scan;
  else scanId.value = scan.id;
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('faceid.live.title')" :description="t('faceid.live.description')">
      <template #actions>
        <UiButton v-if="company.can('attendance.manage')" variant="secondary" :icon="Plus" :to="`/c/${company.currentId}/faceid/terminals?add=1`">{{ t("faceid.terminals.add") }}</UiButton>
      </template>
      <template #meta>
        <StatusPill v-if="live" tone="success" live size="sm" :label="t('faceid.live.live')" />
        <StatusPill v-else-if="isToday" tone="warning" size="sm" :label="t('faceid.live.reconnecting')" />
        <StatusPill v-else tone="neutral" size="sm" :label="fmt.day(day!, 'weekday')" />
      </template>
    </PageHeader>

    <KpiStrip :items="kpis" :loading="dayScans.isPending.value" :columns="4" phone="grid" />

    <div class="flex flex-wrap items-center gap-2">
      <DatePicker v-model="day" size="sm" :max="today" :placeholder="t('common.today')" format="weekday" class="w-56 max-sm:w-full" />
      <UiButton v-if="!isToday" size="sm" variant="ghost" @click="day = null">{{ t("common.today") }}</UiButton>
      <div class="no-scrollbar max-w-full overflow-x-auto">
        <SegmentedControl v-model="result" size="sm" :options="results" />
      </div>
      <span class="flex-1" />
      <SelectBox v-if="deviceOptions.length > 1" v-model="device" size="sm" class="w-60 max-sm:w-full" :options="deviceOptions" clearable :placeholder="t('faceid.filter.anyTerminal')" />
    </div>

    <section class="ui-card overflow-hidden" :aria-label="t('faceid.live.feed')" @pointerenter="hovering = true" @pointerleave="hovering = false">
      <div v-if="skeleton" class="flex flex-col gap-1 p-3">
        <div v-for="n in 6" :key="n" class="flex items-center gap-3 px-1 py-2">
          <SkeletonBlock width="48px" height="48px" radius="999px" />
          <div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="40%" /><SkeletonBlock width="25%" height="10px" /></div>
          <SkeletonBlock width="84px" height="22px" radius="999px" />
        </div>
      </div>
      <ErrorState v-else-if="scans.isError.value" class="p-6" :error="scans.error.value" :retry="() => scans.refetch()" />
      <EmptyState
        v-else-if="!shown.length"
        class="py-12"
        :icon="filtered ? CircleAlert : ScanFace"
        tone="neutral"
        :title="filtered ? t('faceid.live.noneFiltered') : isToday ? t('faceid.live.emptyTitle') : t('faceid.live.emptyPastTitle')"
        :description="filtered ? undefined : isToday ? t('faceid.live.emptyBody') : undefined"
      >
        <UiButton v-if="filtered" variant="secondary" size="sm" @click="(result = 'all'), (device = null)">{{ t("faceid.filter.clear") }}</UiButton>
        <UiButton v-else-if="status.data.value && !status.data.value.total && company.can('attendance.manage')" variant="primary" :icon="Plus" :to="`/c/${company.currentId}/faceid/terminals?add=1`">{{ t("faceid.terminals.add") }}</UiButton>
      </EmptyState>
      <TransitionGroup v-else tag="ul" name="faceid-feed" class="relative divide-y divide-line">
        <ScanItem v-for="scan in shown" :key="scan.id" :scan="scan" :fresh="fresh.has(scan.id)" :show-branch="showBranch" @open="scanId = $event.id" @photo="photo" />
      </TransitionGroup>
      <p v-if="scans.data.value && scans.data.value.count > shown.length && shown.length" class="border-t border-line px-4 py-2.5 text-xs text-subtle">
        {{ t("faceid.live.more", { shown: shown.length, total: scans.data.value.count }) }}
      </p>
    </section>

    <ScanDrawer :scans="shown" />
    <ImageLightbox v-if="lightbox" v-model:open="lightboxOpen" :images="[{ src: lightbox.photo_url!, alt: scanName(lightbox) }]" :title="`${scanName(lightbox)} · ${lightbox.device.name}`" />
  </div>
</template>

<style scoped>
.faceid-feed-enter-active,
.faceid-feed-move {
  transition:
    transform 240ms var(--ease-out),
    opacity 200ms var(--ease-out);
}
.faceid-feed-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}
@media (prefers-reduced-motion: reduce) {
  .faceid-feed-enter-active,
  .faceid-feed-move {
    transition: none;
  }
}
</style>
