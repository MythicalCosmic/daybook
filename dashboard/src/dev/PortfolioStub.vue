<script setup lang="ts">
/** Dev-only stand-in for package A's portfolio page (§13.1): one card per company. */
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import CompanyLogo from "@/components/CompanyLogo.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import { useCompanyStore } from "@/stores/company";

const { t } = useI18n();
const company = useCompanyStore();
</script>

<template>
  <div>
    <PageHeader :title="t('dev.portfolio.title')" :description="t('shell.company.portfolioHint')" />
    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <RouterLink
        v-for="item in company.companies"
        :key="item.id"
        :to="`/c/${item.id}`"
        class="flex flex-col gap-4 rounded-card border border-line bg-surface p-4 transition-colors hover:border-line-strong"
      >
        <div class="flex items-center gap-3">
          <CompanyLogo :name="item.name" :src="item.logo" :size="36" :alert="(item.alerts ?? 0) > 0" style="--logo-ring: var(--c-surface)" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ item.name }}</p>
            <p class="text-xs text-muted">{{ item.role.name }}</p>
          </div>
          <UiBadge v-if="item.pending" :count="item.pending" tone="primary" />
        </div>
        <div class="grid grid-cols-3 gap-3">
          <SkeletonBlock v-for="n in 3" :key="n" height="34px" radius="8px" />
        </div>
      </RouterLink>
    </div>
    <div class="mt-4 rounded-card border border-dashed border-line-strong">
      <EmptyState size="sm" tone="neutral" :title="t('dev.stub.title', { pkg: 'A' })" :description="t('dev.stub.body')" />
    </div>
  </div>
</template>
