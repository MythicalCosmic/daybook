<script setup lang="ts">
/**
 * One stock count. While it is open it is blind: each line shows the product, series and expiry,
 * never what the books expect; the counter types what is on the shelf in packs and parts and adds
 * anything found that isn't listed. Once counted, a manager sees what was expected and the
 * difference (at cost with finance.view) and applies it: differences become count adjustments.
 */
import { Check, ClipboardCheck, PackagePlus, Save } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useCount, useRefresh } from "../api";
import ProductPicker from "../components/ProductPicker.vue";
import { COUNT_TONES, num, packsAndParts, partsOf } from "../lib";
import type { CountLine, Product } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const route = useRoute();
const refresh = useRefresh();

const id = computed(() => Number(route.params.countId ?? 0));
const query = useCount(id);
const count = computed(() => query.data.value?.count ?? null);
const lines = computed(() => query.data.value?.lines ?? []);
const isOpen = computed(() => count.value?.status === "open");
const canCount = computed(() => company.can(["stock.manage", "stock.operate"]));
const canApply = computed(() => company.can("stock.manage"));
const showCost = computed(() => lines.value.some((line) => line.value_difference !== undefined));

/** What the counter typed, per line: whole packs and loose parts. */
const drafts = reactive<Record<number, { packs: number | null; parts: number | null }>>({});
watch(
  lines,
  (rows) => {
    for (const line of rows) {
      if (drafts[line.id]) continue;
      const per = Math.max(1, line.units_per_pack);
      const counted = line.counted === null ? null : num(line.counted);
      drafts[line.id] = counted === null ? { packs: null, parts: null } : { packs: Math.floor(counted / per), parts: counted % per };
    }
  },
  { immediate: true },
);
const dirty = computed(() =>
  lines.value.filter((line) => {
    const draft = drafts[line.id];
    if (!draft || (draft.packs === null && draft.parts === null)) return false;
    return line.counted === null || partsOf(draft.packs, draft.parts, line.units_per_pack) !== num(line.counted);
  }),
);

const busy = ref<string | null>(null);
const cid = () => company.currentId ?? 0;
async function run(kind: string, action: () => Promise<unknown>, done: string): Promise<boolean> {
  busy.value = kind;
  try {
    await action();
    toast.success(done);
    refresh();
    return true;
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
    return false;
  } finally {
    busy.value = null;
  }
}
async function save(): Promise<boolean> {
  const rows = dirty.value.map((line) => ({ line: line.id, counted: String(partsOf(drafts[line.id]!.packs, drafts[line.id]!.parts, line.units_per_pack)) }));
  if (!rows.length) return true;
  return run("save", () => stockApi.countLines(cid(), id.value, rows), t("stock.count.saved", { n: rows.length }, rows.length));
}
async function submit(): Promise<void> {
  if (!(await save())) return;
  await run("submit", () => stockApi.submitCount(cid(), id.value), t("stock.count.submittedToast"));
}
const apply = () => run("apply", () => stockApi.applyCount(cid(), id.value), t("stock.count.appliedToast"));

const found = reactive({ open: false, product: null as number | null, unitsPerPack: 1, partLabel: "", series: "", expires: null as string | null, packs: null as number | null, parts: null as number | null });
function startFound(): void {
  Object.assign(found, { open: true, product: null, unitsPerPack: 1, partLabel: "", series: "", expires: null, packs: null, parts: null });
}
function pickFound(row: Product | null): void {
  found.unitsPerPack = row?.units_per_pack ?? 1;
  found.partLabel = row?.part_label ?? "";
}
async function saveFound(): Promise<void> {
  const counted = partsOf(found.packs, found.parts, found.unitsPerPack);
  if (!found.product || !found.series.trim() || !found.expires || counted <= 0) return;
  const ok = await run("found", () => stockApi.found(cid(), id.value, { product: found.product!, series: found.series.trim(), expires_on: found.expires!, counted: String(counted) }), t("stock.count.foundToast"));
  if (ok) found.open = false;
}

const differences = computed(() => lines.value.filter((line) => line.difference !== undefined && line.difference !== null && num(line.difference) !== 0));
const qty = (line: CountLine, value: string | number | null | undefined) => packsAndParts(value, line.units_per_pack, line.part_label, t);
</script>

