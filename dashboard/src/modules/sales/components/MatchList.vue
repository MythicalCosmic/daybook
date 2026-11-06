<script setup lang="ts">
/**
 * The match list (plan §14.7): item codes from the cash-register program that the medicines
 * catalogue doesn't know. Matching a code once remembers it and settles every line waiting for
 * it (their stock moves then); a code that isn't goods (a bag, a service) can be set aside.
 * Set-aside codes stay one tap away and can still be matched.
 */
import { Link2, PackageX, SearchCheck } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ComboBox from "@/components/ComboBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import MoneyText from "@/components/MoneyText.vue";
import type { OptionSource, SelectOption } from "@/components/options";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId } from "@/stores/company";

import { salesApi, useCodes, useSalesMutation } from "../api";
import type { LineCode } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const cid = useCompanyId();
const confirm = useConfirm();
const which = useRouteState<"waiting" | "skipped">("codes", rs.enum(["waiting", "skipped"] as const, "waiting"));
const query = useCodes(which);
const views = computed(() => [
  { value: "waiting" as const, label: t("sales.match.waiting") },
  { value: "skipped" as const, label: t("sales.match.skipped") },
]);

const target = ref<LineCode | null>(null);
const product = ref<number | null>(null);
const picked = ref<SelectOption<number> | null>(null);
const source: OptionSource<number> = async (q, signal) => {
  const found = await salesApi.products(cid.value, q, signal);
  return found.results.map((row) => ({
    value: row.id,
    label: row.name,
    description: [row.barcode, row.inn, row.rx_required ? t("sales.lines.rx") : ""].filter(Boolean).join(" · "),
  }));
};
function start(row: LineCode): void {
  target.value = row;
  product.value = null;
  picked.value = null;
}

const match = useSalesMutation((c, vars: { code: string; product: number }) => salesApi.match(c, vars.code, vars.product));
async function submit(): Promise<void> {
  if (!target.value || !product.value) return;
  const done = await match.mutateAsync({ code: target.value.code, product: product.value });
  toast.success(t("sales.match.done", { n: done.lines }, done.lines));
  target.value = null;
}

const skip = useSalesMutation((c, code: string) => salesApi.skip(c, code));
async function askSkip(row: LineCode): Promise<void> {
  const ok = await confirm({ title: t("sales.match.skipTitle", { code: row.code }), message: t("sales.match.skipBody", { name: row.name }), confirmLabel: t("sales.match.skip") });
  if (!ok) return;
  await skip.mutateAsync(row.code);
  toast.success(t("sales.match.skippedToast"));
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <SegmentedControl v-model="which" :options="views" size="sm" :aria-label="t('sales.import.tab.match')" />
      <p class="text-sm text-muted">{{ t("sales.match.hint") }}</p>
    </div>
    <div v-if="query.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState
      v-else-if="!query.data.value?.results.length"
      :icon="which === 'waiting' ? SearchCheck : PackageX"
      tone="success"
      :title="which === 'waiting' ? t('sales.match.emptyTitle') : t('sales.match.emptySkipped')"
      :description="which === 'waiting' ? t('sales.match.emptyBody') : undefined"
    />
    <ul v-else class="flex flex-col divide-y divide-line rounded-xl border border-line bg-surface">
      <li v-for="row in query.data.value.results" :key="row.code" class="flex flex-wrap items-center gap-3 px-4 py-3">
        <div class="min-w-0 flex-1">
          <p class="truncate font-medium text-fg">{{ row.name }}</p>
          <p class="truncate text-xs text-muted">
            <span class="font-mono">{{ row.code }}</span>
            · {{ t("sales.match.lines", { n: row.lines }, row.lines) }}
            · <MoneyText :value="row.total" />
            · {{ row.branches.join(", ") }}
            <template v-if="row.last_day"> · {{ t("sales.match.last", { day: fmt.day(row.last_day) }) }}</template>
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <UiButton v-if="which === 'waiting'" size="sm" variant="ghost" :icon="PackageX" @click="askSkip(row)">{{ t("sales.match.skip") }}</UiButton>
          <UiButton size="sm" variant="primary" :icon="Link2" @click="start(row)">{{ t("sales.match.match") }}</UiButton>
        </div>
      </li>
    </ul>

    <UiDialog :open="!!target" :title="t('sales.match.dialogTitle', { code: target?.code ?? '' })" :description="t('sales.match.dialogBody', { name: target?.name ?? '', n: target?.lines ?? 0 }, target?.lines ?? 0)" size="md" @update:open="(value: boolean) => !value && (target = null)">
      <FormField :label="t('sales.match.product')" required>
        <ComboBox v-model="product" :source="source" :selected="picked" :placeholder="t('sales.match.search')" :search-placeholder="t('sales.match.search')" @change="(value: SelectOption<number> | null) => (picked = value)" />
      </FormField>
      <template #footer>
        <UiButton variant="ghost" @click="target = null">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :icon="Link2" :disabled="!product" :loading="match.isPending.value" @click="submit">{{ t("sales.match.confirm") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
