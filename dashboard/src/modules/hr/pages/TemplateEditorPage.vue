<script setup lang="ts">
/**
 * One contract template (`hr/contract-templates/:id`, "new" for a new one): its name, kind and
 * language, the text with placeholder chips, and beside it the live preview: the text filled in for
 * a person picked here, exactly as the server prints the PDF. On a phone the text and the preview
 * are two tabs.
 */
import { useQuery } from "@tanstack/vue-query";
import { refDebounced } from "@vueuse/core";
import { ArrowLeft, Braces, EllipsisVertical, Eye, PencilLine, Save, Trash2, TriangleAlert, UserRound } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { onBeforeRouteLeave, RouterLink, useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import { qk } from "@/api/keys";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { hrApi, MODULE, useHrMutation, useTemplate } from "../api";
import TemplateBodyEditor from "../components/TemplateBodyEditor.vue";
import { unknownPlaceholders } from "../lib";
import { sanitizeContractHtml } from "../sanitize";
import { CONTRACT_KINDS, type ContractKind, type TemplateInput, type TemplateLanguage } from "../types";
import "../contract.css";

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const confirm = useConfirm();
const { isPhone } = useBreakpoints();

const param = computed(() => String(route.params.templateId ?? "new"));
const id = computed(() => (/^\d+$/.test(param.value) ? Number(param.value) : null));
const isNew = computed(() => id.value === null);
const query = useTemplate(id);
const base = computed(() => `/c/${company.currentId}/hr/contract-templates`);

const blank = (): TemplateInput => ({ name: "", kind: "indefinite", language: "uz", body: "", is_active: true });
const draft = reactive<TemplateInput>(blank());
const saved = ref<TemplateInput>(blank());
const errors = reactive<Record<string, string | undefined>>({});
usePageTitle(() => (isNew.value ? t("hr.template.new") : draft.name || saved.value.name || undefined));

watch(
  () => query.data.value,
  (value) => {
    if (!value) return;
    const next = { name: value.name, kind: value.kind, language: value.language, body: value.body, is_active: value.is_active };
    saved.value = { ...next };
    Object.assign(draft, next);
  },
  { immediate: true },
);
watch(isNew, (fresh) => {
  if (fresh) {
    saved.value = blank();
    Object.assign(draft, blank());
  }
});

const dirty = computed(() => (Object.keys(draft) as Array<keyof TemplateInput>).some((key) => draft[key] !== saved.value[key]));
const unknown = computed(() => unknownPlaceholders(draft.body));
/** "" (fits any contract) can't be a select value: the select says "any" for it. */
const kindOptions = computed(() => [{ value: "any" as const, label: t("hr.template.anyKind") }, ...CONTRACT_KINDS.map((kind) => ({ value: kind, label: t(`hr.contractKind.${kind}`) }))]);
const kindChoice = computed({
  get: () => draft.kind || "any",
  set: (value: ContractKind | "any") => (draft.kind = value === "any" ? "" : value),
});
const languageOptions = computed(() => (["uz", "ru", "en"] as TemplateLanguage[]).map((value) => ({ value, label: t(`hr.language.${value}`) })));

// Saving --------------------------------------------------------------------------------------
const save = useHrMutation((companyId, input: { id: number | null; body: TemplateInput }) =>
  input.id ? hrApi.updateTemplate(companyId, input.id, input.body) : hrApi.createTemplate(companyId, input.body),
);

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!draft.name.trim()) errors.name = t("hr.form.required");
  if (!draft.body.trim()) errors.body = t("hr.template.bodyRequired");
  if (errors.name || errors.body) return;
  try {
    const result = await save.mutateAsync({ id: id.value, body: { ...draft, name: draft.name.trim() } });
    saved.value = { name: result.name, kind: result.kind, language: result.language, body: result.body, is_active: result.is_active };
    Object.assign(draft, saved.value);
    toast.success(t("hr.template.saved"));
    if (isNew.value) void router.replace(`${base.value}/${result.id}`);
  } catch (failure) {
    if (isApiError(failure)) for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
  }
}

function discard(): void {
  Object.assign(draft, saved.value);
}

const remove = useHrMutation((companyId, templateId: number) => hrApi.removeTemplate(companyId, templateId));
async function runRemove(): Promise<void> {
  if (!id.value) return;
  const templateId = id.value;
  const answer = await confirm({
    title: t("hr.template.deleteTitle"),
    message: t("hr.template.deleteBody"),
    tone: "danger",
    confirmLabel: t("common.delete"),
    icon: Trash2,
    onConfirm: () => remove.mutateAsync(templateId),
  });
  if (answer) {
    saved.value = { ...draft };
    toast.success(t("hr.template.deleted"));
    void router.push(base.value);
  }
}
const menu = computed<MenuEntry[]>(() => (isNew.value ? [] : [{ label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void runRemove() }]));

// Leaving with unsaved text asks first.
onBeforeRouteLeave(async () => {
  if (!dirty.value) return true;
  const answer = await confirm({ title: t("hr.template.leaveTitle"), message: t("hr.template.leaveBody"), tone: "danger", confirmLabel: t("common.discard") });
  return !!answer;
});

