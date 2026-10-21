<script setup lang="ts">
/**
 * The party directory (plan §6.2 "Counterparties with balances"): customers, suppliers, state
 * bodies, with what each owes us, what we owe them and the overdue part; search, kind and "who
 * owes" filters in the URL. A row opens the counterparty's page.
 */
import { Building2, Plus, UsersRound } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import MoneyCell from "@/components/MoneyCell.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { formatPhone } from "@/lib/format";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useCounterparties } from "../api";
import CounterpartyFormDialog from "../components/CounterpartyFormDialog.vue";
import { fitTags, isZeroMoney, PARTY_TONES } from "../lib";
import type { Counterparty } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const canRecord = computed(() => company.can("finance.record"));

const kind = useRouteState("kind", rs.enum(["all", "customer", "supplier", "state", "other"] as const, "all"));
const owes = useRouteState("owes", rs.enum(["any", "us", "we"] as const, "any"));
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "finance.counterparties", url: true });
watch([kind, owes, search], () => table.resetPage());

const params = computed(() => ({
  ...(kind.value !== "all" ? { kind: kind.value } : {}),
  ...(owes.value !== "any" ? { owes: owes.value } : {}),
  ...(search.value ? { q: search.value } : {}),
  active: "true",
  ...table.params.value,
}));
const parties = useCounterparties(params);
const filtered = computed(() => kind.value !== "all" || owes.value !== "any" || !!search.value);

const columns = computed<TableColumn<Counterparty>[]>(() => [
  { id: "name", header: t("finance.parties.name"), minWidth: 230, sticky: true, hideable: false },
  // A full "+998 90 123 45 67", "Yetkazib beruvchi" and "Последнее движение" fit; the widths
  // still leave the name its 230 px on a 1440 screen.
  { id: "kind", header: t("finance.parties.kind"), width: 136, value: (row) => row.kind_label },
  { id: "phone", header: t("finance.parties.phone"), width: 156, format: (value) => formatPhone(String(value ?? "")) || "—" },
  { id: "owes_us", header: t("finance.parties.owesUs"), numeric: true, width: 150 },
  { id: "we_owe", header: t("finance.parties.weOwe"), numeric: true, width: 140 },
  { id: "last_activity", header: t("finance.parties.lastActivity"), width: 160, format: (value) => (value ? fmt.day(String(value), "short") : "—") },
  { id: "tags", header: t("finance.parties.tags"), width: 132, value: (row) => row.tags.join(", ") },
]);

/** "Shuhrat Karimov · STIR 305112874": the contact and the tax number, in the page's language. */
const partyLine = (row: Counterparty) => [row.contact_person, row.tin ? t("finance.parties.tinShort", { tin: row.tin }) : ""].filter(Boolean).join(" · ");

/** The tags that fit the 132 px column on one line (about 14 letters). */
const fittingTags = (tags: readonly string[]) => fitTags(tags, 14);

