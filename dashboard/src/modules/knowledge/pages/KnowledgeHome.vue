<script setup lang="ts">
/**
 * Knowledge base home: what the shelves hold, which pages people still have to confirm (managers
 * can remind them in one click), the spaces, and what changed lately.
 */
import { BellRing, BookOpen, CircleCheckBig, FilePen, FilePlus2, FolderPlus, Layers, Library, Search, Settings, Users } from "@lucide/vue";
import { refDebounced } from "@vueuse/core";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, useOverview, usePages, useRefresh, useSpaces } from "../api";
import KnowledgeSettingsPanel from "../components/KnowledgeSettingsPanel.vue";
import PageListItem from "../components/PageListItem.vue";
import ReadProgress from "../components/ReadProgress.vue";
import SpaceDialog from "../components/SpaceDialog.vue";
import { audienceText } from "../lib";
import type { PageRow } from "../types";

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const { isPhone } = useBreakpoints();
const canManage = useCan("knowledge.manage");
const overview = useOverview();
const spaces = useSpaces();
const refresh = useRefresh();
const skeleton = useDelayedPending(computed(() => overview.isPending.value || spaces.isPending.value));
const creatingSpace = ref(false);
const settingsOpen = ref(false);
const reminding = ref<number | null>(null);
const base = computed(() => `/c/${company.currentId}/knowledge`);

// Phones have no sidebar: search lives here.
const query = ref("");
const debounced = refDebounced(query, 200);
const searching = computed(() => debounced.value.trim().length >= 2);
const results = usePages(computed(() => ({ q: searching.value ? debounced.value.trim() : undefined, page_size: 10 })));

const counts = computed(() => overview.data.value?.counts);
const kpis = computed(() => [
  { id: "spaces", label: t("knowledge.kpi.spaces"), value: counts.value?.spaces ?? null, icon: Layers },
  { id: "published", label: t("knowledge.kpi.published"), value: counts.value?.published ?? null, icon: BookOpen },
  ...(canManage.value ? [{ id: "drafts", label: t("knowledge.kpi.drafts"), value: counts.value?.drafts ?? null, icon: FilePen }] : []),
  { id: "ack", label: t("knowledge.kpi.mustRead"), value: counts.value?.require_ack ?? null, icon: CircleCheckBig, hint: t("knowledge.kpi.mustReadHint") },
]);

async function remind(page: PageRow): Promise<void> {
  reminding.value = page.id;
  try {
    const { reminded } = await knowledgeApi.remind(company.currentId ?? 0, page.id);
    toast.success(reminded ? t("knowledge.readers.reminded", { n: reminded }, reminded) : t("knowledge.readers.nobodyToRemind"));
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    reminding.value = null;
  }
}

useHotkey("n", () => canManage.value && void router.push(`${base.value}/new`), { description: "knowledge.hotkey.newPage", group: "page" });
</script>

