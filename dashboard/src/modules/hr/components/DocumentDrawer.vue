<script setup lang="ts">
/**
 * One document in a side panel synced with `?document=`: whose and what, its dates and state, the
 * file itself (an image inline, a PDF in the viewer; an ID scan stays locked without hr.sensitive),
 * and, for hr.manage, verify, change or delete it.
 */
import { CircleCheck, EllipsisVertical, Eye, ExternalLink, FileText, LockKeyhole, Pencil, ShieldCheck, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PdfPreview from "@/components/PdfPreview.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { closeQueryKey } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { hrApi, useDocument, useHrMutation } from "../api";
import { DOCUMENT_STATE_TONES, documentState, hrAccess, needsSensitive } from "../lib";
import type { HrDocument } from "../types";
import DaysChip from "./DaysChip.vue";

const props = withDefaults(defineProps<{ warnDays?: number }>(), { warnDays: 30 });
const emit = defineEmits<{ edit: [document: HrDocument] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const id = computed(() => {
  const raw = route.query.document;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useDocument(id);
const doc = computed(() => query.data.value ?? null);
const state = computed(() => (doc.value ? (doc.value.state ?? documentState(doc.value.expires_on, today.value, props.warnDays)) : null));
const locked = computed(() => !!doc.value && (doc.value.file_hidden || (!doc.value.file && needsSensitive(doc.value.kind) && !access.value.sensitive)));
// The file opens only when asked: every opening is audited on the server, so the drawer never
// fetches it by itself.
const showFile = ref(false);
watch(id, () => (showFile.value = false));

const items = computed<DescriptionItem[]>(() => {
  const d = doc.value;
  if (!d) return [];
  return [
    { key: "kind", label: t("hr.field.kind"), value: t(`hr.kind.${d.kind}`) },
    { key: "number", label: t("hr.field.number"), value: d.number || null, mono: true },
    { key: "issued", label: t("hr.field.issuedOn"), value: d.issued_on ? fmt.day(d.issued_on, "long") : null },
    { key: "expires", label: t("hr.field.expiresOn"), value: d.expires_on ? fmt.day(d.expires_on, "long") : t("hr.document.noExpiry") },
    ...(d.issuer ? [{ key: "issuer", label: t("hr.field.issuer"), value: d.issuer, wide: true }] : []),
    { key: "uploaded", label: t("hr.document.uploadedBy"), value: d.uploaded_by ? `${d.uploaded_by} · ${fmt.day(d.created_at.slice(0, 10), "medium")}` : fmt.day(d.created_at.slice(0, 10), "medium") },
    { key: "visible", label: t("hr.document.visibleShort"), value: d.visible_to_employee ? t("common.yes") : t("common.no") },
  ];
});

const verify = useHrMutation((cid, docId: number) => hrApi.verifyDocument(cid, docId));
async function runVerify(): Promise<void> {
  const d = doc.value;
  if (!d) return;
  try {
    await verify.mutateAsync(d.id);
    toast.success(t("hr.document.verifiedToast", { name: d.member.name }));
  } catch {
    // The HTTP layer showed why.
  }
}

const remove = useHrMutation((cid, docId: number) => hrApi.removeDocument(cid, docId));
async function runRemove(): Promise<void> {
  const d = doc.value;
  if (!d) return;
  const answer = await confirm({
    title: t("hr.document.deleteTitle"),
    message: t("hr.document.deleteBody", { name: d.member.name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
    icon: Trash2,
    onConfirm: () => remove.mutateAsync(d.id),
  });
  if (answer) {
    toast.success(t("hr.document.deleted"));
    closeQueryKey(router, "document");
  }
}

const menu = computed<MenuEntry[]>(() => {
  const d = doc.value;
  if (!d || !access.value.manage) return [];
  return [
    { label: t("common.edit"), icon: Pencil, onSelect: () => emit("edit", d) },
    { type: "separator" },
    { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void runRemove() },
  ];
});
</script>

<template>
  <UiDrawer query-key="document" size="lg" :title="doc ? doc.title || t(`hr.kind.${doc.kind}`) : t('hr.document.one')">
    <template #header-actions>
      <DropdownMenu v-if="menu.length" :items="menu" align="end">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="56px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="16px" />
        <SkeletonBlock height="240px" radius="12px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="doc" class="flex flex-col gap-5">
        <header class="flex items-start gap-3">
          <RouterLink :to="`/c/${company.currentId}/people/${doc.member.id}`" class="shrink-0" :aria-label="doc.member.name">
            <UserAvatar :name="doc.member.name" :src="doc.member.photo_url" :size="44" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${company.currentId}/people/${doc.member.id}`" class="block truncate text-base font-semibold text-fg hover:text-primary hover:underline">{{ doc.member.name }}</RouterLink>
            <p v-if="doc.position" class="truncate text-sm text-muted">{{ doc.position }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill v-if="state && state !== 'no_expiry'" :tone="DOCUMENT_STATE_TONES[state]" size="sm" :label="t(`hr.documentState.${state}`)" />
              <DaysChip v-if="doc.expires_on" :day="doc.expires_on" :warn-days="warnDays" prefix="expires" />
              <StatusPill v-if="doc.verified" tone="success" size="sm" :icon="CircleCheck" :dot="false" :label="t('hr.document.verified')" />
              <StatusPill v-else tone="neutral" size="sm" :label="t('hr.document.notVerified')" />
            </div>
          </div>
        </header>

        <InlineAlert
          v-if="!doc.verified && access.manage && !locked"
          tone="info"
          size="sm"
          :icon="ShieldCheck"
          :title="t('hr.document.verifyTitle')"
          :description="t('hr.document.verifyBody')"
        >
          <template #actions>
            <UiButton size="sm" variant="primary" :icon="ShieldCheck" :loading="verify.isPending.value" @click="runVerify">{{ t("hr.document.verify") }}</UiButton>
          </template>
        </InlineAlert>
        <p v-else-if="doc.verified && doc.verified_at" class="text-sm text-muted">
          {{ doc.verified_by ? t("hr.document.verifiedBy", { name: doc.verified_by, date: fmt.day(doc.verified_at.slice(0, 10), "medium") }) : t("hr.document.verifiedOn", { date: fmt.day(doc.verified_at.slice(0, 10), "medium") }) }}
        </p>

        <DescriptionList :items="items" :columns="2" />

        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("hr.field.file") }}</h3>
          <div v-if="locked" class="flex items-center gap-3 rounded-card border border-dashed border-line-strong px-4 py-5 text-sm text-muted" data-file-locked>
            <LockKeyhole :size="18" class="shrink-0 text-subtle" aria-hidden="true" />{{ t("hr.document.fileHidden") }}
          </div>
          <p v-else-if="!doc.file" class="rounded-card border border-dashed border-line-strong px-4 py-5 text-sm text-muted">{{ t("hr.document.noFile") }}</p>
          <PdfPreview v-else-if="showFile" :src="doc.file" :title="doc.title || t(`hr.kind.${doc.kind}`)" height="min(60vh, 720px)" />
          <div v-else class="flex flex-wrap items-center gap-3 rounded-card border border-line px-4 py-3" data-file-card>
            <span class="grid size-10 shrink-0 place-items-center rounded-[10px] bg-surface-2 text-muted" aria-hidden="true"><FileText :size="19" /></span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-semibold text-fg">{{ doc.title || t(`hr.kind.${doc.kind}`) }}</p>
              <p class="text-xs text-muted">{{ t("hr.document.openAudited") }}</p>
            </div>
            <div class="flex shrink-0 items-center gap-1.5">
              <UiButton :href="doc.file" target="_blank" variant="ghost" :icon="ExternalLink">{{ t("common.pdf.open") }}</UiButton>
              <UiButton :icon="Eye" @click="showFile = true">{{ t("hr.document.showHere") }}</UiButton>
            </div>
          </div>
        </section>
      </div>
    </div>
  </UiDrawer>
</template>