/** "Rustam Qodirov (ijara)" → initials of the name, not of the note in brackets. */
const avatarName = (name: string) => name.replace(/\s*[(\[].*$/, "") || name;

function open(row: Counterparty): void {
  void router.push(`/c/${company.currentId}/finance/counterparties/${row.id}`);
}

const formOpen = ref(false);
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.counterparties')" :description="t('finance.parties.description')">
      <template #actions>
        <UiButton v-if="canRecord" variant="primary" :icon="Plus" @click="formOpen = true">{{ t("finance.parties.new") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="parties.data.value?.results"
      :total="parties.data.value?.count"
      row-key="id"
      :loading="parties.isPending.value"
      :fetching="parties.isFetching.value"
      :error="parties.error.value"
      :retry="() => parties.refetch()"
      clickable
      :filtered="filtered"
      csv-name="counterparties"
      @row-click="open"
      @clear-filters="
        kind = 'all';
        owes = 'any';
        search = '';
      "
    >
      <template #toolbar>
        <div class="flex flex-wrap items-center gap-2">
          <TextInput v-model="search" type="search" size="sm" class="w-full sm:w-64" :placeholder="t('finance.parties.searchPlaceholder')" clearable />
          <SegmentedControl
            v-model="kind"
            size="sm"
            :options="[
              { value: 'all', label: t('finance.parties.allKinds') },
              { value: 'customer', label: t('finance.parties.customers') },
              { value: 'supplier', label: t('finance.parties.suppliers') },
              { value: 'state', label: t('finance.parties.state') },
            ]"
          />
          <SelectBox
            v-model="owes"
            size="sm"
            class="w-44"
            :options="[
              { value: 'any', label: t('finance.parties.owesAny') },
              { value: 'us', label: t('finance.parties.owesUsFilter') },
              { value: 'we', label: t('finance.parties.weOweFilter') },
            ]"
          />
        </div>
      </template>
      <template #empty>
        <EmptyState :icon="UsersRound" :title="filtered ? t('finance.tx.noMatch') : t('finance.parties.emptyTitle')" :description="filtered ? t('finance.tx.noMatchBody') : t('finance.parties.emptyBody')">
          <UiButton v-if="!filtered && canRecord" variant="primary" :icon="Plus" @click="formOpen = true">{{ t("finance.parties.new") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-name="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="avatarName(row.name)" :size="30" shape="rounded" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.name">{{ row.name }}</p>
            <p class="truncate text-xs text-muted" :title="partyLine(row) || undefined">{{ partyLine(row) || row.kind_label }}</p>
          </div>
        </div>
      </template>
      <template #cell-kind="{ row }"><StatusPill :tone="PARTY_TONES[row.kind]" size="sm" :label="row.kind_label" /></template>
      <template #cell-owes_us="{ row }">
        <span v-if="isZeroMoney(row.owes_us)" class="text-subtle">—</span>
        <span v-else class="flex min-w-0 flex-col items-end">
          <MoneyCell :value="row.owes_us" :colored="false" strong />
          <!-- The late part stays inside its column ("200 ming kechikkan", cut with the exact
               amount on hover), never over the phone number beside it. -->
          <span
            v-if="!isZeroMoney(row.overdue)"
            class="mt-0.5 max-w-full truncate text-xs text-warning"
            :title="t('finance.parties.overdueSub', { amount: fmt.money(row.overdue) })"
            data-testid="party-overdue"
          >{{ t("finance.parties.overdueSub", { amount: fmt.money(row.overdue, undefined, { compact: true, currencyDisplay: "none" }) }) }}</span>
        </span>
      </template>
      <template #cell-we_owe="{ row }">
        <span v-if="isZeroMoney(row.we_owe)" class="text-subtle">—</span>
        <MoneyCell v-else :value="row.we_owe" :colored="false" strong />
      </template>
      <template #cell-tags="{ row }">
        <!-- One line, so a row keeps its height: the tags that fit, "+N" for the rest (all in the tooltip). -->
        <span class="flex min-w-0 gap-1 overflow-hidden" :title="row.tags.join(', ') || undefined">
          <span v-for="tag in fittingTags(row.tags).shown" :key="tag" class="shrink-0 whitespace-nowrap rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted">{{ tag }}</span>
          <span v-if="fittingTags(row.tags).more" class="shrink-0 whitespace-nowrap rounded-full px-1 py-0.5 text-xs font-semibold text-subtle">+{{ fittingTags(row.tags).more }}</span>
        </span>
      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="avatarName(row.name)" :size="34" shape="rounded" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.name }}</p>
            <p class="truncate text-xs text-muted">{{ row.kind_label }}<template v-if="row.phone"> · {{ formatPhone(row.phone) }}</template></p>
          </div>
          <div class="text-right">
            <p v-if="!isZeroMoney(row.owes_us)" class="text-sm font-semibold tabular-nums text-success">+{{ fmt.money(row.owes_us, undefined, { compact: true }) }}</p>
            <p v-if="!isZeroMoney(row.we_owe)" class="text-sm font-semibold tabular-nums text-danger">−{{ fmt.money(row.we_owe, undefined, { compact: true }) }}</p>
            <Building2 v-if="isZeroMoney(row.owes_us) && isZeroMoney(row.we_owe)" :size="14" class="ml-auto text-subtle" />
          </div>
        </div>
      </template>
    </DataTable>

    <CounterpartyFormDialog v-model:open="formOpen" @saved="(party) => open(party)" />
  </div>
</template>
