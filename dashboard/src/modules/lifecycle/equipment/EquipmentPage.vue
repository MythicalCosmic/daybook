<script setup lang="ts">
/**
 * People › Lifecycle › Equipment: uniforms, keys and devices, who has what, and what comes back when
 * they leave. People first: each with what they hold (confirmed in the app or not), flags for what
 * needs doing (not confirmed, a last day coming, still out after leaving), filters by branch,
 * category and flag; "Items" is the stock to give out, by category, with the pharmacy's suggested
 * categories on first use. Give with a photo; take back with the condition, a photo, and for a loss
 * or damage a write-off or a deduction proposed to payroll. Built on the assets module (`assets`).
 */
import { Blocks, Boxes, CircleAlert, Clock, HandHelping, PackageOpen, PackagePlus, Plus, Search, Undo2, UsersRound } from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import BranchPicker from "@/components/BranchPicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import AddItemsDialog from "./AddItemsDialog.vue";
import { equipmentApi, useAssetsOn, useCategories, useEquipment, useEquipmentMutation, useStock } from "./api";
import DeductionDialog from "./DeductionDialog.vue";
import HolderRow from "./HolderRow.vue";
import IssueDialog from "./IssueDialog.vue";
import { categoryIcon, filterPeople, naturalOrder, stockByCategory } from "./lib";
import ReturnDialog from "./ReturnDialog.vue";
import { EQUIPMENT_TABS, type CategoryInput, type EquipmentTab, type HeldItem, type Holder, type PersonFlag, type StockItem } from "./types";

const { t } = useI18n();
const company = useCompanyStore();
const assetsOn = useAssetsOn();

const tab = useRouteState<EquipmentTab>("tab", rs.enum(EQUIPMENT_TABS, "people"));
const branch = useRouteState("branch", rs.optionalNumber());
const data = useEquipment(branch);
const page = computed(() => data.data.value ?? null);
const can = computed(() => page.value?.can ?? { values: false, devices: false, deduct: false, pay: false, register: false });
const skeleton = useDelayedPending(computed(() => data.isPending.value && assetsOn.value));
const stock = useStock("stock", computed(() => tab.value === "items"));
const categories = useCategories();
const multiBranch = computed(() => company.current?.branch_scope === null || (company.current?.branch_scope?.length ?? 0) > 1);

// ─── People ──────────────────────────────────────────────────────────────
const query = ref("");
const category = useRouteState("category", rs.optionalNumber());
const FLAGS: PersonFlag[] = ["unconfirmed", "leaving", "left", "empty"];
const flag = useRouteState<PersonFlag | "all">("flag", rs.enum(["all", ...FLAGS] as const, "all"));
const rows = computed(() => filterPeople(page.value?.people ?? [], { q: query.value, category: category.value, flags: flag.value === "all" ? [] : [flag.value] }));
const flagCounts = computed(() => {
  const list = page.value?.people ?? [];
  return {
    unconfirmed: list.filter((row) => row.unconfirmed > 0).length,
    leaving: list.filter((row) => row.leaving_soon).length,
    left: list.filter((row) => row.overdue > 0).length,
    empty: list.filter((row) => !row.items.length).length,
  };
});
const flagOptions = computed(() => [
  { value: "all" as const, label: t("lifecycle.equipment.filter.all") },
  ...FLAGS.filter((key) => key !== "empty" || flagCounts.value.empty).map((key) => ({ value: key, label: t(`lifecycle.equipment.filter.${key}`), count: flagCounts.value[key] || undefined })),
]);
const categoryOptions = computed(() => [
  { value: 0, label: t("lifecycle.equipment.filter.anyCategory") },
  ...(categories.data.value?.categories ?? []).filter((row) => row.out > 0).map((row) => ({ value: row.id, label: row.name, icon: categoryIcon(row.icon) })),
]);
const categoryModel = computed<number>({ get: () => category.value ?? 0, set: (value) => (category.value = value || null) });
const filtered = computed(() => !!query.value.trim() || flag.value !== "all" || category.value !== null);

