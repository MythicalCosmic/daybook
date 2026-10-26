<script setup lang="ts">
/**
 * People › Departments: the company's structure as an org chart. Each card names a department, its
 * head and how many people it has; selecting one opens its panel (`?department=12`, so Back closes
 * it) with its people. Owners and managers who see every branch edit the structure: new
 * departments and sub-departments, rename, move, heads, delete.
 */
import { Ellipsis, Network, Plus, Trash2 } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { usePermission } from "@/lib/usePermission";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useDepartmentMutations, useDepartments, usePeopleStats } from "../api";
import DepartmentBranch from "../components/DepartmentBranch.vue";
import type { DepartmentDialogMode } from "../components/DepartmentDialog.vue";
import { departmentMenu, type DepartmentAction } from "../components/departmentMenu";
import DepartmentPanel from "../components/DepartmentPanel.vue";
import { buildDepartmentTree, deleteOutcome, parentPath, placedCount } from "../departments";
import type { Department } from "../types";

const DepartmentDialog = defineAsyncComponent(() => import("../components/DepartmentDialog.vue"));

const { t } = useI18n();
const company = useCompanyStore();
const confirm = useConfirm();
const { can } = usePermission();

const departments = useDepartments();
const list = computed(() => departments.data.value ?? []);
const roots = computed(() => buildDepartmentTree(list.value));
/** No department has sub-departments yet: a grid of cards reads better than a column of them. */
const flat = computed(() => roots.value.every((root) => root.children.length === 0));
const skeleton = useDelayedPending(computed(() => departments.isPending.value));
const stats = usePeopleStats();

/**
 * Who changes the structure: the server says so on every department; before there is one, owners
 * and managers with members.manage who see every branch (the same rule).
 */
const canEdit = computed(() =>
  list.value.length ? list.value.some((d) => d.can_edit) : can("members.manage") && (company.current?.is_owner || company.current?.branch_scope === null),
);
/** Who puts people in and takes them out (the server checks each person's branches). */
const canPlace = computed(() => can("members.manage"));

/** Department counts are company-wide; the headcount is the viewer's branches: compare them only for someone who sees every branch. */
const seesEveryBranch = computed(() => !!company.current && (company.current.is_owner || company.current.branch_scope === null));
const summary = computed(() => {
  if (!list.value.length) return [];
  const placed = placedCount(list.value);
  const parts = [t("people.dept.count", { n: list.value.length }, list.value.length), t("people.dept.placed", { n: placed }, placed)];
  const current = stats.data.value?.current;
  if (seesEveryBranch.value && current !== undefined && current > placed) parts.push(t("people.dept.unplaced", { n: current - placed }, current - placed));
  return parts;
});

// ─── The panel ───────────────────────────────────────────────────────────────
const selectedId = useRouteState("department", rs.optionalNumber(), { push: true });
const selected = computed(() => list.value.find((d) => d.id === selectedId.value) ?? null);
// A department deleted elsewhere (or a stale link) closes its panel once the list is in.
watch([selectedId, () => departments.data.value], ([id, data]) => {
  if (id !== null && data && !data.some((d) => d.id === id)) selectedId.value = null;
});

function openPanel(department: Department): void {
  selectedId.value = department.id;
}
const panelMenu = computed(() => (selected.value ? departmentMenu(selected.value, t, (action) => onAction(action, selected.value!)) : []));

// ─── Edits ───────────────────────────────────────────────────────────────────
const dialog = ref<{ mode: DepartmentDialogMode; department: Department | null; parentId: number | null; key: number } | null>(null);
let dialogKey = 0;
const dialogOpen = computed({
  get: () => dialog.value !== null,
  set: (value: boolean) => {
    if (!value) dialog.value = null;
  },
});

function openDialog(mode: DepartmentDialogMode, department: Department | null = null, parentId: number | null = null): void {
  dialog.value = { mode, department, parentId, key: ++dialogKey };
}

const { update, remove } = useDepartmentMutations();

async function clearHead(department: Department): Promise<void> {
  const head = department.head;
  if (!head) return;
  try {
    const saved = await update.mutateAsync({ id: department.id, body: { head_id: null } });
    toast.success(t("people.dept.headCleared", { name: saved.name }), {
      action: { label: t("common.undo"), onClick: () => update.mutate({ id: department.id, body: { head_id: head.id } }) },
    });
  } catch {
    // The HTTP layer showed why.
  }
}

