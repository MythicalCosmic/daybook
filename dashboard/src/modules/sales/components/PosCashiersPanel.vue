<script setup lang="ts">
/**
 * Settings → Cash-register cashiers (plan §14.7): the cashier names or codes the cash-register
 * program puts on its receipts, each linked to a person once. Imported receipts then carry that
 * person, earlier ones included, for the cashier's lines and the night-pharmacist figures.
 */
import { UserRoundCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useOptions, usePosCashiers, useSalesMutation } from "../api";
import type { PosCashier } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = usePosCashiers();
const options = useOptions();
const canEdit = computed(() => company.can("sales.manage"));
const people = computed(() => [
  { value: 0, label: t("sales.pos.nobody") },
  ...(options.data.value?.cashiers ?? []).map((person) => ({ value: person.id, label: person.name })),
]);

const map = useSalesMutation((cid, vars: { id: number; member: number | null }) => salesApi.mapCashier(cid, vars.id, vars.member));
async function change(row: PosCashier, value: number | null): Promise<void> {
  await map.mutateAsync({ id: row.id, member: value || null });
  toast.success(t("sales.pos.saved", { code: row.code }));
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <p class="text-sm text-muted">{{ t("sales.pos.description") }}</p>
    <div v-if="query.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="56px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="!query.data.value?.length" size="sm" :icon="UserRoundCheck" tone="neutral" :title="t('sales.pos.emptyTitle')" :description="t('sales.pos.emptyBody')" />
    <ul v-else class="flex flex-col divide-y divide-line rounded-xl border border-line bg-surface">
      <li v-for="row in query.data.value" :key="row.id" class="grid items-center gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_260px]">
        <div class="min-w-0">
          <p class="truncate font-mono text-sm font-semibold text-fg">{{ row.code }}</p>
          <p class="truncate text-xs text-muted">
            {{ t("sales.pos.receipts", { n: row.receipts }, row.receipts) }}
            <template v-if="row.last_sold_at"> · {{ t("sales.pos.last", { when: fmt.instant(row.last_sold_at, "short") }) }}</template>
          </p>
        </div>
        <SelectBox :model-value="row.member?.id ?? 0" :options="people" :disabled="!canEdit || map.isPending.value" :aria-label="t('sales.pos.who', { code: row.code })" @update:model-value="(value: number | null) => change(row, value)" />
      </li>
    </ul>
  </div>
</template>
