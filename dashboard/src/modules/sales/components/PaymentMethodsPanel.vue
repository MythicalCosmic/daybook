<script setup lang="ts">
/**
 * Settings → Payment methods (the `payment-methods` panel): how customers pay, in the order the
 * cashier sees them in Kassa (move with the arrows), each with its kind, the account its money
 * lands on, the provider's fee (booked as a bank fee at close) and an on/off switch. The default
 * methods (Naqd, Uzcard, Humo, Click, Payme…) can be renamed; at least one cash method stays on.
 */
import { ArrowDown, ArrowUp, Pencil, Plus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import NumberInput from "@/components/NumberInput.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useMethods, useOptions, useSalesMutation } from "../api";
import { METHOD_ICONS } from "../format";
import type { MethodKind, PaymentMethod, PaymentMethodInput } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const query = useMethods();
const options = useOptions();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const canEdit = computed(() => company.can("sales.manage"));
const methods = computed(() => query.data.value ?? []);
const fmt = useFormat();
/** In Settings the page header already says the list is in the cashier's order. */
const route = useRoute();
const inSettings = computed(() => route.name === "settings.page");

/** The line under a method's name: its kind, where its money lands and its fee ("0,6%" in uz). */
function detail(method: PaymentMethod): string {
  const parts = [t(`sales.methods.kind.${method.kind}`)];
  if (method.kind !== "cash" && method.kind !== "credit") parts.push(method.account?.name ?? t("sales.methods.branchClearing"));
  if (Number(method.fee_percent)) parts.push(t("sales.methods.fee", { n: fmt.percent(Number(method.fee_percent), 2) }));
  return parts.join(" · ");
}

const KINDS: MethodKind[] = ["cash", "card", "qr", "transfer", "credit", "installment", "other"];
const kinds = computed(() => KINDS.map((value) => ({ value, label: t(`sales.methods.kind.${value}`), icon: METHOD_ICONS[value] })));
const accounts = computed(() => (options.data.value?.accounts ?? []).map((a) => ({ value: a.id, label: a.name })));

const save = useSalesMutation((cid, vars: { id: number | null; input: PaymentMethodInput }) =>
  vars.id ? salesApi.updateMethod(cid, vars.id, vars.input) : salesApi.createMethod(cid, vars.input),
);
const reorder = useSalesMutation((cid, ids: number[]) => salesApi.reorderMethods(cid, ids));

async function toggle(method: PaymentMethod, active: boolean): Promise<void> {
  await save.mutateAsync({ id: method.id, input: { is_active: active } });
}
async function move(index: number, step: number): Promise<void> {
  const ids = methods.value.map((m) => m.id);
  const target = index + step;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  await reorder.mutateAsync(ids);
}

const dialog = ref(false);
const editing = ref<PaymentMethod | null>(null);
const name = ref("");
const kind = ref<MethodKind | null>("card");
const account = ref<number | null>(null);
const fee = ref<number | null>(0);
const nameError = ref<string | null>(null);
function openDialog(method: PaymentMethod | null): void {
  editing.value = method;
  name.value = method?.name ?? "";
  kind.value = method?.kind ?? "card";
  account.value = method?.account?.id ?? null;
  fee.value = method ? Number(method.fee_percent) : 0;
  nameError.value = null;
  dialog.value = true;
}
async function submit(): Promise<void> {
  if (!name.value.trim()) {
    nameError.value = t("common.form.required");
    return;
  }
  const input: PaymentMethodInput = { name: name.value.trim(), kind: kind.value ?? "other", account_id: kind.value === "cash" ? null : account.value, fee_percent: String(fee.value ?? 0) };
  await save.mutateAsync({ id: editing.value?.id ?? null, input });
  toast.success(t("sales.methods.saved"));
  dialog.value = false;
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="skeleton" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 6" :key="n" height="52px" radius="10px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <section v-else class="ui-card">
      <header v-if="!inSettings || canEdit" class="flex items-center gap-2 px-4 pb-2 pt-4">
        <p v-if="!inSettings" class="flex-1 text-sm text-muted">{{ t("sales.methods.hint") }}</p>
        <UiButton v-if="canEdit" size="sm" variant="ghost" :icon="Plus" :class="inSettings && 'ml-auto'" @click="openDialog(null)">{{ t("sales.methods.add") }}</UiButton>
      </header>
      <ol :class="['divide-y divide-line', (!inSettings || canEdit) && 'border-t border-line']">
        <li v-for="(method, index) in methods" :key="method.id" :class="['flex items-center gap-3 px-4 py-2.5', !method.is_active && 'opacity-60']">
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted"><component :is="METHOD_ICONS[method.kind]" :size="16" /></span>
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-2 text-sm font-semibold text-fg">
              <span class="truncate">{{ method.name }}</span>
              <UiBadge v-if="method.kind === 'credit'" size="sm" tone="info">{{ t("sales.methods.creditBadge") }}</UiBadge>
            </p>
            <!-- Wraps on a phone rather than cutting the account and the fee off; in full on hover. -->
            <p class="text-xs text-muted sm:truncate" :title="detail(method)">{{ detail(method) }}</p>
          </div>
          <template v-if="canEdit">
            <div class="flex max-sm:hidden">
              <IconButton :icon="ArrowUp" :label="t('sales.methods.up')" size="sm" :disabled="index === 0" @click="move(index, -1)" />
              <IconButton :icon="ArrowDown" :label="t('sales.methods.down')" size="sm" :disabled="index === methods.length - 1" @click="move(index, 1)" />
            </div>
            <IconButton :icon="Pencil" :label="t('common.edit')" size="sm" @click="openDialog(method)" />
            <ToggleSwitch :model-value="method.is_active" size="sm" :aria-label="t('sales.methods.active')" @update:model-value="(value: boolean) => toggle(method, value)" />
          </template>
        </li>
      </ol>
    </section>

    <UiDialog v-model:open="dialog" :title="editing ? t('sales.methods.editTitle') : t('sales.methods.newTitle')" size="sm">
      <div class="flex flex-col gap-4">
        <FormField :label="t('sales.methods.name')" :error="nameError" required>
          <TextInput v-model="name" :maxlength="50" :placeholder="t('sales.methods.namePlaceholder')" @update:model-value="nameError = null" />
        </FormField>
        <FormField :label="t('sales.methods.kindLabel')">
          <SelectBox v-model="kind" :options="kinds" />
        </FormField>
        <FormField v-if="kind !== 'cash' && kind !== 'credit'" :label="t('sales.methods.account')" :hint="t('sales.methods.accountHint')" optional>
          <SelectBox v-model="account" :options="accounts" clearable :placeholder="t('sales.methods.branchClearing')" />
        </FormField>
        <FormField v-if="kind !== 'cash'" :label="t('sales.methods.feeLabel')" :hint="t('sales.methods.feeHint')">
          <NumberInput v-model="fee" :min="0" :max="100" :step="0.1" :decimals="2" suffix="%" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="dialog = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="save.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
