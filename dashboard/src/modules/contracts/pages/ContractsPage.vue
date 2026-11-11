<script setup lang="ts">
/**
 * Contracts (Shartnomalar): the business's leases, supply and service contracts, licences and
 * insurance. What they cost a month and what needs a look on top; chips for what ends soon,
 * drafts and the ended ones; a kind filter and search (the branch comes from the sidebar's
 * branch filter). Each row shows who with, the money, its term and the next date that matters.
 * `?new=1` opens the form (the command palette).
 */
import { CalendarClock, ChevronRight, FilePlus2, FileSignature, Paperclip, RefreshCw } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useContracts, useSummary } from "../api";
import ContractFormDialog from "../components/ContractFormDialog.vue";
import TermBar from "../components/TermBar.vue";
import { byAttention, dayTone, KIND_ICONS, KIND_TILES, STATUS_TONES } from "../lib";
import { KINDS, type ContractRow } from "../types";

type View = "all" | "ending" | "draft" | "past";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();
const today = useCompanyToday();

const search = useRouteState("q", rs.string(""));
const kind = useRouteState("kind", rs.string(""));
const view = useRouteState("view", rs.string("all"));
const creating = useRouteState("new", rs.boolean(false));

const canManage = computed(() => company.can("finance.manage"));
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const params = computed(() => ({
  q: search.value || undefined,
  kind: kind.value || undefined,
  branch: branch.value,
  ending: view.value === "ending" ? true : undefined,
  status: view.value === "draft" ? "draft" : view.value === "past" ? "all" : undefined,
}));
const list = useContracts(params);
const summary = useSummary(computed(() => ({ branch: branch.value })));

const rows = computed<ContractRow[]>(() => {
  const found = list.data.value ?? [];
  if (view.value === "past") return found.filter((row) => row.status === "ended" || row.status === "terminated");
  return found;
});
const groups = computed(() => {
  const sorted = byAttention(rows.value);
  if (view.value !== "all") return [{ id: view.value, rows: sorted }];
  const look = sorted.filter((row) => row.attention);
  const rest = sorted.filter((row) => !row.attention);
  return [
    { id: "attention", rows: look },
    { id: "all", rows: rest },
  ].filter((group) => group.rows.length);
});

const kpis = computed(() => {
  const data = summary.data.value;
  return [
    { id: "in_force", label: t("contracts.kpi.inForce"), value: data?.in_force ?? null, format: "number" as const, hint: data ? t("contracts.kpi.total", { n: data.total }, data.total) : undefined },
    {
      id: "monthly",
      label: t("contracts.kpi.monthly"),
      value: data?.monthly_cost ?? null,
      format: "money" as const,
      compact: true,
      currency: data?.currency,
      hint: data?.unpriced ? t("contracts.kpi.unpriced", { n: data.unpriced }, data.unpriced) : t("contracts.kpi.monthlyHint"),
    },
    { id: "ending", label: t("contracts.kpi.ending"), value: data?.ending_soon ?? null, format: "number" as const, hint: data ? t("contracts.kpi.endingHint", { n: data.remind_days }, data.remind_days) : undefined },
    { id: "notice", label: t("contracts.kpi.notice"), value: data?.notice_due ?? null, format: "number" as const, hint: t("contracts.kpi.noticeHint") },
  ];
});

const views = computed(() => {
  const ending = (summary.data.value?.ending_soon ?? 0) + (summary.data.value?.notice_due ?? 0);
  return [
    { value: "all" as View, label: t("contracts.view.all") },
    { value: "ending" as View, label: t("contracts.view.ending"), count: ending || undefined },
    { value: "draft" as View, label: t("contracts.view.draft") },
    { value: "past" as View, label: t("contracts.view.past") },
  ];
});
const viewModel = computed<View>({ get: () => (["all", "ending", "draft", "past"].includes(view.value) ? (view.value as View) : "all"), set: (value) => (view.value = value) });
const kindOptions = computed(() => KINDS.map((value) => ({ value, label: t(`contracts.kind.${value}`) })));
const kindModel = computed({ get: () => kind.value || null, set: (value: string | null) => (kind.value = value ?? "") });
const filtered = computed(() => Boolean(search.value || kind.value || view.value !== "all"));

function link(row: ContractRow): string {
  return `/c/${company.currentId}/contracts/${row.id}`;
}

/** "Ends in 45 days", "Notice by 22 Nov", "Ended 3 Oct", "No end date". */
function when(row: ContractRow): string {
  if (row.status === "terminated") return row.ends_on ? t("contracts.when.terminated", { day: fmt.day(row.ends_on, "medium") }) : t(`contracts.status.terminated`);
  if (row.status === "ended") return row.ends_on ? t("contracts.when.ended", { day: fmt.day(row.ends_on, "medium") }) : t(`contracts.status.ended`);
  if (!row.key_day || row.days_left === null) return t("contracts.when.open");
  if (row.attention === "notice" || (row.auto_renews && row.notice_deadline === row.key_day)) {
    return row.days_left === 0 ? t("contracts.when.noticeToday") : t("contracts.when.notice", { day: fmt.day(row.key_day, "short"), n: row.days_left }, row.days_left);
  }
  if (row.days_left === 0) return t("contracts.when.endsToday");
  if (row.auto_renews) return t("contracts.when.renews", { day: fmt.day(row.key_day, "medium") });
  return t("contracts.when.ends", { n: row.days_left, day: fmt.day(row.key_day, "short") }, row.days_left);
}

function details(row: ContractRow): string {
  const parts = [row.counterparty?.name, row.number ? `№ ${row.number}` : "", row.branch?.name ?? t("contracts.wholeCompany")];
  return parts.filter(Boolean).join(" · ");
}

