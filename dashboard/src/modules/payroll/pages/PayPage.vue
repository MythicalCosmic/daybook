<script setup lang="ts">
/**
 * Pay setups (plan §6.2 "Pay setups table with history"): everyone with their pay now (type,
 * amount, proration, overtime and task rates), when it started and what changes next; people with
 * no pay setup stand out. A row opens the person's history (`?member=`) with "Change pay".
 * `?missing=1` shows only the people without one (a run's warning links here).
 */
import { CalendarClock, Clock3, Lock, Search, UserRoundX, WalletCards } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useCompanyPeople } from "@/components/pickers";
import { normalize } from "@/components/options";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useCompensations } from "../api";
import PayAmount from "../components/PayAmount.vue";
import PayDrawer from "../components/PayDrawer.vue";
import { payRows } from "../lib";
import type { Member, PayRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const compensations = useCompensations();
// The team list names everyone, also those without a pay setup (members.view; without it, only
// the people who have one are listed).
const peopleQuery = useCompanyPeople(
  computed(() => company.can("members.view")),
  computed(() => ({ status: "active" })),
);
const people = computed<Member[]>(() => (peopleQuery.data.value ?? []).map((person) => ({ id: person.id, name: person.name, photo_url: person.photo_url ?? null, position: person.subtitle ?? null })));
const rows = computed(() => payRows(people.value, compensations.data.value ?? [], today.value));

const missingOnly = useRouteState("missing", rs.boolean(false));
const type = useRouteState("type", rs.enum(["all", "monthly", "daily", "hourly", "per_task"] as const, "all"));
const search = ref("");
const visible = computed(() => {
  const needle = normalize(search.value.trim());
  return rows.value
    .filter((row) => (missingOnly.value ? !row.current : true))
    .filter((row) => (type.value === "all" ? true : row.current?.pay_type === type.value))
    .filter((row) => !needle || normalize(`${row.member.name} ${row.member.position ?? ""}`).includes(needle));
});
const missing = computed(() => rows.value.filter((row) => !row.current).length);
const filtered = computed(() => missingOnly.value || type.value !== "all" || !!search.value);

const table = useDataTable({ id: "payroll.pay", pageSize: 500, hidden: ["proration"] });
const columns = computed<TableColumn<PayRow>[]>(() => [
  { id: "person", header: t("payroll.payslips.person"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "type", header: t("payroll.pay.type"), width: 130, value: (row) => (row.current ? t(`payroll.payType.${row.current.pay_type}`) : "") },
  { id: "amount", header: t("payroll.pay.amount"), width: 170, numeric: true, value: (row) => row.current?.amount ?? null },
  { id: "proration", header: t("payroll.pay.proration"), width: 150, value: (row) => (row.current ? t(`payroll.proration.${row.current.proration}`) : "") },
  { id: "extras", header: t("payroll.pay.extras"), width: 190, value: (row) => [row.current?.overtime_eligible ? t("payroll.pay.overtime") : "", row.current?.pays_task_rates ? t("payroll.pay.taskRates") : ""].filter(Boolean).join(", ") },
  { id: "since", header: t("payroll.pay.since"), width: 150, value: (row) => row.current?.effective_from ?? "" },
]);

const activeKey = computed(() => (typeof route.query.member === "string" ? route.query.member : null));
function open(row: PayRow): void {
  void router.push({ query: { ...route.query, member: String(row.member.id) } });
}
const per = (row: PayRow) => (row.current ? t(`payroll.pay.per.${row.current.pay_type}`) : "");
const loading = computed(() => compensations.isPending.value || (company.can("members.view") && peopleQuery.isPending.value));
</script>

<template>
  <div>
    <PageHeader :title="t('payroll.nav.pay')" :description="t('payroll.pay.description')" />

    <DataTable
      :state="table"
      :columns="columns"
      :rows="visible"
      :row-key="(row: PayRow) => row.member.id"
      :loading="loading"
      :fetching="compensations.isFetching.value"
      :error="compensations.error.value"
      :retry="() => compensations.refetch()"
      clickable
      :active-key="activeKey"
      :filtered="filtered"
      hide-pagination
      csv-name="pay-setups"
      @row-click="open"
      @clear-filters="
        search = '';
        missingOnly = false;
        type = 'all';
      "
    >
      <template #toolbar>
        <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <TextInput v-model="search" :icon="Search" size="sm" clearable :placeholder="t('payroll.payslips.search')" class="w-full sm:w-64" />
          <SegmentedControl
            v-model="type"
            size="sm"
            :options="[
              { value: 'all', label: t('payroll.pay.allTypes') },
              { value: 'monthly', label: t('payroll.payType.monthly') },
              { value: 'daily', label: t('payroll.payType.daily') },
              { value: 'hourly', label: t('payroll.payType.hourly') },
              { value: 'per_task', label: t('payroll.payType.per_task') },
            ]"
          />
          <button
            v-if="missing || missingOnly"
            type="button"
            :class="[
              'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm font-semibold transition-colors',
              missingOnly ? 'border-warning bg-warning-soft text-warning' : 'border-line text-muted hover:border-line-strong hover:text-fg',
            ]"
            :aria-pressed="missingOnly"
            data-testid="missing-filter"
            @click="missingOnly = !missingOnly"
          >
            <UserRoundX :size="14" />{{ t("payroll.pay.missing", { n: missing }, missing) }}
          </button>
        </div>
      </template>
      <template #empty>
        <EmptyState :icon="WalletCards" :title="filtered ? t('payroll.pay.noMatch') : t('payroll.pay.empty')" :description="filtered ? undefined : t('payroll.pay.emptyBody')" />
      </template>
      <template #cell-person="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="30" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p v-if="row.member.position" class="truncate text-xs text-muted">{{ row.member.position }}</p>
          </div>
        </div>
      </template>
      <template #cell-type="{ row }">
        <span v-if="row.current" class="text-sm text-fg">{{ t(`payroll.payType.${row.current.pay_type}`) }}</span>
        <StatusPill v-else tone="warning" size="sm" :label="t('payroll.pay.none')" />
      </template>
      <template #cell-amount="{ row }">
        <PayAmount v-if="row.current" cell strong :value="row.current.amount" :currency="row.current.currency" :sub="per(row)" />
        <span v-else class="text-sm text-subtle">—</span>
      </template>
      <template #cell-proration="{ row }"><span class="text-sm text-muted">{{ row.current ? t(`payroll.proration.${row.current.proration}`) : "" }}</span></template>
      <template #cell-extras="{ row }">
        <div v-if="row.current" class="flex flex-wrap gap-1">
          <span v-if="row.current.overtime_eligible" class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted"><Clock3 :size="11" />{{ t("payroll.pay.overtime") }}</span>
          <span v-if="row.current.pays_task_rates" class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted">{{ t("payroll.pay.taskRates") }}</span>
        </div>
      </template>
      <template #cell-since="{ row }">
        <div v-if="row.current" class="flex min-w-0 flex-col">
          <span class="inline-flex items-center gap-1 text-sm text-fg">
            <Lock v-if="row.current.locked" :size="12" class="text-subtle" :aria-label="t('payroll.pay.locked')" />{{ fmt.day(row.current.effective_from, "medium") }}
          </span>
          <span v-if="row.upcoming" class="inline-flex items-center gap-1 truncate text-xs font-semibold text-info"><CalendarClock :size="11" />{{ t("payroll.pay.changes", { date: fmt.day(row.upcoming.effective_from, "short") }) }}</span>
        </div>
        <span v-else-if="row.upcoming" class="inline-flex items-center gap-1 text-xs font-semibold text-info"><CalendarClock :size="11" />{{ t("payroll.pay.starts", { date: fmt.day(row.upcoming.effective_from, "short") }) }}</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ [row.member.position, row.current ? t(`payroll.payType.${row.current.pay_type}`) : null].filter(Boolean).join(" · ") }}</p>
            <p v-if="row.upcoming" class="mt-0.5 inline-flex items-center gap-1 text-xs font-semibold text-info"><CalendarClock :size="11" />{{ t("payroll.pay.changes", { date: fmt.day(row.upcoming.effective_from, "short") }) }}</p>
          </div>
          <PayAmount v-if="row.current" cell strong :value="row.current.amount" :currency="row.current.currency" :sub="per(row)" />
          <StatusPill v-else tone="warning" size="sm" :label="t('payroll.pay.none')" />
        </div>
      </template>
    </DataTable>

    <PayDrawer :rows="rows" />
  </div>
</template>
