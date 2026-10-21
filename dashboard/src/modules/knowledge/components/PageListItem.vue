<script setup lang="ts">
/** A page in a list: emoji, title, its space and when it changed; read progress for managers. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import RelativeTime from "@/components/RelativeTime.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useCompanyStore } from "@/stores/company";

import type { PageRow } from "../types";
import ReadProgress from "./ReadProgress.vue";

const props = withDefaults(defineProps<{ page: PageRow; showRead?: boolean; showExcerpt?: boolean }>(), { showRead: false, showExcerpt: false });
const { t } = useI18n();
const company = useCompanyStore();
const to = computed(() => `/c/${company.currentId}/knowledge/p/${props.page.id}`);
</script>

<template>
  <RouterLink :to="to" class="group flex min-w-0 items-center gap-3 rounded-[10px] px-2.5 py-2.5 transition-colors hover:bg-highlight">
    <span class="grid size-9 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-[18px] dark:bg-surface-3" aria-hidden="true">{{ page.emoji || "📄" }}</span>
    <span class="min-w-0 flex-1">
      <span class="flex min-w-0 items-center gap-2">
        <span class="truncate text-base font-semibold text-fg group-hover:text-accent-fg">{{ page.title }}</span>
        <StatusPill v-if="!page.published" size="sm" tone="neutral" :label="t('knowledge.draft')" />
        <StatusPill v-else-if="page.require_ack" size="sm" tone="primary" :dot="false" :label="t('knowledge.mustRead')" />
      </span>
      <span class="mt-0.5 block truncate text-xs text-muted">
        {{ page.space.icon }} {{ page.space.name }}
        <template v-if="showExcerpt && page.excerpt"> · {{ page.excerpt }}</template>
        <template v-else>
          · <RelativeTime :value="page.updated_at" /><template v-if="page.updated_by"> · {{ page.updated_by.name }}</template>
        </template>
      </span>
    </span>
    <ReadProgress v-if="showRead && page.require_ack && page.read" :read="page.read" compact class="hidden sm:flex" />
    <slot name="end" />
  </RouterLink>
</template>
