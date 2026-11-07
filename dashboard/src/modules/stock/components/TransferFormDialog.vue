<script setup lang="ts">
/**
 * A transfer between pharmacies (Filiallararo ko‘chirish): from, to, and what goes, each line a
 * product with its series (or the earliest-expiring ones, FEFO, when no series is picked) and a
 * quantity in packs and parts. The expiry board hands its selected batches over in `prefill`.
 * "Send now" sends it at once; otherwise it stays a draft.
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
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { stockApi, useRefresh } from "../api";
import { partsOf } from "../lib";
import type { BatchPrefill, Product } from "../types";
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
const props = withDefaults(defineProps<{ from?: number | null; prefill?: BatchPrefill[] }>(), { from: null, prefill: () => [] });
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();

const form = reactive({ from: null as number | null, to: null as number | null, note: "", send: true });
const lines = ref<Line[]>([]);
const errors = reactive<Record<string, string | undefined>>({});
const saving = ref(false);
let keys = 0;

const toOptions = computed(() => (company.current?.branches ?? []).filter((b) => b.id !== form.from).map((b) => ({ value: b.id, label: b.name })));

function blankLine(): Line {
  return { key: ++keys, product: null, initial: null, unitsPerPack: 1, partLabel: "", batch: null, batchOptions: [], packs: null, parts: null };
}

watch(open, (value) => {
  if (!value) return;
  for (const key of Object.keys(errors)) delete errors[key];
  form.from = props.from ?? (company.branchFilter.length === 1 ? (company.branchFilter[0] ?? null) : null);
  form.to = null;
  form.note = "";
  form.send = true;
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
  if (!product || !form.from) return;
  const rows = await stockApi.batches(company.currentId ?? 0, { product: product.id, branch: form.from, status: "sellable" });
  line.batchOptions = rows.map((row) => ({ value: row.batch_id, label: row.series, description: t("stock.batch.until", { day: fmt.day(row.expires_on) }) }));
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.from) errors.from = t("stock.transfer.errFrom");
  if (!form.to) errors.to = t("stock.transfer.errTo");
  const rows = lines.value
    .filter((line) => line.product)
    .map((line) => ({ product: line.product!, batch: line.batch, quantity: String(partsOf(line.packs, line.parts, line.unitsPerPack)) }));
  if (!rows.length || rows.some((row) => Number(row.quantity) <= 0)) errors.lines = t("stock.transfer.errLines");
  if (Object.keys(errors).length) return;
  saving.value = true;
  try {
    const detail = await stockApi.createTransfer(company.currentId ?? 0, { from_branch: form.from!, to_branch: form.to!, note: form.note.trim(), send: form.send, lines: rows });
    toast.success(form.send ? t("stock.transfer.sentToast", { number: detail.transfer.number }) : t("stock.transfer.draftToast"));
    refresh();
    emit("saved", detail.transfer.id);
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
    const unshown = unshownFieldError(error, ["from_branch", "to_branch", "lines"]);
    if (unshown) toast.error(unshown);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.transfer.newTitle')" :description="t('stock.transfer.newDescription')" size="lg">
    <div class="flex flex-col gap-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField :label="t('stock.transfer.from')" :error="errors.from ?? errors.from_branch" required>
          <BranchPicker v-model="form.from" :clearable="false" />
        </FormField>
        <FormField :label="t('stock.transfer.to')" :error="errors.to ?? errors.to_branch" required>
          <SelectBox v-model="form.to" :options="toOptions" clearable :placeholder="t('stock.transfer.pickTo')" />
        </FormField>
      </div>
      <InlineAlert v-if="errors.lines" tone="danger" size="sm">{{ errors.lines }}</InlineAlert>
      <ul class="flex flex-col gap-3" data-testid="transfer-lines">
        <li v-for="line in lines" :key="line.key" class="grid grid-cols-1 gap-2 rounded-[12px] border border-line p-3 sm:grid-cols-[1fr_160px_auto]">
          <ProductPicker v-model="line.product" :initial="line.initial" size="sm" @change="(row) => pickProduct(line, row)" />
          <SelectBox v-model="line.batch" :options="line.batchOptions" clearable size="sm" :placeholder="t('stock.transfer.fefo')" />
          <div class="flex items-center gap-2">
            <NumberInput v-model="line.packs" :min="0" size="sm" class="w-24" :suffix="t('stock.field.packsShort')" />
            <NumberInput v-if="line.unitsPerPack > 1" v-model="line.parts" :min="0" :max="line.unitsPerPack - 1" size="sm" class="w-24" :suffix="line.partLabel || t('stock.field.partsShort')" />
            <IconButton :icon="Trash2" size="sm" :label="t('common.delete')" :disabled="lines.length === 1" @click="lines = lines.filter((row) => row.key !== line.key)" />
          </div>
        </li>
      </ul>
      <div><UiButton size="sm" variant="secondary" :icon="Plus" @click="lines.push(blankLine())">{{ t("stock.transfer.addLine") }}</UiButton></div>
      <FormField :label="t('stock.field.note')" optional>
        <TextArea v-model="form.note" :rows="2" :maxlength="2000" />
      </FormField>
      <ToggleSwitch v-model="form.send" :label="t('stock.transfer.sendNow')" :description="t('stock.transfer.sendNowHint')" />
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-testid="transfer-save" @click="save">{{ form.send ? t("stock.transfer.send") : t("stock.transfer.saveDraft") }}</UiButton>
    </template>
  </UiDialog>
</template>
