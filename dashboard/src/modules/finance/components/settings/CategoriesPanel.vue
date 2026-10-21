<script setup lang="ts">
/**
 * The category tree (plan §6.2 "category tree (drag, merge)"): income and expense side by side,
 * two levels, drag a category under another or to the top (Alt+arrows too), rename, recolour,
 * add a subcategory, merge one into another, archive or delete. System categories carry a badge:
 * they can be renamed, never deleted.
 */
import { Archive, ArchiveRestore, Ellipsis, GitMerge, Lock, Pencil, Plus, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ComboBox from "@/components/ComboBox.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import TreeList from "@/components/TreeList.vue";
import { moveNode, type TreeMove, type TreeNode } from "@/components/tree";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useCategories, useMoveCategory, useRefresh } from "../../api";
import { ACCOUNT_SWATCHES, categoryOptions, colorFor, findCategory } from "../../lib";
import type { CategoryKind, CategoryNode } from "../../types";

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const categories = useCategories();
const move = useMoveCategory();
const showArchived = ref(false);
const expanded = ref<Array<string | number>>([]);
const canSensitive = computed(() => company.can("payroll.view"));

function toTree(kind: CategoryKind): TreeNode[] {
  return (categories.data.value ?? [])
    .filter((node) => node.kind === kind && (showArchived.value || node.is_active))
    .map((node) => ({
      id: node.id,
      label: node.name,
      badge: node.entries || undefined,
      locked: false,
      children: node.children.filter((c) => showArchived.value || c.is_active).map((child) => ({ id: child.id, label: child.name, badge: child.entries || undefined })),
    }));
}

const sides = computed(() => (["income", "expense"] as const).map((kind) => ({ kind, nodes: toTree(kind) })));

function onMove(kind: CategoryKind, change: TreeMove): void {
  const tree = categories.data.value ?? [];
  const nodes = toTree(kind);
  const next = moveNode(nodes, change);
  // Rebuild the API tree in the new order for the optimistic update.
  const byId = new Map<number, CategoryNode>();
  for (const node of tree) {
    byId.set(node.id, node);
    for (const child of node.children) byId.set(child.id, child);
  }
  const rebuilt = next.map((top) => ({ ...byId.get(Number(top.id))!, parent_id: null, children: (top.children ?? []).map((c) => ({ ...byId.get(Number(c.id))!, parent_id: Number(top.id), children: [] })) }));
  const others = tree.filter((node) => node.kind !== kind);
  move.mutate({ id: Number(change.id), parent: change.parentId === null ? null : Number(change.parentId), index: change.index, next: kind === "income" ? [...rebuilt, ...others] : [...others, ...rebuilt] });
}

// Create and edit ------------------------------------------------------------------------------

const dialog = ref({ open: false, mode: "create" as "create" | "edit", kind: "expense" as CategoryKind, id: null as number | null });
const form = ref({ name: "", parent: null as number | null, color: "", is_capex: false, is_sensitive: false });
const saving = ref(false);

function create(kind: CategoryKind, parent: number | null = null): void {
  form.value = { name: "", parent, color: "", is_capex: false, is_sensitive: false };
  dialog.value = { open: true, mode: "create", kind, id: null };
}

function edit(id: number): void {
  const node = findCategory(categories.data.value, id);
  if (!node) return;
  form.value = { name: node.name, parent: node.parent_id, color: node.color, is_capex: node.is_capex, is_sensitive: node.is_sensitive };
  dialog.value = { open: true, mode: "edit", kind: node.kind, id };
}

const parentChoices = computed(() =>
  (categories.data.value ?? []).filter((node) => node.kind === dialog.value.kind && node.id !== dialog.value.id && node.is_active).map((node) => ({ value: node.id, label: node.name, color: colorFor(node.id, node.color) })),
);

