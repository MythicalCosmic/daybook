<script setup lang="ts">
/**
 * The knowledge base's left column: search across pages ("/" focuses it), then every space with
 * its page tree. The space of the page on screen opens by itself.
 */
import { FileSearch, FolderPlus, Search } from "@lucide/vue";
import { refDebounced } from "@vueuse/core";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import IconButton from "@/components/IconButton.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import { useHotkey } from "@/core/hotkeys";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCan } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";

import { usePages, useSpaces } from "../api";
import { displayTitle } from "../lib";
import SpaceDialog from "./SpaceDialog.vue";
import SpaceTreeSection from "./SpaceTreeSection.vue";

const props = defineProps<{ currentSpaceId: number | null; currentPageId: number | null }>();

const { t } = useI18n();
const company = useCompanyStore();
const canManage = useCan("knowledge.manage");
const spaces = useSpaces();
const skeleton = useDelayedPending(computed(() => spaces.isPending.value));
const creating = ref(false);

const query = ref("");
const debounced = refDebounced(query, 180);
const searching = computed(() => debounced.value.trim().length >= 2);
const results = usePages(computed(() => ({ q: searching.value ? debounced.value.trim() : undefined, page_size: 12 })));
const base = computed(() => `/c/${company.currentId}/knowledge`);

const expanded = ref<number[]>([]);
watch(
  () => props.currentSpaceId,
  (id) => {
    if (id !== null && !expanded.value.includes(id)) expanded.value = [...expanded.value, id];
  },
  { immediate: true },
);
// With a few spaces, open them all: there is nothing to hide.
watch(
  () => spaces.data.value,
  (list) => {
    if (list && list.length <= 4 && expanded.value.length <= 1) expanded.value = Array.from(new Set([...expanded.value, ...list.map((space) => space.id)]));
  },
  { immediate: true },
);

function toggle(id: number): void {
  expanded.value = expanded.value.includes(id) ? expanded.value.filter((item) => item !== id) : [...expanded.value, id];
}

const searchInput = ref<InstanceType<typeof TextInput> | null>(null);
useHotkey(
  "/",
  () => {
    const input = (searchInput.value?.$el as HTMLElement | undefined)?.querySelector("input");
    input?.focus();
  },
  { description: "knowledge.hotkey.search", group: "page" },
);
</script>

<template>
  <nav class="flex min-h-0 flex-col gap-3" :aria-label="t('knowledge.sidebar.label')">
    <TextInput ref="searchInput" v-model="query" enterkeyhint="search" :icon="Search" :placeholder="t('knowledge.sidebar.search')" clearable :aria-label="t('knowledge.sidebar.search')" />

    <div v-if="searching" class="flex flex-col gap-0.5">
      <p class="px-2 pb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("knowledge.sidebar.results") }}</p>
      <div v-if="results.isFetching.value && !results.data.value" class="flex flex-col gap-2 px-2" aria-hidden="true">
        <SkeletonBlock v-for="n in 3" :key="n" height="28px" radius="7px" />
      </div>
      <p v-else-if="!(results.data.value?.results.length)" class="flex items-center gap-2 px-2 py-3 text-sm text-muted">
        <FileSearch :size="15" class="shrink-0" />{{ t("knowledge.sidebar.noResults") }}
      </p>
      <RouterLink
        v-for="page in results.data.value?.results ?? []"
        :key="page.id"
        :to="`${base}/p/${page.id}`"
        class="flex flex-col rounded-[8px] px-2 py-1.5 hover:bg-highlight"
        active-class="bg-accent-soft"
      >
        <span class="truncate text-sm font-semibold text-fg">{{ displayTitle(page) }}</span>
        <span class="truncate text-xs text-muted">{{ page.space.icon }} {{ page.space.name }} · {{ page.excerpt }}</span>
      </RouterLink>
    </div>

    <template v-else>
      <div class="flex items-center gap-1 px-2">
        <span class="flex-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("knowledge.sidebar.spaces") }}</span>
        <IconButton v-if="canManage" :icon="FolderPlus" :label="t('knowledge.space.newTitle')" size="sm" @click="creating = true" />
      </div>
      <div v-if="skeleton" class="flex flex-col gap-2 px-1" aria-hidden="true">
        <SkeletonBlock v-for="n in 4" :key="n" height="28px" radius="8px" />
      </div>
      <div v-else class="flex flex-col gap-0.5">
        <SpaceTreeSection
          v-for="space in spaces.data.value ?? []"
          :key="space.id"
          :space="space"
          :expanded="expanded.includes(space.id)"
          :active="space.id === currentSpaceId && currentPageId === null"
          :current-page-id="space.id === currentSpaceId ? currentPageId : null"
          @toggle="toggle(space.id)"
        />
      </div>
    </template>
    <SpaceDialog v-model:open="creating" />
  </nav>
</template>
