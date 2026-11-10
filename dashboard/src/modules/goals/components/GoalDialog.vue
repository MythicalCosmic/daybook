<script setup lang="ts">
/**
 * Set a business goal (or change one): what it measures (metrics whose module is off say so),
 * the period (this month, quarter, half year, year or one's own), a branch where the metric can be
 * per branch, the target in the metric's unit, who owns it and why. While it is filled in, the
 * preview shows where the metric stands now, its pace to the period's end and the state the
 * target would have; the title is suggested from the choices until it is typed.
 */
import { CircleAlert } from "@lucide/vue";
import { refDebounced } from "@vueuse/core";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { goalsApi, presetPeriod, STATE_TONES, useGoalWrite, useMetrics, usePreview, type Goal, type GoalInput, type MetricKey, type PeriodPreset } from "../api";
import { METRIC_ICONS, useGoalFormat } from "../format";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ today: string; goal?: Goal | null }>();

const { t } = useI18n();
const fmt = useFormat();
const show = useGoalFormat();
const company = useCompanyStore();
const metrics = useMetrics(open);
const editing = computed(() => !!props.goal);
const preset = ref<PeriodPreset>("quarter");
const titleTouched = ref(false);
const error = ref<string | null>(null);
const errors = reactive<Record<string, string | undefined>>({});
const form = reactive({
  metric: null as MetricKey | null,
  starts_on: null as string | null,
  ends_on: null as string | null,
  branch: null as number | null,
  target: null as string | null,
  number: null as number | null,
  title: "",
  owner: null as number | null,
  note: "",
});

const options = computed(() => metrics.data.value?.metrics ?? []);
const metric = computed(() => options.value.find((row) => row.key === form.metric) ?? null);
const unit = computed(() => metric.value?.unit ?? "money");
const targetText = computed(() => (unit.value === "money" ? form.target : form.number !== null ? String(form.number) : null));

watch(
  open,
  (isOpen) => {
    if (!isOpen) return;
    error.value = null;
    for (const key of Object.keys(errors)) delete errors[key];
    titleTouched.value = !!props.goal;
    if (props.goal) {
      preset.value = "custom";
      Object.assign(form, {
        metric: props.goal.metric,
        starts_on: props.goal.starts_on,
        ends_on: props.goal.ends_on,
        branch: props.goal.branch?.id ?? null,
        target: props.goal.unit === "money" ? props.goal.target : null,
        number: props.goal.unit === "money" ? null : Number(props.goal.target),
        title: props.goal.title,
        owner: props.goal.owner?.id ?? null,
        note: props.goal.note,
      });
      return;
    }
    preset.value = "quarter";
    Object.assign(form, { metric: null, ...presetPeriod("quarter", props.today), branch: null, target: null, number: null, title: "", owner: null, note: "" });
  },
  { immediate: true },
);
watch(
  () => metrics.data.value,
  (data) => {
    if (!data || editing.value || form.metric) return;
    form.metric = data.metrics.find((row) => row.available)?.key ?? null;
  },
  { immediate: true },
);
watch(preset, (value) => {
  if (value !== "custom") Object.assign(form, presetPeriod(value, props.today));
});
watch(
  () => form.metric,
  (key, before) => {
    if (!key || !before || editing.value) return;
    form.target = null;
    form.number = null;
    if (!metric.value?.branchable) form.branch = null;
  },
);

// The preview follows the form a moment after typing stops.
const previewParams = computed(() =>
  form.metric && form.starts_on && form.ends_on && form.starts_on <= form.ends_on
    ? { metric: form.metric, starts_on: form.starts_on, ends_on: form.ends_on, branch: form.branch, target: targetText.value }
    : null,
);
const debounced = refDebounced(previewParams, 350);
const preview = usePreview(debounced);

const periodName = computed(() => {
  if (!form.starts_on || !form.ends_on) return "";
  if (preset.value !== "custom") return t(`goals.periodName.${preset.value}`);
  return `${fmt.day(form.starts_on, "short")} – ${fmt.day(form.ends_on, "short")}`;
});
const suggestedTitle = computed(() => {
  if (!metric.value) return "";
  const target = targetText.value ? show.value({ unit: unit.value }, targetText.value) : "";
  const branch = form.branch ? metrics.data.value?.branches.find((row) => row.id === form.branch)?.name : null;
  const label = t(`goals.metric.${metric.value.key}`);
  const base = target ? t(metric.value.better === "down" ? "goals.titleDown" : "goals.titleUp", { metric: label, target }) : label;
  return [base, branch, periodName.value].filter(Boolean).join(" · ");
});
watch(suggestedTitle, (title) => {
  if (!titleTouched.value) form.title = title;
});

