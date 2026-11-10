<script setup lang="ts">
/**
 * Writing a policy (`hr/policies/new`, `hr/policies/:policyId/edit`): its title and category, the
 * text in the knowledge base's editor and an optional file (the signed order, a scan), and beside
 * them who it applies to (positions, branches, with the live count) and whether and how soon people
 * sign. "Save draft" keeps the next version as a draft (the who-and-how settings apply at once);
 * "Publish" makes it the version in force, asking everyone again or keeping the signatures.
 */
import { ArrowLeft, EllipsisVertical, FileText, Lock, Paperclip, Save, Send, Trash2, Users, X } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { onBeforeRouteLeave, RouterLink, useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import AvatarStack from "@/components/AvatarStack.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StickyActionBar from "@/components/StickyActionBar.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { useRefresh } from "../api";
import { policyApi, useAudience, usePolicy, usePolicyVersion } from "../policies/api";
import { CATEGORY_ICONS } from "../policies/lib";
import PolicyTextField from "../policies/PolicyTextField.vue";
import PublishDialog from "../policies/PublishDialog.vue";
import { POLICY_CATEGORIES, type PolicyCategory, type PolicyDetail } from "../policies/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();

// A new policy gets its id when first saved; the page stays (and its address follows).
const createdId = ref<number | null>(null);
const routeId = computed(() => (/^\d+$/.test(String(route.params.policyId ?? "")) ? Number(route.params.policyId) : null));
const id = computed(() => routeId.value ?? createdId.value);
const isNew = computed(() => id.value === null);
const query = usePolicy(id);
const policy = computed<PolicyDetail | null>(() => query.data.value ?? null);
const base = computed(() => `/c/${company.currentId}/hr/policies`);
const back = computed(() => (id.value ? `${base.value}/${id.value}` : base.value));

// The text starts from the draft, or from the version in force for a new draft.
const textNumber = computed(() => policy.value?.draft?.number ?? policy.value?.version?.number ?? null);
const text = usePolicyVersion(id, textNumber);

interface Settings {
  title: string;
  category: PolicyCategory;
  position_ids: number[];
  branch_ids: number[];
  requires_ack: boolean;
  ack_within_days: number;
}
const blankSettings = (): Settings => ({ title: "", category: "dispensing", position_ids: [], branch_ids: [], requires_ack: true, ack_within_days: 7 });
const copy = (value: Settings): Settings => ({ ...value, position_ids: [...value.position_ids], branch_ids: [...value.branch_ids] });
const settings = reactive<Settings>(blankSettings());
const savedSettings = ref<Settings>(blankSettings());
const body = ref("");
const savedBody = ref("");
const note = ref("");
const savedNote = ref("");
const files = ref<File[]>([]);
const removeFile = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
usePageTitle(() => (isNew.value ? t("hr.policy.new") : settings.title || policy.value?.title || undefined));

const settingsDirty = computed(() => JSON.stringify(settings) !== JSON.stringify(savedSettings.value));
const textDirty = computed(() => body.value !== savedBody.value || note.value !== savedNote.value || files.value.length > 0 || removeFile.value);
const dirty = computed(() => settingsDirty.value || textDirty.value);

watch(
  policy,
  (row) => {
    if (!row) return;
    const next: Settings = {
      title: row.title,
      category: row.category,
      position_ids: row.positions.map((item) => item.id),
      branch_ids: row.branches.map((item) => item.id),
      requires_ack: row.requires_ack,
      ack_within_days: row.ack_within_days,
    };
    // A refetch while editing keeps what the person typed.
    if (!settingsDirty.value) Object.assign(settings, copy(next));
    savedSettings.value = next;
  },
  { immediate: true },
);

// The editor tidies a freshly loaded text once (whitespace, an empty last paragraph): that first
// change is the baseline, not an edit.
let adoptUntil = 0;
watch(
  () => text.data.value,
  (version) => {
    if (!version || textDirty.value) return;
    const continuing = !!policy.value?.draft;
    body.value = savedBody.value = version.body;
    note.value = savedNote.value = continuing ? version.change_note : "";
    adoptUntil = Date.now() + 1500;
  },
  { immediate: true },
);
watch(body, (value) => {
  if (Date.now() < adoptUntil && value !== savedBody.value) {
    savedBody.value = value;
    adoptUntil = 0;
  }
});

const hasFile = computed(() => !removeFile.value && (files.value.length > 0 || !!text.data.value?.has_file));
const published = computed(() => !!policy.value?.version);
const nextNumber = computed(() => policy.value?.draft?.number ?? (policy.value?.versions.reduce((top, row) => Math.max(top, row.number), 0) ?? 0) + 1);
const canPublish = computed(() => isNew.value || dirty.value || !!policy.value?.draft);
// Only opening an existing policy waits for it: one saved here for the first time keeps the form.
const loading = computed(() => routeId.value !== null && (query.isPending.value || (!!textNumber.value && text.isPending.value)));

// Who it applies to, live ------------------------------------------------------------------------
const audienceParams = computed(() => ({ position: [...settings.position_ids], branch: [...settings.branch_ids] }));
const audience = useAudience(audienceParams);
const audienceCount = computed(() => audience.data.value?.count ?? 0);
const categoryOptions = computed(() => POLICY_CATEGORIES.map((value) => ({ value, label: t(`hr.policy.category.${value}`), icon: CATEGORY_ICONS[value] })));

// Saving -----------------------------------------------------------------------------------------
const saving = ref(false);

function validate(forPublish: boolean): boolean {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!settings.title.trim()) errors.title = t("hr.form.required");
  const empty = !body.value.replace(/<[^>]*>/g, "").trim() && !hasFile.value;
  if (forPublish && empty) errors.body = t("hr.policy.textRequired");
  return !errors.title && !errors.body;
}

