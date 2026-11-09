<script setup lang="ts">
/**
 * Add or edit an employee (`?employee=new` or `?employee=<id>`, so Back closes it and a link opens
 * it): the photo (cropped to the round avatar it becomes, uploaded after the save), the name and
 * phone, where they work (position, department, locations, schedule, hire date) and the numbers
 * the Face ID terminals know them by. Server refusals land on their fields.
 */
import { Camera, ScanFace, Trash2, UserRound } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { z } from "zod";

import BranchPicker from "@/components/BranchPicker.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";
import { closeQueryKey } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { removeEmployeePhoto, useDepartments, useEmployee, useEmployeeSave, usePositions, useSchedules } from "../../api";
import type { Employee, EmployeeInput } from "../../types";
import FaceNumbersInput from "./FaceNumbersInput.vue";
import PhotoCropper from "./PhotoCropper.vue";
import { usePhotoUpload } from "./teamApi";

const emit = defineEmits<{ saved: [employee: Employee, created: boolean] }>();

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();

const value = computed(() => {
  const raw = router.currentRoute.value.query.employee;
  return (Array.isArray(raw) ? raw[0] : raw) ?? null;
});
const open = computed(() => value.value !== null);
const editingId = computed(() => (value.value && /^\d+$/.test(value.value) ? Number(value.value) : null));
const creating = computed(() => value.value === "new");

const employee = useEmployee(editingId);
const positions = usePositions();
const departments = useDepartments();
const schedules = useSchedules(open);
const save = useEmployeeSave();
const upload = usePhotoUpload();

const positionOptions = computed(() => (positions.data.value ?? []).filter((p) => p.is_active || p.id === form.values.position_id).map((p) => ({ value: p.id, label: p.name })));
const departmentOptions = computed(() =>
  (departments.data.value ?? []).map((d) => ({ value: d.id, label: d.name, description: d.path.length > 1 ? d.path.slice(0, -1).join(" › ") : undefined })),
);
const scheduleOptions = computed(() => (schedules.data.value ?? []).filter((s) => s.is_active || s.id === form.values.schedule_id).map((s) => ({ value: s.id, label: s.name })));

const schema = z.object({
  first_name: z.string().trim().min(1, "common.form.required").max(150, "common.form.tooLong"),
  last_name: z.string().trim().max(150, "common.form.tooLong"),
  phone: z.string().trim().max(32, "common.form.tooLong"),
  position_id: z.number().nullable(),
  department_id: z.number().nullable(),
  branch_ids: z.array(z.number()),
  face_numbers: z.array(z.string()),
  schedule_id: z.number().nullable(),
  hire_date: z.string().nullable(),
});

/** New people start at the one location in view (the branch filter, or the only branch there is). */
function defaultBranches(): number[] {
  if (company.branchFilter.length === 1) return [...company.branchFilter];
  const branches = company.current?.branches ?? [];
  return branches.length === 1 ? [branches[0]!.id] : [];
}

function valuesOf(row: Employee | undefined): EmployeeInput {
  return {
    first_name: row?.first_name ?? "",
    last_name: row?.last_name ?? "",
    phone: row?.phone ?? "",
    position_id: row?.position?.id ?? null,
    department_id: row?.department?.id ?? null,
    branch_ids: row ? [...row.branch_ids] : defaultBranches(),
    face_numbers: row ? [...row.face_numbers] : [],
    schedule_id: row?.schedule?.id ?? null,
    hire_date: row?.hire_date ?? null,
  };
}

const photo = ref<Blob | null>(null);
const photoUrl = ref<string | null>(null);
/** The saved photo goes when the form is saved. */
const dropPhoto = ref(false);
const cropping = ref<File | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);

function setPhoto(blob: Blob | null): void {
  if (photoUrl.value) URL.revokeObjectURL(photoUrl.value);
  photo.value = blob;
  photoUrl.value = blob ? URL.createObjectURL(blob) : null;
}

