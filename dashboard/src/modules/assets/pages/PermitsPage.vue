<script setup lang="ts">
/**
 * Licences and permits (Litsenziyalar va ruxsatnomalar): what the business must keep valid,
 * expired first, then those ending within their warning days, then the rest, each with its
 * branch, number, issuer, days left and the scan. The owner bot warns from the warning days
 * ahead, a week before and when it has expired.
 */
import { FileCheck2, FileWarning, Pencil, Plus, ScrollText, Trash2, Upload } from "@lucide/vue";
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { assetsApi, usePermits, useRefresh } from "../api";
import type { Permit, PermitKind } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const permits = usePermits();
const canManage = computed(() => company.can("assets.manage"));

const KINDS: PermitKind[] = ["pharmacy_licence", "controlled_licence", "lease", "fire_safety", "sanitary", "cash_register", "insurance", "other"];

const groups = computed(() => {
  const rows = permits.data.value ?? [];
  const expired = rows.filter((row) => row.days_left !== null && row.days_left < 0);
  const soon = rows.filter((row) => row.days_left !== null && row.days_left >= 0 && row.days_left <= row.remind_days);
  const fine = rows.filter((row) => row.days_left === null || row.days_left > row.remind_days);
  return [
    { id: "expired", rows: expired },
    { id: "soon", rows: soon },
    { id: "valid", rows: fine },
  ].filter((group) => group.rows.length);
});

function tone(row: Permit): "danger" | "warning" | "success" | "neutral" {
  if (row.days_left === null) return "neutral";
  if (row.days_left < 0) return "danger";
  if (row.days_left <= Math.min(row.remind_days, 30)) return "warning";
  return "success";
}

function left(row: Permit): string {
  if (row.days_left === null || !row.valid_until) return t("assets.permits.noEnd");
  if (row.days_left < 0) return t("assets.permits.expiredOn", { day: fmt.day(row.valid_until, "medium") });
  return t("assets.permits.until", { day: fmt.day(row.valid_until, "medium"), n: row.days_left });
}

// The form ---------------------------------------------------------------------------------------

const open = ref(false);
const editing = ref<Permit | null>(null);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({
  kind: "pharmacy_licence" as PermitKind,
  name: "",
  number: "",
  issuer: "",
  issued_on: null as string | null,
  valid_until: null as string | null,
  remind_days: 60,
  branch: null as number | null,
  responsible: null as number | null,
  notes: "",
});

function edit(row: Permit | null): void {
  editing.value = row;
  for (const key of Object.keys(errors)) delete errors[key];
  Object.assign(form, {
    kind: row?.kind ?? "pharmacy_licence",
    name: row?.name ?? "",
    number: row?.number ?? "",
    issuer: row?.issuer ?? "",
    issued_on: row?.issued_on ?? null,
    valid_until: row?.valid_until ?? null,
    remind_days: row?.remind_days ?? 60,
    branch: row?.branch ?? null,
    responsible: row?.responsible ?? null,
    notes: row?.notes ?? "",
  });
  open.value = true;
}

const kindOptions = computed(() => KINDS.map((value) => ({ value, label: t(`assets.permitKind.${value}`) })));

function pickKind(value: PermitKind | null): void {
  const before = form.kind;
  form.kind = value ?? "other";
  // A name that only repeated the kind follows it.
  if (!form.name || form.name === t(`assets.permitKind.${before}`)) form.name = form.kind === "other" ? "" : t(`assets.permitKind.${form.kind}`);
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.name.trim()) {
    errors.name = t("assets.form.errName");
    return;
  }
  saving.value = true;
  const cid = company.currentId ?? 0;
  const input = { ...form, name: form.name.trim() };
  try {
    if (editing.value) await assetsApi.updatePermit(cid, editing.value.id, input);
    else await assetsApi.createPermit(cid, input);
    toast.success(t("assets.permits.saved"));
    refresh();
    open.value = false;
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    saving.value = false;
  }
}

async function remove(row: Permit): Promise<void> {
  const answer = await confirm({
    title: t("assets.permits.deleteTitle", { name: row.name }),
    confirmLabel: t("assets.item.delete"),
    tone: "danger",
    onConfirm: () => assetsApi.deletePermit(company.currentId ?? 0, row.id),
  });
  if (answer) {
    toast.success(t("assets.item.deleted"));
    refresh();
  }
}