/** Saves what changed; answers the policy's id (a new policy's too), or null when it failed. */
async function persist(): Promise<number | null> {
  saving.value = true;
  try {
    let policyId = id.value;
    if (policyId === null) {
      const created = await policyApi.create(cid.value, { ...copy(settings), title: settings.title.trim(), body: body.value, change_note: note.value.trim() });
      policyId = created.id;
      if (files.value[0]) await policyApi.saveDraft(cid.value, policyId, { file: files.value[0] });
      createdId.value = policyId;
    } else {
      if (settingsDirty.value) await policyApi.update(cid.value, policyId, { ...copy(settings), title: settings.title.trim() });
      if (textDirty.value) {
        await policyApi.saveDraft(cid.value, policyId, { body: body.value, change_note: note.value.trim(), file: files.value[0] ?? null, remove_file: removeFile.value && !files.value.length });
      }
    }
    savedSettings.value = copy(settings);
    savedBody.value = body.value;
    savedNote.value = note.value;
    files.value = [];
    removeFile.value = false;
    refresh();
    return policyId;
  } catch (failure) {
    if (isApiError(failure)) for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
    return null;
  } finally {
    saving.value = false;
  }
}

/** The address of a policy saved for the first time (the page itself stays). */
function followAddress(): void {
  if (routeId.value === null && createdId.value !== null) void router.replace(`${base.value}/${createdId.value}/edit`);
}

async function saveDraft(): Promise<void> {
  if (!validate(false)) return;
  if ((await persist()) === null) return;
  toast.success(t("hr.policy.saved"));
  followAddress();
}

// Publishing -------------------------------------------------------------------------------------
const publishing = ref(false);
const publishOpen = ref(false);
let leaving = false;

async function startPublish(): Promise<void> {
  if (!validate(true)) return;
  if ((dirty.value || isNew.value) && (await persist()) === null) return;
  publishOpen.value = true;
}

// Closed without publishing: a new policy's address follows its first save.
watch(publishOpen, (open) => {
  if (!open && !leaving) followAddress();
});

async function publish(input: { asks_again: boolean; change_note: string }): Promise<void> {
  const policyId = id.value;
  if (policyId === null) return;
  publishing.value = true;
  try {
    const result = await policyApi.publish(cid.value, policyId, published.value ? input : { asks_again: true });
    leaving = true;
    publishOpen.value = false;
    refresh();
    const number = result.version?.number ?? 1;
    const asked = result.tally?.total ?? 0;
    toast.success(result.requires_ack && (input.asks_again || !published.value) ? t("hr.policy.publishedAsked", { n: number, asked }) : t("hr.policy.publishedToast", { n: number }));
    void router.push(`${base.value}/${policyId}`);
  } catch {
    // The HTTP layer said why.
  } finally {
    publishing.value = false;
  }
}

