<script setup lang="ts">
/**
 * Contract templates (plan §6.2 HR): the company's texts that contracts are printed from, each with
 * its kind and language; a template opens in the editor (`hr/contract-templates/:id`).
 */
import { Braces, FileSignature, Languages, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useTemplates } from "../api";
import { placeholdersIn } from "../lib";

const { t, locale } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = useTemplates();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const base = computed(() => `/c/${company.currentId}/hr/contract-templates`);
/** Active first, then by name. */
const rows = computed(() => {
  const collator = new Intl.Collator(locale.value);
  return [...(query.data.value ?? [])].sort((a, b) => Number(b.is_active) - Number(a.is_active) || collator.compare(a.name, b.name));
});
</script>

<template>
  <div>
    <PageHeader :title="t('hr.nav.templates')" :description="t('hr.template.description')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" :to="`${base}/new`">{{ t("hr.template.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="n in 3" :key="n" class="ui-card flex flex-col gap-3 p-4"><SkeletonBlock width="60%" height="18px" /><SkeletonBlock width="40%" /><SkeletonBlock height="28px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !rows.length" class="ui-card">
      <EmptyState :icon="FileSignature" size="lg" :title="t('hr.template.emptyTitle')" :description="t('hr.template.emptyBody')">
        <UiButton variant="primary" :icon="Plus" :to="`${base}/new`">{{ t("hr.template.new") }}</UiButton>
      </EmptyState>
    </div>
    <ul v-else class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      <li v-for="row in rows" :key="row.id">
        <RouterLink :to="`${base}/${row.id}`" class="ui-card group flex h-full flex-col gap-3 p-4 transition-colors hover:border-line-strong">
          <div class="flex items-start gap-3">
            <span class="grid size-10 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg" aria-hidden="true"><FileSignature :size="19" /></span>
            <div class="min-w-0 flex-1">
              <p class="line-clamp-2 text-base font-semibold text-fg group-hover:text-primary">{{ row.name }}</p>
              <p class="truncate text-sm text-muted">{{ row.kind ? t(`hr.contractKind.${row.kind}`) : t("hr.template.anyKind") }}</p>
            </div>
          </div>
          <div class="mt-auto flex flex-wrap items-center gap-1.5">
            <StatusPill :tone="row.is_active ? 'success' : 'neutral'" size="sm" :label="row.is_active ? t('hr.template.active') : t('hr.template.inactive')" />
            <StatusPill tone="neutral" variant="outline" size="sm" :dot="false" :icon="Languages" :label="t(`hr.language.${row.language}`)" />
            <StatusPill tone="neutral" variant="outline" size="sm" :dot="false" :icon="Braces" :label="t('hr.template.placeholdersCount', { n: placeholdersIn(row.body).length }, placeholdersIn(row.body).length)" />
            <span class="ml-auto text-xs text-subtle">{{ t("hr.template.updated", { date: fmt.day(row.updated_at.slice(0, 10), "medium") }) }}</span>
          </div>
        </RouterLink>
      </li>
    </ul>
  </div>
</template>
