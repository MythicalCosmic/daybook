<script setup lang="ts">
/**
 * Price tags for the shelf as a PDF (Narx yorlig‘i): the items whose price changed in the last
 * days at one pharmacy, at the price it sells next, each with a signature line. Prescription
 * medicines aren't displayed to the public: they print on a counter list instead.
 */
import { Printer } from "@lucide/vue";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi } from "../api";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ products?: number[] }>(), { products: () => [] });

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();

const branch = ref<number | null>(null);
const days = ref<number | null>(7);
const busy = ref(false);
const problem = ref<string | null>(null);

watch(open, (value) => {
  if (!value) return;
  branch.value = company.branchFilter.length === 1 ? (company.branchFilter[0] ?? null) : (company.current?.branches?.[0]?.id ?? null);
  days.value = 7;
  problem.value = null;
});

function since(): string {
  const day = new Date(`${today.value}T00:00:00`);
  day.setDate(day.getDate() - Math.max(0, days.value ?? 7));
  const month = String(day.getMonth() + 1).padStart(2, "0");
  const date = String(day.getDate()).padStart(2, "0");
  return `${day.getFullYear()}-${month}-${date}`;
}

async function print(): Promise<void> {
  if (!branch.value) return;
  busy.value = true;
  problem.value = null;
  try {
    const input = props.products.length ? { branch: branch.value, products: props.products } : { branch: branch.value, changed_since: since() };
    const link = await stockApi.priceTags(company.currentId ?? 0, input);
    window.open(link.url, "_blank", "noopener");
    open.value = false;
  } catch (error) {
    problem.value = isApiError(error) ? error.message : t("stock.priceTags.failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="t('stock.priceTags.title')" :description="t('stock.priceTags.description')">
    <div class="flex flex-col gap-4">
      <InlineAlert v-if="problem" tone="danger" size="sm">{{ problem }}</InlineAlert>
      <FormField :label="t('stock.field.branch')" required>
        <BranchPicker v-model="branch" :clearable="false" />
      </FormField>
      <FormField v-if="!products.length" :label="t('stock.priceTags.days')">
        <NumberInput v-model="days" :min="0" :max="365" data-testid="price-tags-days" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Printer" :loading="busy" :disabled="!branch" data-testid="price-tags-print" @click="print">{{ t("stock.priceTags.print") }}</UiButton>
    </template>
  </UiDialog>
</template>
