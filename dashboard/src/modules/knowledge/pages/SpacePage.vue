<script setup lang="ts">
/**
 * One space: who reads it and every page in it as cards, in the tree's order (pages inside other
 * pages say where they sit). Managers see drafts and how many people have read each must-read
 * page; they reorder pages in the sidebar tree, or with "Move" on a page.
 */
import { Archive, ArchiveRestore, BookOpen, Ellipsis, FilePen, FilePlus2, FileText, Pencil, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePages, useRefresh, useSpaces, useTree } from "../api";
import ReadProgress from "../components/ReadProgress.vue";
import SpaceDialog from "../components/SpaceDialog.vue";
import { audienceText, flatten } from "../lib";
import type { PageRow } from "../types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const canManage = useCan("knowledge.manage");
const refresh = useRefresh();

const spaceId = computed(() => Number(route.params.spaceId));
const spaces = useSpaces();
const space = computed(() => spaces.data.value?.find((item) => item.id === spaceId.value) ?? null);
usePageTitle(() => space.value?.name);
const tree = useTree(spaceId);
const pages = usePages(computed(() => ({ space: spaceId.value, page_size: 200 })));
const skeleton = useDelayedPending(computed(() => spaces.isPending.value || tree.isPending.value || pages.isPending.value));
const editing = ref(false);
const base = computed(() => `/c/${company.currentId}/knowledge`);
const newPage = computed(() => ({ path: `${base.value}/new`, query: { space: String(spaceId.value) } }));

/** Every page in the tree's order, with the page it sits in. */
const cards = computed(() => {
  const rows = new Map((pages.data.value?.results ?? []).map((row) => [row.id, row]));
  const titles = new Map<number, string>();
  return flatten(tree.data.value ?? [])
    .map(({ node, depth }) => {
      titles.set(node.id, node.title);
      const row = rows.get(node.id);
      return row ? { row, depth, parent: row.parent_id ? (titles.get(row.parent_id) ?? null) : null } : null;
    })
    .filter((card): card is { row: PageRow; depth: number; parent: string | null } => card !== null);
});
const stats = computed(() => {
  const rows = cards.value.map((card) => card.row);
  return {
    total: rows.length,
    mustRead: rows.filter((row) => row.published && row.require_ack).length,
    drafts: rows.filter((row) => !row.published).length,
  };
});

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
    <ErrorState v-if="spaces.isError.value || tree.isError.value || pages.isError.value" :error="spaces.error.value ?? tree.error.value ?? pages.error.value" :retry="() => (spaces.refetch(), tree.refetch(), pages.refetch())" />
    <div v-else-if="skeleton || !space" class="flex flex-col gap-4">
      <SkeletonBlock width="40%" height="28px" />
      <SkeletonBlock width="60%" />
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"><SkeletonBlock v-for="n in 6" :key="n" height="150px" radius="12px" /></div>
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
          <StatusPill size="sm" tone="neutral" :icon="BookOpen" :dot="false" :label="t('knowledge.pagesCount', { n: stats.total }, stats.total)" />
          <StatusPill v-if="stats.mustRead" size="sm" tone="primary" :dot="false" :label="t('knowledge.space.mustReadCount', { n: stats.mustRead })" />
          <StatusPill v-if="canManage && stats.drafts" size="sm" tone="neutral" :icon="FilePen" :dot="false" :label="t('knowledge.draftsCount', { n: stats.drafts }, stats.drafts)" />
          <StatusPill v-if="space.archived" size="sm" tone="warning" :label="t('knowledge.archived')" />
        </template>
      </PageHeader>

      <EmptyState
        v-if="!cards.length"
        :icon="FileText"
        :title="t('knowledge.space.emptyTitle')"
        :description="canManage ? t('knowledge.space.emptyBody') : t('knowledge.space.emptyReader')"
        class="ui-card"
      >
        <UiButton v-if="canManage" variant="primary" :icon="FilePlus2" :to="newPage">{{ t("knowledge.sidebar.writeFirst") }}</UiButton>
      </EmptyState>

      <template v-else>
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <RouterLink
            v-for="card in cards"
            :key="card.row.id"
            :to="`${base}/p/${card.row.id}`"
            class="ui-card group flex min-w-0 flex-col gap-2.5 p-4 transition-[box-shadow,transform] duration-150 hover:-translate-y-px hover:shadow-raised"
          >
            <div class="flex items-start gap-3">
              <span class="grid size-10 shrink-0 place-items-center rounded-[11px] bg-surface-2 text-[20px] dark:bg-surface-3" aria-hidden="true">{{ card.row.emoji || "📄" }}</span>
              <div class="min-w-0 flex-1">
                <p v-if="card.parent" class="truncate text-[11px] font-semibold uppercase tracking-[0.05em] text-subtle">{{ t("knowledge.space.inside", { title: card.parent }) }}</p>
                <h3 class="line-clamp-2 text-base font-semibold leading-snug text-fg group-hover:text-accent-fg">{{ card.row.title }}</h3>
              </div>
            </div>
            <p class="line-clamp-2 min-h-[2.6em] text-sm text-muted">{{ card.row.excerpt || t("knowledge.page.emptyTitle") }}</p>
            <div class="mt-auto flex min-w-0 flex-wrap items-center gap-2 border-t border-line pt-2.5 text-xs text-muted">
              <StatusPill v-if="!card.row.published" size="sm" tone="neutral" :label="t('knowledge.draft')" />
              <StatusPill v-else-if="card.row.require_ack" size="sm" tone="primary" :dot="false" :label="t('knowledge.mustRead')" />
              <span class="min-w-0 truncate"><RelativeTime :value="card.row.updated_at" /><template v-if="card.row.updated_by"> · {{ card.row.updated_by.name }}</template></span>
              <ReadProgress v-if="canManage && card.row.require_ack && card.row.read" :read="card.row.read" compact class="ml-auto" />
            </div>
          </RouterLink>
        </div>
        <p v-if="canManage" class="mt-3 hidden text-xs text-subtle lg:block">{{ t("knowledge.space.dragHint") }}</p>
      </template>

      <SpaceDialog v-model:open="editing" :space="space" />
    </template>
  </div>
</template>
