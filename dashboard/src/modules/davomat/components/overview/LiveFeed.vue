<script setup lang="ts">
/**
 * The live feed (v8 F bar): every scan of today as a row with the terminal's snapshot in a ring of
 * its status colour, the person and their position, the terminal and the branch, the exact time and
 * "2 min ago", and a status chip (on time, late 14 min, left with today's hours, repeat, unknown
 * face, not linked). New rows slide in at the top with a short highlight; while the pointer is over
 * the list it holds still, so a row doesn't move away under the cursor.
 */
import { ArrowUpRight, Radio, ScanFace } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import FaceThumb from "./FaceThumb.vue";
import type { FaceTone, Scan } from "./overviewApi";

const props = withDefaults(defineProps<{ scans: Scan[]; loading?: boolean; error?: unknown; offline?: boolean; retry?: () => unknown }>(), {
  loading: false,
  error: undefined,
  offline: false,
  retry: undefined,
});

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();

const hovering = ref(false);
const frozen = ref<Scan[] | null>(null);
const shown = computed(() => frozen.value ?? props.scans);
watch(hovering, (value) => (frozen.value = value ? [...props.scans] : null));

// Rows that weren't there a moment ago get a short highlight.
const fresh = ref(new Set<number>());
let known: Set<number> | null = null;
watch(
  () => props.scans,
  (scans) => {
    const ids = new Set(scans.map((scan) => scan.id));
    if (known) {
      const added = scans.filter((scan) => !known!.has(scan.id)).map((scan) => scan.id);
      if (added.length) {
        fresh.value = new Set([...fresh.value, ...added]);
        setTimeout(() => {
          const next = new Set(fresh.value);
          added.forEach((id) => next.delete(id));
          fresh.value = next;
        }, 2400);
      }
    }
    known = ids;
  },
  { immediate: true },
);

interface Chip {
  tone: FaceTone;
  label: string;
}

function chipOf(scan: Scan): Chip {
  switch (scan.action) {
    case "checked_in":
      return scan.record?.is_late && scan.record.late_minutes > 0
        ? { tone: "warning", label: t("davomat.overview.chip.late", { n: scan.record.late_minutes }) }
        : { tone: "success", label: t("davomat.overview.chip.onTime") };
    case "checked_out":
      return scan.record?.worked_minutes
        ? { tone: "info", label: t("davomat.overview.chip.left", { hours: fmt.duration(scan.record.worked_minutes) }) }
        : { tone: "info", label: t("davomat.overview.chip.out") };
    case "repeat":
      return { tone: "neutral", label: t("davomat.overview.chip.repeat") };
    case "not_linked":
      return { tone: "warning", label: t("davomat.overview.chip.notLinked") };
    case "stranger":
      return { tone: "danger", label: t("davomat.overview.chip.unknown") };
    default:
      return { tone: "neutral", label: t("davomat.overview.chip.seen") };
  }
}

const chipClass: Record<FaceTone, string> = {
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
  primary: "bg-accent-soft text-accent-fg",
  neutral: "bg-surface-2 text-muted",
};

// The feed's own filter: every scan, the late arrivals, or the faces nobody here is linked to.
type Kind = "all" | "late" | "unknown";
const kind = ref<Kind>("all");
const isLate = (scan: Scan) => scan.action === "checked_in" && !!scan.record?.is_late && scan.record.late_minutes > 0;
const isUnknown = (scan: Scan) => scan.action === "stranger" || scan.action === "not_linked";
const lateCount = computed(() => props.scans.filter(isLate).length);
const unknownCount = computed(() => props.scans.filter(isUnknown).length);
const kinds = computed(() => [
  { value: "all" as const, label: t("davomat.overview.feed.filter.all") },
  { value: "late" as const, label: t("davomat.overview.feed.filter.late"), count: lateCount.value || undefined },
  { value: "unknown" as const, label: t("davomat.overview.feed.filter.unknown"), count: unknownCount.value || undefined },
]);
const filtered = computed(() => (kind.value === "all" ? shown.value : shown.value.filter(kind.value === "late" ? isLate : isUnknown)));

const rows = computed(() =>
  filtered.value.map((scan) => ({
    scan,
    chip: chipOf(scan),
    name: scan.member?.name || scan.name_on_device || t("davomat.overview.chip.unknown"),
    detail: [scan.member?.position?.name, t("davomat.overview.feed.at", { terminal: scan.device.name, branch: scan.branch.name })].filter(Boolean).join(" · "),
  })),
);

function open(scan: Scan): void {
  const base = `/c/${company.currentId}`;
  void router.push(scan.member ? `${base}/team/${scan.member.id}` : `${base}/faceid/people`);
}

const allLink = computed(() => `/c/${company.currentId}/faceid`);
</script>

