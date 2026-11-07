<script setup lang="ts">
/**
 * Overview tile "Stock needs you": receipts waiting for posting, write-offs to approve, transfers
 * that arrived short, open recalls, mandatory medicines missing and items below their minimum.
 * Each line links to its page; nothing to do says so.
 */
import { ArrowUpRight, PackageCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useCompanyStore } from "@/stores/company";

import { useSummary } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const company = useCompanyStore();
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const summary = useSummary(computed(() => ({ branch: branch.value })));

const lines = computed(() => {
  const data = summary.data.value;
  if (!data) return [];
  const base = `/c/${props.companyId}/stock`;
  return [
    { key: "post", n: data.receipts_to_post, label: t("stock.widget.toPost", { n: data.receipts_to_post }, data.receipts_to_post), to: `${base}/receipts`, tone: "text-fg" },
    { key: "approve", n: data.writeoffs_to_approve, label: t("stock.widget.toApprove", { n: data.writeoffs_to_approve }, data.writeoffs_to_approve), to: `${base}/write-offs`, tone: "text-fg" },
    { key: "disputed", n: data.transfers_disputed, label: t("stock.widget.disputed", { n: data.transfers_disputed }, data.transfers_disputed), to: `${base}/transfers`, tone: "text-danger" },
    { key: "recalls", n: data.recalls_open, label: t("stock.widget.recalls", { n: data.recalls_open }, data.recalls_open), to: `${base}/recalls`, tone: "text-danger" },
    { key: "mandatory", n: data.mandatory_missing, label: t("stock.widget.mandatory", { n: data.mandatory_missing }, data.mandatory_missing), to: `${base}/levels?mandatory=1`, tone: "text-warning" },
    { key: "low", n: data.low, label: t("stock.widget.low", { n: data.low }, data.low), to: `${base}/levels?low=1`, tone: "text-warning" },
  ].filter((line) => line.n > 0);
});
</script>

<template>
  <div class="ui-card flex h-full min-h-[148px] min-w-0 flex-col p-4" :aria-busy="summary.isPending.value || undefined" data-testid="stock-attention-widget">
    <RouterLink :to="`/c/${companyId}/stock/levels`" class="group flex items-start gap-2">
      <PackageCheck :size="15" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
      <span class="kpi-label">{{ t("stock.widget.attention") }}</span>
      <ArrowUpRight :size="15" class="mt-px shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </RouterLink>
    <ErrorState v-if="summary.isError.value" class="mt-2.5" compact bare :error="summary.error.value" :retry="() => summary.refetch()" />
    <template v-else-if="summary.isPending.value">
      <SkeletonBlock class="mt-2.5" height="16px" />
      <SkeletonBlock class="mt-2" width="70%" height="16px" />
    </template>
    <ul v-else-if="lines.length" class="mt-2 flex flex-col gap-1 text-sm">
      <li v-for="line in lines" :key="line.key">
        <RouterLink :to="line.to" :class="['hover:underline', line.tone]">{{ line.label }}</RouterLink>
      </li>
    </ul>
    <p v-else class="mt-2 text-sm text-muted">{{ t("stock.widget.allClear") }}</p>
  </div>
</template>