async function save(): Promise<void> {
  if (!form.value.name.trim()) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  try {
    if (dialog.value.mode === "create") {
      await financeApi.createCategory(cid, {
        name: form.value.name.trim(),
        kind: dialog.value.kind,
        parent: form.value.parent,
        color: form.value.color,
        is_capex: form.value.is_capex,
        ...(canSensitive.value ? { is_sensitive: form.value.is_sensitive } : {}),
      });
    } else {
      await financeApi.updateCategory(cid, dialog.value.id!, {
        name: form.value.name.trim(),
        color: form.value.color,
        is_capex: form.value.is_capex,
        ...(canSensitive.value ? { is_sensitive: form.value.is_sensitive } : {}),
      });
    }
    toast.success(t("finance.categories.saved"));
    dialog.value.open = false;
    refresh();
  } finally {
    saving.value = false;
  }
}

// Merge, archive, delete -----------------------------------------------------------------------

const mergeState = ref({ open: false, id: null as number | null, into: null as number | null });
const mergeChoices = computed(() => {
  const node = findCategory(categories.data.value, mergeState.value.id);
  if (!node) return [];
  return categoryOptions(categories.data.value, node.kind, { activeOnly: true }).filter((option) => option.value !== node.id && !(node.children.length && option.description));
});

async function merge(): Promise<void> {
  if (!mergeState.value.id || !mergeState.value.into) return;
  await financeApi.mergeCategory(company.currentId ?? 0, mergeState.value.id, mergeState.value.into);
  toast.success(t("finance.categories.merged"));
  mergeState.value.open = false;
  refresh();
}

async function setActive(id: number, active: boolean): Promise<void> {
  await financeApi.updateCategory(company.currentId ?? 0, id, { is_active: active });
  toast.success(active ? t("finance.categories.restored") : t("finance.categories.archived"));
  refresh();
}

async function remove(id: number): Promise<void> {
  const node = findCategory(categories.data.value, id);
  const answer = await confirm({ title: t("finance.categories.deleteTitle", { name: node?.name ?? "" }), tone: "danger", confirmLabel: t("common.delete"), onConfirm: () => financeApi.deleteCategory(company.currentId ?? 0, id) });
  if (answer) {
    toast.success(t("finance.categories.deleted"));
    refresh();
  }
}

