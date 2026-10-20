<script setup lang="ts">
/**
 * Where is my cash (plan §6.2 "Cash positions"): the flow from tills to the safe, in transit, with
 * people and to the bank; the oldest handover nobody confirmed; handovers that didn't arrive; each
 * branch's tills and safe against its cash limit; and every movement, filterable, with void. The
 * handovers waiting for *you* can be answered right here.
 */
import { AlertOctagon, ArrowRight, Ban, Building2, CircleDot, Clock, HandCoins, Landmark, Plus, Users, Vault, Wallet } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter, RouterLink } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FilterBar from "@/components/FilterBar.vue";
import IconButton from "@/components/IconButton.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { percent } from "@/lib/decimal";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { salesApi, useHandoverAnswer, useMovements, useOptions, usePositions, useSalesMutation } from "../api";
import MovementDialog from "../components/MovementDialog.vue";
import ShiftDrawer from "../components/ShiftDrawer.vue";
import { MOVEMENT_ICONS, MOVEMENT_KINDS, MOVEMENT_TONES, movementSign } from "../format";
import type { Movement, PendingHandover } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const session = useSessionStore();
const confirm = useConfirm();
const options = useOptions();
const positions = usePositions();
const skeleton = useDelayedPending(computed(() => positions.isPending.value));
const data = computed(() => positions.data.value);
const canManage = computed(() => company.can("sales.manage"));
const me = computed(() => session.me?.companies.find((c) => c.id === company.currentId)?.membership_id ?? null);

const flow = computed(() => {
  const totals = data.value?.totals;
  if (!totals) return [];
  const tills = data.value?.branches.reduce((n, b) => n + b.tills.length, 0) ?? 0;
  return [
    { key: "tills", label: t("sales.cash.tills"), amount: totals.tills, icon: Wallet, hint: t("sales.cash.tillsHint", { n: tills }, tills) },
    { key: "safes", label: t("sales.cash.safes"), amount: totals.safes, icon: Vault, hint: t("sales.cash.safesHint") },
    { key: "in_transit", label: t("sales.cash.transit"), amount: totals.in_transit, icon: HandCoins, hint: t("sales.cash.transitHint", { n: data.value?.in_transit.length ?? 0 }, data.value?.in_transit.length ?? 0) },
    { key: "people", label: t("sales.cash.people"), amount: totals.people, icon: Users, hint: t("sales.cash.peopleHint", { n: data.value?.people.length ?? 0 }, data.value?.people.length ?? 0) },
    { key: "to_bank", label: t("sales.cash.bank"), amount: totals.to_bank, icon: Landmark, hint: t("sales.cash.bankHint") },
  ];
});

const answer = useHandoverAnswer();
async function confirmHandover(row: PendingHandover): Promise<void> {
  await answer.mutateAsync({ id: row.id, answer: "confirm" });
  toast.success(t("sales.cash.received", { amount: fmt.money(row.amount) }));
}
async function declineHandover(row: PendingHandover): Promise<void> {
  const reply = await confirm({
    title: t("sales.cash.declineTitle"),
    message: t("sales.cash.declineBody", { name: row.from.name, amount: fmt.money(row.amount) }),
    confirmLabel: t("sales.cash.decline"),
    tone: "danger",
    reason: "optional",
  });
  if (!reply) return;
  await answer.mutateAsync({ id: row.id, answer: "decline", reason: reply.reason });
}

// Movements table
const defs = computed<FilterDef[]>(() => [
  { key: "kind", label: t("sales.filter.kind"), type: "multi", icon: Wallet, options: MOVEMENT_KINDS.map((k) => ({ value: k, label: t(`sales.movement.kind.${k}`), icon: MOVEMENT_ICONS[k] })) },
  { key: "branch", label: t("sales.filter.branch"), type: "multi", icon: Building2, options: (options.data.value?.branches ?? []).map((b) => ({ value: String(b.id), label: b.name })) },
  {
    key: "status",
    label: t("sales.filter.status"),
    type: "select",
    icon: CircleDot,
    options: (["pending", "declined", "done", "void"] as const).map((s) => ({ value: s, label: t(`sales.movement.status.${s}`) })),
  },
  { key: "day", label: t("sales.filter.day"), type: "date-range", params: ["from", "to"] },
]);
const filters = useUrlFilters(defs);
const table = useDataTable({ id: "sales.movements", url: "m_", pageSize: 25 });
watch(() => filters.params.value, () => table.resetPage(), { deep: true });
const movements = useMovements(computed(() => ({ ...filters.params.value, ...table.params.value })));
const columns = computed<TableColumn<Movement>[]>(() => [
  { id: "created_at", header: t("sales.col.when"), width: 140, format: (v) => fmt.instant(String(v), "short") },
  { id: "kind", header: t("sales.col.kind"), minWidth: 200 },
  { id: "created_by", header: t("sales.col.by"), width: 190, value: (row) => row.created_by.name },
  { id: "register", header: t("sales.col.till"), width: 170, value: (row) => `${row.branch.name} · ${row.register.name}` },
  { id: "status", header: t("sales.col.status"), width: 130 },
  { id: "amount", header: t("sales.col.amount"), numeric: true, width: 150, csv: (row) => row.amount },
  ...(canManage.value ? [{ id: "actions", header: "", width: 56, hideable: false, align: "end" as const }] : []),
]);

