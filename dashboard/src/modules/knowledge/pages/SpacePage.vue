<script setup lang="ts">
/**
 * One space: who reads it, its pages as a tree (managers reorder them here too, by dragging or with
 * Alt + arrows), and the space's own settings.
 */
import { Archive, ArchiveRestore, Ellipsis, FilePlus2, FileText, Pencil, Plus, Users } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TreeId, TreeMove } from "@/components/tree";
import TreeList from "@/components/TreeList.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { kbKeys, knowledgeApi, useRefresh, useSpaces, useTree } from "../api";
import SpaceDialog from "../components/SpaceDialog.vue";
import { audienceText, countNodes, moveData, toTreeNodes } from "../lib";
import type { TreeNodeData } from "../types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const client = useQueryClient();
const company = useCompanyStore();
const confirm = useConfirm();
const canManage = useCan("knowledge.manage");
const refresh = useRefresh();

const spaceId = computed(() => Number(route.params.spaceId));
const spaces = useSpaces();
const space = computed(() => spaces.data.value?.find((item) => item.id === spaceId.value) ?? null);
const tree = useTree(spaceId);
const skeleton = useDelayedPending(computed(() => spaces.isPending.value || tree.isPending.value));
const editing = ref(false);
const expanded = ref<TreeId[]>([]);
const base = computed(() => `/c/${company.currentId}/knowledge`);
const newPage = computed(() => ({ path: `${base.value}/new`, query: { space: String(spaceId.value) } }));

const byId = computed(() => {
  const map = new Map<number, TreeNodeData>();
  const walk = (nodes: TreeNodeData[]) => nodes.forEach((node) => (map.set(node.id, node), walk(node.children)));
  walk(tree.data.value ?? []);
  return map;
});
const nodes = computed(() => toTreeNodes(tree.data.value ?? [], t("knowledge.draft")));
const total = computed(() => countNodes(tree.data.value ?? []));

async function move(change: TreeMove): Promise<void> {
  const key = kbKeys.tree(company.currentId ?? 0, spaceId.value);
  const before = client.getQueryData<TreeNodeData[]>(key);
  const parent = change.parentId === null ? null : Number(change.parentId);
  if (before) client.setQueryData(key, moveData(before, { id: Number(change.id), parentId: parent, index: change.index }));
  try {
    await knowledgeApi.move(company.currentId ?? 0, Number(change.id), { parent, index: change.index });
    void refresh();
  } catch {
    if (before) client.setQueryData(key, before);
  }
}

async function archive(): Promise<void> {
  if (!space.value) return;
  const answer = await confirm({
    title: t("knowledge.space.archiveTitle", { name: space.value.name }),
    message: t("knowledge.space.archiveBody"),
    confirmLabel: t("knowledge.space.archive"),
    tone: "danger",
  });
  if (!answer) return;
  await knowledgeApi.archiveSpace(company.currentId ?? 0, space.value.id);
  await refresh();
  toast.success(t("knowledge.space.archived"), {
    action: {
      label: t("common.undo"),
      onClick: async () => {
        await knowledgeApi.restoreSpace(company.currentId ?? 0, spaceId.value);
        await refresh();
      },
    },
  });
  void router.push(base.value);
}

const menu = computed<MenuEntry[]>(() => [
  { label: t("knowledge.space.edit"), icon: Pencil, onSelect: () => (editing.value = true) },
  { type: "separator" },
  space.value?.archived
    ? { label: t("knowledge.space.restore"), icon: ArchiveRestore, onSelect: () => void knowledgeApi.restoreSpace(company.currentId ?? 0, spaceId.value).then(refresh) }
    : { label: t("knowledge.space.archive"), icon: Archive, danger: true, onSelect: () => void archive() },
]);

useHotkey("n", () => canManage.value && void router.push(newPage.value), { description: "knowledge.hotkey.newPage", group: "page" });
</script>

<template>
  <div>
    <ErrorState v-if="spaces.isError.value || tree.isError.value" :error="spaces.error.value ?? tree.error.value" :retry="() => (spaces.refetch(), tree.refetch())" />
    <div v-else-if="skeleton || !space" class="flex flex-col gap-4">
      <SkeletonBlock width="40%" height="28px" />
      <SkeletonBlock width="60%" />
      <SkeletonBlock height="260px" radius="12px" />
    </div>
    <template v-else>
      <PageHeader :title="`${space.icon ? space.icon + ' ' : ''}${space.name}`" :description="space.description || undefined" :back="base" :back-label="t('knowledge.title')">
        <template v-if="canManage" #actions>
          <UiButton variant="primary" :icon="FilePlus2" :to="newPage" kbd="N">{{ t("knowledge.newPage") }}</UiButton>
          <DropdownMenu :items="menu">
            <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" variant="secondary" /></template>
          </DropdownMenu>
        </template>
        <template #meta>
          <StatusPill size="sm" tone="info" :icon="Users" :dot="false" :label="audienceText(space, t('knowledge.space.everyone'))" />
          <StatusPill size="sm" tone="neutral" :dot="false" :label="t('knowledge.pagesCount', { n: total }, total)" />
          <StatusPill v-if="space.archived" size="sm" tone="warning" :label="t('knowledge.archived')" />
        </template>
      </PageHeader>

      <EmptyState
        v-if="!total"
        :icon="FileText"
        :title="t('knowledge.space.emptyTitle')"
        :description="canManage ? t('knowledge.space.emptyBody') : t('knowledge.space.emptyReader')"
        class="ui-card"
      >
        <UiButton v-if="canManage" variant="primary" :icon="FilePlus2" :to="newPage">{{ t("knowledge.sidebar.writeFirst") }}</UiButton>
      </EmptyState>

      <section v-else class="ui-card p-2" :aria-label="t('knowledge.space.contents')">
        <header class="flex items-center gap-2 px-2 pb-2 pt-1">
          <h2 class="flex-1 text-sm font-semibold text-muted">{{ t("knowledge.space.contents") }}</h2>
          <span v-if="canManage" class="hidden text-xs text-subtle sm:inline">{{ t("knowledge.space.dragHint") }}</span>
        </header>
        <TreeList
          v-model:expanded="expanded"
          :nodes="nodes"
          :draggable="canManage"
          :max-depth="3"
          :label="space.name"
          @select="(node) => router.push(`${base}/p/${node.id}`)"
          @move="move"
        >
          <template #node="{ node }">
            <span class="min-w-0 flex-1 truncate">{{ node.label }}</span>
            <StatusPill v-if="byId.get(Number(node.id)) && !byId.get(Number(node.id))!.published" size="sm" tone="neutral" :label="t('knowledge.draft')" />
            <UiBadge v-else-if="byId.get(Number(node.id))?.require_ack" tone="primary" variant="soft">{{ t("knowledge.mustRead") }}</UiBadge>
          </template>
          <template v-if="canManage" #actions="{ node }">
            <IconButton :icon="Plus" :label="t('knowledge.addSubpage')" size="sm" :tooltip="false" :to="{ path: `${base}/new`, query: { space: String(spaceId), parent: String(node.id) } }" />
          </template>
        </TreeList>
      </section>

      <SpaceDialog v-model:open="editing" :space="space" />
    </template>
  </div>
</template>