// Discarding the draft ---------------------------------------------------------------------------
async function discardDraft(): Promise<void> {
  const row = policy.value;
  if (!row?.draft || !row.version) return;
  const answer = await confirm({
    title: t("hr.policy.discardTitle", { n: row.draft.number }),
    message: t("hr.policy.discardBody", { n: row.version.number }),
    tone: "danger",
    confirmLabel: t("hr.policy.discardDraft"),
    icon: Trash2,
    onConfirm: () => policyApi.discardDraft(cid.value, row.id),
  });
  if (!answer) return;
  refresh();
  toast.success(t("hr.policy.discarded"));
  leaving = true;
  void router.push(`${base.value}/${row.id}`);
}

const menu = computed<MenuEntry[]>(() => (policy.value?.draft && policy.value.version ? [{ label: t("hr.policy.discardDraft"), icon: Trash2, danger: true, onSelect: () => void discardDraft() }] : []));

function pickFile(chosen: File[]): void {
  files.value = chosen.slice(0, 1);
  if (chosen.length) removeFile.value = false;
}

// Leaving with unsaved changes asks first.
onBeforeRouteLeave(async () => {
  if (leaving || !dirty.value) return true;
  const answer = await confirm({ title: t("hr.policy.leaveTitle"), message: t("hr.policy.leaveBody"), tone: "danger", confirmLabel: t("common.discard") });
  return !!answer;
});

const barMessage = computed(() => {
  if (isNew.value) return t("hr.policy.newUnsaved");
  if (dirty.value) return t("common.unsaved");
  if (policy.value?.draft) return t("hr.policy.draftNotPublished", { n: policy.value.draft.number });
  return "";
});
</script>

