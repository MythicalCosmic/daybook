<script setup lang="ts">
/**
 * Create or edit a project: name and key, colour and icon, status, dates, lead and team, branch,
 * client, budget and who may see it. Creating opens the new board; editing saves in place.
 */
import { Check, Lock, Users } from "@lucide/vue";
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { z } from "zod";

import { isApiError } from "@/api/http";
import type { Currency } from "@/api/types";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useForm } from "@/lib/useForm";

import { createProject, updateProject, useCompanyId, useOptions, usePeople, useRefreshProjects } from "../api";
import { colorVar, ICON_NAMES, projectIcon } from "../lib";
import { PALETTE, PROJECT_STATUSES, type PaletteColor, type ProjectDetail, type ProjectInput, type ProjectPriority, type ProjectStatus, type Visibility } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ project?: ProjectDetail | null }>(), { project: null });
const emit = defineEmits<{ saved: [project: ProjectDetail] }>();

const { t } = useI18n();
const router = useRouter();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const people = usePeople();
const options = useOptions();
const editing = computed(() => !!props.project);

const schema = z
  .object({
    name: z.string().trim().min(1, "projects.form.nameRequired").max(120),
    key: z
      .string()
      .trim()
      .regex(/^([A-Za-z]{2,6})?$/, "projects.form.keyFormat"),
    description: z.string().max(20000),
    color: z.string(),
    icon: z.string(),
    status: z.string(),
    priority: z.string(),
    visibility: z.string(),
    lead: z.number().nullable(),
    member_ids: z.array(z.number()),
    branch: z.number().nullable(),
    client: z.number().nullable(),
    start_on: z.string().nullable(),
    due_on: z.string().nullable(),
    budget: z.string().nullable(),
    budget_currency: z.enum(["UZS", "USD"]),
  })
  .refine((v) => !v.start_on || !v.due_on || v.due_on >= v.start_on, { path: ["due_on"], message: "projects.form.dueAfterStart" });

function initial() {
  const p = props.project;
  return {
    name: p?.name ?? "",
    key: p?.key ?? "",
    description: p?.description ?? "",
    color: (p?.color ?? "") as string,
    icon: p?.icon ?? "folder-kanban",
    status: (p?.status ?? "planning") as string,
    priority: (p?.priority ?? "normal") as string,
    visibility: (p?.visibility ?? "members") as string,
    lead: p?.lead?.id ?? null,
    member_ids: [] as number[],
    branch: p?.branch?.id ?? null,
    client: p?.client?.id ?? null,
    start_on: p?.start_on ?? null,
    due_on: p?.due_on ?? null,
    budget: p?.budget ?? null,
    budget_currency: (p?.budget_currency ?? options.data.value?.currency ?? "UZS") as Currency,
  };
}

const form = useForm(schema, initial(), {
  onSubmit: async (values) => {
    const body: ProjectInput = {
      name: values.name,
      key: values.key.toUpperCase() || undefined,
      description: values.description,
      color: values.color as PaletteColor,
      icon: values.icon,
      status: values.status as ProjectStatus,
      priority: values.priority as ProjectPriority,
      visibility: values.visibility as Visibility,
      lead: values.lead,
      branch: values.branch,
      client: values.client,
      start_on: values.start_on,
      due_on: values.due_on,
      budget: values.budget,
      budget_currency: values.budget_currency,
    };
    try {
      if (props.project) {
        const saved = await updateProject(companyId.value, props.project.id, { ...body, key: values.key.toUpperCase() || props.project.key });
        toast.success(t("projects.form.saved"));
        emit("saved", saved);
        open.value = false;
      } else {
        const created = await createProject(companyId.value, { ...body, member_ids: values.member_ids });
        toast.success(t("projects.form.created", { key: created.key }));
        emit("saved", created);
        open.value = false;
        void router.push(`/c/${companyId.value}/projects/${created.id}`);
      }
      void refresh();
    } catch (error) {
      if (isApiError(error) && (error.body as { code?: string } | null)?.code === "key") {
        form.setErrors({ key: error.detail ?? "" });
        return;
      }
      throw error;
    }
  },
});

watch(open, (value) => {
  if (value) form.reset(initial());
});

const peopleOptions = computed(() => (people.data.value ?? []).map((p) => ({ id: p.id, name: p.name, photo_url: p.photo_url, subtitle: p.position || undefined })));
const statusOptions = computed(() => PROJECT_STATUSES.map((s) => ({ value: s, label: t(`projects.status.${s}`) })));
const priorityOptions = computed(() => (["low", "normal", "high"] as const).map((v) => ({ value: v, label: t(`projects.priority.${v}`) })));
const branchOptions = computed(() => (options.data.value?.branches ?? []).map((b) => ({ value: b.id, label: b.name })));
const clientOptions = computed(() => (options.data.value?.clients ?? []).map((c) => ({ value: c.id, label: c.name })));
const visibilityOptions = computed(() => [
  { value: "members", label: t("projects.visibility.members"), description: t("projects.visibility.membersTip"), icon: Lock },
  { value: "company", label: t("projects.visibility.company"), description: t("projects.visibility.companyTip"), icon: Users },
]);
const keyPreview = computed(() => (form.values.key || suggest(form.values.name)).toUpperCase());

