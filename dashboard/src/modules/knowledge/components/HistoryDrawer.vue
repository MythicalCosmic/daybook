<script setup lang="ts">
/**
 * Version history (?history=1): every save that changed the page, newest first, with who saved it
 * and the note they left. Picking one previews it; "Restore" saves it again as the newest version.
 */
import { ArrowLeft, History, RotateCcw } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { knowledgeApi, usePutPage, useRefresh, useVersion, useVersions } from "../api";
import type { PageDetail } from "../types";
import PageBody from "./PageBody.vue";

const props = defineProps<{ page: PageDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const putPage = usePutPage();

const open = computed(() => route.query.history !== undefined);
const versions = useVersions(computed(() => props.page.id), open);
const picked = ref<number | null>(null);
const preview = useVersion(computed(() => props.page.id), picked);
const restoring = ref(false);

watch(open, (isOpen) => {
  if (!isOpen) picked.value = null;
});

async function restore(version: number): Promise<void> {
  const answer = await confirm({
    title: t("knowledge.history.restoreTitle", { v: version }),
    message: t("knowledge.history.restoreBody"),
    confirmLabel: t("knowledge.history.restore"),
  });
  if (!answer) return;
  restoring.value = true;
  try {
    const page = await knowledgeApi.restoreVersion(company.currentId ?? 0, props.page.id, version);
    putPage(page);
    void refresh();
    picked.value = null;
    toast.success(t("knowledge.history.restored", { v: version }));
  } catch {
    // Shown by the HTTP layer.
  } finally {
    restoring.value = false;
  }
}
</script>

<template>
  <UiDrawer query-key="history" :title="t('knowledge.history.title')" :description="page.title" :size="picked ? 'xl' : 'md'">
    <div v-if="picked" class="flex flex-col gap-4 p-5">
      <div class="flex flex-wrap items-center gap-2">
        <UiButton size="sm" variant="ghost" :icon="ArrowLeft" @click="picked = null">{{ t("knowledge.history.all") }}</UiButton>
        <span class="flex-1" />
        <UiButton v-if="preview.data.value && !preview.data.value.current" size="sm" variant="primary" :icon="RotateCcw" :loading="restoring" @click="restore(picked)">
          {{ t("knowledge.history.restore") }}
        </UiButton>
      </div>
      <ErrorState v-if="preview.isError.value" compact :error="preview.error.value" :retry="() => preview.refetch()" />
      <div v-else-if="!preview.data.value" class="flex flex-col gap-3"><SkeletonBlock width="50%" height="24px" /><SkeletonBlock :lines="6" /></div>
      <template v-else>
        <div class="rounded-[12px] border border-line bg-surface-2/50 px-4 py-3 dark:bg-surface-2">
          <p class="text-sm font-semibold text-fg">{{ t("knowledge.history.versionN", { v: preview.data.value.version }) }} · {{ fmt.instant(preview.data.value.created_at, "datetime") }}</p>
          <p class="text-sm text-muted">{{ preview.data.value.created_by?.name ?? t("common.audit.system") }}<template v-if="preview.data.value.note"> · “{{ preview.data.value.note }}”</template></p>
        </div>
        <h2 class="text-xl font-semibold text-fg">{{ preview.data.value.emoji }} {{ preview.data.value.title }}</h2>
        <PageBody :html="preview.data.value.body" />
      </template>
    </div>

    <div v-else class="flex flex-col p-4">
      <ErrorState v-if="versions.isError.value" compact :error="versions.error.value" :retry="() => versions.refetch()" />
      <div v-else-if="!versions.data.value" class="flex flex-col gap-3"><SkeletonBlock v-for="n in 4" :key="n" height="52px" radius="10px" /></div>
      <ol v-else class="relative flex flex-col">
        <li v-for="(version, index) in versions.data.value" :key="version.version" class="relative flex gap-3 pb-1">
          <span class="relative flex w-8 shrink-0 justify-center" aria-hidden="true">
            <span v-if="index < versions.data.value.length - 1" class="absolute top-8 bottom-0 w-px bg-line" />
            <UserAvatar :name="version.created_by?.name ?? '?'" :src="version.created_by?.photo_url" :size="28" class="relative mt-2" />
          </span>
          <button type="button" class="mb-1 flex min-w-0 flex-1 flex-col rounded-[10px] px-3 py-2 text-left transition-colors hover:bg-highlight" @click="picked = version.version">
            <span class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-semibold text-fg">{{ t("knowledge.history.versionN", { v: version.version }) }}</span>
              <StatusPill v-if="version.current" size="sm" tone="success" :label="t('knowledge.history.current')" />
              <span v-if="version.version === page.ack_version && page.require_ack" class="inline-flex items-center gap-1 text-xs text-muted"><History :size="12" />{{ t("knowledge.history.mustReadFrom") }}</span>
            </span>
            <span class="truncate text-sm text-muted">{{ version.note || version.title }}</span>
            <span class="text-xs text-subtle">{{ version.created_by?.name ?? t("common.audit.system") }} · <RelativeTime :value="version.created_at" /></span>
          </button>
        </li>
      </ol>
    </div>
  </UiDrawer>
</template>
