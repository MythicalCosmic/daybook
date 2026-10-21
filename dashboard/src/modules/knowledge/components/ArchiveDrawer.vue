<script setup lang="ts">
/**
 * The knowledge base archive (?archive=1, managers): spaces and pages that were archived, newest
 * first, each with "Restore". Nothing in the knowledge base is ever deleted, so this is where an
 * archived how-to comes back from. A page archived with its parent shows under the parent only.
 */
import { Archive, ArchiveRestore, FileText, Folder } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePages, useRefresh, useSpaces } from "../api";
import type { PageRow, Space } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const refresh = useRefresh();

const open = computed(() => route.query.archive !== undefined);
// Asked for only while the drawer is open.
const spaces = useSpaces(true, open);
const pages = usePages({ status: "archived", ordering: "-archived_at", page_size: 100 }, open);
const restoring = ref<string | null>(null);

const archivedSpaces = computed(() =>
  (spaces.data.value ?? []).filter((space) => space.archived).sort((a, b) => (b.archived_at ?? "").localeCompare(a.archived_at ?? "")),
);
const archivedPages = computed(() => {
  const rows = pages.data.value?.results ?? [];
  const ids = new Set(rows.map((row) => row.id));
  // Pages archived with the page above them come back with it.
  return rows.filter((row) => !row.parent_id || !ids.has(row.parent_id));
});
const loading = computed(() => open.value && (spaces.isPending.value || pages.isPending.value));
const failed = computed(() => spaces.isError.value || pages.isError.value);
const empty = computed(() => !archivedSpaces.value.length && !archivedPages.value.length);

function when(value: string | null | undefined): string {
  return value ? t("knowledge.archive.archivedOn", { date: fmt.instant(value, "date") }) : t("knowledge.archived");
}

async function restoreSpace(space: Space): Promise<void> {
  restoring.value = `s${space.id}`;
  try {
    await knowledgeApi.restoreSpace(company.currentId ?? 0, space.id);
    toast.success(t("knowledge.archive.spaceRestored", { name: space.name }));
    await refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    restoring.value = null;
  }
}

async function restorePage(page: PageRow): Promise<void> {
  restoring.value = `p${page.id}`;
  try {
    await knowledgeApi.restore(company.currentId ?? 0, page.id);
    toast.success(t("knowledge.page.restored"), { description: page.title });
    await refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    restoring.value = null;
  }
}
</script>

<template>
  <UiDrawer query-key="archive" :title="t('knowledge.archive.title')" :description="t('knowledge.archive.description')" size="md">
    <div class="flex flex-col gap-6 p-5">
      <ErrorState v-if="failed" compact :error="spaces.error.value ?? pages.error.value" :retry="() => (spaces.refetch(), pages.refetch())" />
      <div v-else-if="loading" class="flex flex-col gap-2">
        <SkeletonBlock width="30%" height="14px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="52px" radius="10px" />
      </div>
      <EmptyState v-else-if="empty" size="sm" :icon="Archive" :title="t('knowledge.archive.emptyTitle')" :description="t('knowledge.archive.emptyBody')" />
      <template v-else>
        <section v-if="archivedSpaces.length" :aria-label="t('knowledge.archive.spaces')">
          <h3 class="mb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("knowledge.archive.spaces") }}</h3>
          <ul class="flex flex-col">
            <li v-for="space in archivedSpaces" :key="space.id" class="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
              <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-[18px]" aria-hidden="true">
                <template v-if="space.icon">{{ space.icon }}</template><Folder v-else :size="16" class="text-subtle" />
              </span>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-semibold text-fg">{{ space.name }}</p>
                <p class="truncate text-xs text-muted">{{ t("knowledge.pagesCount", { n: space.counts.pages }, space.counts.pages) }} · {{ when(space.archived_at) }}</p>
              </div>
              <UiButton size="sm" :icon="ArchiveRestore" :loading="restoring === `s${space.id}`" @click="restoreSpace(space)">{{ t("knowledge.archive.restore") }}</UiButton>
            </li>
          </ul>
        </section>
        <section v-if="archivedPages.length" :aria-label="t('knowledge.archive.pages')">
          <h3 class="mb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("knowledge.archive.pages") }}</h3>
          <ul class="flex flex-col">
            <li v-for="page in archivedPages" :key="page.id" class="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
              <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-[18px]" aria-hidden="true">
                <template v-if="page.emoji">{{ page.emoji }}</template><FileText v-else :size="16" class="text-subtle" />
              </span>
              <div class="min-w-0 flex-1">
                <RouterLink :to="`/c/${company.currentId}/knowledge/p/${page.id}`" class="block truncate text-sm font-semibold text-fg hover:text-accent-fg">{{ page.title }}</RouterLink>
                <p class="truncate text-xs text-muted">{{ `${page.space.icon} ${page.space.name}`.trim() }} · {{ when(page.archived_at) }}</p>
              </div>
              <UiButton size="sm" :icon="ArchiveRestore" :loading="restoring === `p${page.id}`" @click="restorePage(page)">{{ t("knowledge.archive.restore") }}</UiButton>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </UiDrawer>
</template>
