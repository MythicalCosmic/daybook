<script setup lang="ts">
/**
 * Roles and permissions (plan §6.2 "Roles"): every role as a column of the permission matrix,
 * changes staged and saved together, new roles started blank or from a copy, rename, make default
 * and delete from each column's menu. The anti-escalation rules (§5) show in the matrix (locked
 * Owner column, read-only roles, greyed-out permissions) and the server enforces them.
 */
import { Copy, Ellipsis, Pencil, Plus, Search, ShieldCheck, Star, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TextInput from "@/components/TextInput.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { usePermission } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { useDeleteRole, usePermissionRegistry, useRoles, useSaveRole } from "../api";
import PermissionMatrix from "../components/PermissionMatrix.vue";
import type { Role } from "../types";

const { t, te } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const { isPhone } = useBreakpoints();
const { can, isOwner } = usePermission();

const roles = useRoles();
const registry = usePermissionRegistry();
const skeleton = useDelayedPending(computed(() => roles.isPending.value || registry.isPending.value));
const save = useSaveRole();
const remove = useDeleteRole();

const draft = ref<Record<number, string[]>>({});
const query = ref("");
const area = ref<string | null>(null);
const phoneRole = ref<number | null>(null);

const list = computed(() => roles.data.value ?? []);
const areas = computed(() => [...new Set((registry.data.value ?? []).map((p) => p.group))].map((value) => ({ value, label: te(`people.area.${value}`) ? t(`people.area.${value}`) : value })));
const changedRoles = computed(() => list.value.filter((role) => draft.value[role.id]));
// Phones edit one role at a time, the first one besides Owner until another is picked.
watch(
  list,
  (rows) => {
    if (phoneRole.value === null || !rows.some((role) => role.id === phoneRole.value)) phoneRole.value = rows.find((role) => !role.is_owner)?.id ?? null;
  },
  { immediate: true },
);
const shownRoles = computed(() => (isPhone.value ? list.value.filter((role) => role.id === phoneRole.value) : list.value));

/** Rule 2 in the UI: owners grant anything, others only what they hold. */
const grantable = (code: string) => isOwner.value || can(code as never);

async function saveAll(): Promise<void> {
  const pending = changedRoles.value;
  try {
    for (const role of pending) await save.mutateAsync({ id: role.id, body: { permissions: draft.value[role.id] } });
    draft.value = {};
    toast.success(t("people.roles.saved", { n: pending.length }, pending.length));
  } catch {
    // The HTTP layer showed why; what wasn't saved stays staged.
  }
}

// New role / rename -----------------------------------------------------------------------
const dialog = ref<{ mode: "new" | "rename"; role: Role | null } | null>(null);
const name = ref("");
const copyFrom = ref<number | null>(null);
function openNew(from: Role | null = null): void {
  dialog.value = { mode: "new", role: null };
  name.value = from ? t("people.roles.copyName", { name: from.name }) : "";
  copyFrom.value = from?.id ?? null;
}
function openRename(role: Role): void {
  dialog.value = { mode: "rename", role };
  name.value = role.name;
}
const copyOptions = computed(() => list.value.filter((role) => !role.is_owner).map((role) => ({ value: role.id, label: role.name })));
async function submitDialog(): Promise<void> {
  if (!dialog.value || !name.value.trim()) return;
  const current = dialog.value;
  try {
    if (current.mode === "new") {
      const source = list.value.find((role) => role.id === copyFrom.value);
      const permissions = (source?.permissions ?? []).filter(grantable);
      await save.mutateAsync({ id: null, body: { name: name.value.trim(), permissions } });
      toast.success(t("people.roles.created", { name: name.value.trim() }));
    } else if (current.role) {
      await save.mutateAsync({ id: current.role.id, body: { name: name.value.trim() } });
      toast.success(t("people.roles.renamed", { name: name.value.trim() }));
    }
    dialog.value = null;
  } catch {
    // Shown by the HTTP layer (a name taken, a permission not yours).
  }
}

async function makeDefault(role: Role): Promise<void> {
  try {
    await save.mutateAsync({ id: role.id, body: { is_default: true } });
    toast.success(t("people.roles.defaultSet", { name: role.name }));
  } catch {
    // Shown.
  }
}

async function deleteRole(role: Role): Promise<void> {
  const answer = await confirm({ title: t("people.roles.deleteTitle", { name: role.name }), message: t("people.roles.deleteBody"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  try {
    await remove.mutateAsync(role.id);
    toast.success(t("people.roles.deleted", { name: role.name }));
  } catch {
    // Shown (people still hold it, or it is the default).
  }
}

function menu(role: Role): MenuEntry[] {
  const entries: MenuEntry[] = [];
  if (role.can_edit) entries.push({ label: t("people.roles.rename"), icon: Pencil, onSelect: () => openRename(role) });
  if (!role.is_owner) entries.push({ label: t("people.roles.duplicate"), icon: Copy, onSelect: () => openNew(role) });
  if (role.can_edit && !role.is_default && !role.is_owner) entries.push({ label: t("people.roles.makeDefault"), icon: Star, onSelect: () => void makeDefault(role) });
  if (role.can_edit && !role.is_owner && !role.is_default) {
    entries.push({ type: "separator" });
    entries.push({ label: t("common.delete"), icon: Trash2, danger: true, disabled: role.members_count > 0, onSelect: () => void deleteRole(role) });
  }
  return entries;
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('people.roles.title')" :description="t('people.roles.description')" :back="`/c/${company.currentId}/people`" :back-label="t('people.title')">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" @click="openNew()">{{ t("people.roles.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="ui-card flex flex-col gap-3 p-4">
      <SkeletonBlock height="36px" />
      <SkeletonBlock v-for="n in 8" :key="n" height="28px" />
    </div>
    <ErrorState v-else-if="roles.isError.value || registry.isError.value" class="ui-card" :error="roles.error.value ?? registry.error.value" :retry="() => (roles.refetch(), registry.refetch())" />
    <div v-else-if="roles.data.value && !list.length" class="ui-card"><EmptyState :icon="ShieldCheck" :title="t('people.roles.emptyTitle')" :description="t('people.roles.emptyBody')" /></div>
    <template v-else-if="roles.data.value && registry.data.value">
      <div class="flex flex-wrap items-center gap-2">
        <div v-if="isPhone" class="min-w-[180px] flex-1"><SelectBox v-model="phoneRole" :options="list.filter((r) => !r.is_owner).map((r) => ({ value: r.id, label: r.name }))" :placeholder="t('people.roles.pickRole')" /></div>
        <TextInput v-model="query" class="w-full sm:w-[280px]" :icon="Search" :placeholder="t('people.roles.search')" clearable />
        <div class="w-full sm:w-[220px]"><SelectBox v-model="area" :options="areas" :placeholder="t('people.roles.allAreas')" clearable /></div>
        <span class="flex-1" />
        <p class="hidden text-sm text-muted lg:block">{{ t("people.roles.legend") }}</p>
      </div>

      <PermissionMatrix v-model:draft="draft" :roles="shownRoles" :permissions="registry.data.value" :grantable="grantable" :area="area ?? undefined" :query="query">
        <template #header="{ role }">
          <div class="flex flex-col items-center gap-1">
            <div class="flex items-center gap-1">
              <span class="max-w-[120px] truncate text-base font-semibold text-fg" :title="role.name">{{ role.name }}</span>
              <DropdownMenu v-if="menu(role).length" :items="menu(role)" align="end">
                <template #trigger><IconButton :icon="Ellipsis" :label="t('people.roles.options', { name: role.name })" size="sm" /></template>
              </DropdownMenu>
            </div>
            <span class="whitespace-nowrap text-xs font-normal text-muted">{{ t("people.roles.members", { n: role.members_count }, role.members_count) }}</span>
            <UiBadge v-if="role.is_default" tone="info">{{ t("people.roles.default") }}</UiBadge>
            <UiBadge v-if="role.is_owner" tone="primary">{{ t("people.roles.everything") }}</UiBadge>
          </div>
        </template>
      </PermissionMatrix>

      <StickyActionBar :show="changedRoles.length > 0" tone="warning">
        <template #message>{{ t("people.roles.unsaved", { roles: changedRoles.map((r) => r.name).join(", ") }) }}</template>
        <UiButton variant="ghost" @click="draft = {}">{{ t("common.discard") }}</UiButton>
        <UiButton variant="primary" :loading="save.isPending.value" @click="saveAll">{{ t("common.save") }}</UiButton>
      </StickyActionBar>
    </template>

    <UiDialog
      :open="!!dialog"
      :title="dialog?.mode === 'rename' ? t('people.roles.renameTitle') : t('people.roles.newTitle')"
      :description="dialog?.mode === 'new' ? t('people.roles.newDescription') : undefined"
      size="sm"
      @update:open="(value: boolean) => !value && (dialog = null)"
    >
      <form id="role-form" class="flex flex-col gap-4" @submit.prevent="submitDialog">
        <FormField :label="t('people.roles.name')" required>
          <TextInput v-model="name" :maxlength="100" autofocus :placeholder="t('people.roles.namePlaceholder')" />
        </FormField>
        <FormField v-if="dialog?.mode === 'new'" :label="t('people.roles.startFrom')" :hint="t('people.roles.startFromHint')">
          <SelectBox v-model="copyFrom" :options="copyOptions" :placeholder="t('people.roles.blank')" clearable />
        </FormField>
      </form>
      <template #footer>
        <UiButton variant="ghost" @click="dialog = null">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" type="submit" form="role-form" :loading="save.isPending.value" :disabled="!name.trim()">{{ dialog?.mode === "rename" ? t("common.save") : t("common.create") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
