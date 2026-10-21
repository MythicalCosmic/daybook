<script setup lang="ts">
/**
 * One space in the sidebar: its row (open, count, "+ page") and, when expanded, its page tree.
 * Managers drag pages (or use Alt + arrows) to reorder and nest them; the move shows at once and
 * goes back if the server refuses it.
 */
import { ChevronRight, Plus } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import type { TreeId, TreeMove } from "@/components/tree";
import TreeList from "@/components/TreeList.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { kbKeys, knowledgeApi, useRefresh, useTree } from "../api";
import { moveData, pathTo, toTreeNodes } from "../lib";
import type { Space, TreeNodeData } from "../types";

const props = defineProps<{ space: Space; expanded: boolean; currentPageId: number | null; active: boolean }>();
const emit = defineEmits<{ toggle: [] }>();

const { t } = useI18n();
const router = useRouter();
const client = useQueryClient();
const company = useCompanyStore();
const canManage = useCan("knowledge.manage");
const refresh = useRefresh();

const tree = useTree(computed(() => (props.expanded ? props.space.id : null)));
const skeleton = useDelayedPending(computed(() => props.expanded && tree.isPending.value));
const nodes = computed(() => toTreeNodes(tree.data.value ?? [], t("knowledge.draft")));
const openIds = ref<TreeId[]>([]);
const selected = computed<TreeId | null>(() => props.currentPageId);
const base = computed(() => `/c/${company.currentId}/knowledge`);

// Open the tree down to the page on screen.
watch(
  [() => tree.data.value, () => props.currentPageId],
  ([data, pageId]) => {
    if (!data || pageId === null) return;
    const trail = pathTo(data, pageId);
    if (trail) openIds.value = Array.from(new Set([...openIds.value, ...trail]));
  },
  { immediate: true },
);

function open(id: TreeId): void {
  void router.push(`${base.value}/p/${id}`);
}

async function move(change: TreeMove): Promise<void> {
  const key = kbKeys.tree(company.currentId ?? 0, props.space.id);
  const before = client.getQueryData<TreeNodeData[]>(key);
  if (before) client.setQueryData(key, moveData(before, { id: Number(change.id), parentId: change.parentId === null ? null : Number(change.parentId), index: change.index }));
  try {
    await knowledgeApi.move(company.currentId ?? 0, Number(change.id), {
      parent: change.parentId === null ? null : Number(change.parentId),
      index: change.index,
    });
    void refresh();
  } catch {
    if (before) client.setQueryData(key, before);
  }
}
</script>

<template>
  <div class="flex flex-col">
    <div :class="['group flex h-8 items-center gap-1 rounded-[8px] pr-1 transition-colors', active ? 'bg-surface text-fg shadow-xs dark:bg-surface-2' : 'text-fg hover:bg-highlight']">
      <button
        type="button"
        class="grid size-6 shrink-0 place-items-center rounded-[6px] text-subtle hover:text-fg"
        :aria-label="expanded ? t('common.tree.collapse') : t('common.tree.expand')"
        :aria-expanded="expanded"
        @click="emit('toggle')"
      >
        <ChevronRight :size="14" :class="['transition-transform duration-150', expanded && 'rotate-90']" />
      </button>
      <RouterLink :to="`${base}/s/${space.id}`" class="flex min-w-0 flex-1 items-center gap-2 py-1 text-sm font-semibold" @click="!expanded && emit('toggle')">
        <span class="text-[15px] leading-none" aria-hidden="true">{{ space.icon || "📁" }}</span>
        <span class="truncate">{{ space.name }}</span>
      </RouterLink>
      <span class="shrink-0 text-xs tabular-nums text-subtle group-hover:hidden">{{ space.counts.pages || "" }}</span>
      <IconButton
        v-if="canManage"
        :icon="Plus"
        :label="t('knowledge.newPageIn', { space: space.name })"
        size="sm"
        :tooltip="false"
        class="hidden group-hover:inline-flex group-focus-within:inline-flex"
        :to="{ path: `${base}/new`, query: { space: String(space.id) } }"
      />
    </div>
    <div v-if="expanded" class="ml-3 border-l border-line pl-1.5 pt-0.5">
      <div v-if="skeleton" class="flex flex-col gap-2 px-2 py-2" aria-hidden="true">
        <SkeletonBlock v-for="n in 3" :key="n" :width="`${60 + n * 10}%`" height="12px" />
      </div>
      <p v-else-if="tree.data.value && !tree.data.value.length" class="px-2 py-2 text-xs text-muted">
        {{ t("knowledge.sidebar.emptySpace") }}
        <RouterLink v-if="canManage" :to="{ path: `${base}/new`, query: { space: String(space.id) } }" class="font-semibold text-accent-fg hover:underline">{{ t("knowledge.sidebar.writeFirst") }}</RouterLink>
      </p>
      <TreeList
        v-else-if="nodes.length"
        v-model:expanded="openIds"
        :selected="selected"
        :nodes="nodes"
        :draggable="canManage"
        :max-depth="3"
        :indent="14"
        :label="space.name"
        @select="(node) => open(node.id)"
        @move="move"
      >
        <template v-if="canManage" #actions="{ node }">
          <IconButton :icon="Plus" :label="t('knowledge.addSubpage')" size="sm" :tooltip="false" :to="{ path: `${base}/new`, query: { space: String(space.id), parent: String(node.id) } }" />
        </template>
      </TreeList>
    </div>
  </div>
</template>
