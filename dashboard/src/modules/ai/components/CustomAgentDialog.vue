<script setup lang="ts">
/**
 * Making an agent in your own words (briefs/v6-k.md), or changing one. First the gallery: the
 * ready jobs ("Start from an example": the evening report, Monday's best…, only those whose
 * module is on) and "Write my own"; then the form: its name, what it should do (any language, the
 * template's words to change as you like), when it runs, who gets what it writes (me, chosen
 * people, a Telegram group), what it may read (the modules that are on; what you can't read
 * yourself shows why) and its chibi's colour, the chibi beside the name trying it on. Made, it
 * opens its own page; changed, it stays where it is. The server checks everything again and its
 * messages land on their fields.
 */
import { ArrowLeft, Check, Heart, Info, PenLine, Plus, Sparkles } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError, unshownFieldError } from "@/api/http";
import CheckBox from "@/components/CheckBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import type { PersonOption } from "@/components/pickers";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { useCreateCustomAgent, useCustomOptions, useCustomTemplates, useUpdateCustomAgent } from "../api";
import { checkForm, CUSTOM_JOB_MAX, CUSTOM_NAME_MAX, formFromAgent, formFromTemplate, FREQUENCIES, freshForm, MONTH_DAYS, payload, whenText, type CustomFormErrors } from "../customAgent";
import { CUSTOM_COLOR_KEYS, CUSTOM_COLORS } from "../lib";
import type { Agent, CustomAgentForm, CustomAgentInfo, CustomAgentTemplate, CustomRecipients } from "../types";
import AiBuddy from "./AiBuddy.vue";
import { templateIcon } from "./templateIcons";

const props = withDefaults(defineProps<{ agent?: (Pick<Agent, "key" | "name"> & { custom: CustomAgentInfo }) | null }>(), { agent: null });
const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const router = useRouter();
const company = useCompanyStore();
const create = useCreateCustomAgent();
const update = useUpdateCustomAgent();

const editing = computed(() => props.agent !== null);
const step = ref<"pick" | "form">("pick");
const templates = useCustomTemplates(() => open.value && !editing.value);
const options = useCustomOptions(open);
const domains = computed(() => options.data.value?.domains ?? []);

const form = reactive<CustomAgentForm>(freshForm([]));
const checked = ref<CustomFormErrors>({});
const refused = ref<Record<string, string>>({});
const formError = ref<string | null>(null);
const saving = ref(false);
const started = ref(false);

function start(next: CustomAgentForm): void {
  Object.assign(form, next);
  checked.value = {};
  refused.value = {};
  formError.value = null;
  started.value = false;
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    step.value = editing.value ? "form" : "pick";
    start(props.agent ? formFromAgent(props.agent) : freshForm(domains.value));
  },
  { immediate: true },
);

function pick(template: CustomAgentTemplate | null): void {
  start(template ? formFromTemplate(template, domains.value) : freshForm(domains.value));
  step.value = "form";
}

/** A field's message: the server's (in the reader's language), else the form's own check. */
function problem(field: keyof CustomAgentForm): string | undefined {
  const own = checked.value[field];
  return refused.value[field] ?? (own ? t(own) : undefined);
}

// Once Create was pressed, the checks follow what is typed.
watch(form, () => {
  if (started.value) checked.value = checkForm(form);
});

const frequencyOptions = computed(() => FREQUENCIES.map((value) => ({ value, label: t(`ai.custom.freq.${value}`) })));
const recipientOptions = computed<{ value: CustomRecipients; label: string }[]>(() => [
  { value: "me", label: t("ai.custom.to.me") },
  { value: "people", label: t("ai.custom.to.people") },
  { value: "group", label: t("ai.custom.to.group") },
]);
const weekdayOptions = computed(() => [0, 1, 2, 3, 4, 5, 6].map((value) => ({ value, label: t(`common.weekday.long.${value}`) })));
const dayOptions = computed(() => MONTH_DAYS.map((value) => ({ value, label: String(value) })));
const people = computed<PersonOption[]>(() => (options.data.value?.people ?? []).map((person) => ({ id: person.id, name: person.name, subtitle: person.position || undefined, photo_url: person.photo })));
const groups = computed(() => (options.data.value?.groups ?? []).map((group) => ({ value: group.id, label: group.title })));
// Editing someone else's agent: changing what it does, reads or who gets it makes you its owner.
const takesOver = computed(() => !!props.agent && !!options.data.value && props.agent.custom.run_as.id !== options.data.value.me.id);

function toggleDomain(key: string, on: boolean): void {
  form.domains = on ? [...new Set([...form.domains, key])] : form.domains.filter((item) => item !== key);
}

function reasonText(reason: string): string {
  return reason === "switch_off" ? t("ai.custom.reason.switchOff") : t("ai.custom.reason.noAccess");
}

