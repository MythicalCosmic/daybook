<script setup lang="ts">
/**
 * The Settings tab (people who manage the project): details (opens the edit dialog), the board's
 * lists (order, name, WIP limit, delete), labels (name and colour), and archiving.
 */
import { Archive, ArchiveRestore, ArrowDown, ArrowUp, CheckCircle2, Pencil, Plus, Tag, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import IconButton from "@/components/IconButton.vue";
import PageSection from "@/components/PageSection.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { archiveProject, createLabel, deleteLabel, deleteList, reorderLists, restoreProject, updateLabel, useCompanyId, useRefreshProjects } from "../api";
import { colorVar, tint } from "../lib";
import { PALETTE, type BoardList, type Label, type PaletteColor, type ProjectDetail } from "../types";
import ListDialog from "./ListDialog.vue";

const props = defineProps<{ project: ProjectDetail }>();
const emit = defineEmits<{ edit: [] }>();

const { t } = useI18n();
const fmt = useFormat();
const confirm = useConfirm();
const companyId = useCompanyId();
const refresh = useRefreshProjects();

const details = computed<DescriptionItem[]>(() => {
  const p = props.project;
  return [
    { key: "name", label: t("projects.form.name"), value: p.name },
    { key: "key", label: t("projects.form.key"), value: p.key, mono: true },
    { key: "status", label: t("projects.form.status"), value: t(`projects.status.${p.status}`) },
    { key: "lead", label: t("projects.form.lead"), value: p.lead?.name ?? "—" },
    { key: "start", label: t("projects.form.start"), value: p.start_on ? fmt.day(p.start_on, "medium") : "—" },
    { key: "due", label: t("projects.form.due"), value: p.due_on ? fmt.day(p.due_on, "medium") : "—" },
    { key: "budget", label: t("projects.form.budget"), value: p.budget ? fmt.money(p.budget, p.budget_currency) : "—" },
    { key: "visibility", label: t("projects.form.visibility"), value: t(`projects.visibility.${p.visibility}`) },
  ];
});

const listDialog = ref(false);
const editingList = ref<BoardList | null>(null);
const newLabel = ref("");
const newColor = ref<PaletteColor>("chart-3");

async function moveList(index: number, delta: -1 | 1): Promise<void> {
  const ids = props.project.lists.map((l) => l.id);
  const target = index + delta;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  await reorderLists(companyId.value, props.project.id, ids);
  void refresh();
}

async function removeList(list: BoardList): Promise<void> {
  const answer = await confirm({ title: t("projects.list.deleteTitle", { name: list.name }), message: t("projects.list.deleteBody"), tone: "danger", confirmLabel: t("projects.list.delete") });
  if (!answer) return;
  await deleteList(companyId.value, props.project.id, list.id);
  void refresh();
}

async function addLabel(): Promise<void> {
  if (!newLabel.value.trim()) return;
  await createLabel(companyId.value, props.project.id, { name: newLabel.value.trim(), color: newColor.value });
  newLabel.value = "";
  void refresh();
}

async function recolor(label: Label, color: PaletteColor): Promise<void> {
  await updateLabel(companyId.value, props.project.id, label.id, { color });
  void refresh();
}

async function renameLabel(label: Label): Promise<void> {
  const answer = await confirm({ title: t("projects.labels.rename"), reason: "required", reasonLabel: t("projects.labels.name"), reasonPlaceholder: label.name, confirmLabel: t("common.save") });
  if (!answer?.reason.trim()) return;
  await updateLabel(companyId.value, props.project.id, label.id, { name: answer.reason.trim() });
  void refresh();
}

async function removeLabel(label: Label): Promise<void> {
  const answer = await confirm({ title: t("projects.labels.deleteTitle", { name: label.name }), message: t("projects.labels.deleteBody"), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  await deleteLabel(companyId.value, props.project.id, label.id);
  void refresh();
}

async function toggleArchive(): Promise<void> {
  if (props.project.archived_at) {
    await restoreProject(companyId.value, props.project.id);
    toast.success(t("projects.archive.restored", { key: props.project.key }));
  } else {
    const answer = await confirm({ title: t("projects.archive.title", { key: props.project.key }), message: t("projects.archive.body"), tone: "danger", confirmLabel: t("projects.action.archive") });
    if (!answer) return;
    await archiveProject(companyId.value, props.project.id);
    toast.success(t("projects.archive.done", { key: props.project.key }));
  }
  void refresh();
}
</script>

<template>
  <div class="mx-auto flex max-w-[880px] flex-col gap-5">
    <PageSection :title="t('projects.settingsTab.details')" variant="card">
      <template #actions><UiButton size="sm" :icon="Pencil" @click="emit('edit')">{{ t("projects.action.edit") }}</UiButton></template>
      <DescriptionList :items="details" :columns="2" />
    </PageSection>

    <PageSection :title="t('projects.settingsTab.lists')" :description="t('projects.settingsTab.listsHint')" variant="card" flush>
      <template #actions><UiButton size="sm" :icon="Plus" @click="editingList = null; listDialog = true">{{ t("projects.list.add") }}</UiButton></template>
      <ul class="divide-y divide-line">
        <li v-for="(list, index) in project.lists" :key="list.id" class="flex items-center gap-3 px-4 py-2.5">
          <div class="flex items-center">
            <IconButton :icon="ArrowUp" :label="t('projects.settingsTab.up')" size="sm" :disabled="index === 0" @click="moveList(index, -1)" />
            <IconButton :icon="ArrowDown" :label="t('projects.settingsTab.down')" size="sm" :disabled="index === project.lists.length - 1" @click="moveList(index, 1)" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-1.5 font-medium text-fg">
              {{ list.name }}
              <CheckCircle2 v-if="list.is_done" :size="14" class="text-success" :aria-label="t('projects.settingsTab.doneList')" />
            </p>
            <p class="text-xs text-muted">
              {{ list.is_done ? t("projects.settingsTab.doneListHint") : list.wip_limit ? t("projects.list.wipNow", { n: list.wip_limit }) : t("projects.list.wipNone") }}
            </p>
          </div>
          <IconButton :icon="Pencil" :label="t('projects.list.edit')" size="sm" @click="editingList = list; listDialog = true" />
          <IconButton v-if="!list.is_done" :icon="Trash2" :label="t('projects.list.delete')" size="sm" @click="removeList(list)" />
        </li>
      </ul>
    </PageSection>

    <PageSection :title="t('projects.settingsTab.labels')" :description="t('projects.settingsTab.labelsHint')" variant="card">
      <div class="flex flex-col gap-3">
        <div v-for="label in project.labels" :key="label.id" class="flex flex-wrap items-center gap-2">
          <span class="inline-flex h-7 min-w-28 items-center gap-1.5 rounded-full px-3 text-xs font-semibold" :style="{ background: tint(label.color, 20), color: colorVar(label.color) }">
            <Tag :size="12" />{{ label.name }}
          </span>
          <div class="flex gap-1" role="radiogroup" :aria-label="t('projects.labels.color')">
            <button
              v-for="color in PALETTE"
              :key="color"
              type="button"
              role="radio"
              :aria-checked="label.color === color"
              :aria-label="color"
              class="size-5 rounded-full ring-offset-1 ring-offset-surface"
              :class="label.color === color && 'ring-2 ring-fg/50'"
              :style="{ background: colorVar(color) }"
              @click="recolor(label, color)"
            />
          </div>
          <span class="flex-1" />
          <IconButton :icon="Pencil" :label="t('projects.labels.rename')" size="sm" @click="renameLabel(label)" />
          <IconButton :icon="Trash2" :label="t('common.delete')" size="sm" @click="removeLabel(label)" />
        </div>
        <form class="flex flex-wrap items-center gap-2 border-t border-line pt-3" @submit.prevent="addLabel">
          <TextInput v-model="newLabel" size="sm" :maxlength="30" :placeholder="t('projects.labels.newPlaceholder')" class="w-48" />
          <div class="flex gap-1" role="radiogroup" :aria-label="t('projects.labels.color')">
            <button
              v-for="color in PALETTE"
              :key="color"
              type="button"
              role="radio"
              :aria-checked="newColor === color"
              :aria-label="color"
              class="size-5 rounded-full ring-offset-1 ring-offset-surface"
              :class="newColor === color && 'ring-2 ring-fg/50'"
              :style="{ background: colorVar(color) }"
              @click="newColor = color"
            />
          </div>
          <UiButton type="submit" size="sm" :icon="Plus" :disabled="!newLabel.trim()">{{ t("projects.labels.add") }}</UiButton>
        </form>
      </div>
    </PageSection>

    <PageSection :title="t('projects.settingsTab.danger')" variant="card">
      <div class="flex flex-wrap items-center gap-3">
        <p class="min-w-0 flex-1 text-sm text-muted">{{ project.archived_at ? t("projects.settingsTab.restoreHint") : t("projects.settingsTab.archiveHint") }}</p>
        <UiButton :variant="project.archived_at ? 'secondary' : 'danger'" :icon="project.archived_at ? ArchiveRestore : Archive" @click="toggleArchive">
          {{ project.archived_at ? t("projects.action.restore") : t("projects.action.archive") }}
        </UiButton>
      </div>
    </PageSection>

    <ListDialog v-model:open="listDialog" :project-id="project.id" :list="editingList" />
  </div>
</template>