<template>
  <section class="flex min-w-0 flex-col rounded-[18px] border border-line bg-surface" :aria-label="t('davomat.overview.feed.title')">
    <header class="flex items-center gap-3 border-b border-line px-4 py-3.5 md:px-5">
      <h2 class="whitespace-nowrap text-md font-semibold tracking-[-0.01em] text-fg">{{ t("davomat.overview.feed.title") }}</h2>
      <span
        :class="[
          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors',
          offline ? 'bg-surface-2 text-muted' : hovering ? 'bg-surface-2 text-muted' : 'bg-success-soft text-success',
        ]"
        aria-live="polite"
        data-testid="feed-live"
      >
        <span v-if="!offline && !hovering" class="relative flex size-2" aria-hidden="true">
          <span class="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60 motion-reduce:hidden" />
          <span class="relative inline-flex size-2 rounded-full bg-success" />
        </span>
        <Radio v-else :size="12" aria-hidden="true" />
        {{ offline ? t("davomat.overview.feed.offline") : hovering ? t("davomat.overview.feed.paused") : t("davomat.overview.feed.live") }}
      </span>
      <RouterLink :to="allLink" class="ml-auto inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-[8px] px-2 py-1 text-sm font-medium text-muted hover:bg-highlight hover:text-fg">
        {{ t("davomat.overview.feed.all") }}
        <ArrowUpRight :size="15" aria-hidden="true" />
      </RouterLink>
    </header>
    <!-- The feed's filter on its own line: room for every language's labels and counts. -->
    <div v-if="scans.length" class="border-b border-line px-3 py-2 md:px-4">
      <SegmentedControl v-model="kind" size="sm" :options="kinds" :aria-label="t('davomat.overview.feed.filter.label')" data-testid="feed-filter" />
    </div>

    <div v-if="loading && !scans.length" class="flex flex-col gap-1 p-2" aria-hidden="true">
      <div v-for="n in 6" :key="n" class="flex items-center gap-3 px-3 py-2.5">
        <SkeletonBlock circle width="40px" height="40px" />
        <span class="flex flex-1 flex-col gap-2"><SkeletonBlock :width="`${40 + ((n * 13) % 30)}%`" /><SkeletonBlock width="30%" height="10px" /></span>
        <SkeletonBlock width="70px" height="22px" radius="999px" />
      </div>
    </div>
    <ErrorState v-else-if="error && !scans.length" class="m-4" compact :error="error" :retry="retry" />
    <EmptyState v-else-if="!scans.length" class="py-12" size="sm" :icon="ScanFace" :title="t('davomat.overview.feed.empty.title')" :description="t('davomat.overview.feed.empty.body')" />
    <p v-else-if="!rows.length" class="px-5 py-10 text-center text-sm text-muted" data-testid="feed-none">{{ t("davomat.overview.feed.filter.none") }}</p>
    <TransitionGroup
      v-else
      tag="ul"
      name="feed"
      class="relative flex flex-col p-1.5 md:p-2"
      data-testid="feed-list"
      @pointerenter="hovering = true"
      @pointerleave="hovering = false"
    >
      <li v-for="row in rows" :key="row.scan.id">
        <button
          type="button"
          :class="['pressable flex w-full items-center gap-3 rounded-[12px] px-2.5 py-2.5 text-left transition-colors duration-300 hover:bg-highlight md:px-3', fresh.has(row.scan.id) && 'is-fresh']"
          @click="open(row.scan)"
        >
          <FaceThumb :src="row.scan.photo_url ?? row.scan.member?.photo_url" :name="row.scan.member || row.scan.name_on_device ? row.name : ''" :size="40" :tone="row.chip.tone" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-semibold text-fg">{{ row.name }}</span>
            <span class="block truncate text-sm text-muted">{{ row.detail }}</span>
          </span>
          <span class="hidden shrink-0 flex-col items-end sm:flex">
            <span class="text-base font-semibold tabular-nums text-fg">{{ fmt.instant(row.scan.event_at, "time") }}</span>
            <RelativeTime :value="row.scan.event_at" class="text-xs text-subtle" />
          </span>
          <span class="flex shrink-0 flex-col items-end gap-1">
            <span :class="['whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold', chipClass[row.chip.tone]]">{{ row.chip.label }}</span>
            <span class="text-xs tabular-nums text-subtle sm:hidden">{{ fmt.instant(row.scan.event_at, "time") }}</span>
          </span>
        </button>
      </li>
    </TransitionGroup>
  </section>
</template>

<style scoped>
.is-fresh {
  background: color-mix(in srgb, var(--c-primary) 8%, transparent);
}
.feed-enter-active {
  transition:
    opacity 240ms var(--ease-out),
    transform 240ms var(--ease-out);
}
.feed-move {
  transition: transform 240ms var(--ease-out);
}
.feed-enter-from {
  opacity: 0;
  transform: translateY(-10px);
}
.feed-leave-active {
  display: none;
}
@media (prefers-reduced-motion: reduce) {
  .feed-enter-active,
  .feed-move {
    transition: none;
  }
}
</style>