interface Kpi {
  id: string;
  label: string;
  value: string | number | null;
  icon: Component;
  hint?: string;
  format?: "money" | "number";
  currency?: Currency;
  compact?: boolean;
}
const kpis = computed<Kpi[]>(() => {
  const totals = page.value?.totals;
  if (!totals) return [];
  const items: Kpi[] = [
    { id: "out", label: t("lifecycle.equipment.kpi.out"), value: totals.items, icon: HandHelping, hint: t("lifecycle.equipment.kpi.outHint", { n: totals.people }, totals.people) },
    { id: "unconfirmed", label: t("lifecycle.equipment.kpi.unconfirmed"), value: totals.unconfirmed, icon: Clock, hint: t("lifecycle.equipment.kpi.unconfirmedHint") },
    { id: "return", label: t("lifecycle.equipment.kpi.toReturn"), value: totals.to_return, icon: Undo2, hint: t("lifecycle.equipment.kpi.toReturnHint") },
    { id: "stock", label: t("lifecycle.equipment.kpi.stock"), value: totals.in_stock, icon: Boxes },
  ];
  if (can.value.values && totals.value !== null) items.push({ id: "value", label: t("lifecycle.equipment.kpi.value"), value: totals.value, icon: Blocks, format: "money", currency: company.currency, compact: true });
  return items;
});

// ─── Items (stock) ───────────────────────────────────────────────────────
const groups = computed(() => stockByCategory([...(stock.data.value ?? [])].sort(naturalOrder), categories.data.value?.categories ?? []));
const suggestions = computed(() => categories.data.value?.suggestions ?? []);
const noCategories = computed(() => !!categories.data.value && !(categories.data.value.categories ?? []).some((row) => row.kind === "low_value" && (row.stock || row.out)));
const makeCategory = useEquipmentMutation((cid, input: CategoryInput) => equipmentApi.addCategory(cid, input));

// ─── Dialogs ─────────────────────────────────────────────────────────────
const issuing = ref<{ person: { id: number; name: string } | null; items: number[]; key: number } | null>(null);
let dialogKey = 0;
function give(person: { id: number; name: string } | null = null, items: number[] = []): void {
  issuing.value = { person, items, key: ++dialogKey };
}
const issueOpen = computed({ get: () => issuing.value !== null, set: (value: boolean) => !value && (issuing.value = null) });

const returning = ref<{ row: Holder; item: HeldItem; start: "returned" | "lost" | "deduct"; key: number } | null>(null);
const returnOpen = computed({ get: () => returning.value !== null, set: (value: boolean) => !value && (returning.value = null) });
const deducting = ref<{ row: Holder; item: HeldItem; key: number } | null>(null);
const deductOpen = computed({ get: () => deducting.value !== null, set: (value: boolean) => !value && (deducting.value = null) });
function onAction(kind: "returned" | "lost" | "deduct", row: Holder, item: HeldItem): void {
  if (kind === "deduct") deducting.value = { row, item, key: ++dialogKey };
  else returning.value = { row, item, start: kind, key: ++dialogKey };
}

const adding = ref<{ category: number | null; key: number } | null>(null);
const addOpen = computed({ get: () => adding.value !== null, set: (value: boolean) => !value && (adding.value = null) });
function add(categoryId: number | null = null): void {
  adding.value = { category: categoryId, key: ++dialogKey };
}

// `?give=<member id>` opens the dialog for that person (Person 360, the palette).
const giveParam = useRouteState("give", rs.optionalNumber());
watch(
  [giveParam, () => page.value],
  ([id, value]) => {
    if (id === null || !value) return;
    const row = value.people.find((each) => each.person.id === id);
    giveParam.value = null;
    give(row ? { id: row.person.id, name: row.person.name } : null);
  },
  { immediate: true },
);