const create = useGoalWrite(goalsApi.create);
const update = useGoalWrite((cid: number, input: { id: number; body: Partial<GoalInput> }) => goalsApi.update(cid, input.id, input.body));
const saving = computed(() => create.isPending.value || update.isPending.value);
const branchOptions = computed(() => [
  ...(metrics.data.value?.company_wide ? [{ value: 0, label: t("goals.wholeCompany") }] : []),
  ...(metrics.data.value?.branches ?? []).map((row) => ({ value: row.id, label: row.name })),
]);
const branchModel = computed<number | null>({
  get: () => (form.branch === null ? (metrics.data.value?.company_wide ? 0 : null) : form.branch),
  set: (value) => (form.branch = value ? value : null),
});
const peopleOptions = computed(() => (metrics.data.value?.people ?? []).map((row) => ({ value: row.id, label: row.name })));

async function save(): Promise<void> {
  error.value = null;
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.metric) errors.metric = t("goals.errMetric");
  if (!targetText.value || (metric.value?.better === "up" && Number(targetText.value) <= 0)) errors.target = t("goals.errTarget");
  if (!form.title.trim()) errors.title = t("goals.errTitle");
  if (!form.starts_on || !form.ends_on || form.starts_on > form.ends_on) errors.period = t("goals.errPeriod");
  if (Object.keys(errors).length) return;
  const body = { title: form.title.trim(), target: targetText.value!, starts_on: form.starts_on!, ends_on: form.ends_on!, owner: form.owner, note: form.note.trim() };
  try {
    if (props.goal) await update.mutateAsync({ id: props.goal.id, body });
    else await create.mutateAsync({ ...body, metric: form.metric!, branch: form.branch });
    toast.success(editing.value ? t("goals.saved") : t("goals.created"));
    open.value = false;
  } catch (failure) {
    if (!isApiError(failure)) throw failure;
    for (const [field, messages] of Object.entries(failure.fieldErrors)) errors[field] = messages[0];
    error.value = failure.detail ?? null;
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('goals.editTitle') : t('goals.newTitle')" :description="t('goals.dialogDescription')" size="lg">
    <div class="flex flex-col gap-5">
      <FormField :label="t('goals.measure')" :error="errors.metric" required>
        <div v-if="metrics.isPending.value" class="grid grid-cols-2 gap-2 sm:grid-cols-3"><SkeletonBlock v-for="n in 6" :key="n" height="64px" /></div>
        <div v-else role="radiogroup" :aria-label="t('goals.measure')" class="grid grid-cols-2 gap-2 sm:grid-cols-3" data-metrics>
          <button
            v-for="row in options"
            :key="row.key"
            type="button"
            role="radio"
            :aria-checked="form.metric === row.key"
            :disabled="!row.available || editing"
            :title="row.available ? t(`goals.hint.${row.key}`) : t('goals.moduleOffHint')"
            :data-metric="row.key"
            :class="[
              'flex min-h-[64px] flex-col items-start gap-1 rounded-[12px] border p-2.5 text-left transition-colors duration-120',
              form.metric === row.key ? 'border-primary bg-accent-soft' : 'border-line bg-surface hover:border-line-strong hover:bg-surface-2',
              'disabled:cursor-not-allowed disabled:opacity-50',
            ]"
            @click="form.metric = row.key"
          >
            <span class="flex items-center gap-1.5 text-sm font-semibold" :class="form.metric === row.key ? 'text-accent-fg' : 'text-fg'">
              <component :is="METRIC_ICONS[row.key]" :size="15" aria-hidden="true" />{{ t(`goals.metric.${row.key}`) }}
            </span>
            <span class="line-clamp-2 text-xs text-muted">{{ row.available ? t(`goals.hint.${row.key}`) : t("goals.moduleOff") }}</span>
          </button>
        </div>
      </FormField>

      <FormField v-if="!editing" :label="t('goals.period')" :error="errors.period">
        <SegmentedControl
          v-model="preset"
          block
          :options="[
            { value: 'month', label: t('goals.preset.month') },
            { value: 'quarter', label: t('goals.preset.quarter') },
            { value: 'half', label: t('goals.preset.half') },
            { value: 'year', label: t('goals.preset.year') },
            { value: 'custom', label: t('goals.preset.custom') },
          ]"
        />
      </FormField>
      <div v-if="preset === 'custom'" class="grid gap-3 sm:grid-cols-2">
        <FormField :label="t('goals.startsOnLabel')"><DatePicker v-model="form.starts_on" /></FormField>
        <FormField :label="t('goals.endsOnLabel')"><DatePicker v-model="form.ends_on" :min="form.starts_on" /></FormField>
      </div>
      <p v-else-if="form.starts_on && form.ends_on" class="-mt-3 text-xs text-muted">{{ fmt.day(form.starts_on, "medium") }} – {{ fmt.day(form.ends_on, "medium") }}</p>

      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="metric?.better === 'down' ? t('goals.ceiling') : t('goals.target')" :error="errors.target" required>
          <MoneyInput v-if="unit === 'money'" v-model="form.target" :currencies="[company.currency]" :invalid="!!errors.target" data-target />
          <NumberInput v-else v-model="form.number" :min="0" :max="unit === 'percent' ? 100 : undefined" :decimals="unit === 'percent' ? 1 : 0" :suffix="unit === 'percent' ? '%' : undefined" :invalid="!!errors.target" data-target />
        </FormField>
        <FormField v-if="metric?.branchable && !editing" :label="t('goals.where')">
          <SelectBox v-model="branchModel" :options="branchOptions" />
        </FormField>
      </div>

      <div class="rounded-[12px] border border-line bg-surface-2/50 p-3 dark:bg-surface-3/30" aria-live="polite" data-preview>
        <div v-if="!previewParams" class="text-sm text-muted">{{ t("goals.previewEmpty") }}</div>
        <div v-else-if="preview.isPending.value" class="grid grid-cols-3 gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="38px" /></div>
        <template v-else-if="preview.data.value">
          <dl class="grid grid-cols-3 gap-3">
            <div>
              <dt class="text-xs text-muted">{{ t("goals.now") }}</dt>
              <dd class="text-sm font-semibold tabular-nums text-fg">{{ show.value({ unit }, preview.data.value.value) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted">{{ metric?.kind === "level" ? t("goals.onDayOne") : t("goals.pace") }}</dt>
              <dd class="text-sm font-semibold tabular-nums text-fg">{{ show.value({ unit }, metric?.kind === "level" ? preview.data.value.baseline : preview.data.value.forecast) }}</dd>
            </div>
            <div>
              <dt class="text-xs text-muted">{{ t("goals.wouldBe") }}</dt>
              <dd><StatusPill v-if="preview.data.value.state" :tone="STATE_TONES[preview.data.value.state]" :label="t(`goals.state.${preview.data.value.state}`)" size="sm" dot /><span v-else class="text-sm text-subtle">—</span></dd>
            </div>
          </dl>
          <p v-if="metric" class="mt-2 text-xs text-muted">{{ t(`goals.hint.${metric.key}`) }}</p>
        </template>
      </div>

      <FormField :label="t('goals.titleLabel')" :error="errors.title" required>
        <TextInput v-model="form.title" :maxlength="200" :invalid="!!errors.title" data-title @update:model-value="titleTouched = true" />
      </FormField>
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField :label="t('goals.owner')" optional>
          <SelectBox v-model="form.owner" :options="peopleOptions" clearable :placeholder="t('goals.ownerPlaceholder')" />
        </FormField>
        <FormField :label="t('goals.note')" optional>
          <TextArea v-model="form.note" :rows="1" autosize :max-rows="4" :maxlength="500" :placeholder="t('goals.notePlaceholder')" />
        </FormField>
      </div>
      <p v-if="error" class="flex items-start gap-2 rounded-[8px] bg-danger-soft px-3 py-2 text-sm text-danger" role="alert"><CircleAlert :size="15" class="mt-0.5 shrink-0" />{{ error }}</p>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :loading="saving" data-save @click="save">{{ editing ? t("common.save") : t("goals.create") }}</UiButton>
    </template>
  </UiDialog>
</template>
