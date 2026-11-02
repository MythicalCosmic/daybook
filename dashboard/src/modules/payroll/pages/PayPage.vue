<script setup lang="ts">
/**
 * Pay setups (plan §6.2 "Pay setups table with history"): everyone with their pay now (type,
 * amount, proration, overtime and task rates), when it started and what changes next; people with
 * no pay setup stand out. A row opens the person's history (`?member=`) with "Change pay".
 * `?missing=1` shows only the people without one (a run's warning links here).
 */
import { CalendarClock, Clock3, Lock, Search, UserRoundX, WalletCards } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { usePayPeople } from "../api";
import PayAmount from "../components/PayAmount.vue";
import PayDrawer from "../components/PayDrawer.vue";
import { payRowMatches } from "../lib";
import type { PayRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();

// Everyone who can be paid, with today's setup and the next one (the server searches names).
const search = useRouteState("q", rs.string(""));
const people = usePayPeople(() => (search.value ? { q: search.value } : {}));
const rows = computed(() => people.data.value?.results ?? []);

const missingOnly = useRouteState("missing", rs.boolean(false));
const type = useRouteState("type", rs.enum(["all", "monthly", "daily", "hourly", "per_task"] as const, "all"));
const visible = computed(() => rows.value.filter((row) => payRowMatches(row, { missing: missingOnly.value, type: type.value })));
const missing = computed(() => rows.value.filter((row) => !row.current).length);
const { isPhone } = useBreakpoints();
const typeOptions = computed(() => [
  { value: "all" as const, label: t("payroll.pay.allTypes") },
  ...(["monthly", "daily", "hourly", "per_task"] as const).map((value) => ({ value, label: t(`payroll.payType.${value}`) })),
]);
const filtered = computed(() => missingOnly.value || type.value !== "all" || !!search.value);

const table = useDataTable({ id: "payroll.pay", pageSize: 200, hidden: ["proration"] });
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
const where = (row: PayRow) => [row.member.position, row.member.home_branch].filter(Boolean).join(" · ");
</script>

<template>
  <div>
    <PageHeader :title="t('payroll.nav.pay')" :description="t('payroll.pay.description')" />

    <DataTable
      :state="table"
      :columns="columns"
      :rows="visible"
      :row-key="(row: PayRow) => row.member.id"
      :loading="people.isPending.value"
      :fetching="people.isFetching.value"
      :error="people.error.value"
      :retry="() => people.refetch()"
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
          <TextInput v-model="search" :icon="Search" size="sm" clearable :debounce="250" :placeholder="t('payroll.payslips.search')" class="w-full sm:w-64" />
          <!-- Five choices don't fit a phone's width as segments: a select there. -->
          <SelectBox v-if="isPhone" v-model="type" size="sm" :options="typeOptions" class="!w-36 shrink-0" :aria-label="t('payroll.pay.type')" />
          <SegmentedControl v-else v-model="type" size="sm" :options="typeOptions" />
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
            <p v-if="where(row)" class="truncate text-xs text-muted">{{ where(row) }}</p>
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
          <span v-if="row.next" class="inline-flex items-center gap-1 truncate text-xs font-semibold text-info"><CalendarClock :size="11" />{{ t("payroll.pay.changes", { date: fmt.day(row.next.effective_from, "short") }) }}</span>
        </div>
        <span v-else-if="row.next" class="inline-flex items-center gap-1 text-xs font-semibold text-info"><CalendarClock :size="11" />{{ t("payroll.pay.starts", { date: fmt.day(row.next.effective_from, "short") }) }}</span>
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ [row.member.position, row.current ? t(`payroll.payType.${row.current.pay_type}`) : null].filter(Boolean).join(" · ") }}</p>
            <p v-if="row.next" class="mt-0.5 inline-flex items-center gap-1 text-xs font-semibold text-info"><CalendarClock :size="11" />{{ t(row.current ? "payroll.pay.changes" : "payroll.pay.starts", { date: fmt.day(row.next.effective_from, "short") }) }}</p>
          </div>
          <PayAmount v-if="row.current" cell strong :value="row.current.amount" :currency="row.current.currency" :sub="per(row)" />
          <StatusPill v-else tone="warning" size="sm" :label="t('payroll.pay.none')" />
        </div>
      </template>
    </DataTable>

    <PayDrawer :rows="rows" />
  </div>
</template>
