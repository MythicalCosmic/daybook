<script setup lang="ts">
/**
 * Overview widget "Pages to confirm" (managers of the knowledge base): the published pages people
 * must read with the fewest readers so far, and how far each one is. Two columns when the
 * Overview gives it a whole row.
 */
import { BookOpen } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import WidgetCard from "@/components/WidgetCard.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useOverview } from "../api";
import ReadProgress from "../components/ReadProgress.vue";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const overview = useOverview();
const skeleton = useDelayedPending(computed(() => overview.isPending.value));
const pages = computed(() => (overview.data.value?.attention ?? []).slice(0, 6));
const base = computed(() => `/c/${props.companyId}/knowledge`);
</script>

<template>
  <WidgetCard :title="t('knowledge.widget.title')" :icon="BookOpen" :count="overview.data.value?.attention?.length ?? null" count-tone="neutral" :to="base">
    <div v-if="skeleton" class="flex flex-col gap-3 p-2"><SkeletonBlock v-for="n in 3" :key="n" height="36px" radius="8px" /></div>
    <ErrorState v-else-if="overview.isError.value" compact :error="overview.error.value" :retry="() => overview.refetch()" class="m-2" />
    <EmptyState v-else-if="overview.data.value && !pages.length" class="my-auto" size="sm" tone="success" :title="t('knowledge.widget.empty')" :description="t('knowledge.widget.emptyBody')" />
    <ul v-else class="grid gap-x-4 @2xl:grid-cols-2">
      <li v-for="page in pages" :key="page.id">
        <RouterLink :to="`${base}/p/${page.id}`" class="flex flex-col gap-1.5 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight">
          <span class="flex min-w-0 items-center gap-2">
            <span aria-hidden="true">{{ page.emoji || "📄" }}</span>
            <span class="truncate text-sm font-semibold text-fg" :title="page.title">{{ page.title }}</span>
          </span>
          <ReadProgress :read="page.read" />
        </RouterLink>
      </li>
    </ul>
  </WidgetCard>
</template>
