<script setup lang="ts">
/**
 * An import profile (plan §14.7): how one cash-register program's export is read, saved once and
 * reused every day. The column mapper reads a sample file (nothing is saved), proposes a map from
 * the column names it recognizes (Russian, Uzbek and English) and shows the first 20 rows with
 * each mapped column labelled, so the person sees what an import will read before the first one.
 */
import { Save, Upload } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageSection from "@/components/PageSection.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useCompanyId } from "@/stores/company";

import { salesApi, useOptions, useSalesMutation } from "../api";
import { LINE_FIELDS, type FileKind, type ImportPreview, type ImportProfile, type ImportProfileInput, type LineField, type LineUnit } from "../types";

const props = defineProps<{ open: boolean; profile: ImportProfile | null }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const cid = useCompanyId();
const options = useOptions();

const REQUIRED: LineField[] = ["receipt", "code", "quantity"];
const form = reactive({
  name: "",
  file_kind: "csv" as FileKind,
  encoding: "",
  delimiter: "",
  header_row: 1,
  date_format: "",
  default_unit: "pack" as LineUnit,
  branch: 0, // 0: the file has a branch column
  is_active: true,
  columns: {} as Partial<Record<LineField, string>>,
});
const sample = ref<File[]>([]);
const preview = ref<ImportPreview | null>(null);
const reading = ref(false);

watch(
  () => [props.open, props.profile] as const,
  ([open, profile]) => {
    if (!open) return;
    preview.value = null;
    sample.value = [];
    Object.assign(form, {
      name: profile?.name ?? "",
      file_kind: profile?.file_kind ?? "csv",
      encoding: profile?.encoding ?? "",
      delimiter: profile?.delimiter ?? "",
      header_row: profile?.header_row ?? 1,
      date_format: profile?.date_format ?? "",
      default_unit: profile?.default_unit ?? "pack",
      branch: profile ? (profile.branch?.id ?? 0) : (options.data.value?.branches[0]?.id ?? 0),
      is_active: profile?.is_active ?? true,
      columns: { ...(profile?.columns ?? {}) },
    });
  },
  { immediate: true },
);

const visible = computed({ get: () => props.open, set: (value: boolean) => !value && emit("close") });
const kinds = computed(() => [
  { value: "csv" as const, label: "CSV" },
  { value: "xlsx" as const, label: "Excel (xlsx)" },
]);
const units = computed(() => [
  { value: "pack" as const, label: t("sales.profile.unit.pack") },
  { value: "part" as const, label: t("sales.profile.unit.part") },
]);
const branches = computed(() => [
  ...(options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name })),
  { value: 0, label: t("sales.import.branchColumn") },
]);
const encodings = computed(() => [
  { value: "", label: t("sales.profile.auto") },
  { value: "utf-8", label: "UTF-8" },
  { value: "cp1251", label: "Windows-1251" },
  { value: "cp866", label: "DOS-866" },
]);
const delimiters = computed(() => [
  { value: "", label: t("sales.profile.auto") },
  { value: ";", label: ";" },
  { value: ",", label: "," },
  { value: "\t", label: t("sales.profile.tab") },
  { value: "|", label: "|" },
]);
const fields = computed(() => LINE_FIELDS.filter((field) => !(field === "branch" && form.branch)));
const headers = computed(() => {
  const found = new Set<string>(preview.value?.headers.filter(Boolean) ?? []);
  for (const value of Object.values(form.columns)) if (value) found.add(value);
  return [...found];
});
const headerOptions = computed(() => [{ value: "", label: "—" }, ...headers.value.map((name) => ({ value: name, label: name }))]);
const missing = computed(() => {
  const named = (field: LineField) => !!form.columns[field];
  const out = REQUIRED.filter((field) => !named(field));
  if (!named("sold_at") && !named("date")) out.push("sold_at");
  if (!named("total") && !named("price")) out.push("total");
  if (!form.branch && !named("branch")) out.push("branch");
  return out;
});
const mappedAt = computed(() => {
  const at: Record<number, LineField> = {};
  for (const [field, header] of Object.entries(form.columns)) {
    const index = preview.value?.headers.indexOf(header ?? "") ?? -1;
    if (index >= 0) at[index] = field as LineField;
  }
  return at;
});

async function read(): Promise<void> {
  const file = sample.value[0];
  if (!file) return;
  reading.value = true;
  try {
    const found = await salesApi.preview(cid.value, file, { file_kind: form.file_kind, encoding: form.encoding, delimiter: form.delimiter, header_row: form.header_row });
    preview.value = found;
    form.file_kind = found.file_kind;
    // A new map starts from what the mapper recognized; a saved one keeps its own choices.
    for (const [field, header] of Object.entries(found.guess)) {
      if (!form.columns[field as LineField] && header) form.columns[field as LineField] = header;
    }
  } finally {
    reading.value = false;
  }
}
watch(sample, (files) => {
  if (files.length) void read();
});

