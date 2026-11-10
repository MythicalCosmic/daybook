<script setup lang="ts">
/**
 * Policies (Kadrlar › Qoidalar): the company's rules people read and sign in the app. Tabs for the
 * ones in force, the drafts never published and the archived ones; each card says who a policy
 * applies to and how the signing goes (signed of everyone asked, waiting, late, the deadline).
 * "New policy" opens the editor (`?new=1` from the palette too).
 */
import { FileText, Plus, ScrollText, Tags } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { usePolicies } from "../policies/api";
import { policyView } from "../policies/lib";
import PolicyCard from "../policies/PolicyCard.vue";
import { POLICY_CATEGORIES, type Policy, type PolicyView } from "../policies/types";

const { t, locale } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const canManage = computed(() => company.can("hr.manage"));
const base = computed(() => `/c/${company.currentId}/hr/policies`);

const view = useRouteState<PolicyView>("view", rs.enum(["active", "drafts", "archived"] as const, "active"));
const search = useRouteState("q", rs.string(""));
const defs = computed<FilterDef[]>(() => [
  { key: "category", label: t("hr.policy.field.category"), type: "multi", icon: Tags, pinned: true, options: POLICY_CATEGORIES.map((value) => ({ value, label: t(`hr.policy.category.${value}`) })) },
]);
const filters = useUrlFilters(defs);
const filtered = computed(() => filters.active.value > 0 || !!search.value);

const query = usePolicies(() => ({ view: "all", q: search.value || undefined, ...(filters.params.value as { category?: string[] }) }));
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const rows = computed<Policy[]>(() => query.data.value ?? []);
const grouped = computed(() => {
  const collator = new Intl.Collator(locale.value);
  const groups: Record<PolicyView, Policy[]> = { active: [], drafts: [], archived: [] };
  for (const row of rows.value) groups[policyView(row)].push(row);
  // In force: the ones with people late first, then those still collecting signatures.
  groups.active.sort((a, b) => (b.tally?.late ?? 0) - (a.tally?.late ?? 0) || (b.tally?.waiting ?? 0) - (a.tally?.waiting ?? 0) || collator.compare(a.title, b.title));
  return groups;
});
const shown = computed(() => grouped.value[view.value]);

const tabs = computed(() => [
  { id: "active", label: t("hr.policy.tab.active"), count: grouped.value.active.length || undefined },
  { id: "drafts", label: t("hr.policy.tab.drafts"), count: grouped.value.drafts.length || undefined },
  { id: "archived", label: t("hr.policy.tab.archived"), count: grouped.value.archived.length || undefined },
]);

const empty = computed(() => {
  if (filtered.value) return { icon: FileText, title: t("hr.empty.noMatch"), body: t("hr.empty.noMatchBody") };
  if (view.value === "drafts") return { icon: FileText, title: t("hr.policy.emptyDrafts"), body: t("hr.policy.emptyDraftsBody") };
  if (view.value === "archived") return { icon: FileText, title: t("hr.policy.emptyArchived"), body: t("hr.policy.emptyArchivedBody") };
  return { icon: ScrollText, title: t("hr.policy.emptyTitle"), body: t("hr.policy.emptyBody") };
});

// "New policy" from the palette (?new=1).
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (canManage.value) void router.push(`${base.value}/new`);
  },
  { immediate: true },
);
</script>

<template>
  <div>
    <PageHeader v-model:tab="view" :title="t('hr.nav.policies')" :description="t('hr.policy.description')" :tabs="tabs">
      <template v-if="canManage" #actions>
        <UiButton variant="primary" :icon="Plus" :to="`${base}/new`">{{ t("hr.policy.new") }}</UiButton>
      </template>
    </PageHeader>

    <div class="mb-4">
      <FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable :search-placeholder="t('hr.policy.search')" />
    </div>

    <div v-if="skeleton" class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="n in 3" :key="n" class="ui-card flex flex-col gap-3 p-4">
        <div class="flex gap-3"><SkeletonBlock width="40px" height="40px" radius="10px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="70%" height="16px" /><SkeletonBlock width="40%" /></div></div>
        <SkeletonBlock width="60%" /><SkeletonBlock height="8px" radius="99px" />
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !shown.length" class="ui-card">
      <EmptyState :icon="empty.icon" size="lg" :title="empty.title" :description="empty.body">
        <UiButton v-if="filtered" variant="secondary" @click="filters.clear(); search = ''">{{ t("common.filter.clearAll") }}</UiButton>
        <UiButton v-else-if="canManage && view !== 'archived'" variant="primary" :icon="Plus" :to="`${base}/new`">{{ t("hr.policy.new") }}</UiButton>
      </EmptyState>
    </div>
    <ul v-else class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" data-policies>
      <li v-for="row in shown" :key="row.id">
        <PolicyCard :policy="row" :to="`${base}/${row.id}`" />
      </li>
    </ul>
  </div>
</template>