<template>
  <div>
    <ErrorState v-if="query.error.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.isPending.value" class="flex flex-col gap-3"><SkeletonBlock class="h-16" /><SkeletonBlock class="h-48" /></div>
    <template v-else-if="count">
      <PageHeader :title="`${t(`stock.countKind.${count.kind}`)} · ${count.branch.name}`" :description="t('stock.count.startedOn', { day: fmt.instant(count.created_at, 'date') })" :back="`/c/${company.currentId}/stock/counts`">
        <template #meta><StatusPill :tone="COUNT_TONES[count.status]" :label="t(`stock.countStatus.${count.status}`)" /></template>
        <template #actions>
          <template v-if="isOpen && canCount">
            <UiButton variant="secondary" :icon="PackagePlus" @click="startFound">{{ t("stock.count.found") }}</UiButton>
            <UiButton variant="secondary" :icon="Save" :disabled="!dirty.length" :loading="busy === 'save'" data-testid="count-save" @click="save">{{ t("common.save") }}</UiButton>
            <UiButton variant="primary" :icon="ClipboardCheck" :loading="busy === 'submit'" @click="submit">{{ t("stock.count.submit") }}</UiButton>
          </template>
          <UiButton v-if="count.status === 'submitted' && canApply" variant="primary" :icon="Check" :loading="busy === 'apply'" data-testid="count-apply" @click="apply">{{ t("stock.count.apply") }}</UiButton>
        </template>
      </PageHeader>

      <InlineAlert v-if="isOpen" class="mb-4" tone="info">{{ t("stock.count.blindNote") }}</InlineAlert>
      <InlineAlert v-else-if="count.status === 'submitted'" class="mb-4" tone="warning">{{ t("stock.count.reviewNote", { n: differences.length }, differences.length) }}</InlineAlert>
      <div v-if="count.value_difference !== undefined && count.value_difference !== null" class="mb-4 text-sm">
        {{ t("stock.count.difference") }}: <MoneyText :value="count.value_difference" sign="always" colored />
      </div>

      <div class="ui-card overflow-x-auto">
        <table class="w-full min-w-[640px] text-sm" data-testid="count-lines">
          <thead class="text-xs text-muted">
            <tr class="border-b border-line">
              <th class="px-4 py-2 text-start font-medium">{{ t("stock.col.name") }}</th>
              <th class="px-4 py-2 text-start font-medium">{{ t("stock.col.series") }}</th>
              <th class="px-4 py-2 text-start font-medium">{{ t("stock.col.expiresOn") }}</th>
              <th class="px-4 py-2 text-end font-medium">{{ t("stock.count.counted") }}</th>
              <template v-if="!isOpen">
                <th class="px-4 py-2 text-end font-medium">{{ t("stock.count.expected") }}</th>
                <th class="px-4 py-2 text-end font-medium">{{ t("stock.count.difference") }}</th>
                <th v-if="showCost" class="px-4 py-2 text-end font-medium">{{ t("stock.count.atCost") }}</th>
              </template>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="line in lines" :key="line.id" :data-line="line.id">
              <td class="px-4 py-2 text-fg">{{ line.product.name }}</td>
              <td class="px-4 py-2 font-mono text-xs text-muted">{{ line.series }}</td>
              <td class="px-4 py-2 text-xs text-muted">{{ line.expires_on ? fmt.day(line.expires_on) : "—" }}</td>
              <td class="px-4 py-2 text-end">
                <div v-if="isOpen && canCount && drafts[line.id]" class="flex items-center justify-end gap-2">
                  <NumberInput v-model="drafts[line.id]!.packs" :min="0" size="sm" class="w-24" :suffix="t('stock.field.packsShort')" :steppers="false" />
                  <NumberInput v-if="line.units_per_pack > 1" v-model="drafts[line.id]!.parts" :min="0" :max="line.units_per_pack - 1" size="sm" class="w-24" :suffix="line.part_label || t('stock.field.partsShort')" :steppers="false" />
                </div>
                <span v-else-if="line.counted !== null" class="tabular-nums text-fg">{{ qty(line, line.counted) }}</span>
                <span v-else class="text-subtle">{{ t("stock.count.notCounted") }}</span>
              </td>
              <template v-if="!isOpen">
                <td class="px-4 py-2 text-end tabular-nums text-muted">{{ line.expected !== undefined ? qty(line, line.expected) : "—" }}</td>
                <td :class="['px-4 py-2 text-end tabular-nums', num(line.difference) < 0 ? 'text-danger' : num(line.difference) > 0 ? 'text-success' : 'text-subtle']">
                  {{ line.difference !== undefined && line.difference !== null ? qty(line, line.difference) : "—" }}
                </td>
                <td v-if="showCost" class="px-4 py-2 text-end"><MoneyText v-if="line.value_difference !== undefined" :value="line.value_difference" sign="always" colored decimals="never" /></td>
              </template>
            </tr>
            <tr v-if="!lines.length"><td class="px-4 py-6 text-center text-muted" colspan="7">{{ t("stock.count.empty") }}</td></tr>
          </tbody>
        </table>
      </div>

      <UiDialog v-model:open="found.open" :title="t('stock.count.foundTitle')" :description="t('stock.count.foundDescription')" size="sm">
        <div class="flex flex-col gap-3">
          <FormField :label="t('stock.field.product')" required>
            <ProductPicker v-model="found.product" @change="pickFound" />
          </FormField>
          <div class="grid grid-cols-2 gap-3">
            <FormField :label="t('stock.field.series')" required>
              <TextInput v-model="found.series" :maxlength="40" mono />
            </FormField>
            <FormField :label="t('stock.field.expiresOn')" required>
              <DatePicker v-model="found.expires" />
            </FormField>
            <FormField :label="t('stock.field.packs')">
              <NumberInput v-model="found.packs" :min="0" />
            </FormField>
            <FormField v-if="found.unitsPerPack > 1" :label="t('stock.field.looseParts', { label: found.partLabel || t('stock.drawer.parts') })">
              <NumberInput v-model="found.parts" :min="0" :max="found.unitsPerPack - 1" />
            </FormField>
          </div>
        </div>
        <template #footer>
          <UiButton variant="ghost" @click="found.open = false">{{ t("common.cancel") }}</UiButton>
          <UiButton variant="primary" :loading="busy === 'found'" @click="saveFound">{{ t("stock.count.addFound") }}</UiButton>
        </template>
      </UiDialog>
    </template>
  </div>
</template>
