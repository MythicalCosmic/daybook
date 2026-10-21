<script setup lang="ts">
/**
 * Settings → Tills (the `registers` panel): every till by branch with its fiscal serial, the cash
 * it holds now and its open shift. Managers add tills (each gets its own cash account), rename them
 * and archive them (never while a shift is open). Archived tills stay listed, dimmed.
 */
import { Archive, ArchiveRestore, Pencil, Plus, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { salesApi, useOptions, useRegisters, useSalesMutation } from "../api";
import type { Register, RegisterInput } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const options = useOptions();
const query = useRegisters();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const canEdit = computed(() => company.can("sales.manage"));

const groups = computed(() => {
  const byBranch = new Map<number, { id: number; name: string; code: string; registers: Register[] }>();
  for (const register of query.data.value ?? []) {
    const group = byBranch.get(register.branch.id) ?? { ...register.branch, registers: [] };
    group.registers.push(register);
    byBranch.set(register.branch.id, group);
  }
  return [...byBranch.values()];
});

const dialog = ref(false);
const editing = ref<Register | null>(null);
const name = ref("");
const serial = ref("");
const branch = ref<number | null>(null);
const nameError = ref<string | null>(null);
const branches = computed(() => (options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name })));

function openDialog(register: Register | null, branchId: number | null = null): void {
  editing.value = register;
  name.value = register?.name ?? "";
  serial.value = register?.fiscal_serial ?? "";
  branch.value = register?.branch.id ?? branchId ?? options.data.value?.branches[0]?.id ?? null;
  nameError.value = null;
  dialog.value = true;
}

const save = useSalesMutation((cid, vars: { id: number | null; input: RegisterInput }) =>
  vars.id ? salesApi.updateRegister(cid, vars.id, vars.input) : salesApi.createRegister(cid, vars.input),
);
async function submit(): Promise<void> {
  if (!name.value.trim()) {
    nameError.value = t("common.form.required");
    return;
  }
  const input: RegisterInput = { name: name.value.trim(), fiscal_serial: serial.value.trim() };
  if (!editing.value) input.branch_id = branch.value ?? undefined;
  await save.mutateAsync({ id: editing.value?.id ?? null, input });
  toast.success(editing.value ? t("sales.registers.saved") : t("sales.registers.created", { name: input.name }));
  dialog.value = false;
}

const toggle = useSalesMutation((cid, vars: { id: number; active: boolean }) => salesApi.updateRegister(cid, vars.id, { is_active: vars.active }));
async function archive(register: Register): Promise<void> {
  if (register.is_active) {
    const answer = await confirm({ title: t("sales.registers.archiveTitle", { name: register.name }), message: t("sales.registers.archiveBody"), confirmLabel: t("sales.registers.archive") });
    if (!answer) return;
  }
  await toggle.mutateAsync({ id: register.id, active: !register.is_active });
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div v-if="skeleton" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 2" :key="n" height="120px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !groups.length" class="ui-card">
      <EmptyState :icon="Wallet" :title="t('sales.registers.emptyTitle')" :description="t('sales.registers.emptyBody')">
        <UiButton v-if="canEdit" variant="primary" :icon="Plus" @click="openDialog(null)">{{ t("sales.registers.add") }}</UiButton>
      </EmptyState>
    </div>
    <section v-for="group in groups" v-else :key="group.id" class="ui-card">
      <header class="flex items-center gap-2 px-4 pb-2 pt-4">
        <h3 class="flex-1 text-sm font-semibold text-fg">{{ group.name }}<span v-if="group.code" class="ml-2 rounded-[5px] bg-surface-2 px-1.5 py-px text-[11px] font-semibold tracking-wide text-muted">{{ group.code }}</span></h3>
        <UiButton v-if="canEdit" size="sm" variant="ghost" :icon="Plus" @click="openDialog(null, group.id)">{{ t("sales.registers.add") }}</UiButton>
      </header>
      <ul class="divide-y divide-line border-t border-line">
        <li v-for="register in group.registers" :key="register.id" :class="['flex items-center gap-3 px-4 py-3', !register.is_active && 'opacity-55']">
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><Wallet :size="16" /></span>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-fg">{{ register.name }}</p>
            <p class="truncate text-xs text-muted">
              {{ register.fiscal_serial || t("sales.registers.noSerial") }} · {{ register.cash_account.name }}
            </p>
          </div>
          <StatusPill v-if="register.open_shift" size="sm" tone="info" live :label="t('sales.registers.openBy', { name: register.open_shift.cashier.name.split(' ')[0] })" />
          <StatusPill v-else-if="!register.is_active" size="sm" tone="neutral" :label="t('sales.registers.archived')" />
          <div class="w-[120px] text-right max-sm:hidden">
            <p class="text-[11px] text-muted">{{ t("sales.registers.holds") }}</p>
            <MoneyText :value="register.cash_now" class="text-sm font-semibold text-fg" />
          </div>
          <template v-if="canEdit">
            <IconButton :icon="Pencil" :label="t('common.edit')" size="sm" @click="openDialog(register)" />
            <IconButton :icon="register.is_active ? Archive : ArchiveRestore" :label="register.is_active ? t('sales.registers.archive') : t('sales.registers.restore')" size="sm" @click="archive(register)" />
          </template>
        </li>
      </ul>
    </section>

    <UiDialog v-model:open="dialog" :title="editing ? t('sales.registers.editTitle') : t('sales.registers.newTitle')" :description="editing ? undefined : t('sales.registers.newBody')" size="sm">
      <div class="flex flex-col gap-4">
        <FormField v-if="!editing" :label="t('sales.filter.branch')" required>
          <SelectBox v-model="branch" :options="branches" />
        </FormField>
        <FormField :label="t('sales.registers.name')" :error="nameError" required>
          <TextInput v-model="name" :maxlength="50" :placeholder="t('sales.registers.namePlaceholder')" @update:model-value="nameError = null" />
        </FormField>
        <FormField :label="t('sales.registers.serial')" :hint="t('sales.registers.serialHint')" optional>
          <TextInput v-model="serial" :maxlength="32" mono placeholder="UZ-FM 210045" />
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="dialog = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="save.isPending.value" @click="submit">{{ editing ? t("common.save") : t("sales.registers.create") }}</UiButton>
      </template>
    </UiDialog>
    <p class="text-xs text-subtle">{{ t("sales.registers.footnote", { tolerance: fmt.money(options.data.value?.settings.cash_tolerance ?? "0") }) }}</p>
  </div>
</template>