async function submit(): Promise<void> {
  started.value = true;
  checked.value = checkForm(form);
  refused.value = {};
  formError.value = null;
  if (Object.keys(checked.value).length || saving.value) return;
  saving.value = true;
  try {
    const body = payload(form);
    const saved = props.agent ? await update.mutateAsync({ id: props.agent.custom.id, form: body }) : await create.mutateAsync(body);
    toast.success(t(props.agent ? "ai.custom.saved" : "ai.custom.created", { name: saved.name }));
    open.value = false;
    if (!props.agent) void router.push({ name: "ai.agent", params: { companyId: company.currentId ?? 0, key: saved.key } });
  } catch (error) {
    if (!isApiError(error)) throw error;
    refused.value = Object.fromEntries(Object.entries(error.fieldErrors).map(([field, messages]) => [field, messages[0] ?? ""]));
    formError.value = error.detail ?? unshownFieldError(error, Object.keys(form));
  } finally {
    saving.value = false;
  }
}

const title = computed(() => (editing.value ? t("ai.custom.editTitle") : t("ai.custom.newTitle")));
const description = computed(() => (step.value === "pick" ? t("ai.custom.pickBody") : t("ai.custom.formBody")));
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="description" size="lg" data-testid="custom-agent-dialog">
    <!-- The gallery: start from an example, or write it yourself. -->
    <div v-if="step === 'pick'" class="flex flex-col gap-3" data-testid="custom-gallery">
      <h3 class="text-sm font-semibold text-muted">{{ t("ai.custom.examples") }}</h3>
      <div v-if="templates.isPending.value" class="grid gap-2 sm:grid-cols-2" aria-hidden="true">
        <SkeletonBlock v-for="n in 4" :key="n" height="104px" radius="12px" />
      </div>
      <ErrorState v-else-if="templates.isError.value" :error="templates.error.value" :retry="() => templates.refetch()" />
      <div v-else class="grid gap-2 sm:grid-cols-2">
        <button
          v-for="template in templates.data.value ?? []"
          :key="template.key"
          type="button"
          class="group flex min-w-0 flex-col gap-1.5 rounded-card border border-line bg-surface p-3 text-left transition-[border-color,box-shadow] hover:border-line-strong hover:shadow-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          :data-template="template.key"
          @click="pick(template)"
        >
          <span class="flex items-center gap-2">
            <span class="flex size-7 shrink-0 items-center justify-center rounded-lg text-white" :style="{ background: CUSTOM_COLORS[template.color].main }" aria-hidden="true">
              <component :is="templateIcon(template.icon)" :size="15" />
            </span>
            <span class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ template.name }}</span>
          </span>
          <span class="text-xs font-medium text-accent-fg">{{ whenText(template, t) }}</span>
          <span class="line-clamp-2 text-xs leading-relaxed text-muted">{{ template.job }}</span>
        </button>
        <button
          type="button"
          class="flex min-w-0 flex-col items-start gap-1.5 rounded-card border border-dashed border-line-strong bg-surface-2/40 p-3 text-left transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          data-testid="custom-own"
          @click="pick(null)"
        >
          <span class="flex items-center gap-2">
            <span class="flex size-7 items-center justify-center rounded-lg bg-surface text-accent-fg" aria-hidden="true"><PenLine :size="15" /></span>
            <span class="text-sm font-semibold text-fg">{{ t("ai.custom.writeOwn") }}</span>
          </span>
          <span class="text-xs leading-relaxed text-muted">{{ t("ai.custom.writeOwnBody") }}</span>
        </button>
      </div>
    </div>

    <!-- The form. -->
    <form v-else class="flex flex-col gap-5" data-testid="custom-form" novalidate @submit.prevent="submit">
      <div class="flex items-end gap-3">
        <AiBuddy class="mb-1 shrink-0" variant="custom" :color="form.color" mood="on" :size="54" :label="form.name || t('ai.custom.chibi')" data-testid="custom-preview" />
        <FormField class="min-w-0 flex-1" :label="t('ai.custom.field.name')" :error="problem('name')" :count="form.name.length" :max="CUSTOM_NAME_MAX" required>
          <TextInput v-model="form.name" :maxlength="CUSTOM_NAME_MAX" :invalid="!!problem('name')" :placeholder="t('ai.custom.field.namePlaceholder')" data-testid="custom-name" />
        </FormField>
      </div>

      <FormField :label="t('ai.custom.field.job')" :hint="t('ai.custom.field.jobHint')" :error="problem('job')" :count="form.job.length" :max="CUSTOM_JOB_MAX" required>
        <TextArea v-model="form.job" :rows="4" autosize :max-rows="10" :maxlength="CUSTOM_JOB_MAX" :invalid="!!problem('job')" :placeholder="t('ai.custom.field.jobExample')" data-testid="custom-job" />
      </FormField>

      <FormField :label="t('ai.custom.field.when')" :error="problem('at') ?? problem('weekday') ?? problem('month_day') ?? problem('frequency')">
        <div class="flex flex-col gap-2.5">
          <SegmentedControl v-model="form.frequency" :options="frequencyOptions" :aria-label="t('ai.custom.field.when')" data-testid="custom-frequency" />
          <div class="flex flex-wrap items-center gap-2">
            <SelectBox v-if="form.frequency === 'weekly'" v-model="form.weekday" class="w-44" :options="weekdayOptions" :invalid="!!problem('weekday')" data-testid="custom-weekday" />
            <SelectBox v-if="form.frequency === 'monthly'" v-model="form.month_day" class="w-28" :options="dayOptions" :invalid="!!problem('month_day')" data-testid="custom-day" />
            <TimePicker v-model="form.at" class="w-32" :step="15" :invalid="!!problem('at')" data-testid="custom-at" />
            <span class="text-xs text-subtle">{{ t("ai.custom.field.whenHint") }}</span>
          </div>
        </div>
      </FormField>

      <FormField :label="t('ai.custom.field.who')" :error="problem('recipients') ?? problem('people') ?? problem('group')">
        <div class="flex flex-col gap-2.5">
          <SegmentedControl v-model="form.recipients" :options="recipientOptions" :aria-label="t('ai.custom.field.who')" data-testid="custom-recipients" />
          <PersonPicker v-if="form.recipients === 'people'" v-model="form.people" multiple :people="people" :invalid="!!problem('people')" data-testid="custom-people" />
          <template v-else-if="form.recipients === 'group'">
            <SelectBox v-if="groups.length" v-model="form.group" :options="groups" :placeholder="t('ai.custom.field.groupPlaceholder')" :invalid="!!problem('group')" data-testid="custom-group" />
            <p v-else class="text-sm text-muted">{{ t("ai.custom.noGroups") }}</p>
          </template>
          <p v-if="form.recipients !== 'me'" class="flex items-start gap-1.5 text-xs text-subtle">
            <Info :size="13" class="mt-px shrink-0" aria-hidden="true" />{{ t("ai.custom.shareNote") }}
          </p>
        </div>
      </FormField>

      <FormField :label="t('ai.custom.field.reads')" :hint="t('ai.custom.field.readsHint')" :error="problem('domains')">
        <div v-if="options.isPending.value" class="grid gap-2 sm:grid-cols-2" aria-hidden="true">
          <SkeletonBlock v-for="n in 4" :key="n" height="28px" />
        </div>
        <EmptyState v-else-if="!domains.length" size="sm" :icon="Sparkles" :title="t('ai.custom.noDomains')" />
        <div v-else class="grid gap-x-4 gap-y-2 sm:grid-cols-2" data-testid="custom-domains">
          <CheckBox
            v-for="domain in domains"
            :key="domain.key"
            :model-value="form.domains.includes(domain.key)"
            :label="domain.label"
            :description="domain.available ? undefined : reasonText(domain.reason)"
            :disabled="!domain.available && !form.domains.includes(domain.key)"
            :data-domain="domain.key"
            @update:model-value="(on: boolean) => toggleDomain(domain.key, on)"
          />
        </div>
      </FormField>

      <FormField :label="t('ai.custom.field.color')">
        <div class="flex flex-wrap gap-2" role="radiogroup" :aria-label="t('ai.custom.field.color')" data-testid="custom-colors">
          <button
            v-for="key in CUSTOM_COLOR_KEYS"
            :key="key"
            type="button"
            role="radio"
            class="flex size-8 items-center justify-center rounded-full ring-offset-2 ring-offset-surface transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            :class="form.color === key && 'ring-2 ring-fg/60'"
            :style="{ background: CUSTOM_COLORS[key].main }"
            :aria-checked="form.color === key"
            :aria-label="t(`ai.custom.color.${key}`)"
            :data-color="key"
            @click="form.color = key"
          >
            <Check v-if="form.color === key" :size="15" class="text-white" aria-hidden="true" />
          </button>
        </div>
      </FormField>

      <InlineAlert v-if="takesOver" tone="info" :icon="Heart" :description="t('ai.custom.takesOver')" data-testid="custom-takes-over" />
      <InlineAlert v-if="formError" tone="danger" :description="formError" data-testid="custom-error" />
    </form>

    <template #footer>
      <div class="flex w-full flex-wrap items-center gap-2">
        <UiButton v-if="step === 'form' && !editing" variant="ghost" :icon="ArrowLeft" @click="step = 'pick'">{{ t("ai.custom.back") }}</UiButton>
        <span class="flex-1" />
        <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton v-if="step === 'form'" variant="primary" :icon="editing ? Check : Plus" :loading="saving" data-testid="custom-submit" @click="submit">
          {{ editing ? t("common.save") : t("ai.custom.create") }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>
