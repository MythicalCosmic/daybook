<script setup lang="ts">
/**
 * Overview widget "Pages to confirm" (managers of the knowledge base): the published pages people
 * must read with the fewest readers so far, and how far each one is.
 */
import { ArrowRight, BookOpen } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useOverview } from "../api";
import ReadProgress from "../components/ReadProgress.vue";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const overview = useOverview();
const skeleton = useDelayedPending(computed(() => overview.isPending.value));
const pages = computed(() => (overview.data.value?.attention ?? []).slice(0, 4));
const base = computed(() => `/c/${props.companyId}/knowledge`);
</script>

<template>
  <section class="ui-card flex h-full min-w-0 flex-col" :aria-label="t('knowledge.widget.title')">
    <header class="flex items-center gap-2 px-4 pb-2 pt-4">
      <BookOpen :size="16" class="text-subtle" aria-hidden="true" />
      <h3 class="text-sm font-semibold text-fg">{{ t("knowledge.widget.title") }}</h3>
      <span class="flex-1" />
      <RouterLink :to="base" class="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-sm font-semibold text-muted hover:bg-highlight hover:text-fg">
        {{ t("common.viewAll") }}<ArrowRight :size="14" />
      </RouterLink>
    </header>
    <div class="min-h-0 flex-1 px-2 pb-3">
      <div v-if="skeleton" class="flex flex-col gap-3 p-2"><SkeletonBlock v-for="n in 3" :key="n" height="36px" radius="8px" /></div>
      <ErrorState v-else-if="overview.isError.value" compact :error="overview.error.value" :retry="() => overview.refetch()" class="m-2" />
      <EmptyState v-else-if="overview.data.value && !pages.length" size="sm" tone="success" :title="t('knowledge.widget.empty')" :description="t('knowledge.widget.emptyBody')" />
      <ul v-else class="flex flex-col">
        <li v-for="page in pages" :key="page.id">
          <RouterLink :to="`${base}/p/${page.id}`" class="flex flex-col gap-1.5 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
            <span class="flex min-w-0 items-center gap-2">
              <span aria-hidden="true">{{ page.emoji || "📄" }}</span>
              <span class="truncate text-sm font-semibold text-fg">{{ page.title }}</span>
            </span>
            <ReadProgress :read="page.read" />
          </RouterLink>
        </li>
      </ul>
    </div>
  </section>
</template>