<template>
  <div>
    <PageHeader :title="t('knowledge.title')" :description="t('knowledge.description')">
      <template v-if="canManage" #actions>
        <IconButton :icon="Settings" :label="t('knowledge.settings.title')" variant="ghost" @click="settingsOpen = true" />
        <UiButton :icon="FolderPlus" @click="creatingSpace = true">{{ t("knowledge.space.newTitle") }}</UiButton>
        <UiButton variant="primary" :icon="FilePlus2" :to="`${base}/new`" kbd="N">{{ t("knowledge.newPage") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="isPhone" class="mb-5">
      <TextInput v-model="query" type="search" :icon="Search" :placeholder="t('knowledge.sidebar.search')" clearable size="lg" />
      <div v-if="searching" class="ui-card mt-2 p-1.5">
        <p v-if="results.data.value && !results.data.value.results.length" class="px-2 py-3 text-sm text-muted">{{ t("knowledge.sidebar.noResults") }}</p>
        <PageListItem v-for="page in results.data.value?.results ?? []" :key="page.id" :page="page" show-excerpt />
      </div>
    </div>

    <ErrorState v-if="overview.isError.value" :error="overview.error.value" :retry="() => overview.refetch()" />

    <template v-else-if="skeleton">
      <SkeletonBlock height="92px" radius="12px" />
      <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <SkeletonBlock v-for="n in 3" :key="n" height="148px" radius="12px" />
      </div>
    </template>

    <EmptyState
      v-else-if="spaces.data.value && !spaces.data.value.length"
      size="lg"
      :icon="Library"
      :title="t('knowledge.empty.title')"
      :description="canManage ? t('knowledge.empty.body') : t('knowledge.empty.reader')"
    >
      <UiButton v-if="canManage" variant="primary" :icon="FolderPlus" @click="creatingSpace = true">{{ t("knowledge.space.create") }}</UiButton>
    </EmptyState>

    <div v-else-if="overview.data.value" class="flex flex-col gap-6">
      <KpiStrip :items="kpis" />

      <section v-if="canManage && overview.data.value.attention.length" class="ui-card p-1.5" :aria-label="t('knowledge.attention.title')">
        <header class="flex flex-wrap items-center gap-2 px-3 pb-1 pt-3">
          <h2 class="text-md font-semibold text-fg">{{ t("knowledge.attention.title") }}</h2>
          <UiBadge :count="overview.data.value.attention.length" tone="warning" />
          <p class="basis-full text-sm text-muted">{{ t("knowledge.attention.body") }}</p>
        </header>
        <ul>
          <li v-for="page in overview.data.value.attention" :key="page.id" class="flex items-center gap-2">
            <PageListItem :page="page" class="min-w-0 flex-1" />
            <ReadProgress :read="page.read" compact class="hidden md:flex" />
            <UiButton size="sm" variant="ghost" :icon="BellRing" :loading="reminding === page.id" class="mr-2 shrink-0" @click="remind(page)">
              <span class="hidden sm:inline">{{ t("knowledge.readers.remind") }}</span>
            </UiButton>
          </li>
        </ul>
      </section>

      <section v-if="overview.data.value.to_read.length" class="ui-card p-1.5" :aria-label="t('knowledge.toRead.title')">
        <header class="px-3 pb-1 pt-3">
          <h2 class="text-md font-semibold text-fg">{{ t("knowledge.toRead.title") }}</h2>
          <p class="text-sm text-muted">{{ t("knowledge.toRead.body") }}</p>
        </header>
        <PageListItem v-for="page in overview.data.value.to_read" :key="page.id" :page="page" />
      </section>

      <section :aria-label="t('knowledge.sidebar.spaces')">
        <h2 class="mb-3 text-md font-semibold text-fg">{{ t("knowledge.sidebar.spaces") }}</h2>
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <RouterLink
            v-for="space in spaces.data.value ?? []"
            :key="space.id"
            :to="`${base}/s/${space.id}`"
            class="ui-card group flex min-w-0 flex-col gap-3 p-4 transition-[box-shadow,transform] duration-150 hover:-translate-y-px hover:shadow-raised"
          >
            <div class="flex items-start gap-3">
              <span class="grid size-11 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-[22px]" aria-hidden="true">{{ space.icon || "📁" }}</span>
              <div class="min-w-0 flex-1">
                <h3 class="truncate text-md font-semibold text-fg group-hover:text-accent-fg">{{ space.name }}</h3>
                <p class="line-clamp-2 min-h-[2.5em] text-sm text-muted">{{ space.description || t("knowledge.space.noDescription") }}</p>
              </div>
            </div>
            <div class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-3 text-xs text-muted">
              <span class="inline-flex items-center gap-1 font-semibold text-fg"><BookOpen :size="13" class="text-subtle" />{{ t("knowledge.pagesCount", { n: space.counts.pages }, space.counts.pages) }}</span>
              <span class="inline-flex min-w-0 items-center gap-1"><Users :size="13" class="shrink-0 text-subtle" /><span class="truncate">{{ audienceText(space, t("knowledge.space.everyone")) }}</span></span>
              <UiBadge v-if="canManage && space.counts.drafts" tone="neutral" variant="outline">{{ t("knowledge.draftsCount", { n: space.counts.drafts }, space.counts.drafts) }}</UiBadge>
            </div>
          </RouterLink>
        </div>
      </section>

      <section v-if="overview.data.value.recent.length" class="ui-card p-1.5" :aria-label="t('knowledge.recent.title')">
        <h2 class="px-3 pb-1 pt-3 text-md font-semibold text-fg">{{ t("knowledge.recent.title") }}</h2>
        <PageListItem v-for="page in overview.data.value.recent" :key="page.id" :page="page" :show-read="canManage" />
      </section>
    </div>

    <SpaceDialog v-model:open="creatingSpace" />
    <UiDialog v-model:open="settingsOpen" :title="t('knowledge.settings.title')" :description="t('knowledge.settings.description')">
      <KnowledgeSettingsPanel />
    </UiDialog>
  </div>
</template>
