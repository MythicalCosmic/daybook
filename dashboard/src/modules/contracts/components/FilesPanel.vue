<script setup lang="ts">
/**
 * A contract's papers: the signed contract first, then its annexes and the rest. A PDF opens in
 * the page (PdfPreview in a drawer), a picture in the lightbox. People who manage contracts add
 * files (PDF or pictures, up to 20 MB, what each one is picked first) and remove them. Links are
 * signed for ten minutes; the page refetches before they expire.
 */
import { FileImage, FileText, Trash2, Upload } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import FileDrop from "@/components/FileDrop.vue";
import IconButton from "@/components/IconButton.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import PageSection from "@/components/PageSection.vue";
import PdfPreview from "@/components/PdfPreview.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { formatFileSize } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { contractsApi, useRefresh } from "../api";
import type { ContractDetail, ContractFile, ContractFileKind } from "../types";

const props = defineProps<{ contract: ContractDetail }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const files = computed(() => props.contract.file_list);
const pictures = computed(() => files.value.filter((file) => !file.is_pdf));
const canManage = computed(() => props.contract.can.manage);

const viewing = ref<ContractFile | null>(null);
const pdfOpen = computed({ get: () => viewing.value !== null, set: (value: boolean) => !value && (viewing.value = null) });
const lightbox = ref(false);
const lightboxIndex = ref(0);

function name(file: ContractFile): string {
  return file.label || t(`contracts.fileKind.${file.kind}`);
}

function open(file: ContractFile): void {
  if (file.is_pdf) {
    viewing.value = file;
    return;
  }
  lightboxIndex.value = Math.max(0, pictures.value.findIndex((row) => row.id === file.id));
  lightbox.value = true;
}

const adding = ref<File[]>([]);
const addKind = ref<ContractFileKind>(props.contract.file_list.some((file) => file.kind === "signed") ? "annex" : "signed");
const uploading = ref(false);
const kinds = computed(() => (["signed", "annex", "other"] as ContractFileKind[]).map((value) => ({ value, label: t(`contracts.fileKind.${value}`) })));

async function upload(chosen: File[]): Promise<void> {
  if (!chosen.length) return;
  uploading.value = true;
  try {
    for (const file of chosen) await contractsApi.upload(company.currentId ?? 0, props.contract.id, file, addKind.value);
    toast.success(t("contracts.files.added", { n: chosen.length }, chosen.length));
    addKind.value = "annex";
    refresh();
  } catch {
    // The HTTP layer shows why.
  } finally {
    adding.value = [];
    uploading.value = false;
  }
}

async function remove(file: ContractFile): Promise<void> {
  const answer = await confirm({
    title: t("contracts.files.removeTitle", { name: name(file) }),
    confirmLabel: t("contracts.files.remove"),
    tone: "danger",
    onConfirm: () => contractsApi.removeFile(company.currentId ?? 0, file.id),
  });
  if (answer) {
    toast.success(t("contracts.files.removed"));
    refresh();
  }
}
</script>

<template>
  <PageSection variant="card" :title="t('contracts.files.title')" :count="files.length || undefined" flush>
    <ul v-if="files.length" class="divide-y divide-line" data-testid="contract-files">
      <li v-for="file in files" :key="file.id" class="group flex items-center gap-3 px-4 py-2.5">
        <button type="button" class="flex min-w-0 flex-1 items-center gap-3 text-left" @click="open(file)">
          <span class="grid size-9 shrink-0 place-items-center rounded-[9px]" :class="file.is_pdf ? 'bg-danger-soft text-danger' : 'bg-info-soft text-info'">
            <component :is="file.is_pdf ? FileText : FileImage" :size="17" aria-hidden="true" />
          </span>
          <span class="min-w-0">
            <span class="block truncate text-sm font-medium text-fg group-hover:underline">{{ name(file) }}</span>
            <span class="block truncate text-xs text-muted">
              {{ file.label ? `${t(`contracts.fileKind.${file.kind}`)} · ` : "" }}{{ formatFileSize(file.size, fmt.lang.value) }} · {{ fmt.instant(file.created_at, "date") }}
            </span>
          </span>
        </button>
        <IconButton v-if="canManage" :icon="Trash2" size="sm" variant="ghost" :label="t('contracts.files.remove')" @click="remove(file)" />
      </li>
    </ul>
    <div v-else-if="!canManage" class="px-4 py-6">
      <EmptyState :icon="FileText" :title="t('contracts.files.emptyTitle')" size="sm" />
    </div>

    <div v-if="canManage" class="flex flex-col gap-2.5 border-t border-line px-4 py-3" :class="!files.length && 'border-t-0'">
      <SegmentedControl v-model="addKind" :options="kinds" size="sm" block />
      <FileDrop
        v-model="adding"
        accept="application/pdf,image/*"
        multiple
        compact
        :max-files="10"
        :max-size="20 * 1024 * 1024"
        :disabled="uploading"
        :title="t('contracts.files.drop')"
        :hint="t('contracts.files.hint')"
        @update:model-value="upload"
      />
      <p v-if="uploading" class="flex items-center gap-1.5 text-xs text-muted"><Upload :size="13" aria-hidden="true" />{{ t("contracts.files.uploading") }}</p>
    </div>

    <UiDrawer v-model:open="pdfOpen" :title="viewing ? name(viewing) : ''" size="xl">
      <PdfPreview v-if="viewing" :src="viewing.url" :title="name(viewing)" :filename="`${contract.title} - ${name(viewing)}.pdf`" />
    </UiDrawer>
    <ImageLightbox v-model:open="lightbox" v-model:index="lightboxIndex" :images="pictures.map((file) => ({ src: file.url, alt: name(file) }))" :title="contract.title" />
  </PageSection>
</template>
