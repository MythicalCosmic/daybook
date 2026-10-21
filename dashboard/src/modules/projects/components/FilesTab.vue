<script setup lang="ts">
/**
 * Files and links: drop PDFs, spreadsheets and photos (checked and stored privately; downloads use
 * short signed links), and keep the project's links (Figma, Drive, the contractor's chat) in one
 * place.
 */
import { ExternalLink, FileSpreadsheet, FileText, Image, Link2, Paperclip, Plus, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FileDrop from "@/components/FileDrop.vue";
import IconButton from "@/components/IconButton.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";

import { addLink, deleteFile, deleteLink, uploadFile, useCompanyId, useFiles, useLinks, useRefreshProjects } from "../api";
import type { ProjectDetail, ProjectFile, ProjectLink } from "../types";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const confirm = useConfirm();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const files = useFiles(() => props.project.id);
const links = useLinks(() => props.project.id);
const canAdd = computed(() => props.project.capabilities.edit_cards);

const dropped = ref<File[]>([]);
const uploading = ref(false);
const linkTitle = ref("");
const linkUrl = ref("");
const linkError = ref<string | null>(null);

async function upload(list: File[]): Promise<void> {
  if (!list.length) return;
  uploading.value = true;
  try {
    for (const file of list) {
      await uploadFile(companyId.value, props.project.id, file);
    }
    toast.success(t("projects.files.uploaded", { n: list.length }));
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    uploading.value = false;
    dropped.value = [];
  }
}

async function removeFile(file: ProjectFile): Promise<void> {
  const answer = await confirm({ title: t("projects.files.deleteTitle", { name: file.name }), tone: "danger", confirmLabel: t("common.delete") });
  if (!answer) return;
  await deleteFile(companyId.value, props.project.id, file.id);
  void refresh();
}

async function saveLink(): Promise<void> {
  linkError.value = null;
  if (!/^https?:\/\//i.test(linkUrl.value.trim())) {
    linkError.value = t("projects.files.linkInvalid");
    return;
  }
  await addLink(companyId.value, props.project.id, { title: linkTitle.value.trim(), url: linkUrl.value.trim() });
  linkTitle.value = "";
  linkUrl.value = "";
  void refresh();
}

async function removeLink(link: ProjectLink): Promise<void> {
  await deleteLink(companyId.value, props.project.id, link.id);
  void refresh();
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const ICONS = { pdf: FileText, xlsx: FileSpreadsheet, csv: FileSpreadsheet, image: Image } as const;
const host = (url: string) => {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
};
</script>

<template>
  <div class="grid gap-4 lg:grid-cols-[3fr_2fr]">
    <section class="flex min-w-0 flex-col gap-3">
      <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Paperclip :size="15" />{{ t("projects.files.title") }}</h3>
      <FileDrop
        v-if="canAdd"
        v-model="dropped"
        multiple
        accept=".pdf,.xlsx,.csv,image/*"
        :max-size="20 * 1024 * 1024"
        :title="uploading ? t('projects.files.uploading') : t('projects.files.drop')"
        :hint="t('projects.files.dropHint')"
        :disabled="uploading"
        compact
        @update:model-value="upload"
      />
      <div v-if="files.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="56px" radius="10px" /></div>
      <ErrorState v-else-if="files.isError.value" compact :error="files.error.value" :retry="() => files.refetch()" />
      <EmptyState v-else-if="!(files.data.value ?? []).length" size="sm" tone="neutral" :icon="Paperclip" :title="t('projects.files.emptyTitle')" :description="t('projects.files.emptyBody')" />
      <ul v-else class="ui-card divide-y divide-line overflow-hidden">
        <li v-for="file in files.data.value" :key="file.id" class="flex items-center gap-3 px-4 py-3">
          <a v-if="file.kind === 'image'" :href="file.url" target="_blank" rel="noopener" class="block size-11 shrink-0 overflow-hidden rounded-[9px] border border-line bg-surface-2">
            <img :src="file.url" alt="" loading="lazy" class="size-full object-cover" />
          </a>
          <span v-else class="grid size-11 shrink-0 place-items-center rounded-[9px]" :class="file.kind === 'pdf' ? 'bg-danger-soft text-danger' : 'bg-success-soft text-success'">
            <component :is="ICONS[file.kind] ?? FileText" :size="18" />
          </span>
          <div class="min-w-0 flex-1">
            <a :href="file.url" target="_blank" rel="noopener" class="block truncate text-sm font-semibold text-fg hover:text-primary hover:underline">{{ file.name }}</a>
            <p class="truncate text-xs text-muted">{{ size(file.size) }} · {{ file.uploaded_by?.name ?? "—" }} · <RelativeTime :value="file.created_at" /></p>
          </div>
          <IconButton v-if="file.can_delete" :icon="Trash2" :label="t('common.delete')" size="sm" @click="removeFile(file)" />
        </li>
      </ul>
    </section>

    <section class="flex min-w-0 flex-col gap-3">
      <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Link2 :size="15" />{{ t("projects.files.links") }}</h3>
      <form v-if="canAdd" class="ui-card flex flex-col gap-2 p-3" @submit.prevent="saveLink">
        <TextInput v-model="linkUrl" type="url" size="sm" placeholder="https://" :invalid="!!linkError" />
        <div class="flex gap-2">
          <TextInput v-model="linkTitle" size="sm" :placeholder="t('projects.files.linkTitle')" class="flex-1" />
          <UiButton type="submit" size="sm" variant="secondary" :icon="Plus" :disabled="!linkUrl.trim()">{{ t("projects.files.addLink") }}</UiButton>
        </div>
        <p v-if="linkError" class="text-xs text-danger">{{ linkError }}</p>
      </form>
      <div v-if="links.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="48px" radius="10px" /></div>
      <EmptyState v-else-if="!(links.data.value ?? []).length" size="sm" tone="neutral" :icon="Link2" :title="t('projects.files.noLinks')" :description="t('projects.files.noLinksBody')" />
      <ul v-else class="ui-card divide-y divide-line overflow-hidden">
        <li v-for="link in links.data.value" :key="link.id" class="flex items-center gap-3 px-4 py-2.5">
          <span class="grid size-8 shrink-0 place-items-center rounded-[8px] bg-surface-2 text-muted"><Link2 :size="15" /></span>
          <div class="min-w-0 flex-1">
            <a :href="link.url" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1 truncate text-sm font-semibold text-fg hover:text-primary">{{ link.title }}<ExternalLink :size="12" class="shrink-0 text-subtle" /></a>
            <p class="truncate text-xs text-muted">{{ host(link.url) }} · {{ link.added_by?.name ?? "—" }}</p>
          </div>
          <IconButton v-if="link.can_delete" :icon="Trash2" :label="t('common.delete')" size="sm" @click="removeLink(link)" />
        </li>
      </ul>
    </section>
  </div>
</template>
