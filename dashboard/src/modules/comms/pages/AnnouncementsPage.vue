<script setup lang="ts">
/**
 * Announcements (plan §6.2): everything sent and scheduled, with who it went to and how many have
 * read it. Status tabs and search live in the URL; a row opens the announcement.
 */
import { CalendarClock, Megaphone, Pin, SquarePen } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useAnnouncements, useStats } from "../api";
import AudienceChips from "../components/AudienceChips.vue";
import type { Announcement, AnnouncementStatus } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();

type Tab = "all" | "sent" | "scheduled" | "pinned" | "cancelled";
const tab = useRouteState<Tab>("tab", rs.enum(["all", "sent", "scheduled", "pinned", "cancelled"] as const, "all"));
const search = useRouteState("q", rs.string(""));
const stats = useStats();
const table = useDataTable({ id: "comms.list", url: true, pageSize: 25, pageSizes: [25, 50, 100] });
watch([tab, search], () => table.resetPage());

const params = computed(() => {
  const status: AnnouncementStatus[] | undefined = tab.value === "sent" ? ["sent"] : tab.value === "scheduled" ? ["scheduled"] : tab.value === "cancelled" ? ["cancelled"] : undefined;
  return { status, pinned: tab.value === "pinned" ? "true" : undefined, q: search.value || undefined, ...table.params.value };
});
const query = useAnnouncements(params);

const tabs = computed(() => [
  { id: "all", label: t("comms.tab.all") },
  { id: "sent", label: t("comms.tab.sent") },
  { id: "scheduled", label: t("comms.tab.scheduled"), count: stats.data.value?.scheduled || undefined },
  { id: "pinned", label: t("comms.tab.pinned"), count: stats.data.value?.pinned || undefined },
  { id: "cancelled", label: t("comms.tab.cancelled") },
]);

const kpis = computed(() => {
  const s = stats.data.value;
  return [
    { id: "sent", label: t("comms.kpi.sent"), value: s?.sent_30d, hint: t("comms.kpi.last30") },
    { id: "rate", label: t("comms.kpi.readRate"), value: s?.read_rate_30d !== null && s?.read_rate_30d !== undefined ? Number(s.read_rate_30d) : null, format: (v: number) => fmt.percent(v, 1), hint: t("comms.kpi.last30") },
    { id: "unread", label: t("comms.kpi.unread"), value: s?.unread_people_30d, hint: t("comms.kpi.unreadHint") },
    { id: "scheduled", label: t("comms.kpi.scheduled"), value: s?.scheduled, hint: t("comms.kpi.scheduledHint") },
  ];
});

const TONES: Record<AnnouncementStatus, StatusTone> = { draft: "neutral", scheduled: "info", sent: "success", cancelled: "neutral" };

function when(row: Announcement): string {
  if (row.status === "scheduled" && row.scheduled_for) return fmt.instant(row.scheduled_for, "short");
  if (row.sent_at) return fmt.relative(row.sent_at);
  return fmt.instant(row.created_at, "short");
}
function rate(row: Announcement): number {
  return row.recipients_count ? (row.read_count / row.recipients_count) * 100 : 0;
}
function rateTone(value: number): "success" | "warning" | "danger" {
  return value >= 80 ? "success" : value >= 50 ? "warning" : "danger";
}

const columns = computed<TableColumn<Announcement>[]>(() => [
  { id: "title", header: t("comms.col.announcement"), minWidth: 300, sticky: true, hideable: false },
  { id: "audience", header: t("comms.col.audience"), width: 220, value: (row) => [...row.branches, ...row.positions].map((x) => x.name).join(", ") || t("comms.audience.everyone") },
  { id: "when", header: t("comms.col.when"), width: 150, value: (row) => when(row) },
  { id: "read", header: t("comms.col.read"), width: 190, value: (row) => row.read_rate ?? "" },
  { id: "status", header: t("comms.col.status"), width: 130, value: (row) => t(`comms.status.${row.status}`) },
]);