const fileInput = ref<HTMLInputElement | null>(null);
const uploadFor = ref<Permit | null>(null);
function pickFile(row: Permit): void {
  uploadFor.value = row;
  fileInput.value?.click();
}
async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !uploadFor.value) return;
  await assetsApi.uploadPermit(company.currentId ?? 0, uploadFor.value.id, file);
  toast.success(t("assets.item.uploaded"));
  refresh();
}
</script>

<template>
  <div>
    <PageHeader :title="t('assets.nav.permits')" :description="t('assets.permits.description')">
      <template #actions>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="edit(null)">{{ t("assets.permits.add") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="permits.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="72px" radius="12px" /></div>
    <div v-else-if="!permits.data.value?.length" class="ui-card">
      <EmptyState :icon="ScrollText" :title="t('assets.permits.emptyTitle')" :description="t('assets.permits.emptyBody')">
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="edit(null)">{{ t("assets.permits.add") }}</UiButton>
      </EmptyState>
    </div>
    <div v-else class="flex flex-col gap-4">
      <PageSection v-for="group in groups" :key="group.id" variant="card" :title="t(`assets.permits.group.${group.id}`)" :count="group.rows.length" flush>
        <ul class="divide-y divide-line" :data-testid="`permits-${group.id}`">
          <li v-for="row in group.rows" :key="row.id" class="flex flex-wrap items-center gap-3 px-4 py-3">
            <component :is="tone(row) === 'danger' ? FileWarning : FileCheck2" :size="18" class="shrink-0" :class="tone(row) === 'danger' ? 'text-danger' : 'text-muted'" aria-hidden="true" />
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium text-fg">{{ row.name }}</p>
              <p class="truncate text-xs text-muted">
                {{ [t(`assets.permitKind.${row.kind}`), row.number, row.issuer, row.branch_name ?? t("assets.form.companyLevel")].filter(Boolean).join(" · ") }}
              </p>
            </div>
            <StatusPill size="sm" :tone="tone(row)" :label="left(row)" />
            <a v-if="row.file_url" :href="row.file_url" target="_blank" rel="noopener" class="text-sm font-medium text-primary hover:underline">{{ t("assets.permits.scan") }}</a>
            <template v-if="canManage">
              <UiButton size="sm" variant="ghost" :icon="Upload" :aria-label="t('assets.permits.upload')" @click="pickFile(row)" />
              <UiButton size="sm" variant="ghost" :icon="Pencil" :aria-label="t('assets.item.edit')" @click="edit(row)" />
              <UiButton size="sm" variant="ghost" :icon="Trash2" :aria-label="t('assets.item.delete')" @click="remove(row)" />
            </template>
          </li>
        </ul>
      </PageSection>
    </div>
    <input ref="fileInput" type="file" class="sr-only" accept="image/*,application/pdf" @change="upload" />

    <UiDialog v-model:open="open" :title="editing ? t('assets.permits.editTitle') : t('assets.permits.add')" :description="t('assets.permits.formBody')" size="md">
      <div class="flex flex-col gap-3">
        <FormField :label="t('assets.permits.kind')">
          <SelectBox :model-value="form.kind" :options="kindOptions" @update:model-value="(value) => pickKind(value as PermitKind | null)" />
        </FormField>
        <FormField :label="t('assets.field.name')" :error="errors.name" required>
          <TextInput v-model="form.name" :maxlength="120" />
        </FormField>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('assets.permits.number')" optional><TextInput v-model="form.number" :maxlength="64" mono /></FormField>
          <FormField :label="t('assets.permits.issuer')" optional><TextInput v-model="form.issuer" :maxlength="150" /></FormField>
          <FormField :label="t('assets.permits.issuedOn')" optional><DatePicker v-model="form.issued_on" clearable /></FormField>
          <FormField :label="t('assets.permits.validUntil')" :hint="t('assets.permits.validUntilHint')" :error="errors.valid_until" optional>
            <DatePicker v-model="form.valid_until" clearable />
          </FormField>
          <FormField :label="t('assets.col.branch')" :error="errors.branch" optional>
            <BranchPicker v-model="form.branch" clearable :placeholder="t('assets.form.companyLevel')" />
          </FormField>
          <FormField :label="t('assets.permits.remind')" :hint="t('assets.permits.remindHint')">
            <NumberInput v-model="form.remind_days" :min="1" :max="365" :suffix="t('assets.settings.days')" />
          </FormField>
        </div>
        <FormField :label="t('assets.permits.responsible')" optional><PersonPicker v-model="form.responsible" clearable /></FormField>
        <FormField :label="t('assets.field.notes')" optional><TextArea v-model="form.notes" :rows="2" autosize :max-rows="5" /></FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="saving" @click="save">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
