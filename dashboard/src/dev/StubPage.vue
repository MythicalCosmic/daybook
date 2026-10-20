<script setup lang="ts">
/** A placeholder page for a module that hasn't landed: real header, skeleton body, the owner package. */
import { Hammer } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { findModule } from "@/core/modules";

const props = defineProps<{ pkg: string }>();

const { t } = useI18n();
const route = useRoute();
const module = computed(() => findModule(route.meta.module));
const title = computed(() => (route.meta.title ? t(route.meta.title) : module.value ? t(module.value.title) : ""));
</script>

<template>
  <div>
    <PageHeader :title="title">
      <template #meta>
        <StatusPill tone="warning" :label="t('dev.stub.badge')" size="sm" />
      </template>
    </PageHeader>
    <div class="grid gap-4 md:grid-cols-3">
      <div v-for="n in 3" :key="n" class="flex flex-col gap-3 rounded-card border border-line bg-surface p-4">
        <SkeletonBlock width="40%" height="12px" />
        <SkeletonBlock width="70%" height="22px" />
        <SkeletonBlock height="36px" radius="8px" />
      </div>
    </div>
    <div class="mt-4 rounded-card border border-dashed border-line-strong bg-surface">
      <EmptyState :icon="Hammer" tone="neutral" :title="t('dev.stub.title', { pkg: props.pkg })" :description="t('dev.stub.body')" />
    </div>
  </div>
</template>