function saved(id: number): void {
  void router.push(link({ id } as ContractRow));
}

function clear(): void {
  search.value = "";
  kind.value = "";
  view.value = "all";
}
</script>

<template>
  <div>
    <PageHeader :title="t('contracts.title')" :description="t('contracts.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="FilePlus2" data-testid="contracts-new" @click="creating = true">{{ t("contracts.new") }}</UiButton>
      </template>
    </PageHeader>

    <KpiStrip class="mb-4" :items="kpis" :loading="summary.isPending.value" :columns="4" phone="grid" />

    <div class="mb-4 flex flex-wrap items-center gap-2">
      <SegmentedControl v-model="viewModel" :options="views" size="sm" data-testid="contracts-views" />
      <div class="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
        <SelectBox v-model="kindModel" size="sm" class="w-full sm:w-48" :options="kindOptions" clearable :placeholder="t('contracts.filter.anyKind')" />
        <TextInput v-model="search" :debounce="300" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('contracts.filter.search')" clearable />
      </div>
    </div>

    <ErrorState v-if="list.isError.value" :error="list.error.value" :retry="() => list.refetch()" />
    <div v-else-if="list.isPending.value" class="grid gap-3">
      <SkeletonBlock v-for="n in 4" :key="n" height="84px" radius="14px" />
    </div>
    <div v-else-if="!rows.length" class="ui-card">
      <EmptyState
        v-if="!filtered"
        :icon="FileSignature"
        :title="t('contracts.empty.title')"
        :description="t('contracts.empty.body')"
      >
        <UiButton v-if="canManage" variant="primary" :icon="FilePlus2" @click="creating = true">{{ t("contracts.new") }}</UiButton>
      </EmptyState>
      <EmptyState v-else :icon="FileSignature" :title="t('contracts.empty.filteredTitle')" :description="t('contracts.empty.filteredBody')">
        <UiButton variant="secondary" @click="clear">{{ t("contracts.filter.clear") }}</UiButton>
      </EmptyState>
    </div>

    <div v-else class="flex flex-col gap-4">
      <PageSection
        v-for="group in groups"
        :key="group.id"
        variant="card"
        flush
        :title="t(`contracts.group.${group.id}`)"
        :count="group.rows.length"
      >
        <ul class="divide-y divide-line" :data-testid="`contracts-${group.id}`">
          <li v-for="row in group.rows" :key="row.id">
            <RouterLink
              :to="link(row)"
              class="group relative flex items-center gap-3.5 px-4 py-3.5 transition-colors hover:bg-surface-2/60 focus-visible:bg-surface-2/60 focus-visible:outline-none"
              :class="row.attention && 'bg-warning-soft/40'"
              :data-testid="`contract-row-${row.id}`"
            >
              <span class="grid size-10 shrink-0 place-items-center rounded-[11px]" :class="KIND_TILES[row.kind]">
                <component :is="KIND_ICONS[row.kind]" :size="19" aria-hidden="true" />
              </span>
              <span class="flex min-w-0 flex-1 flex-col gap-1.5">
                <span class="flex min-w-0 items-center gap-2">
                  <span class="truncate font-medium text-fg">{{ row.title }}</span>
                  <StatusPill v-if="row.status !== 'active'" size="sm" :tone="STATUS_TONES[row.status]" :label="t(`contracts.status.${row.status}`)" />
                  <RefreshCw v-if="row.auto_renews && row.status !== 'ended' && row.status !== 'terminated'" :size="13" class="shrink-0 text-info" :aria-label="t('contracts.autoRenews')" />
                  <span v-if="row.files" class="hidden shrink-0 items-center gap-0.5 text-xs text-subtle sm:inline-flex"><Paperclip :size="12" aria-hidden="true" />{{ row.files }}</span>
                </span>
                <span class="truncate text-xs text-muted">{{ t(`contracts.kind.${row.kind}`) }} · {{ details(row) }}</span>
                <TermBar
                  class="max-w-[420px]"
                  compact
                  :starts-on="row.term_starts_on"
                  :ends-on="row.ends_on"
                  :today="today"
                  :status="row.status"
                  :auto-renews="row.auto_renews"
                />
                <!-- Phones: the money and the next date under the name. -->
                <span class="flex flex-wrap items-center gap-x-3 gap-y-1 sm:hidden">
                  <span v-if="row.amount" class="text-sm font-semibold tabular-nums text-fg">
                    <MoneyText :value="row.amount" :currency="row.currency" decimals="auto" />
                    <span class="ml-1 text-xs font-normal text-muted">{{ t(`contracts.per.${row.period}`) }}</span>
                  </span>
                  <StatusPill size="sm" variant="plain" :tone="dayTone(row)" :icon="CalendarClock" :label="when(row)" />
                </span>
              </span>
              <span class="hidden shrink-0 flex-col items-end gap-1 sm:flex">
                <span v-if="row.amount" class="text-sm font-semibold tabular-nums text-fg">
                  <MoneyText :value="row.amount" :currency="row.currency" decimals="auto" />
                  <span class="ml-1 text-xs font-normal text-muted">{{ t(`contracts.per.${row.period}`) }}</span>
                </span>
                <StatusPill size="sm" variant="plain" :tone="dayTone(row)" :icon="CalendarClock" :label="when(row)" />
              </span>
              <ChevronRight :size="16" class="shrink-0 text-subtle transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </RouterLink>
          </li>
        </ul>
      </PageSection>
    </div>

    <ContractFormDialog v-model:open="creating" @saved="saved" />
  </div>
</template>
