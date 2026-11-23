<script setup lang="ts">
/**
 * Ko‘z › Overview (docs/KOZ.md §6.1): one day of one branch or all of them. The headline numbers
 * against the same day last week (came in, receipts, conversion, left without buying, the longest
 * wait, alerts), each saying why when it is missing; the hour chart; what stood out; the alerts
 * open now and the boxes' status. A company without boxes gets the page that explains Ko‘z and
 * leads to pairing. Branch and day live in the URL.
 */
import { BellRing, Cctv, DoorOpen, Hourglass, Percent, ReceiptText, UserRoundX } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import ChartCard, { type ChartCsv } from "@/components/ChartCard.vue";
import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiCard from "@/components/KpiCard.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useOverview, useSettings } from "../api";
import BoxStatus from "../components/BoxStatus.vue";
import HourChart from "../components/HourChart.vue";
import InsightList from "../components/InsightList.vue";
import OpenAlerts from "../components/OpenAlerts.vue";
import PitchCard from "../components/PitchCard.vue";
import { formatSeconds } from "../lib/format";
import { comparedLeft, conversionPercent, conversionPoints, hourRange, missingReason, needsSetup, percentChange, trimHours } from "../lib/overview";
import { DEFAULT_RULES } from "../lib/rules";
import type { HourRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const branch = useRouteState("branch", rs.optionalNumber());
const day = useRouteState("day", rs.day());
const params = computed(() => ({ branch: branch.value, day: day.value ?? today.value }));
const overview = useOverview(params);
const settings = useSettings();
const queueWaitS = computed(() => settings.data.value?.queue_wait_s ?? DEFAULT_RULES.queue_wait_s);

const data = computed(() => overview.data.value ?? null);
const switching = computed(() => overview.isPlaceholderData.value);
const isToday = computed(() => (day.value ?? today.value) === today.value);
const hours = computed(() => trimHours(data.value?.hours ?? []));
const partialHour = computed(() => (isToday.value && hours.value.length ? hours.value[hours.value.length - 1]!.hour : null));

const branches = computed(() => company.current?.branches ?? []);
const branchOptions = computed(() => [{ value: 0, label: t("vision.filter.allBranches") }, ...branches.value.map((b) => ({ value: b.id, label: b.name }))]);
const branchName = (id: number) => branches.value.find((b) => b.id === id)?.name ?? "";

const compareLabel = computed(() => {
  const label = data.value?.totals.compare?.label;
  return label === "same_weekday_last_week" ? t("vision.compare.same_weekday_last_week") : t("vision.compare.other");
});

function reason(field: Parameters<typeof missingReason>[0]): string | undefined {
  if (!data.value) return undefined;
  const why = missingReason(field, data.value);
  return why ? t(`vision.missing.${why}`) : undefined;
}

const kpis = computed(() => {
  const totals = data.value?.totals;
  if (!totals) return [];
  const compare = totals.compare;
  const conversion = conversionPercent(totals.conversion);
  return [
    {
      id: "visitors",
      label: t("vision.kpi.visitors"),
      value: totals.visitors,
      icon: DoorOpen,
      delta: percentChange(totals.visitors, compare?.visitors),
      deltaLabel: compareLabel.value,
      hint: reason("visitors"),
    },
    {
      id: "receipts",
      label: t("vision.kpi.receipts"),
      value: totals.receipts,
      icon: ReceiptText,
      delta: percentChange(totals.receipts, compare?.receipts),
      deltaLabel: compareLabel.value,
      hint: reason("receipts"),
    },
    {
      id: "conversion",
      label: t("vision.kpi.conversion"),
      value: conversion,
      format: "percent" as const,
      icon: Percent,
      delta: conversionPoints(totals),
      points: true,
      deltaLabel: compareLabel.value,
      hint: reason("conversion") ?? (totals.visitors !== null && totals.receipts !== null ? t("vision.kpi.conversionHint", { receipts: fmt.number(totals.receipts), visitors: fmt.number(totals.visitors) }) : undefined),
    },
    {
      id: "left",
      label: t("vision.kpi.left"),
      value: totals.left,
      icon: UserRoundX,
      delta: percentChange(totals.left, comparedLeft(totals)),
      inverse: true,
      deltaLabel: compareLabel.value,
      hint: reason("left") ?? t("vision.kpi.leftHint"),
    },
    {
      id: "wait",
      label: t("vision.kpi.wait"),
      value: totals.wait_max_s,
      format: (value: number) => formatSeconds(value, fmt.lang.value),
      icon: Hourglass,
      hint: reason("wait") ?? (totals.wait_avg_s !== null ? t("vision.kpi.waitAvg", { wait: formatSeconds(totals.wait_avg_s, fmt.lang.value) }) : undefined),
    },
    {
      id: "alerts",
      label: t("vision.kpi.alerts"),
      value: totals.alerts,
      icon: BellRing,
      hint: totals.unattended_minutes ? t("vision.kpi.unattended", { time: t("vision.hours.minutes", { n: totals.unattended_minutes }) }) : totals.alerts ? undefined : t("vision.kpi.noAlerts"),
      to: `/c/${company.currentId}/vision/alerts`,
    },
  ];
});

const offline = computed(() => (data.value?.agents ?? []).filter((agent) => !agent.online));
const csv = computed(
  () =>
    ({
      filename: `koz-${params.value.day}`,
      columns: [
        { key: "hour", label: t("vision.hours.hour"), value: (row: HourRow) => hourRange(row.hour) },
        { key: "visitors", label: t("vision.hours.visitors") },
        { key: "receipts", label: t("vision.hours.receipts") },
        { key: "queue_max", label: t("vision.hours.queue") },
        { key: "wait_max_s", label: t("vision.hours.waitSeconds") },
        { key: "staff_avg", label: t("vision.hours.atCounter") },
        { key: "staff_checked_in", label: t("vision.hours.onShift") },
        { key: "unattended_minutes", label: t("vision.hours.unattendedMinutes") },
      ],
      rows: hours.value,
    }) as unknown as ChartCsv<never>,
);
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('vision.title')" :description="t('vision.overview.description')">
      <template v-if="!needsSetup(data)" #actions>
        <SelectBox v-if="branches.length > 1" :model-value="branch ?? 0" size="sm" class="w-48 max-sm:w-full" :options="branchOptions" :aria-label="t('vision.filter.branch')" @update:model-value="branch = $event || null" />
        <DatePicker v-model="day" size="sm" :max="today" :placeholder="t('common.today')" format="weekday" class="w-56 max-sm:w-full" />
        <UiButton variant="primary" size="sm" :icon="Cctv" :to="{ path: `/c/${company.currentId}/vision/live`, query: branch ? { branch } : {} }">{{ t("vision.overview.live") }}</UiButton>
      </template>
    </PageHeader>

    <template v-if="overview.isPending.value">
      <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6"><SkeletonBlock v-for="n in 6" :key="n" height="118px" radius="12px" /></div>
      <SkeletonBlock height="380px" radius="12px" />
      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]"><SkeletonBlock height="240px" radius="12px" /><SkeletonBlock height="240px" radius="12px" /></div>
    </template>
    <ErrorState v-else-if="overview.isError.value && !data" class="ui-card" :error="overview.error.value" :retry="() => overview.refetch()" />
    <PitchCard v-else-if="needsSetup(data)" :can-manage="company.can('vision.manage')" />

    <template v-else-if="data">
      <div v-if="!data.setup.entrance || !data.setup.counter || offline.length" class="flex flex-col gap-2">
        <InlineAlert v-if="!data.setup.entrance" tone="info" size="sm" :title="t('vision.setup.noEntrance.title')" :description="t('vision.setup.noEntrance.body')" data-setup="entrance">
          <template v-if="company.can('vision.manage')" #actions><UiButton size="sm" variant="secondary" :to="`/c/${company.currentId}/vision/cameras`">{{ t("vision.setup.action") }}</UiButton></template>
        </InlineAlert>
        <InlineAlert v-if="!data.setup.counter" tone="info" size="sm" :title="t('vision.setup.noCounter.title')" :description="t('vision.setup.noCounter.body')" data-setup="counter">
          <template v-if="company.can('vision.manage')" #actions><UiButton size="sm" variant="secondary" :to="`/c/${company.currentId}/vision/cameras`">{{ t("vision.setup.action") }}</UiButton></template>
        </InlineAlert>
        <InlineAlert
          v-for="agent in offline"
          :key="agent.id"
          tone="warning"
          size="sm"
          :description="t('vision.setup.offline', { name: agent.name, time: agent.last_seen_at ? fmt.relative(agent.last_seen_at) : '—' })"
          data-setup="offline"
        />
      </div>

      <div :class="['grid grid-cols-2 gap-3 transition-opacity md:grid-cols-3 xl:grid-cols-6', switching && 'opacity-60']" data-headline>
        <KpiCard v-for="kpi in kpis" :key="kpi.id" v-bind="kpi" :loading="switching" :data-kpi="kpi.id" />
      </div>

      <ChartCard :title="t('vision.hours.title')" :subtitle="t('vision.hours.subtitle')" :loading="switching" :empty="!hours.length" :empty-text="t('vision.hours.empty')" :csv="csv" height="320px">
        <HourChart :hours="hours" :queue-wait-s="queueWaitS" :partial-hour="partialHour" />
      </ChartCard>

      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
        <InsightList :insights="data.insights" :loading="switching" />
        <div class="flex min-w-0 flex-col gap-4">
          <OpenAlerts v-if="isToday" :alerts="data.open_alerts" />
          <BoxStatus v-if="data.agents.length" :agents="data.agents" :branch-name="branchName" />
        </div>
      </div>
    </template>
  </div>
</template>