// Preview ---------------------------------------------------------------------------------------
const pane = ref<"text" | "preview">("text");
const person = ref<number | null>(null);
const body = refDebounced(computed(() => draft.body), 600);
const preview = useQuery({
  queryKey: computed(() => qk(cid.value, MODULE, "preview", { id: id.value, member: person.value, body: body.value, language: draft.language })),
  // The text as it is in the editor, saved or not, in the template's language.
  queryFn: ({ signal }) => hrApi.previewTemplate(cid.value, id.value, { member_id: person.value, body: body.value, language: draft.language }, signal),
  enabled: computed(() => cid.value > 0 && !!person.value && !!body.value.trim()),
  placeholderData: (previous) => previous,
  staleTime: 60_000,
});
/** A placeholder's readable name ("Lavozim"), or the raw token for one the dictionary doesn't know. */
const placeholderName = (key: string) => (te(`hr.placeholder.${key}`) ? t(`hr.placeholder.${key}`) : `{{${key}}}`);
const previewHtml = computed(() => sanitizeContractHtml(preview.data.value?.html ?? ""));
const showText = computed(() => !isPhone.value || pane.value === "text");
const showPreview = computed(() => !isPhone.value || pane.value === "preview");
</script>

<template>
  <div class="flex flex-col gap-4 pb-16">
    <RouterLink :to="base" class="group -mb-1 -ml-1 inline-flex w-fit items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg">
      <ArrowLeft :size="15" class="transition-transform duration-150 group-hover:-translate-x-0.5" />{{ t("hr.nav.templates") }}
    </RouterLink>

    <div v-if="query.isPending.value && !isNew" class="flex flex-col gap-4">
      <SkeletonBlock height="44px" width="50%" />
      <SkeletonBlock height="420px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="isApiError(query.error.value) && query.error.value.status === 404 ? undefined : () => query.refetch()" />

    <template v-else>
      <section class="ui-card flex flex-col gap-4 p-4 md:p-5">
        <div class="flex items-start gap-2">
          <FormField :label="t('hr.template.name')" :error="errors.name" required class="min-w-0 flex-1">
            <TextInput v-model="draft.name" :maxlength="120" :placeholder="t('hr.template.namePlaceholder')" :invalid="!!errors.name" />
          </FormField>
          <DropdownMenu v-if="menu.length" :items="menu" align="end">
            <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" variant="secondary" class="mt-6" /></template>
          </DropdownMenu>
        </div>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <FormField :label="t('hr.field.contractKind')">
            <SelectBox v-model="kindChoice" :options="kindOptions" />
          </FormField>
          <FormField :label="t('hr.template.language')">
            <SelectBox v-model="draft.language" :options="languageOptions" />
          </FormField>
          <ToggleSwitch v-model="draft.is_active" :label="t('hr.template.activeLabel')" class="sm:pb-1.5" />
        </div>
      </section>

      <SegmentedControl
        v-if="isPhone"
        v-model="pane"
        block
        :options="[
          { value: 'text', label: t('hr.template.text'), icon: PencilLine },
          { value: 'preview', label: t('hr.template.preview'), icon: Eye },
        ]"
      />

      <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div v-show="showText" class="flex min-w-0 flex-col gap-2">
          <InlineAlert v-if="unknown.length" tone="warning" size="sm" :icon="TriangleAlert" :title="t('hr.template.unknownTitle')" :description="t('hr.template.unknownBody', { list: unknown.map((key) => `{{${key}}}`).join(', ') })" />
          <TemplateBodyEditor v-model="draft.body" :invalid="!!errors.body" />
          <p v-if="errors.body" class="text-sm text-danger">{{ errors.body }}</p>
        </div>

        <section v-show="showPreview" class="ui-card flex min-w-0 flex-col overflow-hidden xl:sticky xl:top-4 xl:max-h-[calc(100dvh-120px)]" :aria-label="t('hr.template.preview')">
          <header class="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <h2 class="flex items-center gap-1.5 text-sm font-semibold text-fg"><Eye :size="15" class="text-subtle" aria-hidden="true" />{{ t("hr.template.preview") }}</h2>
            <div class="min-w-[200px] flex-1">
              <PersonPicker v-model="person" size="sm" :placeholder="t('hr.template.previewFor')" />
            </div>
          </header>
          <div class="min-h-[320px] flex-1 overflow-y-auto bg-surface-2/50 p-3 sm:p-5">
            <EmptyState v-if="!person" size="sm" tone="neutral" :icon="UserRound" :title="t('hr.template.previewPick')" :description="t('hr.template.previewPickBody')" />
            <EmptyState v-else-if="!draft.body.trim()" size="sm" tone="neutral" :icon="Braces" :title="t('hr.template.previewEmpty')" />
            <div v-else-if="preview.isPending.value" class="hr-paper-sheet flex flex-col gap-3"><SkeletonBlock v-for="n in 8" :key="n" :width="n % 3 ? '100%' : '70%'" /></div>
            <ErrorState v-else-if="preview.isError.value" compact :error="preview.error.value" :retry="() => preview.refetch()" />
            <template v-else-if="preview.data.value">
              <InlineAlert v-if="preview.data.value.empty.length" tone="info" size="sm" class="mb-3" :description="t('hr.template.missing', { list: preview.data.value.empty.map(placeholderName).join(', ') })" />
              <!-- v-html is safe here: the server's rendering, sanitized again by sanitizeContractHtml. -->
              <article :class="['hr-paper hr-paper-sheet transition-opacity', preview.isFetching.value && 'opacity-70']" v-html="previewHtml" />
            </template>
          </div>
        </section>
      </div>
    </template>

    <StickyActionBar :show="dirty || isNew" :message="isNew ? t('hr.template.newUnsaved') : t('common.unsaved')" tone="warning">
      <UiButton v-if="!isNew" variant="ghost" @click="discard">{{ t("common.discard") }}</UiButton>
      <UiButton variant="primary" :icon="Save" :loading="save.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
    </StickyActionBar>
  </div>
</template>
