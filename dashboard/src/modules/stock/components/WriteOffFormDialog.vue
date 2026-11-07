<script setup lang="ts">
/**
 * Propose a write-off (Hisobdan chiqarish): the pharmacy, the reason, and the series with their
 * quantities. Unfit goods (expired, damaged, a quality defect, a recall) are later destroyed by a
 * commission with an act; a shortage or the pharmacy's own use has no destruction step. The expiry
 * board hands its selected batches over in `prefill`. Photos are added on the write-off's page.
 */
import { Plus, Trash2 } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import type { SelectOption } from "@/components/options";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import { partsOf } from "../lib";
import { WRITEOFF_REASONS, type BatchPrefill, type Product, type WriteOffReason } from "../types";
import ProductPicker from "./ProductPicker.vue";

interface Line {
  key: number;
  product: number | null;
  initial: { id: number; name: string } | null;
  unitsPerPack: number;
  partLabel: string;
  batch: number | null;
  batchOptions: SelectOption<number>[];
  packs: number | null;
  parts: number | null;
}

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ branch?: number | null; reason?: WriteOffReason; prefill?: BatchPrefill[]; recall?: number | null }>(), {
  branch: null,
  reason: "expired",
  prefill: () => [],
  recall: null,
});
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();

const form = reactive({ branch: null as number | null, reason: "expired" as WriteOffReason, note: "" });
const lines = ref<Line[]>([]);
const errors = reactive<Record<string, string | undefined>>({});
const saving = ref(false);
let keys = 0;

const reasonOptions = computed(() => WRITEOFF_REASONS.map((value) => ({ value, label: t(`stock.reason.${value}`) })));
const unfit = computed(() => ["expired", "damaged", "recall", "quality"].includes(form.reason));

function blankLine(): Line {
  return { key: ++keys, product: null, initial: null, unitsPerPack: 1, partLabel: "", batch: null, batchOptions: [], packs: null, parts: null };
}

watch(open, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  form.branch = props.branch ?? (company.branchFilter.length === 1 ? (company.branchFilter[0] ?? null) : null);
  form.reason = props.reason;
  form.note = "";
  lines.value = props.prefill.length
    ? props.prefill.map((row) => {
        const per = Math.max(1, row.unitsPerPack);
        return {
          key: ++keys,
          product: row.product.id,
          initial: row.product,
          unitsPerPack: per,
          partLabel: row.partLabel,
          batch: row.batchId,
          batchOptions: [{ value: row.batchId, label: row.series }],
          packs: Math.floor(row.quantity / per),
          parts: row.quantity % per,
        };
      })
    : [blankLine()];
});

async function pickProduct(line: Line, product: Product | null): Promise<void> {
  line.unitsPerPack = product?.units_per_pack ?? 1;
  line.partLabel = product?.part_label ?? "";
  line.batch = null;
  line.batchOptions = [];
  if (!product || !form.branch) return;
  const rows = await stockApi.batches(company.currentId ?? 0, { product: product.id, branch: form.branch });
  line.batchOptions = rows.map((row) => ({
    value: row.batch_id,
    label: row.series,
    description: `${t("stock.batch.until", { day: fmt.day(row.expires_on) })}${row.status !== "sellable" ? ` · ${t(`stock.batchStatus.${row.status}`)}` : ""}`,
  }));
  if (line.batchOptions.length === 1) line.batch = line.batchOptions[0]!.value;
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.branch) errors.branch = t("stock.writeoff.errBranch");
  const rows = lines.value
    .filter((line) => line.product)
    .map((line) => ({ batch: line.batch, quantity: String(partsOf(line.packs, line.parts, line.unitsPerPack)) }));
  if (!rows.length || rows.some((row) => !row.batch || Number(row.quantity) <= 0)) errors.lines = t("stock.writeoff.errLines");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const detail = await stockApi.proposeWriteoff(company.currentId ?? 0, {
      branch: form.branch!,
      reason: form.reason,
      note: form.note.trim(),
      recall: props.recall,
      lines: rows.map((row) => ({ batch: row.batch!, quantity: row.quantity })),
    });
    toast.success(detail.writeoff.status === "approved" ? t("stock.writeoff.approvedToast", { number: detail.writeoff.number }) : t("stock.writeoff.proposedToast"));
    refresh();
    emit("saved", detail.writeoff.id);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["branch", "reason", "lines"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.writeoff.newTitle')" :description="t('stock.writeoff.newDescription')" size="lg">
    <div class="flex flex-col gap-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('stock.field.branch')" :error="errors.branch" required>
          <BranchPicker v-model="form.branch" :clearable="false" />
        </FormField>
        <FormField :label="t('stock.writeoff.reason')" required>
          <SelectBox v-model="form.reason" :options="reasonOptions" />
        </FormField>
      </div>
      <InlineAlert :tone="unfit ? 'warning' : 'neutral'" size="sm">{{ unfit ? t("stock.writeoff.unfitNote") : t("stock.writeoff.fitNote") }}</InlineAlert>
      <InlineAlert v-if="errors.lines" tone="danger" size="sm">{{ errors.lines }}</InlineAlert>
      <ul class="flex flex-col gap-3" data-testid="writeoff-lines">
        <li v-for="line in lines" :key="line.key" class="grid grid-cols-1 gap-2 rounded-[12px] border border-line p-3 sm:grid-cols-[1fr_160px_auto]">
          <ProductPicker v-model="line.product" :initial="line.initial" size="sm" @change="(row) => pickProduct(line, row)" />
          <SelectBox v-model="line.batch" :options="line.batchOptions" clearable size="sm" :placeholder="t('stock.writeoff.pickSeries')" />
          <div class="flex items-center gap-2">
            <NumberInput v-model="line.packs" :min="0" size="sm" class="w-24" :suffix="t('stock.field.packsShort')" />
            <NumberInput v-if="line.unitsPerPack > 1" v-model="line.parts" :min="0" :max="line.unitsPerPack - 1" size="sm" class="w-24" :suffix="line.partLabel || t('stock.field.partsShort')" />
            <IconButton :icon="Trash2" size="sm" :label="t('common.delete')" :disabled="lines.length === 1" @click="lines = lines.filter((row) => row.key !== line.key)" />
          </div>
        </li>
      </ul>
      <div><UiButton size="sm" variant="secondary" :icon="Plus" @click="lines.push(blankLine())">{{ t("stock.writeoff.addLine") }}</UiButton></div>
      <FormField :label="t('stock.field.note')" optional>
        <TextArea v-model="form.note" :rows="2" :maxlength="2000" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="writeoff-save" @click="save">{{ t("stock.writeoff.propose") }}</UiButton>
    </template>
  </UiDialog>
</template>