const save = useSalesMutation((c, input: ImportProfileInput) => (props.profile ? salesApi.updateProfile(c, props.profile.id, input) : salesApi.createProfile(c, input)));
async function submit(): Promise<void> {
  const columns = Object.fromEntries(Object.entries(form.columns).filter(([field, header]) => header && fields.value.includes(field as LineField)));
  await save.mutateAsync({
    name: form.name.trim(),
    file_kind: form.file_kind,
    encoding: form.encoding,
    delimiter: form.delimiter,
    header_row: form.header_row,
    date_format: form.date_format.trim(),
    default_unit: form.default_unit,
    branch_id: form.branch || null,
    is_active: form.is_active,
    columns,
  });
  toast.success(t("sales.profile.saved"));
  emit("close");
}
</script>

<template>
  <UiDrawer v-model:open="visible" size="xl" :title="profile ? profile.name : t('sales.profile.newTitle')" :description="t('sales.profile.description')">
    <form class="flex flex-col gap-4 p-5 max-sm:p-4" @submit.prevent="submit">
      <PageSection variant="card" :title="t('sales.profile.file')">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('sales.profile.name')" :hint="t('sales.profile.nameHint')" required>
            <TextInput v-model="form.name" :maxlength="80" />
          </FormField>
          <FormField :label="t('sales.profile.branch')" :hint="t('sales.profile.branchHint')">
            <SelectBox v-model="form.branch" :options="branches" />
          </FormField>
          <FormField :label="t('sales.profile.kind')">
            <SegmentedControl v-model="form.file_kind" :options="kinds" block :aria-label="t('sales.profile.kind')" />
          </FormField>
          <FormField :label="t('sales.profile.defaultUnit')" :hint="t('sales.profile.defaultUnitHint')">
            <SegmentedControl v-model="form.default_unit" :options="units" block :aria-label="t('sales.profile.defaultUnit')" />
          </FormField>
          <template v-if="form.file_kind === 'csv'">
            <FormField :label="t('sales.profile.encoding')"><SelectBox v-model="form.encoding" :options="encodings" /></FormField>
            <FormField :label="t('sales.profile.delimiter')"><SelectBox v-model="form.delimiter" :options="delimiters" /></FormField>
          </template>
          <FormField :label="t('sales.profile.headerRow')" :hint="t('sales.profile.headerRowHint')">
            <NumberInput v-model="form.header_row" :min="1" :max="50" />
          </FormField>
          <FormField :label="t('sales.profile.dateFormat')" :hint="t('sales.profile.dateFormatHint')" optional>
            <TextInput v-model="form.date_format" :maxlength="32" placeholder="%d.%m.%Y %H:%M" />
          </FormField>
          <ToggleSwitch v-if="profile" v-model="form.is_active" layout="row" :label="t('sales.profile.active')" :description="t('sales.profile.activeHint')" />
        </div>
      </PageSection>

      <PageSection variant="card" :title="t('sales.profile.mapper')" :description="t('sales.profile.mapperHint')">
        <div class="flex flex-col gap-4">
          <div class="flex flex-wrap items-end gap-3">
            <FileDrop v-model="sample" class="min-w-[240px] flex-1" :accept="form.file_kind === 'xlsx' ? '.xlsx' : '.csv,.txt'" :max-size="20 * 1024 * 1024" compact :title="t('sales.profile.sample')" />
            <UiButton v-if="sample.length" variant="secondary" :icon="Upload" :loading="reading" @click="read">{{ t("sales.profile.readAgain") }}</UiButton>
          </div>
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <FormField v-for="field in fields" :key="field" :label="t(`sales.profile.field.${field}`)" :required="REQUIRED.includes(field)" :error="missing.includes(field) ? t('sales.profile.needed') : null">
              <SelectBox :model-value="form.columns[field] ?? ''" :options="headerOptions" placeholder="—" @update:model-value="(value: string | null) => (form.columns[field] = value || undefined)" />
            </FormField>
          </div>
          <p v-if="missing.length" class="text-sm text-warning">{{ t("sales.profile.missing", { fields: missing.map((field) => t(`sales.profile.field.${field}`)).join(", ") }) }}</p>
          <div v-if="preview" class="overflow-x-auto rounded-lg border border-line">
            <table class="w-full min-w-max text-xs">
              <thead class="bg-surface-2">
                <tr>
                  <th v-for="(header, index) in preview.headers" :key="index" class="whitespace-nowrap px-2 py-1.5 text-start font-medium text-fg">
                    {{ header || "—" }}
                    <span v-if="mappedAt[index]" class="mt-0.5 block font-normal text-primary">{{ t(`sales.profile.field.${mappedAt[index]}`) }}</span>
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="(cells, rowIndex) in preview.rows" :key="rowIndex">
                  <td v-for="(cell, index) in cells" :key="index" :class="['whitespace-nowrap px-2 py-1 tabular-nums', mappedAt[index] ? 'text-fg' : 'text-subtle']">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
            <p class="px-2 py-1.5 text-xs text-muted">{{ t("sales.profile.previewCount", { shown: preview.rows.length, total: preview.total_rows }) }}</p>
          </div>
        </div>
      </PageSection>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="emit('close')">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Save" :disabled="!form.name.trim() || missing.length > 0" :loading="save.isPending.value" @click="submit">{{ t("common.save") }}</UiButton>
    </template>
  </UiDrawer>
</template>
