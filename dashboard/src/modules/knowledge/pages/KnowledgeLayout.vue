<script setup lang="ts">
/**
 * The reading side of the knowledge base: the spaces sidebar on the left (desktop) and the page,
 * space or home on the right. On phones the sidebar steps aside; each page carries its own way
 * around (search on the home, the tree on a space, breadcrumbs on a page).
 */
import { computed } from "vue";
import { RouterView, useRoute } from "vue-router";

import { useBreakpoints } from "@/lib/useBreakpoints";

import { usePage } from "../api";
import KbSidebar from "../components/KbSidebar.vue";

const route = useRoute();
const { isPhone } = useBreakpoints();

const pageId = computed(() => (route.params.pageId ? Number(route.params.pageId) : null));
const page = usePage(pageId);
const spaceId = computed(() => {
  if (route.params.spaceId) return Number(route.params.spaceId);
  return pageId.value !== null ? (page.data.value?.space.id ?? null) : null;
});
</script>

<template>
  <div class="lg:grid lg:grid-cols-[264px_minmax(0,1fr)] lg:gap-8">
    <aside v-if="!isPhone" class="hidden lg:block">
      <div class="sticky top-5 max-h-[calc(100dvh-var(--topbar-h)-40px)] overflow-y-auto pb-6 pr-1">
        <KbSidebar :current-space-id="spaceId" :current-page-id="pageId" />
      </div>
    </aside>
    <div class="min-w-0">
      <RouterView />
    </div>
  </div>
</template>