<template>
  <div class="flex flex-col gap-4 pb-16">
    <RouterLink :to="back" class="group -mb-1 -ml-1 inline-flex w-fit items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg">
      <ArrowLeft :size="15" class="transition-transform duration-150 group-hover:-translate-x-0.5" />{{ id && policy ? policy.title : t("hr.nav.policies") }}
    </RouterLink>

    <div v-if="loading" class="flex flex-col gap-4" aria-hidden="true">
      <SkeletonBlock height="56px" width="60%" />
      <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]"><SkeletonBlock height="480px" radius="12px" /><SkeletonBlock height="360px" radius="12px" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="isApiError(query.error.value) && query.error.value.status === 404 ? undefined : () => query.refetch()" />
    <div v-else-if="policy && !policy.can_change" class="ui-card">
      <EmptyState :icon="Lock" :title="t('hr.policy.cantChange')" :description="t('hr.policy.cantChangeBody')">
        <UiButton :to="back">{{ t("common.back") }}</UiButton>
      </EmptyState>
    </div>

    <template v-else>
      <section class="ui-card flex flex-col gap-4 p-4 md:p-5">
        <div class="flex items-start gap-2">
          <FormField :label="t('hr.policy.field.title')" :error="errors.title" required class="min-w-0 flex-1">
            <TextInput v-model="settings.title" :maxlength="150" :placeholder="t('hr.policy.titlePlaceholder')" :invalid="!!errors.title" size="lg" data-policy-title />
          </FormField>
          <DropdownMenu v-if="menu.length" :items="menu" align="end">
            <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" variant="secondary" class="mt-6" /></template>
          </DropdownMenu>
        </div>
        <FormField :label="t('hr.policy.field.category')" class="max-w-[320px]">
          <SelectBox v-model="settings.category" :options="categoryOptions" />
        </FormField>
      </section>

      <div class="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div class="flex min-w-0 flex-col gap-2">
          <PolicyTextField v-model="body" :placeholder="t('hr.policy.textPlaceholder')" :invalid="!!errors.body" />
          <p v-if="errors.body" class="text-sm text-danger">{{ errors.body }}</p>
        </div>

        <aside class="flex min-w-0 flex-col gap-4 xl:sticky xl:top-4">
          <section class="ui-card flex flex-col gap-4 p-4" data-policy-audience>
            <h2 class="flex items-center gap-2 text-sm font-semibold text-fg"><Users :size="15" class="text-subtle" aria-hidden="true" />{{ t("hr.policy.section.audience") }}</h2>
            <FormField :label="t('hr.policy.field.positions')">
              <PositionPicker v-model="settings.position_ids" multiple :placeholder="t('hr.policy.everyPosition')" />
            </FormField>
            <FormField :label="t('hr.policy.field.branches')">
              <BranchPicker v-model="settings.branch_ids" multiple :placeholder="t('hr.policy.everyBranch')" />
            </FormField>
            <div class="flex items-center gap-3 rounded-[10px] bg-surface-2 px-3 py-2.5 dark:bg-surface-3" aria-live="polite" data-policy-audience-count>
              <AvatarStack v-if="audience.data.value?.people.length" :people="audience.data.value.people" :max="5" :size="26" />
              <p class="min-w-0 flex-1 text-sm text-fg">
                <template v-if="audience.isPending.value">{{ t("common.loading") }}</template>
                <template v-else-if="audienceCount">{{ t("hr.policy.audienceCount", { n: audienceCount }, audienceCount) }}</template>
                <template v-else>{{ t("hr.policy.audienceNone") }}</template>
              </p>
            </div>
            <p class="text-xs text-subtle">{{ t("hr.policy.ownersNote") }}</p>
          </section>

          <section class="ui-card flex flex-col gap-4 p-4">
            <h2 class="text-sm font-semibold text-fg">{{ t("hr.policy.section.signature") }}</h2>
            <ToggleSwitch v-model="settings.requires_ack" :label="t('hr.policy.field.requiresAck')" :description="settings.requires_ack ? undefined : t('hr.policy.toReadHint')" />
            <FormField v-if="settings.requires_ack" :label="t('hr.policy.field.days')" :hint="t('hr.policy.daysHint')">
              <NumberInput v-model="settings.ack_within_days" :min="1" :max="90" :suffix="t('hr.policy.daysSuffix')" steppers class="max-w-[180px]" />
            </FormField>
            <InlineAlert v-if="published && settingsDirty" tone="info" size="sm" :description="t('hr.policy.settingsApply')" />
          </section>

          <section class="ui-card flex flex-col gap-3 p-4">
            <h2 class="flex items-center gap-2 text-sm font-semibold text-fg"><Paperclip :size="15" class="text-subtle" aria-hidden="true" />{{ t("hr.policy.section.file") }}</h2>
            <div v-if="files.length" class="flex items-center gap-2 rounded-[10px] border border-line px-3 py-2">
              <FileText :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
              <p class="min-w-0 flex-1 truncate text-sm text-fg">{{ t("hr.policy.fileNew", { name: files[0]!.name }) }}</p>
              <IconButton :icon="X" :label="t('common.file.remove')" size="sm" @click="files = []" />
            </div>
            <div v-else-if="text.data.value?.has_file && !removeFile" class="flex items-center gap-2 rounded-[10px] border border-line px-3 py-2">
              <FileText :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
              <a v-if="text.data.value.file_url" :href="text.data.value.file_url" target="_blank" rel="noopener" class="min-w-0 flex-1 truncate text-sm font-medium text-fg hover:text-primary">{{ t(`hr.policy.fileType.${text.data.value.file_type ?? "pdf"}`) }}</a>
              <IconButton :icon="X" :label="t('common.file.remove')" size="sm" @click="removeFile = true" />
            </div>
            <FileDrop v-else :model-value="files" accept="application/pdf,image/*" :max-size="20 * 1024 * 1024" compact :hint="t('hr.policy.fileHint')" @update:model-value="pickFile" />
            <UiButton v-if="removeFile" size="sm" variant="ghost" class="self-start" @click="removeFile = false">{{ t("common.undo") }}</UiButton>
          </section>

          <section v-if="published" class="ui-card flex flex-col gap-3 p-4">
            <FormField :label="t('hr.policy.field.changeNote')" :hint="t('hr.policy.changeNoteHint')">
              <TextArea v-model="note" :rows="2" :max-rows="5" :maxlength="300" :placeholder="t('hr.policy.changeNotePlaceholder')" />
            </FormField>
          </section>
        </aside>
      </div>

      <StickyActionBar :show="isNew || dirty || !!policy?.draft" :message="barMessage" :tone="dirty || isNew ? 'warning' : 'neutral'">
        <UiButton variant="secondary" :icon="Save" :loading="saving && !publishOpen" :disabled="!dirty && !isNew" data-save-draft @click="saveDraft">{{ t("hr.policy.saveDraft") }}</UiButton>
        <UiButton variant="primary" :icon="Send" :disabled="!canPublish" :loading="saving && publishOpen" data-publish @click="startPublish">{{ t("hr.policy.publish") }}</UiButton>
      </StickyActionBar>

      <PublishDialog
        v-model:open="publishOpen"
        :number="nextNumber"
        :republish="published"
        :requires-ack="settings.requires_ack"
        :days="settings.ack_within_days"
        :audience="audienceCount"
        :change-note="note"
        :busy="publishing"
        @confirm="publish"
      />
    </template>
  </div>
</template>