async function deleteDepartment(department: Department): Promise<void> {
  const outcome = deleteOutcome(list.value, department);
  const answer = await confirm({
    title: t("people.dept.deleteTitle", { name: department.name }),
    message: t(outcome.key, { parent: outcome.parent ?? "" }),
    tone: "danger",
    icon: Trash2,
    confirmLabel: t("common.delete"),
  });
  if (!answer) return;
  try {
    await remove.mutateAsync(department.id);
    if (selectedId.value === department.id) selectedId.value = null;
    toast.success(t("people.dept.deleted", { name: department.name }));
  } catch {
    // Back in the chart; the HTTP layer showed why.
  }
}

function onAction(action: DepartmentAction, department: Department): void {
  if (action === "addSub") openDialog("create", null, department.id);
  else if (action === "clearHead") void clearHead(department);
  else if (action === "delete") void deleteDepartment(department);
  else openDialog(action, department);
}

function onSaved(department: Department): void {
  // A new department opens at once, ready for its people.
  if (dialog.value?.mode === "create") selectedId.value = department.id;
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('people.nav.departments')" :description="t('people.dept.description')">
      <template v-if="canEdit && list.length" #actions>
        <UiButton variant="primary" :icon="Plus" data-new-department @click="openDialog('create')">{{ t("people.dept.new") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="flex flex-col gap-4" aria-hidden="true">
      <SkeletonBlock width="320px" height="104px" radius="14px" />
      <div class="flex flex-wrap gap-4 pl-9">
        <SkeletonBlock v-for="n in 3" :key="n" width="240px" height="104px" radius="14px" />
      </div>
    </div>
    <ErrorState v-else-if="departments.isError.value" class="ui-card" :error="departments.error.value" :retry="() => departments.refetch()" />

    <section v-else-if="departments.data.value && !list.length" class="ui-card px-5 py-10" data-departments-empty>
      <EmptyState :icon="Network" :title="t('people.dept.emptyTitle')" :description="t('people.dept.emptyBody')">
        <UiButton v-if="canEdit" variant="primary" :icon="Plus" data-new-department @click="openDialog('create')">{{ t("people.dept.new") }}</UiButton>
        <p v-else class="max-w-sm text-sm text-muted">{{ t("people.dept.emptyNoEdit") }}</p>
      </EmptyState>
    </section>

    <template v-else-if="list.length">
      <p class="-mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted" data-departments-summary>
        <template v-for="(part, index) in summary" :key="index">
          <span v-if="index" class="text-subtle" aria-hidden="true">·</span>
          <span class="tabular-nums">{{ part }}</span>
        </template>
      </p>
      <ul
        :aria-label="t('people.dept.chart')"
        :class="flat ? 'grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] items-start gap-4' : 'flex flex-col gap-8'"
        data-org-chart
      >
        <DepartmentBranch
          v-for="root in roots"
          :key="root.department.id"
          :node="root"
          :selected-id="selectedId"
          :can-edit="canEdit"
          top
          @open="openPanel"
          @action="onAction"
        />
      </ul>
    </template>

    <UiDrawer query-key="department" :title="selected?.name ?? ''" :description="selected ? parentPath(selected) || undefined : undefined" size="md">
      <template v-if="canEdit && selected" #header-actions>
        <DropdownMenu :items="panelMenu" align="end">
          <template #trigger><IconButton :icon="Ellipsis" :label="t('people.dept.actions')" data-panel-menu /></template>
        </DropdownMenu>
      </template>
      <DepartmentPanel
        v-if="selected"
        :key="selected.id"
        :department="selected"
        :departments="list"
        :can-edit="canEdit"
        :can-place="canPlace"
        @open="openPanel"
        @action="onAction"
      />
    </UiDrawer>

    <DepartmentDialog
      v-if="dialog"
      :key="dialog.key"
      v-model:open="dialogOpen"
      :mode="dialog.mode"
      :department="dialog.department"
      :parent-id="dialog.parentId"
      :departments="list"
      @saved="onSaved"
    />
  </div>
</template>
