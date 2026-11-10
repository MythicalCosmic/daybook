<script setup lang="ts">
/**
 * Who signed a policy: everyone the current version asks, in the viewer's branches, with when they
 * signed (and which version they read), or the deadline they have (late in red), and when they were
 * last reminded. Tabs by state (`?state=late` from the late notice); "Remind" on one row or on all
 * still to sign (hr.manage).
 */
import { BellRing, CircleCheck, EllipsisVertical, Hourglass, Search, TriangleAlert, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import DataTable from "@/components/DataTable.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import IconButton from "@/components/IconButton.vue";
import PersonCell from "@/components/PersonCell.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import { useDataTable } from "@/components/useDataTable";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyToday } from "@/stores/company";

import { useSignatures } from "./api";
import { daysUntil, STANDING_TONES } from "./lib";
import type { PolicyDetail, Signature, SignatureState } from "./types";

const props = defineProps<{ policy: PolicyDetail; canRemind: boolean }>();
const emit = defineEmits<{ remind: [memberIds: number[] | null, count: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const today = useCompanyToday();

type StateTab = "all" | SignatureState;
const state = useRouteState<StateTab>("state", rs.enum(["all", "waiting", "late", "signed"] as const, "all"));
const search = useRouteState("q", rs.string(""));
const table = useDataTable({ id: "hr.policy.people", url: "p" });
table.resetPageOn(() => [state.value, search.value]);

const params = computed(() => ({ ...(state.value === "all" ? {} : { state: state.value }), ...(search.value ? { q: search.value } : {}), ...table.params.value }));
const query = useSignatures(() => props.policy.id, params);

const tally = computed(() => props.policy.tally);
const tabs = computed(() => {
  const row = tally.value;
  const count = (n: number | undefined) => (n ? ` · ${n}` : "");
  return [
    { value: "all" as const, label: `${t("common.all")}${count(row?.total)}` },
    { value: "waiting" as const, label: `${t("hr.policy.state.waiting")}${count(row?.waiting)}`, icon: Hourglass },
    { value: "late" as const, label: `${t("hr.policy.state.late")}${count(row?.late)}`, icon: TriangleAlert },
    { value: "signed" as const, label: `${t("hr.policy.state.signed")}${count(row?.signed)}`, icon: CircleCheck },
  ];
});

const columns = computed<TableColumn<Signature>[]>(() => [
  { id: "member", header: t("hr.field.person"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "branch", header: t("hr.policy.col.branch"), minWidth: 140, value: (row) => row.branch?.name ?? "" },
  { id: "state", header: t("hr.field.status"), width: 130, value: (row) => row.state },
  { id: "when", header: t("hr.policy.col.when"), minWidth: 190, value: (row) => row.signed_at ?? row.due_on },
  { id: "reminded", header: t("hr.policy.col.reminded"), width: 150, value: (row) => row.reminded_at ?? "" },
  { id: "actions", header: "", width: 56, align: "end", hideable: false, value: () => "" },
]);

function when(row: Signature): { text: string; tone: "muted" | "danger" | "success" } {
  if (row.signed_at) {
    const date = fmt.instant(row.signed_at, "short");
    const read = row.signed_number && props.policy.version && row.signed_number !== props.policy.ack_number ? ` · ${t("hr.policy.versionShort", { n: row.signed_number })}` : "";
    return { text: `${t("hr.policy.signedOn", { date })}${read}`, tone: "success" };
  }
  const left = daysUntil(row.due_on, today.value);
  if (left < 0) return { text: t("hr.policy.lateSince", { date: fmt.day(row.due_on, "short") }), tone: "danger" };
  if (left === 0) return { text: t("hr.policy.dueToday"), tone: "muted" };
  return { text: t("hr.policy.dueOn", { date: fmt.day(row.due_on, "short") }), tone: "muted" };
}

function rowMenu(row: Signature): MenuEntry[] {
  if (!props.canRemind || row.state === "signed") return [];
  return [{ label: t("hr.policy.remindOne"), icon: BellRing, onSelect: () => emit("remind", [row.member.id], 1) }];
}

const waitingCount = computed(() => (tally.value ? tally.value.waiting + tally.value.late : 0));
defineExpose({ waitingCount });
</script>

<template>
  <div class="flex flex-col gap-3">
    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      :row-key="(row: Signature) => row.member.id"
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="!!search || state !== 'all'"
      @clear-filters="
        search = '';
        state = 'all';
      "
    >
      <template #toolbar>
        <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <SegmentedControl v-model="state" :options="tabs" size="sm" :aria-label="t('hr.field.status')" />
          <TextInput
            :model-value="search"
            type="search"
            :icon="Search"
            clearable
            size="sm"
            :debounce="300"
            :placeholder="t('hr.policy.searchPeople')"
            class="w-full sm:ml-auto sm:w-[240px]"
            @update:model-value="(value) => (search = value ?? '')"
          />
        </div>
      </template>
      <template #empty>
        <EmptyState
          :icon="Users"
          :title="search || state !== 'all' ? t('hr.empty.noMatch') : t('hr.policy.peopleEmpty')"
          :description="search || state !== 'all' ? t('hr.empty.noMatchBody') : t('hr.policy.peopleEmptyBody')"
        />
      </template>
      <template #cell-member="{ row }">
        <PersonCell :person="row.member" :subtitle="row.position?.name" link />
      </template>
      <template #cell-branch="{ row }">
        <span class="truncate text-sm text-fg">{{ row.branch?.name ?? "—" }}</span>
      </template>
      <template #cell-state="{ row }">
        <StatusPill :tone="STANDING_TONES[row.state as SignatureState]" size="sm" :label="t(`hr.policy.state.${row.state}`)" />
      </template>
      <template #cell-when="{ row }">
        <div class="flex min-w-0 flex-col">
          <span :class="['truncate text-sm tabular-nums', when(row).tone === 'danger' ? 'font-medium text-danger' : when(row).tone === 'success' ? 'text-fg' : 'text-muted']">{{ when(row).text }}</span>
          <span v-if="!row.signed_at && row.earlier_signed_at" class="truncate text-xs text-subtle">{{ t("hr.policy.signedBefore") }}</span>
        </div>
      </template>
      <template #cell-reminded="{ row }">
        <RelativeTime v-if="row.reminded_at" :value="row.reminded_at" class="text-sm text-muted" />
        <span v-else class="text-sm text-subtle">—</span>
      </template>
      <template #cell-actions="{ row }">
        <DropdownMenu v-if="rowMenu(row).length" :items="rowMenu(row)" align="end">
          <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" @click.stop /></template>
        </DropdownMenu>
        <span v-else aria-hidden="true" />

      </template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <PersonCell :person="row.member" :subtitle="[row.position?.name, row.branch?.name].filter(Boolean).join(' · ')" link size="lg" class="min-w-0 flex-1" />
          <StatusPill :tone="STANDING_TONES[row.state as SignatureState]" size="sm" :label="t(`hr.policy.state.${row.state}`)" />
        </div>
        <div class="mt-2 flex items-center gap-2 pl-12">
          <span :class="['min-w-0 flex-1 truncate text-sm tabular-nums', when(row).tone === 'danger' ? 'font-medium text-danger' : 'text-muted']">{{ when(row).text }}</span>
          <IconButton v-if="canRemind && row.state !== 'signed'" :icon="BellRing" :label="t('hr.policy.remindOne')" size="sm" @click.stop="emit('remind', [row.member.id], 1)" />
        </div>
      </template>
    </DataTable>
  </div>
</template>
