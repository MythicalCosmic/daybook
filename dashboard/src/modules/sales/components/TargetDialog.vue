<script setup lang="ts">
/**
 * Set a monthly sales target for the company, a branch or one cashier. Setting one that exists for
 * the same month and scope changes its amount.
 */
import { Target } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { formatDay } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";

import { salesApi, useOptions, useSalesMutation } from "../api";
import type { Target as SalesTarget } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ month: string; target?: SalesTarget | null }>(), { target: null });

const { t } = useI18n();
const fmt = useFormat();
const options = useOptions();
type Scope = "company" | "branch" | "person";
const scope = ref<Scope>("company");
const branch = ref<number | null>(null);
const member = ref<number | null>(null);
const amount = ref<string | null>(null);
const error = ref<string | null>(null);

watch(open, (value) => {
  if (!value) return;
  scope.value = props.target?.scope ?? "company";
  branch.value = props.target?.branch?.id ?? null;
  member.value = props.target?.member?.id ?? null;
  amount.value = props.target?.amount ?? null;
  error.value = null;
});

const scopes = computed(() => (["company", "branch", "person"] as const).map((value) => ({ value, label: t(`sales.targets.scope.${value}`) })));
const branchOptions = computed(() => (options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name })));
const people = computed(() => (options.data.value?.cashiers ?? []).map((p) => ({ value: p.id, label: p.name, avatar: { name: p.name } })));
const monthLabel = computed(() => formatDay(props.month, fmt.lang.value, "monthYear"));

const save = useSalesMutation((cid, input: { month: string; amount: string; branch_id: number | null; member_id: number | null }) =>
  props.target ? salesApi.updateTarget(cid, props.target.id, input.amount) : salesApi.setTarget(cid, input),
);

async function submit(): Promise<void> {
  if (!amount.value) return void (error.value = t("common.form.required"));
  if (scope.value === "branch" && !branch.value) return void (error.value = t("sales.targets.pickBranch"));
  if (scope.value === "person" && !member.value) return void (error.value = t("sales.targets.pickPerson"));
  await save.mutateAsync({
    month: props.month,
    amount: amount.value,
    branch_id: scope.value === "branch" ? branch.value : null,
    member_id: scope.value === "person" ? member.value : null,
  });
  toast.success(t("sales.targets.saved"));
  open.value = false;
}
</script>

<template>
  <UiDialog v-model:open="open" :title="target ? t('sales.targets.editTitle') : t('sales.targets.newTitle')" :description="monthLabel" size="sm">
    <div class="flex flex-col gap-4">
      <SegmentedControl v-if="!target" v-model="scope" :options="scopes" block :aria-label="t('sales.targets.scopeLabel')" />
      <FormField v-if="scope === 'branch'" :label="t('sales.filter.branch')" required>
        <SelectBox v-model="branch" :options="branchOptions" :disabled="!!target" />
      </FormField>
      <FormField v-if="scope === 'person'" :label="t('sales.col.cashier')" required>
        <SelectBox v-model="member" :options="people" :disabled="!!target" />
      </FormField>
      <FormField :label="t('sales.targets.amount')" :error="error" required>
        <MoneyInput v-model="amount" @update:model-value="error = null" />
      </FormField>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Target" :loading="save.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
    </template>
  </UiDialog>
</template>
