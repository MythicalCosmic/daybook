<script setup lang="ts">
/**
 * Add things to give out. Uniforms, badges and keys are cheap and many: "10 lab coats" makes ten
 * numbered items (each with its own inventory number, nothing to type), a size as their note. A
 * device (a phone, a scanner) is one at a time with its cost, serial and model, and only for
 * someone who manages assets (it depreciates in Finance). A category can be made on the spot, from
 * the pharmacy's suggestions or by name.
 */
import { PackagePlus, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { equipmentApi, useCategories, useEquipmentMutation, useStock } from "./api";
import { addErrors, addPayload, categoryIcon, itemIndex, previewNames, type AddErrors, type AddForm } from "./lib";
import type { AddItemsInput, CategoryInput, EquipmentCategories, StockItem } from "./types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ category?: number | null }>(), { category: null });
const emit = defineEmits<{ saved: [items: StockItem[]] }>();

const { t } = useI18n();
const company = useCompanyStore();
const categories = useCategories(open);
const list = computed(() => categories.data.value?.categories ?? []);
const suggestions = computed(() => categories.data.value?.suggestions ?? []);
/** A scoped viewer adds things to one of their branches; owners may leave it company-wide. */
const needsBranch = computed(() => company.current?.branch_scope !== null && company.current?.branch_scope !== undefined && !company.current?.is_owner);

const blank = (): AddForm => ({ category: props.category, name: "", quantity: 1, branch: null, note: "", cost: null, serial: "", model: "" });
const form = ref<AddForm>(blank());
const errors = ref<AddErrors>({});
const newName = ref("");
watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    form.value = blank();
    errors.value = {};
    newName.value = "";
  },
  { immediate: true },
);

const category = computed(() => list.value.find((row) => row.id === form.value.category) ?? null);
const device = computed(() => !!category.value && category.value.kind !== "low_value");
// A new item takes the category's name in the singular feel of the stock ("Xalat"); an empty name follows the category.
watch(category, (row, before) => {
  if (!row) return;
  if (!form.value.name.trim() || form.value.name === before?.name) form.value.name = row.name;
  if (row.kind !== "low_value") form.value.quantity = 1;
});

// Numbering goes on from the company's last "<name> №N" (given out or not), as the server does.
const everything = useStock("all", open);
const baseName = (name: string) => name.replace(/\s*№\s*\d+\s*$/, "").trim().toLocaleLowerCase();
const startAt = computed(() => {
  const base = form.value.name.trim().toLocaleLowerCase();
  const taken = (everything.data.value ?? []).filter((item) => baseName(item.name) === base).map((item) => itemIndex(item.name));
  return Math.max(0, ...taken) + 1;
});
const preview = computed(() => previewNames(form.value.name, device.value ? 1 : form.value.quantity, startAt.value));
const makeCategory = useEquipmentMutation((cid, input: CategoryInput) => equipmentApi.addCategory(cid, input));
async function addCategory(input: CategoryInput): Promise<void> {
  try {
    const before = new Set(list.value.map((row) => row.id));
    const result: EquipmentCategories = await makeCategory.mutateAsync(input);
    const made = result.categories.find((row) => !before.has(row.id)) ?? result.categories.find((row) => row.name.toLocaleLowerCase() === (input.name ?? "").toLocaleLowerCase());
    if (made) form.value.category = made.id;
    newName.value = "";
  } catch {
    // The HTTP layer showed why.
  }
}

const message = (key: string | undefined) => (key ? t(`lifecycle.equipment.error.${key}`) : null);
const save = useEquipmentMutation((cid, input: AddItemsInput) => equipmentApi.addItems(cid, input));
async function submit(): Promise<void> {
  errors.value = addErrors(form.value, device.value, needsBranch.value);
  if (Object.keys(errors.value).length) return;
  try {
    const result = await save.mutateAsync(addPayload(form.value, device.value));
    toast.success(t("lifecycle.equipment.add.done", { n: result.items.length }, result.items.length));
    emit("saved", result.items);
    open.value = false;
  } catch {
    // The HTTP layer showed why.
  }
}
</script>