/** The key the server will most likely pick (initials, else the first letters). */
function suggest(name: string): string {
  const words = name
    .normalize("NFKD")
    .replace(/[^A-Za-z\s]/g, "")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length >= 2) return words.map((w) => w[0]).join("").slice(0, 6);
  return (words[0] ?? "").slice(0, 4) || "KEY";
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('projects.form.editTitle') : t('projects.form.newTitle')" :description="editing ? undefined : t('projects.form.newHint')" size="lg">
    <form id="project-form" class="flex flex-col gap-5" novalidate @submit="form.submit">
      <InlineAlert v-if="form.formError.value" tone="danger" :description="form.formError.value" />
      <div class="grid gap-4 sm:grid-cols-[1fr_160px]">
        <FormField :label="t('projects.form.name')" :error="form.errors.name" required>
          <TextInput v-model="form.values.name" :placeholder="t('projects.form.namePlaceholder')" autofocus :invalid="!!form.errors.name" @blur="form.touch('name')" />
        </FormField>
        <FormField :label="t('projects.form.key')" :hint="t('projects.form.keyHint', { key: `${keyPreview}-1` })" :error="form.errors.key">
          <TextInput v-model="form.values.key" :placeholder="keyPreview" mono :maxlength="6" :invalid="!!form.errors.key" @blur="form.touch('key')" />
        </FormField>
      </div>

      <FormField :label="t('projects.form.description')" optional>
        <TextArea v-model="form.values.description" :rows="3" :placeholder="t('projects.form.descriptionPlaceholder')" />
      </FormField>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('projects.form.color')">
          <div class="flex flex-wrap gap-2" role="radiogroup" :aria-label="t('projects.form.color')">
            <button
              v-for="color in PALETTE"
              :key="color"
              type="button"
              role="radio"
              :aria-checked="form.values.color === color"
              :aria-label="color"
              class="pressable grid size-8 place-items-center rounded-full ring-offset-2 ring-offset-surface transition-shadow"
              :class="form.values.color === color && 'ring-2 ring-fg/60'"
              :style="{ background: colorVar(color) }"
              @click="form.values.color = color"
            >
              <Check v-if="form.values.color === color" :size="14" class="text-white" />
            </button>
          </div>
        </FormField>
        <FormField :label="t('projects.form.icon')">
          <div class="flex flex-wrap gap-1.5" role="radiogroup" :aria-label="t('projects.form.icon')">
            <button
              v-for="name in ICON_NAMES"
              :key="name"
              type="button"
              role="radio"
              :aria-checked="form.values.icon === name"
              :aria-label="name"
              class="pressable grid size-8 place-items-center rounded-[8px] border transition-colors"
              :class="form.values.icon === name ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-muted hover:bg-highlight hover:text-fg'"
              @click="form.values.icon = name"
            >
              <component :is="projectIcon(name)" :size="16" />
            </button>
          </div>
        </FormField>
      </div>

      <div class="grid gap-4 sm:grid-cols-3">
        <FormField :label="t('projects.form.status')">
          <SelectBox v-model="form.values.status" :options="statusOptions" />
        </FormField>
        <FormField :label="t('projects.form.start')" optional>
          <DatePicker v-model="form.values.start_on" clearable />
        </FormField>
        <FormField :label="t('projects.form.due')" :error="form.errors.due_on" optional>
          <DatePicker v-model="form.values.due_on" clearable :min="form.values.start_on" />
        </FormField>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('projects.form.lead')" :hint="t('projects.form.leadHint')">
          <PersonPicker v-model="form.values.lead" :people="peopleOptions" :placeholder="t('projects.form.leadPlaceholder')" />
        </FormField>
        <FormField v-if="!editing" :label="t('projects.form.team')" optional>
          <PersonPicker v-model="form.values.member_ids" multiple :people="peopleOptions" :exclude="form.values.lead ? [form.values.lead] : []" :placeholder="t('projects.form.teamPlaceholder')" />
        </FormField>
        <FormField v-else :label="t('projects.form.priority')">
          <SegmentedControl v-model="form.values.priority" :options="priorityOptions" block />
        </FormField>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('projects.form.branch')" optional>
          <SelectBox v-model="form.values.branch" :options="branchOptions" clearable :placeholder="t('projects.form.wholeCompany')" />
        </FormField>
        <FormField :label="t('projects.form.client')" optional>
          <SelectBox v-model="form.values.client" :options="clientOptions" clearable :placeholder="t('projects.form.noClient')" />
        </FormField>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('projects.form.budget')" :hint="t('projects.form.budgetHint')" optional>
          <MoneyInput v-model="form.values.budget" v-model:currency="form.values.budget_currency" :currencies="['UZS', 'USD']" />
        </FormField>
        <FormField v-if="!editing" :label="t('projects.form.priority')">
          <SegmentedControl v-model="form.values.priority" :options="priorityOptions" block />
        </FormField>
      </div>

      <FormField :label="t('projects.form.visibility')">
        <RadioCards v-model="form.values.visibility" :options="visibilityOptions" :columns="2" />
      </FormField>
    </form>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" type="submit" form="project-form" :loading="form.submitting.value">
        {{ editing ? t("common.save") : t("projects.form.create") }}
      </UiButton>
    </template>
  </UiDialog>
</template>