function menu(id: number): MenuEntry[] {
  const node = findCategory(categories.data.value, id);
  if (!node) return [];
  const entries: MenuEntry[] = [{ label: t("finance.categories.edit"), icon: Pencil, onSelect: () => edit(id) }];
  if (node.parent_id === null) entries.push({ label: t("finance.categories.addChild"), icon: Plus, onSelect: () => create(node.kind, id) });
  if (!node.is_system) {
    entries.push({ label: t("finance.categories.merge"), icon: GitMerge, onSelect: () => (mergeState.value = { open: true, id, into: null }) });
    entries.push({ type: "separator" });
    if (node.is_active) entries.push({ label: t("finance.categories.archive"), icon: Archive, onSelect: () => void setActive(id, false) });
    else entries.push({ label: t("finance.categories.restore"), icon: ArchiveRestore, onSelect: () => void setActive(id, true) });
    if (!node.entries && !node.children.length) entries.push({ label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void remove(id) });
  }
  return entries;
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-3">
      <p class="min-w-0 flex-1 text-sm text-muted">{{ t("finance.categories.help") }}</p>
      <ToggleSwitch v-model="showArchived" size="sm" :label="t('finance.categories.showArchived')" />
    </div>
    <ErrorState v-if="categories.isError.value" :error="categories.error.value" :retry="() => categories.refetch()" />
    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section v-for="side in sides" :key="side.kind" class="ui-card flex min-w-0 flex-col">
        <header class="flex items-center gap-2 border-b border-line px-4 py-3">
          <span :class="['size-2.5 rounded-full', side.kind === 'income' ? 'bg-success' : 'bg-chart-1']" aria-hidden="true" />
          <h3 class="flex-1 text-sm font-semibold text-fg">{{ t(`finance.categories.${side.kind}`) }}</h3>
          <UiButton size="sm" variant="ghost" :icon="Plus" @click="create(side.kind)">{{ t("finance.categories.new") }}</UiButton>
        </header>
        <div class="p-2">
          <div v-if="categories.isPending.value" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 8" :key="n" height="28px" /></div>
          <TreeList v-else v-model:expanded="expanded" :nodes="side.nodes" draggable :max-depth="1" :label="t(`finance.categories.${side.kind}`)" @move="(change) => onMove(side.kind, change)">
            <template #node="{ node }">
              <span class="flex min-w-0 items-center gap-2">
                <span class="size-2.5 shrink-0 rounded-full" :style="{ background: colorFor(Number(node.id), findCategory(categories.data.value, Number(node.id))?.color) }" aria-hidden="true" />
                <span :class="['truncate', findCategory(categories.data.value, Number(node.id))?.is_active === false && 'text-subtle line-through']">{{ node.label }}</span>
                <UiTooltip v-if="findCategory(categories.data.value, Number(node.id))?.is_system" :content="t('finance.categories.systemHint')">
                  <Lock :size="12" class="shrink-0 text-subtle" />
                </UiTooltip>
                <span v-if="findCategory(categories.data.value, Number(node.id))?.is_capex" class="rounded-full bg-info-soft px-1.5 text-[10px] font-semibold text-info">{{ t("finance.categories.capex") }}</span>
                <span v-if="findCategory(categories.data.value, Number(node.id))?.is_sensitive" class="rounded-full bg-warning-soft px-1.5 text-[10px] font-semibold text-warning">{{ t("finance.categories.sensitive") }}</span>
              </span>
            </template>
            <template #actions="{ node }">
              <UiBadge v-if="node.badge" :count="Number(node.badge)" :max="999" />
              <DropdownMenu :items="menu(Number(node.id))" width="220px">
                <template #trigger>
                  <IconButton :icon="Ellipsis" size="sm" :label="t('finance.categories.actions', { name: node.label })" />
                </template>
              </DropdownMenu>
            </template>
          </TreeList>
        </div>
      </section>
    </div>

    <UiDialog v-model:open="dialog.open" :title="dialog.mode === 'create' ? t('finance.categories.newTitle') : t('finance.categories.editTitle')" size="sm">
      <div class="flex flex-col gap-3">
        <FormField :label="t('finance.categories.name')" required>
          <TextInput v-model="form.name" :maxlength="100" autofocus />
        </FormField>
        <FormField v-if="dialog.mode === 'create'" :label="t('finance.categories.parent')" optional>
          <ComboBox v-model="form.parent" :options="parentChoices" clearable :placeholder="t('finance.categories.topLevel')" />
        </FormField>
        <FormField :label="t('finance.accounts.color')" optional>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="swatch in ACCOUNT_SWATCHES"
              :key="swatch"
              type="button"
              :class="['size-7 rounded-full border-2', form.color === swatch ? 'border-fg' : 'border-transparent']"
              :style="{ background: swatch }"
              :aria-label="swatch"
              :aria-pressed="form.color === swatch"
              @click="form.color = swatch"
            />
          </div>
        </FormField>
        <ToggleSwitch v-if="dialog.kind === 'expense'" v-model="form.is_capex" :label="t('finance.categories.capexLabel')" :description="t('finance.categories.capexHint')" layout="row" />
        <ToggleSwitch v-if="canSensitive" v-model="form.is_sensitive" :label="t('finance.categories.sensitiveLabel')" :description="t('finance.categories.sensitiveHint')" layout="row" />
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="dialog.open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" :disabled="!form.name.trim()" @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>

    <UiDialog v-model:open="mergeState.open" :title="t('finance.categories.mergeTitle', { name: findCategory(categories.data.value, mergeState.id)?.name ?? '' })" :description="t('finance.categories.mergeBody')" size="sm">
      <ComboBox v-model="mergeState.into" :options="mergeChoices" :placeholder="t('finance.categories.mergeInto')" />
      <template #footer>
        <UiButton variant="ghost" @click="mergeState.open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :disabled="!mergeState.into" @click="merge">{{ t("finance.categories.merge") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