<template>
  <UiDialog v-model:open="open" size="md" :title="t('lifecycle.equipment.add.title')" :description="t('lifecycle.equipment.add.description')">
    <div class="flex flex-col gap-4">
      <FormField :label="t('lifecycle.equipment.field.category')" :error="message(errors.category)" required>
        <div class="flex flex-col gap-2.5">
          <div v-if="list.length" class="flex flex-wrap gap-1.5" role="radiogroup" :aria-label="t('lifecycle.equipment.field.category')" data-add-categories>
            <button
              v-for="row in list"
              :key="row.id"
              type="button"
              role="radio"
              :aria-checked="form.category === row.id"
              :disabled="!row.may_add"
              :class="[
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-45',
                form.category === row.id ? 'border-[var(--c-primary)] bg-accent-soft font-semibold text-accent-fg' : 'border-line text-fg hover:border-line-strong',
              ]"
              :data-category="row.id"
              @click="form.category = row.id"
            >
              <component :is="categoryIcon(row.icon)" :size="14" aria-hidden="true" />{{ row.name }}
            </button>
          </div>
          <div v-if="suggestions.length" class="flex flex-col gap-1.5 rounded-[12px] bg-surface-2/60 p-2.5 dark:bg-surface-3/40" data-suggestions>
            <p class="text-xs font-medium text-muted">{{ t("lifecycle.equipment.add.suggested") }}</p>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="suggestion in suggestions"
                :key="suggestion.key"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-full border border-dashed border-line-strong bg-surface px-3 py-1 text-sm text-fg hover:border-[var(--c-primary)] hover:text-accent-fg"
                :data-suggestion="suggestion.key"
                @click="addCategory({ suggestion: suggestion.key })"
              >
                <Plus :size="13" aria-hidden="true" /><component :is="categoryIcon(suggestion.icon)" :size="14" aria-hidden="true" />{{ suggestion.name }}
              </button>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <TextInput v-model="newName" size="sm" class="min-w-0 flex-1" :maxlength="100" :placeholder="t('lifecycle.equipment.add.newCategory')" @keydown.enter.prevent="newName.trim() && addCategory({ name: newName.trim(), kind: 'low_value' })" />
            <UiButton size="sm" variant="secondary" :icon="Plus" :disabled="!newName.trim()" :loading="makeCategory.isPending.value" @click="addCategory({ name: newName.trim(), kind: 'low_value' })">{{ t("lifecycle.equipment.add.makeCategory") }}</UiButton>
          </div>
        </div>
      </FormField>

      <template v-if="category">
        <div class="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <FormField :label="t('lifecycle.equipment.field.name')" :error="message(errors.name)" required>
            <TextInput v-model="form.name" :maxlength="110" :invalid="!!errors.name" :placeholder="t('lifecycle.equipment.add.namePlaceholder')" data-add-name />
          </FormField>
          <FormField v-if="!device" :label="t('lifecycle.equipment.field.quantity')" :error="message(errors.quantity)" required>
            <NumberInput v-model="form.quantity" :min="1" :max="100" steppers :invalid="!!errors.quantity" data-add-quantity />
          </FormField>
        </div>
        <p v-if="preview.length > 1" class="-mt-2 text-xs text-muted" data-add-preview>
          {{ t("lifecycle.equipment.add.preview", { first: preview[0], last: preview[preview.length - 1], n: preview.length }) }}
        </p>
        <template v-if="device">
          <div class="grid gap-4 sm:grid-cols-2">
            <FormField :label="t('lifecycle.equipment.field.model')" optional>
              <TextInput v-model="form.model" :maxlength="80" :placeholder="t('lifecycle.equipment.add.modelPlaceholder')" />
            </FormField>
            <FormField :label="t('lifecycle.equipment.field.serial')" optional>
              <TextInput v-model="form.serial" :maxlength="64" />
            </FormField>
          </div>
          <FormField :label="t('lifecycle.equipment.field.cost')" :error="message(errors.cost)" :hint="t('lifecycle.equipment.add.costHint')" required>
            <MoneyInput v-model="form.cost" :currencies="[company.currency]" :invalid="!!errors.cost" />
          </FormField>
          <InlineAlert tone="info" size="sm" :description="t('lifecycle.equipment.add.deviceNote')" />
        </template>
        <template v-else>
          <FormField :label="t('lifecycle.equipment.field.size')" :hint="t('lifecycle.equipment.add.sizeHint')" optional>
            <TextInput v-model="form.note" :maxlength="120" :placeholder="t('lifecycle.equipment.add.sizePlaceholder')" />
          </FormField>
          <FormField :label="t('lifecycle.equipment.field.unitCost')" :hint="t('lifecycle.equipment.add.unitCostHint')" optional>
            <MoneyInput v-model="form.cost" :currencies="[company.currency]" />
          </FormField>
        </template>
        <FormField :label="t('lifecycle.equipment.field.branch')" :error="message(errors.branch)" :required="needsBranch" :optional="!needsBranch" :hint="needsBranch ? undefined : t('lifecycle.equipment.add.branchHint')">
          <BranchPicker v-model="form.branch" :clearable="!needsBranch" :invalid="!!errors.branch" />
        </FormField>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="PackagePlus" :disabled="!category" :loading="save.isPending.value" data-add-submit @click="submit">
        {{ t("lifecycle.equipment.add.submit", { n: preview.length || 1 }, preview.length || 1) }}
      </UiButton>
    </template>
  </UiDialog>
</template>