const form = useForm(schema, valuesOf(undefined), {
  onSubmit: async (values) => {
    const body: EmployeeInput = { ...values, phone: values.phone.trim(), first_name: values.first_name.trim(), last_name: values.last_name.trim() };
    let saved = await save.mutateAsync({ id: editingId.value, body });
    const created = editingId.value === null;
    if (photo.value) {
      try {
        saved = await upload.mutateAsync({ id: saved.id, photo: photo.value });
      } catch {
        // The employee is saved; the photo can be added again from their page.
      }
    } else if (dropPhoto.value && !created) {
      try {
        saved = await removeEmployeePhoto(company.currentId ?? 0, saved.id);
      } catch {
        // The HTTP layer has shown why; the rest is saved.
      }
    }
    setPhoto(null);
    dropPhoto.value = false;
    emit("saved", saved, created);
    if (created) {
      toast.success(t("davomat.team.form.created", { name: saved.full_name }), {
        action: { label: t("davomat.team.form.openProfile"), onClick: () => void router.push(`/c/${company.currentId}/team/${saved.id}`) },
      });
    } else {
      toast.success(t("davomat.team.form.saved", { name: saved.full_name }));
    }
    closeQueryKey(router, "employee");
  },
});

// A new drawer starts clean; an edit fills in when the employee arrives, once per opening, so a
// refetch while the form is open (back to the tab, a scan) never wipes what is being typed.
let filledFor: string | null = null;
watch(
  [value, () => employee.data.value],
  ([current, row]) => {
    if (current === null) {
      filledFor = null;
      return;
    }
    if (current === filledFor) return;
    cropping.value = null;
    dropPhoto.value = false;
    if (current === "new") {
      form.reset(valuesOf(undefined));
      filledFor = current;
    } else if (row && row.id === editingId.value) {
      form.reset(valuesOf(row));
      filledFor = current;
    }
  },
  { immediate: true },
);
watch(open, (isOpen) => {
  if (!isOpen) setPhoto(null);
});

const loading = computed(() => editingId.value !== null && !employee.data.value && employee.isPending.value);
const title = computed(() => (creating.value ? t("davomat.team.form.newTitle") : t("davomat.team.form.editTitle")));
const displayName = computed(() => [form.values.first_name, form.values.last_name].filter(Boolean).join(" ") || t("davomat.team.form.newTitle"));
const currentPhoto = computed(() => photoUrl.value ?? (dropPhoto.value ? null : (employee.data.value?.photo_url ?? null)));

function removePhoto(): void {
  if (photo.value) setPhoto(null);
  else dropPhoto.value = true;
}

function pick(): void {
  fileInput.value?.click();
}

function chosen(event: Event): void {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  target.value = "";
  if (file) cropping.value = file;
}

function cropped(blob: Blob): void {
  setPhoto(blob);
  cropping.value = null;
}
</script>