const tabs = computed(() => [
  { value: "people" as const, label: t("lifecycle.equipment.tab.people"), icon: UsersRound },
  { value: "items" as const, label: t("lifecycle.equipment.tab.items"), icon: PackageOpen, count: page.value?.totals.in_stock || undefined },
]);
const stockLine = (item: StockItem) => [item.number, item.serial ? t("lifecycle.equipment.serial", { serial: item.serial }) : "", item.notes, multiBranch.value ? item.branch?.name : ""].filter(Boolean).join(" · ");
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('lifecycle.nav.equipment')" :description="t('lifecycle.equipment.description')">
      <template v-if="assetsOn && page" #actions>
        <UiButton variant="secondary" :icon="PackagePlus" data-add-items @click="add()">{{ t("lifecycle.equipment.addItems") }}</UiButton>
        <UiButton variant="primary" :icon="HandHelping" data-give-out @click="give()">{{ t("lifecycle.equipment.giveOut") }}</UiButton>
      </template>
    </PageHeader>

    <!-- The assets module is off: equipment lives there. -->
    <div v-if="!assetsOn" class="ui-card" data-assets-off>
      <EmptyState :icon="PackageOpen" size="lg" :title="t('lifecycle.equipment.off.title')" :description="t('lifecycle.equipment.off.body')">
        <UiButton v-if="company.can('company.settings')" variant="primary" :to="`/c/${company.currentId}/settings/features`">{{ t("lifecycle.equipment.off.action") }}</UiButton>
        <p v-else class="max-w-sm text-sm text-muted">{{ t("lifecycle.equipment.off.ask") }}</p>
      </EmptyState>
    </div>

    <template v-else>
      <KpiStrip v-if="page || skeleton" :items="kpis" :loading="skeleton" phone="grid" data-equipment-kpis />

      <div class="flex flex-wrap items-center gap-3">
        <div class="no-scrollbar max-w-full overflow-x-auto">
          <SegmentedControl v-model="tab" :options="tabs" :aria-label="t('lifecycle.nav.equipment')" />
        </div>
        <span class="flex-1" />
        <BranchPicker v-if="multiBranch" v-model="branch" clearable size="sm" class="w-full sm:w-52" :placeholder="t('lifecycle.equipment.filter.allBranches')" />
      </div>

      <ErrorState v-if="data.isError.value" class="ui-card" :error="data.error.value" :retry="() => data.refetch()" />

      <!-- People -->
      <template v-else-if="tab === 'people'">
        <div class="flex flex-col gap-2.5 lg:flex-row lg:items-center" data-people-filters>
          <TextInput v-model="query" type="search" size="sm" :icon="Search" clearable class="w-full lg:w-64" :placeholder="t('lifecycle.equipment.filter.search')" />
          <SelectBox v-if="categoryOptions.length > 1" v-model="categoryModel" :options="categoryOptions" size="sm" class="w-full lg:w-56" />
          <div class="no-scrollbar max-w-full overflow-x-auto">
            <SegmentedControl v-model="flag" :options="flagOptions" size="sm" :aria-label="t('lifecycle.equipment.filter.label')" />
          </div>
        </div>
        <div v-if="skeleton" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 4" :key="n" height="92px" radius="14px" /></div>
        <div v-else-if="page && !page.totals.items && !filtered" class="ui-card" data-equipment-empty>
          <EmptyState :icon="HandHelping" :title="t('lifecycle.equipment.empty.title')" :description="t('lifecycle.equipment.empty.body')">
            <div class="flex flex-wrap justify-center gap-2">
              <UiButton variant="secondary" :icon="PackagePlus" @click="add()">{{ t("lifecycle.equipment.addItems") }}</UiButton>
              <UiButton variant="primary" :icon="HandHelping" @click="give()">{{ t("lifecycle.equipment.giveOut") }}</UiButton>
            </div>
          </EmptyState>
        </div>
        <div v-else-if="page && !rows.length" class="ui-card">
          <EmptyState :icon="Search" tone="neutral" :title="t('lifecycle.equipment.empty.filtered')" :description="t('lifecycle.equipment.empty.filteredBody')" />
        </div>
        <TransitionGroup v-else tag="div" name="eq-list" class="flex flex-col gap-2.5" data-holders>
          <HolderRow v-for="row in rows" :key="row.person.id" :row="row" :can="can" :today="page!.today" @give="(each) => give({ id: each.person.id, name: each.person.name })" @action="onAction" />
        </TransitionGroup>
      </template>

      <!-- Items: the stock to give out -->
      <template v-else>
        <section v-if="suggestions.length && noCategories" class="ui-card flex flex-col gap-3 p-4" data-suggest>
          <div class="flex items-start gap-3">
            <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-primary"><PackagePlus :size="18" aria-hidden="true" /></span>
            <div class="min-w-0">
              <h2 class="text-md font-semibold text-fg">{{ t("lifecycle.equipment.suggest.title") }}</h2>
              <p class="text-sm text-muted">{{ t("lifecycle.equipment.suggest.body") }}</p>
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="suggestion in suggestions"
              :key="suggestion.key"
              type="button"
              class="inline-flex items-center gap-2 rounded-full border border-dashed border-line-strong bg-surface px-3.5 py-1.5 text-sm font-medium text-fg transition-colors hover:border-[var(--c-primary)] hover:bg-accent-soft hover:text-accent-fg"
              :data-suggestion="suggestion.key"
              :disabled="makeCategory.isPending.value"
              @click="makeCategory.mutate({ suggestion: suggestion.key })"
            >
              <component :is="categoryIcon(suggestion.icon)" :size="15" aria-hidden="true" />{{ suggestion.name }}<Plus :size="13" class="text-subtle" aria-hidden="true" />
            </button>
          </div>
        </section>

        <div v-if="stock.isPending.value" class="grid gap-3 md:grid-cols-2"><SkeletonBlock v-for="n in 4" :key="n" height="150px" radius="14px" /></div>
        <ErrorState v-else-if="stock.isError.value" class="ui-card" :error="stock.error.value" :retry="() => stock.refetch()" />
        <div v-else-if="!groups.length" class="ui-card">
          <EmptyState :icon="Boxes" :title="t('lifecycle.equipment.stock.emptyTitle')" :description="t('lifecycle.equipment.stock.emptyBody')">
            <UiButton variant="primary" :icon="PackagePlus" @click="add()">{{ t("lifecycle.equipment.addItems") }}</UiButton>
          </EmptyState>
        </div>
        <div v-else class="grid items-start gap-3 md:grid-cols-2" data-stock>
          <section v-for="group in groups" :key="group.category.id" class="ui-card flex flex-col overflow-hidden" :data-stock-group="group.category.id">
            <header class="flex items-center gap-3 border-b border-line px-4 py-3">
              <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(group.category.icon)" :size="17" aria-hidden="true" /></span>
              <div class="min-w-0 flex-1">
                <h2 class="truncate text-base font-semibold text-fg">{{ group.category.name }}</h2>
                <p class="text-xs text-muted">
                  {{ t("lifecycle.equipment.inStock", { n: group.items.length }, group.items.length) }}
                  <template v-if="group.category.kind !== 'low_value'"> · {{ t("lifecycle.equipment.device") }}</template>
                </p>
              </div>
              <UiButton v-if="group.category.kind === 'low_value' || can.devices" size="sm" variant="ghost" :icon="Plus" :aria-label="t('lifecycle.equipment.addTo', { name: group.category.name })" @click="add(group.category.id)">{{ t("lifecycle.equipment.add.short") }}</UiButton>
            </header>
            <ul v-if="group.items.length" class="flex max-h-80 flex-col overflow-y-auto py-1">
              <li v-for="item in group.items" :key="item.id" class="group/stock flex min-w-0 items-center gap-3 px-4 py-2 hover:bg-surface-2/60 dark:hover:bg-surface-3/40" :data-stock-item="item.id">
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-fg">{{ item.model ? `${item.name} · ${item.model}` : item.name }}</p>
                  <p class="truncate text-xs text-muted">{{ stockLine(item) }}</p>
                </div>
                <StatusPill v-if="item.condition !== 'good'" size="sm" variant="outline" :tone="item.condition === 'new' ? 'success' : item.condition === 'damaged' ? 'danger' : 'warning'" :label="t(`lifecycle.equipment.condition.${item.condition}`)" />
                <UiButton size="sm" variant="ghost" :icon="HandHelping" class="opacity-70 group-hover/stock:opacity-100" @click="give(null, [item.id])">{{ t("lifecycle.equipment.give") }}</UiButton>
              </li>
            </ul>
            <p v-else class="flex items-center gap-2 px-4 py-4 text-sm text-muted"><CircleAlert :size="15" class="text-subtle" aria-hidden="true" />{{ t("lifecycle.equipment.stock.none") }}</p>
          </section>
        </div>
      </template>
    </template>

    <IssueDialog v-if="issuing" :key="issuing.key" v-model:open="issueOpen" :person="issuing.person" :items="issuing.items" />
    <ReturnDialog v-if="returning" :key="returning.key" v-model:open="returnOpen" :holder="returning.row" :item="returning.item" :can="can" :start="returning.start" />
    <DeductionDialog v-if="deducting" :key="deducting.key" v-model:open="deductOpen" :holder="deducting.row" :item="deducting.item" />
    <AddItemsDialog v-if="adding" :key="adding.key" v-model:open="addOpen" :category="adding.category" />
  </div>
</template>

<style scoped>
.eq-list-move {
  transition: transform 220ms var(--ease-out, ease);
}
</style>
