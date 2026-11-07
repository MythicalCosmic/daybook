<script setup lang="ts">
/**
 * Overview tile "Expiring within 30 days": how many batches on hand expire within a month and what
 * they are worth (at cost with finance.view, else at retail), and how many have already expired.
 * Opens the expiry board.
 */
import { ArrowUpRight, Hourglass } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useSummary } from "../api";

defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const summary = useSummary(computed(() => ({ branch: branch.value })));
const value = computed(() => summary.data.value?.expiring_30d_value ?? summary.data.value?.expiring_30d_retail ?? null);
</script>

<template>
  <RouterLink :to="`/c/${companyId}/stock/expiry`" class="ui-card group flex h-full min-h-[148px] min-w-0 flex-col p-4 transition-colors hover:border-line-strong" :aria-busy="summary.isPending.value || undefined" data-testid="stock-expiring-widget">
    <div class="flex items-start gap-2">
      <Hourglass :size="15" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
      <span class="kpi-label">{{ t("stock.widget.expiring") }}</span>
      <ArrowUpRight :size="15" class="mt-px shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </div>
    <ErrorState v-if="summary.isError.value" class="mt-2.5" compact bare :error="summary.error.value" :retry="() => summary.refetch()" @click.stop.prevent />
    <template v-else-if="summary.isPending.value">
      <SkeletonBlock class="mt-2.5" width="62%" height="26px" />
      <SkeletonBlock class="mt-auto" height="16px" />
    </template>
    <template v-else-if="summary.data.value">
      <p class="kpi-value mt-1.5 truncate">{{ fmt.money(value, undefined, { compact: true, decimals: "never" }) }}</p>
      <p class="mt-0.5 truncate text-xs text-muted">
        {{ t("stock.widget.batches", { n: summary.data.value.expiring_30d }, summary.data.value.expiring_30d) }}
        · {{ summary.data.value.expiring_30d_value !== undefined ? t("stock.expiry.atCost") : t("stock.expiry.atRetail") }}
      </p>
      <p v-if="summary.data.value.expired" class="mt-auto pt-2 text-xs font-medium text-danger">{{ t("stock.widget.expired", { n: summary.data.value.expired }, summary.data.value.expired) }}</p>
    </template>
  </RouterLink>
</template>
