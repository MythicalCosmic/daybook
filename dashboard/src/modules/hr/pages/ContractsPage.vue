<script setup lang="ts">
/**
 * Contracts (plan §6.2 HR): tabs by status, chips for "ending soon" and "on probation", each row
 * with its period, how soon it ends, probation and whether the employee has read it; the drawer on
 * `?contract=`; "New contract" (`?new=1` opens it from the palette). Actions ask before they act.
 */
import { BadgeCheck, CircleCheck, Clock4, EllipsisVertical, FileSignature, Plus, Tags, Timer } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useContracts, useWarnDays } from "../api";
import ContractActionDialog from "../components/ContractActionDialog.vue";
import ContractDrawer from "../components/ContractDrawer.vue";
import ContractFormDialog from "../components/ContractFormDialog.vue";
import DaysChip from "../components/DaysChip.vue";
import { ACTION_ICONS } from "../icons";
import { CONTRACT_TONES, contractActions, contractParams, hrAccess, onProbation, type ContractView } from "../lib";
import { CONTRACT_KINDS, type Contract } from "../types";
import { useContractActions } from "../useContractActions";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const view = useRouteState<ContractView>("status", rs.enum(["active", "draft", "ended", "all"] as const, "active"));
const search = useRouteState("q", rs.string(""));
const warn = useWarnDays();

const defs = computed<FilterDef[]>(() => [
  { key: "ending", label: t("hr.contract.filter.ending"), type: "boolean", icon: Timer, pinned: true, trueLabel: t("hr.contract.filter.endingYes", { n: warn.value.contracts }, warn.value.contracts), falseLabel: t("common.all") },
  { key: "probation", label: t("hr.contract.filter.probation"), type: "boolean", icon: Clock4, pinned: true, trueLabel: t("hr.contract.filter.probationYes", { n: warn.value.probation }, warn.value.probation), falseLabel: t("common.all") },
  { key: "kind", label: t("hr.field.contractKind"), type: "multi", icon: Tags, options: CONTRACT_KINDS.map((kind) => ({ value: kind, label: t(`hr.contractKind.${kind}`) })) },
]);
const filters = useUrlFilters(defs);
const table = useDataTable({ id: "hr.contracts", url: true });
table.resetPageOn(() => [filters.params.value, search.value, view.value]);

const params = computed(() => ({ ...contractParams(view.value, filters.values.value, search.value, warn.value), ...table.params.value }));
const contracts = useContracts(params);
const filtered = computed(() => filters.active.value > 0 || !!search.value);

const tabs = computed(() => [
  { id: "active", label: t("hr.contract.tab.active") },
  { id: "draft", label: t("hr.contract.tab.draft") },
  { id: "ended", label: t("hr.contract.tab.ended") },
  { id: "all", label: t("hr.contract.tab.all") },
]);

const columns = computed<TableColumn<Contract>[]>(() => [
  { id: "member", header: t("hr.field.person"), minWidth: 200, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "kind", header: t("hr.field.contractKind"), minWidth: 170, value: (row) => t(`hr.contractKind.${row.kind}`) },
  { id: "status", header: t("hr.field.status"), width: 120, value: (row) => row.status },
  { id: "period", header: t("hr.field.period"), width: 210, value: (row) => row.starts_on },
  { id: "probation", header: t("hr.field.probation"), width: 150, value: (row) => row.probation_until ?? "" },
  { id: "ack", header: t("hr.contract.ack"), width: 72, align: "center", value: (row) => (row.acknowledged_at ? "1" : "") },
  { id: "actions", header: "", width: 56, align: "end", hideable: false, value: () => "" },
]);

function open(row: Contract): void {
  void router.push({ query: { ...route.query, contract: String(row.id) } });
}
const activeKey = computed(() => (typeof route.query.contract === "string" ? route.query.contract : null));

// A renewal is a new contract: open it.
const { request: actionRequest, run: runAction, perform } = useContractActions((result, action) => {
  if (action === "renew") void router.push({ query: { ...route.query, contract: String(result.id) } });
});
function rowMenu(row: Contract): MenuEntry[] {
  return contractActions(row).map((action) => ({
    label: t(`hr.contract.action.${action}`),
    icon: ACTION_ICONS[action],
    danger: action === "terminate" || action === "end",
    onSelect: () => void runAction(row, action),
  }));
}

// "New contract" opens from the palette and the overview too (?new=1).
const creating = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (access.value.manage) creating.value = true;
  },
  { immediate: true },
);
function created(contract: Contract): void {
  void router.push({ query: { ...route.query, contract: String(contract.id), status: contract.status === "draft" ? "draft" : route.query.status } });
}
</script>

