<script setup lang="ts">
/**
 * One person's scans on one day (Face ID's `events/?member=&date=`), as the day went: the
 * terminal's snapshot in the ring of what the scan did (tap it for the full picture), the time,
 * what it did (came in, late by 14 min, left after 9 h, a repeat) and at which terminal.
 */
import { ScanFace } from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyToday } from "@/stores/company";

import FaceThumb from "../overview/FaceThumb.vue";
import type { Scan } from "../overview/overviewApi";
import { SCAN_TONES } from "./team";
import { useMemberScans } from "./teamApi";

const ImageLightbox = defineAsyncComponent(() => import("@/components/ImageLightbox.vue"));

const props = defineProps<{ memberId: number; day: string; name: string; photo?: string | null }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();
const query = useMemberScans(() => props.memberId, () => props.day);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const scans = computed(() => [...(query.data.value?.results ?? [])].sort((a, b) => a.event_at.localeCompare(b.event_at)));
const photos = computed(() => scans.value.filter((scan) => scan.photo_url));
const lightbox = ref(false);
const index = ref(0);
const images = computed(() => photos.value.map((scan) => ({ src: scan.photo_url!, caption: `${fmt.instant(scan.event_at, "time")} · ${scan.device.name}` })));

function tone(scan: Scan) {
  if (scan.action === "checked_in" && scan.record?.is_late) return "warning" as const;
  return SCAN_TONES[scan.action];
}

function chip(scan: Scan): string {
  if (scan.action === "checked_in" && scan.record?.is_late) return t("davomat.employee.scan.late", { d: fmt.duration(scan.record.late_minutes) });
  if (scan.action === "checked_out" && scan.record?.worked_minutes) return t("davomat.employee.scan.left", { d: fmt.duration(scan.record.worked_minutes) });
  return t(`davomat.employee.scan.${scan.action}`);
}

function show(scan: Scan): void {
  const at = photos.value.findIndex((item) => item.id === scan.id);
  if (at < 0) return;
  index.value = at;
  lightbox.value = true;
}

const heading = computed(() => (props.day === today.value ? t("davomat.employee.scans.today") : fmt.day(props.day, "weekday")));
</script>

<template>
  <section class="ui-card flex flex-col" :aria-label="t('davomat.employee.scans.title')" data-employee-scans>
    <header class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
      <div class="min-w-0">
        <h2 class="truncate text-base font-semibold text-fg first-letter:uppercase">{{ heading }}</h2>
        <p class="text-xs text-muted">{{ t("davomat.employee.scans.title") }}</p>
      </div>
      <span v-if="scans.length" class="shrink-0 text-sm tabular-nums text-muted">{{ t("davomat.employee.scans.count", { n: scans.length }, scans.length) }}</span>
    </header>

    <div v-if="skeleton" class="flex flex-col gap-3 p-4" aria-hidden="true">
      <div v-for="n in 3" :key="n" class="flex items-center gap-3"><SkeletonBlock circle width="44px" height="44px" /><SkeletonBlock width="60%" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" bare compact :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="!scans.length" size="sm" tone="neutral" :icon="ScanFace" :title="t('davomat.employee.scans.empty')" :description="day === today ? t('davomat.employee.scans.emptyToday') : undefined" />
    <ol v-else class="flex flex-col px-4 py-2">
      <li v-for="(scan, at) in scans" :key="scan.id" class="relative flex items-center gap-3 py-2.5" :data-scan="scan.id">
        <span v-if="at < scans.length - 1" class="absolute left-[21px] top-[54px] h-[calc(100%-42px)] w-px bg-line" aria-hidden="true" />
        <button
          type="button"
          class="relative shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--c-primary)] disabled:cursor-default"
          :disabled="!scan.photo_url"
          :aria-label="t('davomat.employee.scans.photo')"
          @click="show(scan)"
        >
          <FaceThumb :src="scan.photo_url ?? photo ?? null" :name="name" :size="44" :tone="tone(scan)" />
        </button>
        <div class="min-w-0 flex-1">
          <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span class="text-md font-semibold tabular-nums text-fg">{{ fmt.instant(scan.event_at, "time") }}</span>
            <StatusPill size="sm" :tone="tone(scan)" :label="chip(scan)" />
          </p>
          <p class="truncate text-xs text-muted">{{ scan.device.name }} · {{ scan.branch.name }}</p>
        </div>
      </li>
    </ol>
    <ImageLightbox v-if="lightbox" v-model:open="lightbox" v-model:index="index" :images="images" :title="name" />
  </section>
</template>