<template>
  <UiDrawer query-key="employee" :title="title" size="md">
    <div v-if="loading" class="flex flex-col gap-4 p-5" aria-hidden="true">
      <div class="flex items-center gap-4"><SkeletonBlock circle width="72px" height="72px" /><SkeletonBlock width="40%" /></div>
      <SkeletonBlock v-for="n in 6" :key="n" height="36px" radius="8px" />
    </div>

    <div v-else-if="cropping" class="p-5">
      <h3 class="mb-3 text-center text-md font-semibold text-fg">{{ t("davomat.team.photo.title") }}</h3>
      <PhotoCropper :file="cropping" @done="cropped" @cancel="cropping = null" />
    </div>

    <form v-else id="employee-form" class="flex flex-col gap-6 p-5" novalidate @submit.prevent="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />

      <section class="flex items-center gap-4">
        <button type="button" class="group relative shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--c-primary)]" :aria-label="t('davomat.team.photo.upload')" @click="pick">
          <UserAvatar :name="displayName" :src="currentPhoto" :size="72" />
          <span class="absolute inset-0 grid place-items-center rounded-full bg-overlay text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100" aria-hidden="true">
            <Camera :size="20" />
          </span>
        </button>
        <div class="min-w-0">
          <p class="text-base font-semibold text-fg">{{ t("davomat.team.form.photo") }}</p>
          <p class="mt-0.5 text-sm text-muted">{{ photo ? t("davomat.team.photo.pending") : dropPhoto ? t("davomat.team.photo.removing") : t("davomat.team.form.photoHint") }}</p>
          <div class="mt-2 flex flex-wrap gap-2">
            <UiButton size="sm" variant="secondary" :icon="Camera" @click="pick">{{ currentPhoto ? t("davomat.team.photo.change") : t("davomat.team.photo.upload") }}</UiButton>
            <UiButton v-if="currentPhoto" size="sm" variant="ghost" :icon="Trash2" data-remove-photo @click="removePhoto">{{ t("davomat.team.photo.remove") }}</UiButton>
          </div>
          <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" class="hidden" data-photo-input @change="chosen" />
        </div>
      </section>

      <section class="flex flex-col gap-4">
        <h3 class="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.06em] text-subtle"><UserRound :size="14" aria-hidden="true" />{{ t("davomat.team.form.person") }}</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('davomat.team.form.firstName')" :error="form.errors.first_name" required>
            <TextInput v-model="form.values.first_name" autocomplete="off" :invalid="!!form.errors.first_name" data-field="first_name" @blur="form.touch('first_name')" />
          </FormField>
          <FormField :label="t('davomat.team.form.lastName')" :error="form.errors.last_name">
            <TextInput v-model="form.values.last_name" autocomplete="off" :invalid="!!form.errors.last_name" data-field="last_name" />
          </FormField>
        </div>
        <FormField :label="t('davomat.team.form.phone')" :error="form.errors.phone" optional>
          <TextInput v-model="form.values.phone" type="tel" inputmode="tel" autocomplete="off" placeholder="+998 90 123 45 67" :invalid="!!form.errors.phone" data-field="phone" />
        </FormField>
      </section>

      <section class="flex flex-col gap-4">
        <h3 class="text-xs font-semibold uppercase tracking-[0.06em] text-subtle">{{ t("davomat.team.form.work") }}</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('davomat.team.form.position')" :error="form.errors.position_id">
            <SelectBox v-model="form.values.position_id" :options="positionOptions" clearable :placeholder="t('davomat.team.form.noPosition')" :invalid="!!form.errors.position_id" />
          </FormField>
          <FormField :label="t('davomat.team.form.department')" :error="form.errors.department_id">
            <SelectBox v-model="form.values.department_id" :options="departmentOptions" clearable :placeholder="t('davomat.team.form.noDepartment')" :invalid="!!form.errors.department_id" />
          </FormField>
        </div>
        <FormField :label="t('davomat.team.form.branches')" :hint="t('davomat.team.form.branchesHint')" :error="form.errors.branch_ids">
          <BranchPicker v-model="form.values.branch_ids" multiple :clearable="false" :invalid="!!form.errors.branch_ids" />
        </FormField>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('davomat.team.form.schedule')" :hint="t('davomat.team.form.scheduleHint')" :error="form.errors.schedule_id">
            <SelectBox v-model="form.values.schedule_id" :options="scheduleOptions" clearable :placeholder="t('davomat.team.form.noSchedule')" :invalid="!!form.errors.schedule_id" />
          </FormField>
          <FormField :label="t('davomat.team.form.hireDate')" :error="form.errors.hire_date">
            <DatePicker v-model="form.values.hire_date" clearable :invalid="!!form.errors.hire_date" />
          </FormField>
        </div>
      </section>

      <section class="flex flex-col gap-3 rounded-[14px] border border-line bg-surface-2/50 p-4">
        <div class="flex items-start gap-3">
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><ScanFace :size="18" aria-hidden="true" /></span>
          <div class="min-w-0">
            <h3 class="text-base font-semibold text-fg">{{ t("davomat.team.form.faceTitle") }}</h3>
            <p class="mt-0.5 text-sm text-muted">{{ t("davomat.team.form.faceHint") }}</p>
          </div>
        </div>
        <FormField :error="form.errors.face_numbers" :label="t('davomat.team.face.label')" for="employee-face-numbers">
          <FaceNumbersInput id="employee-face-numbers" v-model="form.values.face_numbers" :invalid="!!form.errors.face_numbers" />
        </FormField>
      </section>
    </form>

    <template v-if="!cropping && !loading" #footer>
      <UiButton variant="ghost" @click="closeQueryKey(router, 'employee')">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="employee-form" :loading="form.submitting.value" data-save-employee>{{ creating ? t("davomat.team.form.create") : t("common.save") }}</UiButton>
    </template>
  </UiDrawer>
</template>
