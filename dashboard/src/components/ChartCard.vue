<script setup lang="ts">
/**
 * The frame every chart sits in (plan §6.3): title, an optional headline value and subtitle, a slot
 * for the range control, a menu with "Download PNG" and "Download CSV", and the loading (skeleton
 * after 150 ms), empty and error states, so each chart fails on its own.
 *
 *   <ChartCard :title="t('sales.netByDay')" :loading="q.isPending.value" :error="q.error.value" :retry="q.refetch"
 *     :empty="!points.length" :csv="{ filename: 'sales', columns, rows }">
 *     <LineChart … />
 *   </ChartCard>
 */
import { ArrowRight, BarChart3, Download, Ellipsis, Image as ImageIcon } from "@lucide/vue";
import { computed, provide, ref, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import { downloadFile, safeFilename, toCsv, type CsvColumn } from "@/lib/csv";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { CHART_CARD_KEY } from "./chartCard";
import DropdownMenu, { type MenuEntry } from "./DropdownMenu.vue";
import EmptyState from "./EmptyState.vue";
import ErrorState from "./ErrorState.vue";
import IconButton from "./IconButton.vue";
import SkeletonBlock from "./SkeletonBlock.vue";
import { vTruncateTitle } from "./truncateTitle";

export interface ChartCsv<Row = Record<string, unknown>> {
  filename: string;
  columns: CsvColumn<Row>[];
  rows: readonly Row[];
}

const props = withDefaults(
  defineProps<{
    title: string;
    subtitle?: string;
    /** A headline number above the chart ("48,1 mln so‘m"). */
    value?: string;
    loading?: boolean;
    error?: unknown;
    retry?: () => unknown;
    empty?: boolean;
    emptyText?: string;
    csv?: ChartCsv<never> | (() => ChartCsv<never>) | null;
    /** Body height while loading or empty, to keep the layout still. */
    height?: string;
    flush?: boolean;
    /** Before the title, as on the Overview's other cards (WidgetCard). */
    icon?: Component;
    /** The page behind the chart: "View all →" beside the menu. */
    to?: RouteLocationRaw;
    linkLabel?: string;
  }>(),
  {
    subtitle: undefined,
    value: undefined,
    loading: false,
    error: undefined,
    retry: undefined,
    empty: false,
    emptyText: undefined,
    csv: null,
    height: "240px",
    flush: false,
    icon: undefined,
    to: undefined,
    linkLabel: undefined,
  },
);

const { t } = useI18n();
const root = ref<HTMLElement | null>(null);
let toPng: ((background: string) => string | null) | null = null;
provide(CHART_CARD_KEY, { register: (fn) => (toPng = fn) });

const skeleton = useDelayedPending(computed(() => props.loading));
const exportable = computed(() => !props.loading && !props.error && !props.empty);

function png(): void {
  const background = root.value ? getComputedStyle(root.value).getPropertyValue("--c-surface").trim() || "#ffffff" : "#ffffff";
  // The canvas wants a plain color; let the browser normalize the token.
  const probe = document.createElement("span");
  probe.style.color = background;
  document.body.appendChild(probe);
  const color = getComputedStyle(probe).color;
  probe.remove();
  const url = toPng?.(color);
  if (!url) return;
  const link = document.createElement("a");
  link.href = url;
  link.download = safeFilename(props.title, "png");
  link.click();
}

function csvDownload(): void {
  const data = typeof props.csv === "function" ? props.csv() : props.csv;
  if (!data) return;
  downloadFile(safeFilename(data.filename, "csv"), toCsv(data.columns as CsvColumn<unknown>[], data.rows as readonly unknown[]));
}

const menu = computed<MenuEntry[]>(() => {
  const entries: MenuEntry[] = [{ label: t("common.chart.png"), icon: ImageIcon, onSelect: png }];
  if (props.csv) entries.push({ label: t("common.chart.csv"), icon: Download, onSelect: csvDownload });
  return entries;
});
</script>

<template>
  <section ref="root" class="ui-card flex min-w-0 flex-col" :aria-label="title" :aria-busy="loading || undefined">
    <header :class="['@container flex flex-wrap items-start gap-x-3 gap-y-2 px-4 pb-2 pt-4', !icon && 'md:px-5']">
      <div class="min-w-[min(100%,180px)] flex-1">
        <h3 class="flex min-h-5 min-w-0 items-center gap-2 text-sm font-semibold text-fg">
          <component :is="icon" v-if="icon" :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
          <span v-truncate-title class="truncate">{{ title }}</span>
        </h3>
        <p v-if="value && !loading" class="mt-1 truncate text-xl font-semibold tracking-[-0.015em] tabular-nums text-fg">{{ value }}</p>
        <SkeletonBlock v-else-if="value !== undefined && skeleton" class="mt-1.5" width="140px" height="24px" />
        <p v-if="subtitle" v-truncate-title class="mt-0.5 truncate text-xs text-muted">{{ subtitle }}</p>
      </div>
      <div class="-mt-0.5 flex min-w-0 max-w-full items-center gap-1">
        <slot name="actions" />
        <RouterLink
          v-if="to"
          :to="to"
          :title="linkLabel ?? t('common.viewAll')"
          class="group/link relative inline-flex shrink-0 items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted transition-colors after:absolute after:-inset-x-1 after:-inset-y-2.5 after:content-[''] hover:bg-highlight hover:text-fg"
        >
          <!-- As on every Overview card (WidgetCard): a narrow card shows the arrow, and says the label to screen readers only. -->
          <span class="@max-[24rem]:sr-only">{{ linkLabel ?? t("common.viewAll") }}</span><ArrowRight :size="14" class="transition-transform duration-150 group-hover/link:translate-x-0.5" aria-hidden="true" />
        </RouterLink>
        <DropdownMenu v-if="exportable" :items="menu" width="190px">
          <template #trigger>
            <IconButton :icon="Ellipsis" :label="t('common.chart.actions')" size="sm" />
          </template>
        </DropdownMenu>
      </div>
    </header>
    <div :class="['min-w-0 flex-1', !flush && 'px-3 pb-3 md:px-4 md:pb-4']">
      <div v-if="loading" :style="{ height }" class="flex items-end gap-2 px-1 pb-1">
        <template v-if="skeleton">
          <SkeletonBlock v-for="n in 12" :key="n" :height="`${30 + ((n * 37) % 60)}%`" radius="5px" class="flex-1" />
        </template>
      </div>
      <div v-else-if="error" :style="{ minHeight: height }" class="grid place-items-center">
        <ErrorState compact :error="error" :retry="retry" class="border-0 bg-transparent" />
      </div>
      <div v-else-if="empty" :style="{ minHeight: height }" class="grid place-items-center">
        <EmptyState size="sm" tone="neutral" :icon="BarChart3" :title="emptyText ?? t('common.chart.empty')" />
      </div>
      <slot v-else />
    </div>
    <footer v-if="$slots.footer" class="border-t border-line px-4 py-2.5 text-sm md:px-5">
      <slot name="footer" />
    </footer>
  </section>
</template>