const voidMovement = useSalesMutation((cid, vars: { id: number; reason: string }) => salesApi.voidMovement(cid, vars.id, vars.reason));
async function askVoid(row: Movement): Promise<void> {
  if (!canManage.value || row.status === "void") return;
  const reply = await confirm({
    title: t("sales.cash.voidTitle"),
    message: t("sales.cash.voidBody", { kind: t(`sales.movement.kind.${row.kind}`), amount: fmt.money(row.amount) }),
    confirmLabel: t("sales.cash.void"),
    tone: "danger",
    reason: "required",
  });
  if (!reply) return;
  await voidMovement.mutateAsync({ id: row.id, reason: reply.reason });
  toast.success(t("sales.cash.voided"));
}

// "Record movement" opens from the palette too (?new=movement).
const dialog = ref(route.query.new === "movement");
watch(dialog, (value) => {
  if (!value && route.query.new) void router.replace({ query: { ...route.query, new: undefined } });
});
const pendingForMe = computed(() => (data.value?.in_transit ?? []).filter((row) => row.to.id === me.value));
const limitUse = (total: string, limit: string | null) => (limit ? percent(total, limit, 0) : null);
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('sales.cash.title')" :description="t('sales.cash.description')" class="!mb-0">
      <template v-if="canManage" #actions>
        <UiButton variant="primary" :icon="Plus" @click="dialog = true">{{ t("sales.cash.record") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      <SkeletonBlock v-for="n in 5" :key="n" height="96px" radius="12px" />
    </div>
    <ErrorState v-else-if="positions.isError.value" :error="positions.error.value" :retry="() => positions.refetch()" />
    <template v-else-if="data">
      <!-- The flow -->
      <ol class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <li v-for="(step, index) in flow" :key="step.key" class="ui-card relative flex min-w-0 flex-col gap-1 p-4 max-sm:last:col-span-2">
          <div class="flex items-center gap-2 text-xs font-medium text-muted">
            <component :is="step.icon" :size="15" class="text-subtle" aria-hidden="true" />{{ step.label }}
          </div>
          <p class="truncate text-lg font-semibold tabular-nums text-fg"><MoneyText :value="step.amount" compact /></p>
          <p class="truncate text-xs text-subtle">{{ step.hint }}</p>
          <ArrowRight v-if="index < flow.length - 1" :size="16" class="absolute -right-[13px] top-1/2 z-[1] hidden -translate-y-1/2 rounded-full bg-canvas text-subtle xl:block" aria-hidden="true" />
        </li>
      </ol>

      <!-- Handovers waiting for me -->
      <section v-if="pendingForMe.length" class="ui-card border-[color-mix(in_srgb,var(--c-primary)_30%,var(--c-border))] p-4">
        <h2 class="flex items-center gap-2 text-sm font-semibold text-fg"><HandCoins :size="16" class="text-primary" />{{ t("sales.cash.forYou", { n: pendingForMe.length }) }}</h2>
        <ul class="mt-3 flex flex-col gap-2">
          <li v-for="row in pendingForMe" :key="row.id" class="flex flex-wrap items-center gap-3 rounded-[10px] bg-surface-2/70 px-3 py-2.5">
            <PersonCell :person="row.from" size="sm" :subtitle="`${row.branch.name} · ${row.register.name} · ${fmt.relative(row.since)}`" class="min-w-0 flex-1" />
            <MoneyText :value="row.amount" class="text-md font-semibold text-fg" />
            <div class="flex gap-2">
              <UiButton size="sm" variant="ghost" @click="declineHandover(row)">{{ t("sales.cash.decline") }}</UiButton>
              <UiButton size="sm" variant="primary" :loading="answer.isPending.value" @click="confirmHandover(row)">{{ t("sales.cash.confirm") }}</UiButton>
            </div>
          </li>
        </ul>
      </section>

      <InlineAlert
        v-if="data.oldest_pending && data.oldest_pending.hours >= 1 && data.oldest_pending.to.id !== me"
        tone="warning"
        :icon="Clock"
        :title="t('sales.cash.oldest', { from: data.oldest_pending.from.name, to: data.oldest_pending.to.name, amount: fmt.money(data.oldest_pending.amount) })"
        :description="t('sales.cash.oldestBody', { hours: data.oldest_pending.hours, branch: data.oldest_pending.branch.name })"
      />
      <InlineAlert
        v-for="row in data.declined"
        :key="row.id"
        tone="danger"
        :icon="AlertOctagon"
        :title="t('sales.cash.declinedTitle', { to: row.to.name, amount: fmt.money(row.amount), from: row.from.name })"
        :description="row.decline_reason ? `«${row.decline_reason}» · ${t('sales.cash.declinedHint')}` : t('sales.cash.declinedHint')"
      />

      <!-- Branches -->
      <div class="grid gap-4 lg:grid-cols-2">
        <section v-for="branch in data.branches" :key="branch.id" class="ui-card flex min-w-0 flex-col">
          <header class="flex items-start gap-3 px-4 pb-3 pt-4">
            <div class="min-w-0 flex-1">
              <h3 class="flex items-center gap-2 text-base font-semibold text-fg">
                {{ branch.name }}<span v-if="branch.code" class="rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] font-semibold tracking-wide text-muted">{{ branch.code }}</span>
              </h3>
              <p class="mt-0.5 text-xs text-muted">{{ t("sales.cash.inBranch") }}</p>
            </div>
            <p class="text-lg font-semibold tabular-nums text-fg"><MoneyText :value="branch.total" compact /></p>
          </header>
          <div v-if="limitUse(branch.total, branch.cash_limit) !== null" class="px-4 pb-3">
            <ProgressBar
              size="sm"
              :value="Math.min(limitUse(branch.total, branch.cash_limit)!, 100)"
              :tone="limitUse(branch.total, branch.cash_limit)! >= 100 ? 'danger' : limitUse(branch.total, branch.cash_limit)! >= 80 ? 'warning' : 'success'"
              :label="t('sales.cash.limit', { amount: fmt.money(branch.cash_limit, undefined, { compact: true }), percent: limitUse(branch.total, branch.cash_limit) })"
              show-value
            />
          </div>
          <ul class="divide-y divide-line border-t border-line">
            <li v-for="till in branch.tills" :key="till.register.id" class="flex items-center gap-3 px-4 py-2.5">
              <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-accent-soft text-accent-fg"><Wallet :size="15" /></span>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-semibold text-fg">{{ till.register.name }}</p>
                <p class="truncate text-xs text-muted">
                  <template v-if="till.shift">
                    <RouterLink :to="{ query: { ...$route.query, shift: String(till.shift.id) } }" class="font-medium text-fg hover:underline">{{ till.shift.code }}</RouterLink>
                    · {{ till.shift.cashier.name }} · {{ t("sales.today.since", { time: fmt.instant(till.shift.since, "time") }) }}
                  </template>
                  <template v-else>{{ t("sales.cash.tillClosed") }}</template>
                </p>
              </div>
              <StatusPill v-if="till.shift" size="sm" tone="info" live :label="t('sales.status.open')" />
              <MoneyText :value="till.amount" class="text-sm font-semibold text-fg" />
            </li>
            <li v-if="branch.safe" class="flex items-center gap-3 px-4 py-2.5">
              <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-muted"><Vault :size="15" /></span>
              <p class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ t("sales.cash.safe") }}</p>
              <MoneyText :value="branch.safe.amount" class="text-sm font-semibold text-fg" />
            </li>
          </ul>
        </section>
      </div>

      <p class="-mt-2 text-xs text-subtle">{{ t("sales.cash.openHint") }}</p>
      <div class="grid gap-4 lg:grid-cols-2">
        <section class="ui-card flex min-w-0 flex-col">
          <h3 class="px-4 pb-2 pt-4 text-sm font-semibold text-fg">{{ t("sales.cash.transitList") }}</h3>
          <ul v-if="data.in_transit.length" class="divide-y divide-line border-t border-line">
            <li v-for="row in data.in_transit" :key="row.id" class="flex items-center gap-3 px-4 py-2.5">
              <HandCoins :size="16" class="shrink-0 text-warning" aria-hidden="true" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-fg">{{ t("sales.cash.fromTo", { from: row.from.name, to: row.to.name }) }}</p>
                <p class="truncate text-xs text-muted">{{ row.branch.name }} · {{ fmt.relative(row.since) }}</p>
              </div>
              <MoneyText :value="row.amount" class="text-sm font-semibold text-fg" />
            </li>
          </ul>
          <EmptyState v-else size="sm" tone="success" :title="t('sales.cash.noTransit')" :description="t('sales.cash.noTransitBody')" />
        </section>
        <section class="ui-card flex min-w-0 flex-col">
          <h3 class="px-4 pb-2 pt-4 text-sm font-semibold text-fg">{{ t("sales.cash.peopleList") }}</h3>
          <ul v-if="data.people.length" class="divide-y divide-line border-t border-line">
            <li v-for="row in data.people" :key="row.account_id" class="flex items-center gap-3 px-4 py-2.5">
              <PersonCell :person="row.member" size="sm" class="min-w-0 flex-1" />
              <MoneyText :value="row.amount" class="text-sm font-semibold text-fg" />
            </li>
          </ul>
          <EmptyState v-else size="sm" tone="neutral" :title="t('sales.cash.noPeople')" :description="t('sales.cash.noPeopleBody')" />
        </section>
      </div>
    </template>

    <section class="flex flex-col gap-3">
      <h2 class="text-md font-semibold text-fg">{{ t("sales.cash.movements") }}</h2>
      <DataTable
        :state="table"
        :columns="columns"
        :rows="movements.data.value?.results"
        :total="movements.data.value?.count"
        row-key="id"
        :loading="movements.isPending.value"
        :fetching="movements.isFetching.value"
        :error="movements.error.value"
        :retry="() => movements.refetch()"
        :filtered="filters.active.value > 0"
        :empty-title="t('sales.cash.noMovements')"
        :empty-description="t('sales.cash.noMovementsBody')"
        csv-name="cash-movements"
        :row-class="(row) => (row.status === 'void' ? 'opacity-55' : undefined)"
        @clear-filters="filters.clear()"
      >
        <template #toolbar><FilterBar v-model="filters.values.value" :defs="defs" /></template>
        <template #cell-kind="{ row }">
          <span class="flex min-w-0 items-center gap-2">
            <component :is="MOVEMENT_ICONS[row.kind]" :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="min-w-0">
              <span class="block truncate font-medium text-fg">{{ t(`sales.movement.kind.${row.kind}`) }}<template v-if="row.receiver"> · {{ row.receiver.name }}</template></span>
              <span v-if="row.reason || row.category" class="block truncate text-xs text-muted">{{ [row.category?.name, row.reason].filter(Boolean).join(" · ") }}</span>
            </span>
          </span>
        </template>
        <template #cell-created_by="{ row }"><PersonCell :person="row.created_by" size="sm" /></template>
        <template #cell-actions="{ row }">
          <IconButton v-if="row.status !== 'void'" :icon="Ban" :label="t('sales.cash.void')" size="sm" @click.stop="askVoid(row)" />
        </template>
        <template #cell-status="{ row }"><StatusPill size="sm" :tone="MOVEMENT_TONES[row.status]" :label="t(`sales.movement.status.${row.status}`)" /></template>
        <template #cell-amount="{ row }">
          <span :class="['font-semibold tabular-nums', movementSign(row.kind) > 0 ? 'text-success' : 'text-fg']">{{ movementSign(row.kind) > 0 ? "+" : "−" }}<MoneyText :value="row.amount" /></span>
        </template>
        <template #card="{ row }">
          <div class="flex items-center gap-3">
            <component :is="MOVEMENT_ICONS[row.kind]" :size="16" class="shrink-0 text-subtle" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-semibold text-fg">{{ t(`sales.movement.kind.${row.kind}`) }}<template v-if="row.receiver"> · {{ row.receiver.name }}</template></p>
              <p class="truncate text-xs text-muted">{{ row.created_by.name }} · {{ fmt.instant(row.created_at, "short") }}</p>
            </div>
            <span class="text-sm font-semibold tabular-nums text-fg">{{ movementSign(row.kind) > 0 ? "+" : "−" }}<MoneyText :value="row.amount" /></span>
          </div>
        </template>
      </DataTable>
    </section>
    <MovementDialog v-model:open="dialog" />
    <ShiftDrawer />
  </div>
</template>
