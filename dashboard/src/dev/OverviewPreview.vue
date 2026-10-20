<script setup lang="ts">
/**
 * Dev-only stand-in for package A's Overview, so the mock shell can be judged with a realistic page
 * in it. Numbers are static demo values; "Needs you" reads the mock queue through the real API layer.
 */
import { useQuery } from "@tanstack/vue-query";
import { ArrowUpRight, TrendingUp } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { keys } from "@/api/keys";
import { shellApi } from "@/api/shell";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { dayPart, formatDay, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

defineProps<{ pkg: string }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const session = useSessionStore();

const greeting = computed(() => t(`dev.overview.${dayPart(company.timezone)}`, { name: session.me?.user.first_name ?? "" }));
const today = computed(() => `${formatDay(todayIn(company.timezone), fmt.lang.value, "weekday")} · ${company.current?.name ?? ""}`);

function spark(values: number[], width = 120, height = 36): string {
  const max = Math.max(...values);
  const min = Math.min(...values);
  const step = width / (values.length - 1);
  return values
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(height - 4 - ((v - min) / (max - min || 1)) * (height - 8)).toFixed(1)}`)
    .join(" ");
}

const kpis = computed(() => [
  { id: "sales", label: t("dev.overview.sales"), value: fmt.money("14250000.00"), delta: fmt.delta(8.2), tone: "success" as const, series: [6, 8, 7, 9, 8, 11, 10, 12, 11, 14], color: "var(--c-chart-1)" },
  { id: "tasks", label: t("dev.overview.tasks"), value: "38", sub: t("dev.overview.ofTotal", { n: 52 }), progress: 73, color: "var(--c-chart-2)" },
  { id: "present", label: t("dev.overview.present"), value: "17", sub: t("dev.overview.ofTotal", { n: 21 }), people: ["Madina Saidova", "Alisher Valiyev", "Aziz Karimov", "Jasur Ergashev"] },
  { id: "cash", label: t("dev.overview.cash"), value: fmt.money("86420000.00", "UZS", { compact: true }), hint: fmt.approx("6780", "USD"), series: [9, 9.5, 8.8, 9.9, 10.4, 9.7, 10.9, 11.2, 10.8, 11.6], color: "var(--c-chart-3)" },
]);

const branches = computed(() => [
  { name: "Chilonzor", code: "CHL", open: true, status: t("dev.overview.opened", { time: "08:57", name: "Dilnoza" }), staff: "7/7", tills: 2, sales: fmt.money("6140000", "UZS", { compact: true }), ring: 82 },
  { name: "Yunusobod", code: "YUN", open: false, status: t("dev.overview.notOpened", { n: 12 }), staff: "1/6", tills: 0, sales: fmt.money("0", "UZS", { compact: true }), ring: 12 },
  { name: "Sergeli", code: "SRG", open: true, status: t("dev.overview.opened", { time: "08:41", name: "Bekzod" }), staff: "5/5", tills: 1, sales: fmt.money("4880000", "UZS", { compact: true }), ring: 64 },
]);

const queue = useQuery({
  queryKey: computed(() => keys.queue(company.currentId ?? 0)),
  queryFn: () => shellApi.queue(company.currentId!),
  enabled: computed(() => company.currentId !== null),
});
const queueSkeleton = useDelayedPending(computed(() => queue.isPending.value));

const activity = [
  { name: "Madina Saidova", text: "Fridge temperature check · +4 °C", minutes: 6 },
  { name: "Aziz Karimov", text: "Closed shift CHL-1042 · 14 250 000", minutes: 14 },
  { name: "Alisher Valiyev", text: "Stock count: front shelves", minutes: 52 },
  { name: "Jasur Ergashev", text: "Checked in at Sergeli · 08:41", minutes: 96 },
  { name: "Bekzod Mirzayev", text: "Announcement: New uniform from Monday", minutes: 180 },
];
const ago = (minutes: number) => fmt.relative(new Date(Date.now() - minutes * 60_000).toISOString());
</script>

<template>
  <div>
    <PageHeader :title="greeting" :description="today">
      <template #actions>
        <div class="flex rounded-[9px] bg-surface-2 p-0.5">
          <button class="h-7 rounded-[7px] bg-surface px-3 text-sm font-semibold text-fg shadow-raised">{{ t("common.today") }}</button>
          <button class="h-7 rounded-[7px] px-3 text-sm font-semibold text-muted hover:text-fg">7d</button>
          <button class="h-7 rounded-[7px] px-3 text-sm font-semibold text-muted hover:text-fg">30d</button>
        </div>
      </template>
      <template #meta>
        <StatusPill tone="warning" size="sm" :label="t('dev.overview.preview')" />
      </template>
    </PageHeader>

    <section class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <article v-for="kpi in kpis" :key="kpi.id" class="group flex flex-col rounded-card border border-line bg-surface p-4 transition-colors hover:border-line-strong">
        <div class="flex items-center justify-between">
          <span class="text-sm font-medium text-muted">{{ kpi.label }}</span>
          <ArrowUpRight :size="15" class="text-subtle opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-xl font-semibold tracking-[-0.015em] text-fg">{{ kpi.value }}</span>
          <span v-if="kpi.sub" class="text-sm text-muted">{{ kpi.sub }}</span>
          <span v-if="kpi.hint" class="text-sm text-subtle">{{ kpi.hint }}</span>
        </div>
        <div class="mt-auto flex items-end justify-between gap-3 pt-3">
          <div v-if="kpi.delta" class="flex items-center gap-1.5 text-xs">
            <UiBadge tone="success"><TrendingUp :size="11" class="mr-0.5" />{{ kpi.delta }}</UiBadge>
            <span class="text-muted">{{ t("dev.overview.vsLastWeek") }}</span>
          </div>
          <div v-else-if="kpi.progress" class="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
            <div class="h-full rounded-full" :style="{ width: `${kpi.progress}%`, background: kpi.color }" />
          </div>
          <div v-else-if="kpi.people" class="flex -space-x-1.5">
            <UserAvatar v-for="person in kpi.people" :key="person" :name="person" :size="24" class="ring-2 ring-[var(--c-surface)] rounded-full" />
            <span class="grid h-6 min-w-6 place-items-center rounded-full bg-surface-2 px-1.5 text-[10px] font-semibold text-muted ring-2 ring-[var(--c-surface)]">+13</span>
          </div>
          <span v-else class="flex-1" />
          <svg v-if="kpi.series" viewBox="0 0 120 36" class="h-9 w-[110px] shrink-0" aria-hidden="true">
            <path :d="spark(kpi.series) + ' L120,36 L0,36 Z'" :fill="kpi.color" opacity="0.1" />
            <path :d="spark(kpi.series)" fill="none" :stroke="kpi.color" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
      </article>
    </section>

    <h2 class="mb-3 mt-8 text-md font-semibold text-fg">{{ t("dev.overview.branches") }}</h2>
    <section class="grid grid-cols-1 gap-3 md:grid-cols-3">
      <article v-for="branch in branches" :key="branch.code" class="rounded-card border border-line bg-surface p-4">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h3 class="truncate text-base font-semibold text-fg">{{ branch.name }}</h3>
              <span class="rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] font-semibold text-muted">{{ branch.code }}</span>
            </div>
            <StatusPill class="mt-2" :tone="branch.open ? 'success' : 'danger'" :live="!branch.open" :label="branch.status" size="sm" />
          </div>
          <svg viewBox="0 0 40 40" class="size-11 shrink-0 -rotate-90" aria-hidden="true">
            <circle cx="20" cy="20" r="16" fill="none" stroke="var(--c-surface-2)" stroke-width="4" />
            <circle cx="20" cy="20" r="16" fill="none" :stroke="branch.open ? 'var(--c-success)' : 'var(--c-danger)'" stroke-width="4" stroke-linecap="round" :stroke-dasharray="`${(branch.ring / 100) * 100.5} 100.5`" />
          </svg>
        </div>
        <dl class="mt-4 grid grid-cols-3 gap-2 border-t border-line pt-3 text-sm">
          <div><dt class="text-xs text-muted">{{ t("dev.overview.staff") }}</dt><dd class="mt-0.5 font-semibold text-fg">{{ branch.staff }}</dd></div>
          <div><dt class="text-xs text-muted">{{ t("dev.overview.tills") }}</dt><dd class="mt-0.5 font-semibold text-fg">{{ branch.tills }}</dd></div>
          <div><dt class="text-xs text-muted">{{ t("dev.overview.sales") }}</dt><dd class="mt-0.5 font-semibold text-fg">{{ branch.sales }}</dd></div>
        </dl>
      </article>
    </section>

    <div class="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-5">
      <section class="lg:col-span-3">
        <div class="mb-3 flex items-center gap-2">
          <h2 class="text-md font-semibold text-fg">{{ t("dev.overview.needsYou") }}</h2>
          <UiBadge v-if="queue.data.value" :count="queue.data.value.total" tone="primary" />
          <span class="flex-1" />
          <UiButton variant="ghost" size="sm" :to="{ query: { inbox: 'needs' } }">{{ t("common.viewAll") }}</UiButton>
        </div>
        <div class="overflow-hidden rounded-card border border-line bg-surface">
          <template v-if="queueSkeleton">
            <div v-for="n in 4" :key="n" class="flex items-center gap-3 border-b border-line p-3 last:border-b-0">
              <SkeletonBlock circle height="32px" /><div class="flex flex-1 flex-col gap-1.5"><SkeletonBlock width="60%" /><SkeletonBlock width="35%" height="11px" /></div>
            </div>
          </template>
          <template v-else>
            <RouterLink
              v-for="item in queue.data.value?.results.slice(0, 4) ?? []"
              :key="`${item.kind}:${item.id}`"
              :to="{ query: { inbox: 'needs' } }"
              class="flex items-center gap-3 border-b border-line px-4 py-3 transition-colors last:border-b-0 hover:bg-surface-2/60"
            >
              <UserAvatar :name="item.actor?.name ?? item.title" :size="32" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-base font-medium text-fg">{{ item.title }}</p>
                <p class="truncate text-sm text-muted">{{ item.subtitle }}</p>
              </div>
              <span class="shrink-0 text-xs text-subtle">{{ fmt.relative(item.created_at) }}</span>
            </RouterLink>
          </template>
        </div>
      </section>
      <section class="lg:col-span-2">
        <h2 class="mb-3 text-md font-semibold text-fg">{{ t("dev.overview.activity") }}</h2>
        <ol class="relative flex flex-col gap-4 rounded-card border border-line bg-surface p-4">
          <li v-for="event in activity" :key="event.text" class="flex gap-3">
            <UserAvatar :name="event.name" :size="28" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm text-fg"><span class="font-semibold">{{ event.name }}</span></p>
              <p class="truncate text-sm text-muted">{{ event.text }}</p>
            </div>
            <span class="shrink-0 text-xs text-subtle">{{ ago(event.minutes) }}</span>
          </li>
        </ol>
      </section>
    </div>
  </div>
</template>
