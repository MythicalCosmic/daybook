<script setup lang="ts">
/**
 * Ko‘z › Cameras › Zones: the zone editor for one camera, full width so a finger has room on a
 * phone. Leaving with unsaved zones asks first. `vision.manage` only.
 */
import { Cctv } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { onBeforeRouteLeave, useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useConfirm } from "@/components/useConfirm";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";

import { useCameras } from "../api";
import ZoneEditor from "../components/ZoneEditor.vue";

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();

const id = computed(() => Number(route.params.cameraId));
const cameras = useCameras(null);
const camera = computed(() => (cameras.data.value ?? []).find((c) => c.id === id.value) ?? null);
usePageTitle(() => camera.value?.name);

const editor = ref<InstanceType<typeof ZoneEditor> | null>(null);
onBeforeRouteLeave(async () => {
  if (!editor.value?.dirty) return true;
  const answer = await confirm({ title: t("vision.zones.leaveTitle"), message: t("vision.zones.leaveBody"), confirmLabel: t("vision.zones.leave"), tone: "danger" });
  return !!answer;
});
const back = computed(() => `/c/${company.currentId}/vision/cameras`);
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader
      :title="camera ? `${t('vision.zones.title')} · ${camera.name}` : t('vision.zones.title')"
      :description="t('vision.zones.description')"
      :back="back"
      :back-label="t('vision.nav.cameras')"
      class="!mb-0"
    />
    <div v-if="cameras.isPending.value" class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <SkeletonBlock class="aspect-video" height="auto" radius="14px" />
      <SkeletonBlock height="260px" radius="12px" />
    </div>
    <ErrorState v-else-if="cameras.isError.value" class="ui-card" :error="cameras.error.value" :retry="() => cameras.refetch()" />
    <EmptyState v-else-if="!camera" class="ui-card py-12" :icon="Cctv" :title="t('vision.zones.notFound')" tone="neutral" />
    <ZoneEditor v-else ref="editor" :camera="camera" />
  </div>
</template>