function open(row: Announcement): void {
  void router.push(`/c/${company.currentId}/announcements/${row.id}`);
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader v-model:tab="tab" :title="t('comms.list.title')" :description="t('comms.list.description')" :tabs="tabs">
      <template #actions>
        <UiButton variant="primary" :icon="SquarePen" :to="`/c/${company.currentId}/announcements/new`">{{ t("comms.cmd.new") }}</UiButton>
      </template>
    </PageHeader>

    <KpiStrip :items="kpis" :loading="stats.isPending.value" :columns="4" />

    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      row-key="id"
      clickable
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="!!search || tab !== 'all'"
      csv-name="Announcements"
      :empty-title="t('comms.list.emptyTitle')"
      :empty-description="t('comms.list.emptyBody')"
      :empty-icon="Megaphone"
      @row-click="open"
      @clear-filters="
        search = '';
        tab = 'all';
      "
    >
      <template #toolbar>
        <TextInput v-model="search" class="w-full sm:w-[300px]" size="sm" :placeholder="t('comms.list.search')" clearable />
      </template>
      <template #cell-title="{ row }">
        <div class="flex min-w-0 items-start gap-2.5 py-0.5">
          <UserAvatar :name="row.author?.name ?? '—'" :src="row.author?.photo_url" :size="28" class="mt-0.5" />
          <div class="min-w-0">
            <p class="flex items-center gap-1.5 truncate text-base font-medium text-fg">
              <Pin v-if="row.is_pinned" :size="13" class="shrink-0 text-primary" :aria-label="t('comms.pinned')" />{{ row.title }}
            </p>
            <p class="truncate text-xs text-muted">{{ row.author?.name ?? "—" }}</p>
          </div>
        </div>
      </template>
      <template #cell-audience="{ row }"><AudienceChips :announcement="row" :max="2" /></template>
      <template #cell-when="{ row }">
        <span class="inline-flex items-center gap-1.5 text-sm text-fg">
          <CalendarClock v-if="row.status === 'scheduled'" :size="13" class="text-info" aria-hidden="true" />{{ when(row) }}
        </span>
      </template>
      <template #cell-read="{ row }">
        <div v-if="row.status === 'sent' && row.recipients_count" class="flex min-w-0 items-center gap-2">
          <ProgressBar class="w-20" size="sm" :value="rate(row)" :tone="rateTone(rate(row))" />
          <span class="whitespace-nowrap text-sm tabular-nums text-fg">{{ row.read_count }}/{{ row.recipients_count }}</span>
        </div>
        <span v-else class="text-sm text-subtle">—</span>
      </template>
      <template #cell-status="{ row }">
        <StatusPill size="sm" :tone="row.is_expired ? 'neutral' : TONES[row.status]" :label="row.is_expired ? t('comms.status.expired') : t(`comms.status.${row.status}`)" />
      </template>
      <template #card="{ row }">
        <div class="flex items-start justify-between gap-3">
          <p class="flex min-w-0 items-center gap-1.5 text-base font-semibold text-fg"><Pin v-if="row.is_pinned" :size="13" class="shrink-0 text-primary" /><span class="truncate">{{ row.title }}</span></p>
          <StatusPill size="sm" :tone="row.is_expired ? 'neutral' : TONES[row.status]" :label="row.is_expired ? t('comms.status.expired') : t(`comms.status.${row.status}`)" />
        </div>
        <p class="mt-1 text-xs text-muted">{{ row.author?.name ?? "—" }} · {{ when(row) }}</p>
        <div v-if="row.status === 'sent' && row.recipients_count" class="mt-2 flex items-center gap-2">
          <ProgressBar class="flex-1" size="sm" :value="rate(row)" :tone="rateTone(rate(row))" />
          <span class="text-xs tabular-nums text-muted">{{ t("comms.readOf", { read: row.read_count, total: row.recipients_count }) }}</span>
        </div>
      </template>
    </DataTable>
  </div>
</template>