<template>
  <div>
    <PageHeader v-model:tab="view" :title="t('hr.nav.contracts')" :description="t('hr.contract.description')" :tabs="tabs">
      <template v-if="access.manage" #actions>
        <UiButton variant="primary" :icon="Plus" @click="creating = true">{{ t("hr.contract.new") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="contracts.data.value?.results"
      :total="contracts.data.value?.count"
      row-key="id"
      :loading="contracts.isPending.value"
      :fetching="contracts.isFetching.value"
      :error="contracts.error.value"
      :retry="() => contracts.refetch()"
      clickable
      :active-key="activeKey"
      :filtered="filtered"
      @row-click="open"
      @clear-filters="
        filters.clear();
        search = '';
      "
    >
      <template #toolbar>
        <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('hr.contract.search')" />
      </template>
      <template #empty>
        <EmptyState :icon="FileSignature" :title="filtered ? t('hr.empty.noMatch') : t(`hr.contract.empty.${view}`)" :description="filtered ? t('hr.empty.noMatchBody') : t('hr.contract.emptyBody')">
          <UiButton v-if="!filtered && access.manage" variant="primary" :icon="Plus" @click="creating = true">{{ t("hr.contract.new") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-member="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="28" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p v-if="row.position" class="truncate text-xs text-muted">{{ row.position.name }}</p>
          </div>
        </div>
      </template>
      <template #cell-kind="{ row }">
        <div class="min-w-0">
          <p class="truncate text-sm text-fg">{{ t(`hr.contractKind.${row.kind}`) }}</p>
          <p v-if="row.number" class="truncate text-xs tabular-nums text-muted">№ {{ row.number }}</p>
        </div>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="CONTRACT_TONES[row.status]" size="sm" :label="t(`hr.contractStatus.${row.status}`)" /></template>
      <template #cell-period="{ row }">
        <div class="flex min-w-0 flex-col items-start gap-0.5">
          <span class="text-sm tabular-nums text-fg">{{ row.ends_on ? fmt.range({ from: row.starts_on, to: row.ends_on }) : t("hr.contract.since", { date: fmt.day(row.starts_on, "medium") }) }}</span>
          <DaysChip v-if="row.ends_on && row.status === 'active'" :day="row.ends_on" :warn-days="warn.contracts" prefix="ends" />
        </div>
      </template>
      <template #cell-probation="{ row }">
        <DaysChip v-if="onProbation(row)" :day="row.probation_until!" :warn-days="warn.probation" prefix="probation" always />
        <span v-else-if="row.probation_passed_at" class="inline-flex items-center gap-1 text-sm text-success"><BadgeCheck :size="14" aria-hidden="true" />{{ t("hr.contract.probationPassed") }}</span>
        <span v-else class="text-sm text-subtle">—</span>
      </template>
      <template #cell-ack="{ row }">
        <CircleCheck v-if="row.acknowledged_at" :size="17" class="text-success" :aria-label="t('hr.contract.acknowledged')" />
        <span v-else class="text-sm text-subtle" :aria-label="t('hr.contract.notAcknowledged')">—</span>
      </template>
      <template #cell-actions="{ row }">
        <DropdownMenu v-if="rowMenu(row).length" :items="rowMenu(row)" align="end">
          <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" @click.stop /></template>
        </DropdownMenu>
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="36" />
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="min-w-0 flex-1 truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <StatusPill :tone="CONTRACT_TONES[row.status]" size="sm" :label="t(`hr.contractStatus.${row.status}`)" />
            </div>
            <p class="truncate text-sm text-muted">{{ t(`hr.contractKind.${row.kind}`) }}<template v-if="row.number"> · № {{ row.number }}</template></p>
            <p class="text-xs tabular-nums text-muted">{{ row.ends_on ? fmt.range({ from: row.starts_on, to: row.ends_on }) : t("hr.contract.since", { date: fmt.day(row.starts_on, "medium") }) }}</p>
            <div v-if="(row.ends_on && row.status === 'active') || onProbation(row) || row.acknowledged_at" class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <DaysChip v-if="row.ends_on && row.status === 'active'" :day="row.ends_on" :warn-days="warn.contracts" prefix="ends" />
              <DaysChip v-if="onProbation(row)" :day="row.probation_until!" :warn-days="warn.probation" prefix="probation" always />
              <StatusPill v-if="row.acknowledged_at" tone="success" size="sm" :icon="CircleCheck" :dot="false" :label="t('hr.contract.acknowledged')" />
            </div>
          </div>
        </div>
      </template>
    </DataTable>

    <ContractDrawer :warn="warn" @action="(contract, action) => runAction(contract, action)" />
    <ContractFormDialog v-model:open="creating" @saved="created" />
    <ContractActionDialog v-model:request="actionRequest" :perform="perform" />
  </div>
</template>
