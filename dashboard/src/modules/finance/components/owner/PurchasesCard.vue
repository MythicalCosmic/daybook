<script setup lang="ts">
/**
 * Planned purchases: what the owner means to buy, kept back from the safe amount while it is due
 * within the horizon (or has no date); later ones are listed, not kept back yet. Add one, mark it
 * bought (or dropped), or remove it.
 */
import { Check, Plus, ShoppingCart, Trash2 } from "@lucide/vue";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { ownerMoneyApi, useOwnerMoneyWrite, type OwnerMoney, type PlannedPurchase } from "../../ownerMoney";

const props = defineProps<{ data: OwnerMoney; canWrite: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const adding = ref(false);
const form = reactive({ title: "", amount: null as string | null, due_on: null as string | null });
const errors = reactive<Record<string, string | undefined>>({});
const rows = computed(() => [...props.data.purchases.kept.map((row) => ({ ...row, kept: true })), ...props.data.purchases.later.map((row) => ({ ...row, kept: false }))]);

const add = useOwnerMoneyWrite((cid: number, input: { title: string; amount: string; due_on?: string | null }) => ownerMoneyApi.addPurchase(cid, input));
const update = useOwnerMoneyWrite((cid: number, input: { id: number; done: boolean }) => ownerMoneyApi.updatePurchase(cid, input.id, { done: input.done }));
const remove = useOwnerMoneyWrite((cid: number, id: number) => ownerMoneyApi.removePurchase(cid, id));

function openAdd(): void {
  Object.assign(form, { title: "", amount: null, due_on: null });
  for (const key of Object.keys(errors)) delete errors[key];
  adding.value = true;
}
async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.title.trim()) errors.title = t("finance.myMoney.purchaseTitleNeeded");
  if (!form.amount) errors.amount = t("finance.quick.errAmount");
  if (Object.keys(errors).length) return;
  await add.mutateAsync({ title: form.title.trim(), amount: form.amount!, due_on: form.due_on });
  toast.success(t("finance.myMoney.purchaseAdded"));
  adding.value = false;
}
async function bought(row: PlannedPurchase): Promise<void> {
  await update.mutateAsync({ id: row.id, done: true });
  toast.success(t("finance.myMoney.purchaseDone", { title: row.title }));
}
async function drop(row: PlannedPurchase): Promise<void> {
  const answer = await confirm({ title: t("finance.myMoney.purchaseRemoveTitle", { title: row.title }), message: t("finance.myMoney.purchaseRemoveBody"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  await remove.mutateAsync(row.id);
}
</script>

<template>
  <section class="ui-card flex flex-col p-4 sm:p-5" :aria-label="t('finance.myMoney.purchasesTitle')" data-purchases>
    <header class="mb-3 flex items-center gap-2">
      <ShoppingCart :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.myMoney.purchasesTitle") }}</h3>
      <UiButton v-if="canWrite" size="sm" variant="ghost" :icon="Plus" data-add-purchase @click="openAdd">{{ t("finance.myMoney.addPurchase") }}</UiButton>
    </header>
    <EmptyState v-if="!rows.length" size="sm" tone="neutral" :icon="ShoppingCart" :title="t('finance.myMoney.purchasesEmpty')" :description="t('finance.myMoney.purchasesEmptyBody')" />
    <ul v-else class="-mx-2 flex flex-col">
      <li v-for="row in rows" :key="row.id" class="group flex items-center gap-3 rounded-[10px] px-2 py-2 hover:bg-highlight" :data-purchase="row.id">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold" :class="row.kept ? 'text-fg' : 'text-muted'" :title="row.title">{{ row.title }}</p>
          <p class="truncate text-xs text-muted">
            {{ row.due_on ? fmt.day(row.due_on, "medium") : t("finance.myMoney.noDate") }} ·
            <span :class="row.kept ? 'text-info' : ''">{{ row.kept ? t("finance.myMoney.keptBack") : t("finance.myMoney.notYet") }}</span>
          </p>
        </div>
        <span class="shrink-0 text-sm font-semibold tabular-nums" :class="row.kept ? 'text-fg' : 'text-muted'"><MoneyText :value="row.amount" compact /></span>
        <div v-if="canWrite" class="flex shrink-0 items-center gap-0.5 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
          <IconButton :icon="Check" :label="t('finance.myMoney.markBought', { title: row.title })" size="sm" data-bought @click="bought(row)" />
          <IconButton :icon="Trash2" :label="t('finance.myMoney.removePurchase', { title: row.title })" size="sm" data-remove @click="drop(row)" />
        </div>
      </li>
    </ul>

    <UiDialog v-model:open="adding" :title="t('finance.myMoney.addPurchaseTitle')" :description="t('finance.myMoney.addPurchaseDescription')" size="sm">
      <div class="flex flex-col gap-4">
        <FormField :label="t('finance.myMoney.purchaseWhat')" :error="errors.title" required>
          <TextInput v-model="form.title" :maxlength="200" :placeholder="t('finance.myMoney.purchasePlaceholder')" :invalid="!!errors.title" autofocus />
        </FormField>
        <FormField :label="t('finance.field.amount')" :error="errors.amount" required>
          <MoneyInput v-model="form.amount" :currencies="[company.currency]" :invalid="!!errors.amount" />
        </FormField>
        <FormField :label="t('finance.myMoney.purchaseWhen')" optional :hint="t('finance.myMoney.purchaseWhenHint')">
          <DatePicker v-model="form.due_on" :min="data.today" clearable />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="adding = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="add.isPending.value" data-save-purchase @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </section>
</template>
