<script setup lang="ts">
/**
 * Upload a document, or change one: whose, which kind, its number, dates and the file (kept in
 * private storage, opened through short-lived links). An ID's number is typed hidden for someone
 * without hr.sensitive, and they never see it again. `member` and `kind` prefill it (the overview's
 * "Upload the new one", Person 360).
 */
import { Eye, EyeOff, LockKeyhole, Upload } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import type { SelectOption } from "@/components/options";
import PersonPicker from "@/components/PersonPicker.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { hrApi, useHrMutation } from "../api";
import { hrAccess, kindGroup, needsSensitive } from "../lib";
import { DOCUMENT_KINDS, type DocumentKind, type HrDocument } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ member?: { id: number; name: string } | null; kind?: DocumentKind | null; document?: HrDocument | null }>(), {
  member: null,
  kind: null,
  document: null,
});
const emit = defineEmits<{ saved: [document: HrDocument] }>();

const { t } = useI18n();
const company = useCompanyStore();
const access = computed(() => hrAccess((perm) => company.can(perm)));

const form = reactive({
  member: null as number | null,
  kind: null as DocumentKind | null,
  title: "",
  number: "",
  issued_on: null as string | null,
  expires_on: null as string | null,
  visible_to_employee: true,
  files: [] as File[],
});
const errors = reactive<Record<string, string | undefined>>({});
const showNumber = ref(false);
const editing = computed(() => !!props.document);

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    for (const key of Object.keys(errors)) delete errors[key];
    showNumber.value = false;
    const d = props.document;
    Object.assign(form, {
      member: d?.member.id ?? props.member?.id ?? null,
      kind: d?.kind ?? props.kind ?? null,
      title: d?.title ?? "",
      // A masked number is never sent back: an empty field keeps the stored one.
      number: d && !/[•*]/.test(d.number) ? d.number : "",
      issued_on: d?.issued_on ?? null,
      expires_on: d?.expires_on ?? null,
      visible_to_employee: d?.visible_to_employee ?? !(props.kind && needsSensitive(props.kind)),
      files: [],
    });
  },
  { immediate: true },
);

const kindOptions = computed<SelectOption<DocumentKind>[]>(() =>
  DOCUMENT_KINDS.map((kind) => ({ value: kind, label: t(`hr.kind.${kind}`), group: t(`hr.kindGroup.${kindGroup(kind)}`) })),
);
const idKind = computed(() => !!form.kind && needsSensitive(form.kind));
/** An ID's number is typed hidden without hr.sensitive (they won't see it afterwards either). */
const hiddenNumber = computed(() => idKind.value && !access.value.sensitive);
const maskedStored = computed(() => !!props.document?.number && /[•*]/.test(props.document.number));

const save = useHrMutation((cid, input: { id: number | null; body: Parameters<typeof hrApi.uploadDocument>[1] }) =>
  input.id ? hrApi.updateDocument(cid, input.id, input.body) : hrApi.uploadDocument(cid, input.body),
);

async function submit(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.member) errors.member = t("hr.form.required");
  if (!form.kind) errors.kind = t("hr.form.required");
  if (!editing.value && !form.files.length) errors.file = t("hr.document.fileRequired");
  if (form.issued_on && form.expires_on && form.expires_on < form.issued_on) errors.expires_on = t("hr.document.expiresBeforeIssued");
  if (Object.values(errors).some(Boolean)) return;
  const body = {
    member_id: form.member!,
    kind: form.kind!,
    title: form.title.trim(),
    number: form.number.trim(),
    issued_on: form.issued_on,
    expires_on: form.expires_on,
    visible_to_employee: form.visible_to_employee,
    file: form.files[0] ?? null,
  };
  // Editing leaves the stored number alone unless a new one was typed.
  if (editing.value && !body.number) delete (body as Partial<typeof body>).number;
  try {
    const saved = await save.mutateAsync({ id: props.document?.id ?? null, body });
    toast.success(editing.value ? t("hr.document.saved") : t("hr.document.uploaded"));
    emit("saved", saved);
    open.value = false;
  } catch (failure) {
    if (isApiError(failure)) {
      for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field === "member_id" ? "member" : field] = messages[0];
      const unshown = unshownFieldError(failure, ["member_id", "kind", "title", "number", "issued_on", "expires_on", "file"]);
      if (unshown) toast.error(unshown);
    }
  }
}
</script>

<template>
  <UiDrawer v-model:open="open" size="md" :title="editing ? t('hr.document.editTitle') : t('hr.document.uploadTitle')" :description="t('hr.document.uploadHint')">
    <form class="flex flex-col gap-4 p-5" @submit.prevent="submit">
      <FormField v-if="!member && !editing" :label="t('hr.field.person')" :error="errors.member" required>
        <PersonPicker v-model="form.member" :invalid="!!errors.member" />
      </FormField>
      <p v-else class="flex items-center gap-2 rounded-[10px] bg-surface-2 px-3 py-2 text-sm text-muted">
        {{ t("hr.field.person") }}: <span class="font-semibold text-fg">{{ document?.member.name ?? member?.name }}</span>
      </p>

      <FormField :label="t('hr.field.kind')" :error="errors.kind" required>
        <SelectBox v-model="form.kind" :options="kindOptions" :placeholder="t('hr.document.kindPlaceholder')" :invalid="!!errors.kind" :disabled="editing" />
      </FormField>

      <InlineAlert v-if="idKind && !access.sensitive" tone="info" size="sm" :icon="LockKeyhole" :description="t('hr.document.idNotice')" />

      <FormField :label="t('hr.field.title')" :hint="t('hr.document.titleHint')" :error="errors.title" optional>
        <TextInput v-model="form.title" :maxlength="150" :placeholder="form.kind ? t(`hr.kind.${form.kind}`) : ''" />
      </FormField>

      <FormField :label="t('hr.field.number')" :hint="maskedStored ? t('hr.document.numberKeep') : undefined" :error="errors.number" optional>
        <div class="flex items-center gap-2">
          <TextInput
            v-model="form.number"
            class="min-w-0 flex-1"
            :type="hiddenNumber && !showNumber ? 'password' : 'text'"
            mono
            :maxlength="32"
            autocomplete="off"
            :placeholder="maskedStored ? document!.number : ''"
            :invalid="!!errors.number"
          />
          <IconButton v-if="hiddenNumber" :icon="showNumber ? EyeOff : Eye" :label="showNumber ? t('hr.document.hideNumber') : t('hr.document.showNumber')" variant="secondary" @click="showNumber = !showNumber" />
        </div>
      </FormField>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField :label="t('hr.field.issuedOn')" :error="errors.issued_on" optional>
          <DatePicker v-model="form.issued_on" clearable />
        </FormField>
        <FormField :label="t('hr.field.expiresOn')" :hint="t('hr.document.expiresHint')" :error="errors.expires_on" optional>
          <DatePicker v-model="form.expires_on" :min="form.issued_on" clearable />
        </FormField>
      </div>

      <FormField :label="editing ? t('hr.document.replaceFile') : t('hr.field.file')" :error="errors.file" :required="!editing" :optional="editing">
        <FileDrop v-model="form.files" accept="image/*,application/pdf" :invalid="!!errors.file" :hint="t('hr.document.fileHint')" />
      </FormField>

      <ToggleSwitch v-model="form.visible_to_employee" layout="row" :label="t('hr.document.visible')" :description="t('hr.document.visibleHint')" />
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Upload" :loading="save.isPending.value" @click="submit">{{ editing ? t("common.save") : t("hr.document.upload") }}</UiButton>
    </template>
  </UiDrawer>
</template>
