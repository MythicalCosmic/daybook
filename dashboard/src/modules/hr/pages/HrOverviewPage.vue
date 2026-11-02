<script setup lang="ts">
/**
 * HR overview (the module's first page): the numbers that need attention (people, documents
 * expiring or expired, contracts ending, probation ending, birthdays this week) and, under them,
 * the lists behind those numbers with a one-tap action each: upload the new document, renew the
 * contract, pass or extend probation. Without hr.manage the same page reads only.
 */
import { ArrowRight, BadgeCheck, CalendarPlus, Cake, CircleCheck, Clock4, FilePlus2, FileSignature, FileWarning, Upload, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useOverview } from "../api";
import ContractActionDialog from "../components/ContractActionDialog.vue";
import DaysChip from "../components/DaysChip.vue";
import DocumentFormDrawer from "../components/DocumentFormDrawer.vue";
import { daysUntil, hrAccess } from "../lib";
import type { ExpiringDocument } from "../types";
import { useContractActions } from "../useContractActions";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const overview = useOverview();
const data = computed(() => overview.data.value ?? null);
const skeleton = useDelayedPending(computed(() => overview.isPending.value));
const base = computed(() => `/c/${company.currentId}`);
const warn = computed(() => data.value?.warn_days ?? { documents: 30, contracts: 30, probation: 7 });

const headcount = computed(() => {
  const summary = data.value?.headcount;
  if (!summary) return { value: null, previous: null, spark: [] as number[] };
  return {
    value: Number(summary.totals.headcount ?? 0),
    previous: summary.previous ? Number(summary.previous.headcount ?? 0) : null,
    spark: summary.series.map((point) => Number(point.headcount ?? 0)),
  };
});

const kpis = computed(() => {
  const d = data.value;
  return [
    {
      id: "headcount",
      label: t("hr.overview.kpi.headcount"),
      value: headcount.value.value,
      previous: headcount.value.previous,
      deltaLabel: t("hr.overview.kpi.vs30"),
      spark: headcount.value.spark,
      icon: Users,
      to: `${base.value}/people`,
    },
    {
      id: "documents",
      label: t("hr.overview.kpi.documents"),
      value: d ? d.documents.expiring + d.documents.expired : null,
      hint: d ? (d.documents.expired ? t("hr.overview.kpi.expired", { n: d.documents.expired }, d.documents.expired) : t("hr.overview.kpi.within", { n: warn.value.documents }, warn.value.documents)) : undefined,
      icon: FileWarning,
      to: { path: `${base.value}/hr/documents`, query: { state: d?.documents.expired && !d.documents.expiring ? "expired" : "expiring" } },
    },
    {
      id: "contracts",
      label: t("hr.overview.kpi.contracts"),
      value: d?.contracts.ending ?? null,
      hint: t("hr.overview.kpi.within", { n: warn.value.contracts }, warn.value.contracts),
      icon: FileSignature,
      to: { path: `${base.value}/hr/contracts`, query: { ending: "true" } },
    },
    {
      id: "probation",
      label: t("hr.overview.kpi.probation"),
      value: d?.probation.ending ?? null,
      hint: t("hr.overview.kpi.within", { n: warn.value.probation }, warn.value.probation),
      icon: Clock4,
      to: { path: `${base.value}/hr/contracts`, query: { probation: "true" } },
    },
    {
      id: "birthdays",
      label: t("hr.overview.kpi.birthdays"),
      value: d?.birthdays.length ?? null,
      hint: t("hr.overview.kpi.nextDays"),
      icon: Cake,
      to: `${base.value}/hr/celebrations`,
    },
  ];
});

// Upload the renewed document, prefilled with the person and the kind.
const uploading = ref(false);
const uploadFor = ref<ExpiringDocument | null>(null);
function upload(row: ExpiringDocument | null): void {
  uploadFor.value = row;
  uploading.value = true;
}

const { request: actionRequest, run: runAction, perform } = useContractActions();

function birthdayLabel(day: string): string {
  const left = daysUntil(day, today.value);
  if (left === 0) return t("hr.overview.today");
  if (left === 1) return t("hr.overview.tomorrow");
  return fmt.day(day, "weekday");
}
</script>

