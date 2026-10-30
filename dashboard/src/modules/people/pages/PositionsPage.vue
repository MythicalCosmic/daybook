<script setup lang="ts">
/**
 * Positions (plan §6.2 "Positions: drag to sort"): the jobs people pick when they join, in the
 * order they see them, each with the access it gives (approving someone or changing their job
 * title gives it). Drag a row (or Alt + ↑/↓) to reorder, click one to rename, hide or delete it,
 * or (with roles.manage) change its access, for the people who hold it now too. A position people
 * hold can only be hidden, never deleted.
 */
import { BriefcaseBusiness, Eye, EyeOff, Megaphone, Plus, Repeat, ShieldCheck, Trash2, UserPlus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import type { TreeMove, TreeNode } from "@/components/tree";
import TreeList from "@/components/TreeList.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { usePositionMutations, usePositions, useRoles } from "../api";
import type { PositionInput, PositionRow } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const positions = usePositions();
const skeleton = useDelayedPending(computed(() => positions.isPending.value));
const { create, update, remove, reorder } = usePositionMutations();
// Changing the access a job title gives takes roles.manage; the list shows it to everyone here.
const canSetAccess = useCan("roles.manage");
const roles = useRoles();
const defaultRole = computed(() => roles.data.value?.find((role) => role.is_default) ?? null);

/** "Access: Cashier", or the company's default role for a title without its own. */
function accessLine(row: PositionRow): string {
  const name = row.role?.name ?? defaultRole.value?.name;
  return name ? t("people.positions.accessLine", { name }) : t("people.positions.accessDefaultPlain");
}

const active = computed(() => (positions.data.value ?? []).filter((p) => p.is_active).sort((a, b) => a.order - b.order));
const hidden = computed(() => (positions.data.value ?? []).filter((p) => !p.is_active));
const nodes = computed<TreeNode[]>(() =>
  active.value.map((p) => ({
    id: p.id,
    label: p.name,
    icon: BriefcaseBusiness,
    meta: accessLine(p),
    badge: t("people.positions.people", { n: p.members_count }, p.members_count),
  })),
);

function onMove(move: TreeMove): void {
  const ids = active.value.map((p) => p.id).filter((id) => id !== move.id);
  ids.splice(move.index, 0, Number(move.id));
  reorder.mutate([...ids, ...hidden.value.map((p) => p.id)], {
    onSuccess: () => toast.success(t("people.positions.reordered"), { id: "positions-order" }),
  });
}

// Add / edit -------------------------------------------------------------------------------
const editing = ref<PositionRow | null>(null);
const adding = ref(false);
const name = ref("");
const isActive = ref(true);
const roleId = ref<number | null>(null);
const applyToHolders = ref(true);
function openAdd(): void {
  adding.value = true;
  editing.value = null;
  name.value = "";
  roleId.value = null;
}
function openEdit(id: number | string): void {
  const row = (positions.data.value ?? []).find((p) => p.id === Number(id));
  if (!row) return;
  editing.value = row;
  adding.value = false;
  name.value = row.name;
  isActive.value = row.is_active;
  roleId.value = row.role?.id ?? null;
  applyToHolders.value = true;
}

/** Roles a job title may give: never the Owner role, and only roles the viewer may give (the
 * one it gives now stays listed so the box can show it). */
const accessOptions = computed(() =>
  (roles.data.value ?? [])
    .filter((role) => !role.is_owner && (!role.is_default || role.id === editing.value?.role?.id) && (role.can_assign || role.id === editing.value?.role?.id))
    .map((role) => ({ value: role.id, label: role.name, disabled: !role.can_assign })),
);
const accessPlaceholder = computed(() =>
  defaultRole.value ? t("people.positions.accessDefault", { name: defaultRole.value.name }) : t("people.positions.accessDefaultPlain"),
);
const accessChanged = computed(() => !!editing.value && roleId.value !== (editing.value.role?.id ?? null));
const dialogOpen = computed({
  get: () => adding.value || editing.value !== null,
  set: (value: boolean) => {
    if (!value) {
      adding.value = false;
      editing.value = null;
    }
  },
});

async function submit(): Promise<void> {
  const clean = name.value.trim();
  if (!clean) return;
  try {
    if (adding.value) {
      const body: PositionInput = { name: clean };
      if (canSetAccess.value && roleId.value !== null) body.role_id = roleId.value;
      await create.mutateAsync(body);
      toast.success(t("people.positions.added", { name: clean }));
    } else if (editing.value) {
      const body: PositionInput = { name: clean, is_active: isActive.value };
      if (accessChanged.value) {
        body.role_id = roleId.value;
        body.apply_to_holders = editing.value.members_count > 0 && applyToHolders.value;
      }
      const saved = await update.mutateAsync({ id: editing.value.id, body });
      const applied = saved.applied ?? 0;
      toast.success(applied > 0 ? t("people.positions.savedApplied", { name: clean, n: applied }, applied) : t("people.positions.saved", { name: clean }));
    }
    dialogOpen.value = false;
  } catch {
    // Shown (a name already taken, an access they may not give).
  }
}

async function setVisible(row: PositionRow, visible: boolean): Promise<void> {
  try {
    await update.mutateAsync({ id: row.id, body: { is_active: visible } });
    toast.success(visible ? t("people.positions.shown", { name: row.name }) : t("people.positions.hiddenDone", { name: row.name }));
  } catch {
    // Rolled back.
  }
}

async function deletePosition(row: PositionRow): Promise<void> {
  const answer = await confirm({ title: t("people.positions.deleteTitle", { name: row.name }), message: t("people.positions.deleteBody"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  try {
    await remove.mutateAsync(row.id);
    dialogOpen.value = false;
    toast.success(t("people.positions.deleted", { name: row.name }));
  } catch {
    // Shown (people hold it).
  }
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('people.positions.title')" :description="t('people.positions.description')" :back="`/c/${company.currentId}/people`" :back-label="t('people.title')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" @click="openAdd">{{ t("people.positions.add") }}</UiButton>
      </template>
    </PageHeader>

    <div class="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div class="flex min-w-0 flex-col gap-5">
        <section class="ui-card p-2">
          <div v-if="skeleton" class="flex flex-col gap-2 p-2"><SkeletonBlock v-for="n in 6" :key="n" height="32px" radius="8px" /></div>
          <ErrorState v-else-if="positions.isError.value" compact :error="positions.error.value" :retry="() => positions.refetch()" class="m-2" />
          <EmptyState v-else-if="positions.data.value && !active.length" :icon="BriefcaseBusiness" :title="t('people.positions.emptyTitle')" :description="t('people.positions.emptyBody')">
            <UiButton variant="primary" :icon="Plus" @click="openAdd">{{ t("people.positions.add") }}</UiButton>
          </EmptyState>
          <TreeList v-else :nodes="nodes" draggable :max-depth="0" :label="t('people.positions.title')" @move="onMove" @select="(node) => openEdit(node.id)">
            <template #actions="{ node }">
              <IconButton :icon="EyeOff" size="sm" :label="t('people.positions.hide')" @click="setVisible(active.find((p) => p.id === node.id)!, false)" />
            </template>
          </TreeList>
        </section>

        <section v-if="hidden.length" class="flex flex-col gap-2">
          <h2 class="text-sm font-semibold text-muted">{{ t("people.positions.hiddenTitle", { n: hidden.length }, hidden.length) }}</h2>
          <ul class="ui-card divide-y divide-[var(--c-border)]">
            <li v-for="row in hidden" :key="row.id" class="flex items-center gap-3 px-4 py-2.5">
              <EyeOff :size="15" class="shrink-0 text-subtle" aria-hidden="true" />
              <button type="button" class="min-w-0 flex-1 truncate text-left text-base text-muted hover:text-fg" @click="openEdit(row.id)">{{ row.name }}</button>
              <span class="text-xs text-subtle">{{ t("people.positions.people", { n: row.members_count }, row.members_count) }}</span>
              <UiButton size="sm" variant="ghost" :icon="Eye" @click="setVisible(row, true)">{{ t("people.positions.show") }}</UiButton>
            </li>
          </ul>
        </section>
      </div>

      <aside class="ui-card h-fit p-5">
        <h2 class="text-md font-semibold text-fg">{{ t("people.positions.whyTitle") }}</h2>
        <ul class="mt-3 flex flex-col gap-3 text-sm text-muted">
          <li class="flex gap-2.5"><UserPlus :size="16" class="mt-0.5 shrink-0 text-primary" aria-hidden="true" />{{ t("people.positions.whyJoin") }}</li>
          <li class="flex gap-2.5"><ShieldCheck :size="16" class="mt-0.5 shrink-0 text-primary" aria-hidden="true" />{{ t("people.positions.whyAccess") }}</li>
          <li class="flex gap-2.5"><Repeat :size="16" class="mt-0.5 shrink-0 text-primary" aria-hidden="true" />{{ t("people.positions.whyRoutines") }}</li>
          <li class="flex gap-2.5"><Megaphone :size="16" class="mt-0.5 shrink-0 text-primary" aria-hidden="true" />{{ t("people.positions.whyAnnounce") }}</li>
        </ul>
        <p class="mt-4 rounded-[10px] bg-surface-2/70 px-3 py-2 text-xs text-muted dark:bg-surface-2">{{ t("people.positions.dragHint") }}</p>
      </aside>
    </div>

    <UiDialog v-model:open="dialogOpen" :title="adding ? t('people.positions.addTitle') : t('people.positions.editTitle')" size="sm">
      <form id="position-form" class="flex flex-col gap-4" @submit.prevent="submit">
        <FormField :label="t('people.positions.name')" required>
          <TextInput v-model="name" autofocus :maxlength="100" :placeholder="t('people.positions.namePlaceholder')" />
        </FormField>
        <FormField v-if="canSetAccess" :label="t('people.positions.access')" :hint="t('people.positions.accessHint')">
          <SelectBox v-model="roleId" :options="accessOptions" :placeholder="accessPlaceholder" clearable data-access-select />
        </FormField>
        <p v-else-if="editing" class="text-sm text-muted">{{ accessLine(editing) }}</p>
        <ToggleSwitch
          v-if="accessChanged && editing && editing.members_count > 0"
          v-model="applyToHolders"
          layout="row"
          :label="t('people.positions.applyHolders', { n: editing.members_count })"
          :description="t('people.positions.applyHoldersHint')"
          data-apply-holders
        />
        <ToggleSwitch v-if="editing" v-model="isActive" layout="row" :label="t('people.positions.visible')" :description="t('people.positions.visibleHint')" />
        <p v-if="editing" class="text-sm text-muted">{{ t("people.positions.heldBy", { n: editing.members_count }, editing.members_count) }}</p>
      </form>
      <template #footer>
        <UiButton
          v-if="editing && editing.members_count === 0"
          variant="ghost"
          :icon="Trash2"
          class="mr-auto hover:!text-danger"
          :loading="remove.isPending.value"
          @click="deletePosition(editing)"
          >{{ t("common.delete") }}</UiButton
        >
        <UiButton variant="ghost" @click="dialogOpen = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" form="position-form" :loading="create.isPending.value || update.isPending.value" :disabled="!name.trim()">{{ adding ? t("common.create") : t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