<template>
  <div>
    <PageHeader :title="t('hr.title')" :description="t('hr.overview.description')">
      <template v-if="access.manage" #actions>
        <UiButton :icon="FilePlus2" @click="upload(null)">{{ t("hr.document.upload") }}</UiButton>
        <UiButton variant="primary" :icon="FileSignature" :to="`${base}/hr/contracts?new=1`">{{ t("hr.contract.new") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="overview.isError.value" class="ui-card" :error="overview.error.value" :retry="() => overview.refetch()" />

    <div v-else class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="overview.isPending.value" :columns="5" phone="grid" />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <!-- Documents to renew -->
        <section class="ui-card flex flex-col p-4" :aria-label="t('hr.overview.documents')">
          <header class="mb-2 flex items-center gap-2">
            <FileWarning :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="flex-1 text-sm font-semibold text-fg">{{ t("hr.overview.documents") }}</h2>
            <RouterLink :to="{ path: `${base}/hr/documents`, query: { state: 'expiring' } }" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
              {{ t("common.viewAll") }}<ArrowRight :size="14" />
            </RouterLink>
          </header>
          <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="48px" /></div>
          <EmptyState v-else-if="data && !data.documents.items.length" size="sm" tone="success" :icon="CircleCheck" :title="t('hr.overview.documentsEmpty')" :description="t('hr.overview.documentsEmptyBody', { n: warn.documents }, warn.documents)" />
          <ul v-else-if="data" class="-mx-2 flex flex-col">
            <li v-for="row in data.documents.items" :key="row.id" class="flex items-center gap-1 rounded-[10px] pr-1 hover:bg-highlight">
              <RouterLink :to="{ path: `${base}/hr/documents`, query: { document: String(row.id) } }" class="flex min-h-12 min-w-0 flex-1 items-center gap-3 px-2 py-1.5">
                <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="32" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-fg">{{ row.member.name }}</p>
                  <p class="truncate text-xs text-muted">{{ row.title || t(`hr.kind.${row.kind}`) }} · {{ fmt.day(row.expires_on, "short") }}</p>
                </div>
                <DaysChip :day="row.expires_on" :warn-days="warn.documents" prefix="expires" always />
              </RouterLink>
              <UiButton v-if="access.manage" size="md" variant="ghost" class="max-sm:h-10" :icon="Upload" :aria-label="t('hr.overview.uploadNew')" @click="upload(row)">
                <span class="max-sm:sr-only">{{ t("hr.overview.uploadNew") }}</span>
              </UiButton>
            </li>
          </ul>
        </section>

        <!-- Contracts ending -->
        <section class="ui-card flex flex-col p-4" :aria-label="t('hr.overview.contracts')">
          <header class="mb-2 flex items-center gap-2">
            <FileSignature :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="flex-1 text-sm font-semibold text-fg">{{ t("hr.overview.contracts") }}</h2>
            <RouterLink :to="{ path: `${base}/hr/contracts`, query: { ending: 'true' } }" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
              {{ t("common.viewAll") }}<ArrowRight :size="14" />
            </RouterLink>
          </header>
          <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="48px" /></div>
          <EmptyState v-else-if="data && !data.contracts.items.length" size="sm" tone="success" :icon="CircleCheck" :title="t('hr.overview.contractsEmpty')" :description="t('hr.overview.contractsEmptyBody', { n: warn.contracts }, warn.contracts)" />
          <ul v-else-if="data" class="-mx-2 flex flex-col">
            <li v-for="row in data.contracts.items" :key="row.id" class="flex items-center gap-1 rounded-[10px] pr-1 hover:bg-highlight">
              <RouterLink :to="{ path: `${base}/hr/contracts`, query: { contract: String(row.id) } }" class="flex min-h-12 min-w-0 flex-1 items-center gap-3 px-2 py-1.5">
                <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="32" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-fg">{{ row.member.name }}</p>
                  <p class="truncate text-xs text-muted">{{ t(`hr.contractKind.${row.kind}`) }} · {{ fmt.day(row.ends_on, "short") }}</p>
                </div>
                <DaysChip :day="row.ends_on" :warn-days="warn.contracts" prefix="ends" always />
              </RouterLink>
              <UiButton v-if="access.manage" size="md" variant="ghost" class="max-sm:h-10" :icon="CalendarPlus" :aria-label="t('hr.contract.action.renew')" @click="runAction(row, 'renew')">
                <span class="max-sm:sr-only">{{ t("hr.contract.action.renew") }}</span>
              </UiButton>
            </li>
          </ul>
        </section>

        <!-- Probation ending -->
        <section class="ui-card flex flex-col p-4" :aria-label="t('hr.overview.probation')">
          <header class="mb-2 flex items-center gap-2">
            <Clock4 :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="flex-1 text-sm font-semibold text-fg">{{ t("hr.overview.probation") }}</h2>
            <RouterLink :to="{ path: `${base}/hr/contracts`, query: { probation: 'true' } }" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
              {{ t("common.viewAll") }}<ArrowRight :size="14" />
            </RouterLink>
          </header>
          <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="48px" /></div>
          <EmptyState v-else-if="data && !data.probation.items.length" size="sm" tone="success" :icon="CircleCheck" :title="t('hr.overview.probationEmpty')" :description="t('hr.overview.probationEmptyBody')" />
          <ul v-else-if="data" class="-mx-2 flex flex-col">
            <li v-for="row in data.probation.items" :key="row.id" class="flex flex-wrap items-center gap-1 rounded-[10px] pr-1 hover:bg-highlight">
              <RouterLink :to="{ path: `${base}/hr/contracts`, query: { contract: String(row.id) } }" class="flex min-h-12 min-w-[200px] flex-1 items-center gap-3 px-2 py-1.5">
                <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="32" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-fg">{{ row.member.name }}</p>
                  <p class="truncate text-xs text-muted">{{ t("hr.overview.probationUntil", { date: fmt.day(row.probation_until, "short") }) }}</p>
                </div>
                <DaysChip :day="row.probation_until" :warn-days="warn.probation" prefix="probation" always />
              </RouterLink>
              <div v-if="access.manage" class="flex shrink-0 items-center gap-1 max-sm:w-full max-sm:justify-end max-sm:pb-1.5">
                <UiButton size="md" variant="ghost" class="max-sm:h-10" :icon="Clock4" @click="runAction(row, 'extend-probation')">{{ t("hr.contract.action.extend-probation") }}</UiButton>
                <UiButton size="md" variant="soft" class="max-sm:h-10" :icon="BadgeCheck" @click="runAction(row, 'pass-probation')">{{ t("hr.contract.action.pass-probation") }}</UiButton>
              </div>
            </li>
          </ul>
        </section>

        <!-- Birthdays -->
        <section class="ui-card flex flex-col p-4" :aria-label="t('hr.overview.birthdays')">
          <header class="mb-2 flex items-center gap-2">
            <Cake :size="16" class="text-subtle" aria-hidden="true" />
            <h2 class="flex-1 text-sm font-semibold text-fg">{{ t("hr.overview.birthdays") }}</h2>
            <RouterLink :to="`${base}/hr/celebrations`" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
              {{ t("hr.overview.allCelebrations") }}<ArrowRight :size="14" />
            </RouterLink>
          </header>
          <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="48px" /></div>
          <EmptyState v-else-if="data && !data.birthdays.length" size="sm" tone="neutral" :icon="Cake" :title="t('hr.overview.birthdaysEmpty')" :description="t('hr.overview.birthdaysEmptyBody')" />
          <ul v-else-if="data" class="-mx-2 flex flex-col">
            <li v-for="row in data.birthdays" :key="`${row.member.id}-${row.day}`">
              <RouterLink :to="`${base}/people/${row.member.id}`" class="flex min-h-12 items-center gap-3 rounded-[10px] px-2 py-1.5 hover:bg-highlight">
                <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="32" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-fg">{{ row.member.name }}</p>
                  <p v-if="row.position" class="truncate text-xs text-muted">{{ row.position }}</p>
                </div>
                <span :class="['shrink-0 text-sm', daysUntil(row.day, today) === 0 ? 'font-semibold text-primary' : 'text-muted']">{{ birthdayLabel(row.day) }}</span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <DocumentFormDrawer v-model:open="uploading" :member="uploadFor?.member ?? null" :kind="uploadFor?.kind ?? null" />
    <ContractActionDialog v-model:request="actionRequest" :perform="perform" />
  </div>
</template>
