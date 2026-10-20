<script setup lang="ts">
/**
 * Add or change one shift of the roster: who (or "open shift" for anyone eligible to claim), the
 * day, the hours (a template fills them in one tap), the break, the branch and a note. New shifts
 * are drafts until the roster is published; "Publish now" sends this one at once.
 */
import { CalendarPlus, Trash2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import CheckBox from "@/components/CheckBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import NumberInput from "@/components/NumberInput.vue";
import type { SelectOption } from "@/components/options";
import { useScopedBranches } from "@/components/pickers";
import SelectBox from "@/components/SelectBox.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { useShiftCreate, useShiftDelete, useShiftUpdate } from "../api";
import { slotColor, spanMinutes } from "../lib";
import type { RosterMember, Shift, ShiftTemplate } from "../types";

export interface ShiftDraft {
  shift?: Shift | null;
  memberId?: number | null;
  date: string;
}

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ draft: ShiftDraft | null; members: RosterMember[]; templates: ShiftTemplate[]; branchId?: number | null }>();

const { t } = useI18n();
const fmt = useFormat();
const confirm = useConfirm();
const branches = useScopedBranches();
const create = useShiftCreate();
const update = useShiftUpdate();
const remove = useShiftDelete();

const OPEN = 0;
const form = ref({ member: OPEN as number, date: "", start: "09:00", end: "18:00", breakMinutes: 60 as number | null, branch: 0 as number, position: 0 as number, note: "", publish: false });
const editing = computed(() => !!props.draft?.shift);

watch(
  () => [open.value, props.draft] as const,
  ([isOpen, draft]) => {
    if (!isOpen || !draft) return;
    const shift = draft.shift;
    const member = props.members.find((m) => m.id === (shift?.member_id ?? draft.memberId));
    form.value = {
      member: shift ? (shift.member_id ?? OPEN) : (draft.memberId ?? OPEN),
      date: shift?.date ?? draft.date,
      start: shift?.start ?? props.templates[0]?.starts_at ?? "09:00",
      end: shift?.end ?? props.templates[0]?.ends_at ?? "18:00",
      breakMinutes: shift?.break_minutes ?? props.templates[0]?.break_minutes ?? 60,
      branch: shift?.branch?.id ?? member?.home_branch?.id ?? props.branchId ?? branches.value[0]?.id ?? 0,
      position: shift?.position?.id ?? member?.position?.id ?? 0,
      note: shift?.note ?? "",
      publish: false,
    };
  },
  { immediate: true },
);

const memberOptions = computed<SelectOption<number>[]>(() => [
  { value: OPEN, label: t("attendance.roster.openShift"), description: t("attendance.roster.openShiftHint") },
  ...props.members.map((member) => ({
    value: member.id,
    label: member.name,
    description: [member.position?.name, member.home_branch?.name].filter(Boolean).join(" · ") || undefined,
    avatar: { name: member.name, src: member.photo_url },
  })),
]);
const branchOptions = computed<SelectOption<number>[]>(() => branches.value.map((branch) => ({ value: branch.id, label: branch.name, description: branch.code })));
const positionOptions = computed<SelectOption<number>[]>(() => {
  const seen = new Map<number, string>();
  for (const member of props.members) if (member.position) seen.set(member.position.id, member.position.name);
  return [{ value: 0, label: t("attendance.roster.anyPosition") }, ...[...seen].map(([value, label]) => ({ value, label }))];
});

const length = computed(() => spanMinutes(form.value.start, form.value.end, form.value.breakMinutes ?? 0));
const overnight = computed(() => form.value.end <= form.value.start);
const busy = computed(() => create.isPending.value || update.isPending.value || remove.isPending.value);

function useTemplate(template: ShiftTemplate): void {
  form.value.start = template.starts_at;
  form.value.end = template.ends_at;
  form.value.breakMinutes = template.break_minutes;
}

async function save(): Promise<void> {
  const value = form.value;
  const body = {
    member_id: value.member === OPEN ? null : value.member,
    date: value.date,
    start: value.start,
    end: value.end,
    break_minutes: value.breakMinutes ?? 0,
    branch_id: value.branch || null,
    position_id: value.position || null,
    note: value.note,
  };
  try {
    const shift = props.draft?.shift;
    if (shift) await update.mutateAsync({ shift, patch: body });
    else await create.mutateAsync({ ...body, publish: value.publish });
    toast.success(shift ? t("attendance.roster.saved") : value.publish ? t("attendance.roster.addedPublished") : t("attendance.roster.added"));
    open.value = false;
  } catch {
    // The server's message is shown by the HTTP client.
  }
}

async function destroy(): Promise<void> {
  const shift = props.draft?.shift;
  if (!shift) return;
  const answer = await confirm({
    title: t("attendance.roster.removeTitle"),
    message: shift.published ? t("attendance.roster.removePublished") : t("attendance.roster.removeDraft"),
    confirmLabel: t("common.delete"),
    tone: "danger",
  });
  if (!answer) return;
  try {
    await remove.mutateAsync(shift);
    toast.success(t("attendance.roster.removed"));
    open.value = false;
  } catch {
    // Shown by the HTTP client.
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="editing ? t('attendance.roster.editTitle') : t('attendance.roster.addTitle')" :description="form.date ? fmt.day(form.date, 'weekday') : undefined" size="md">
    <form class="flex flex-col gap-4" @submit.prevent="save">
      <FormField :label="t('attendance.roster.who')">
        <SelectBox v-model="form.member" :options="memberOptions" />
      </FormField>
      <div v-if="templates.length" class="flex flex-col gap-1.5">
        <span class="text-xs font-medium text-muted">{{ t("attendance.roster.templates") }}</span>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="template in templates"
            :key="template.id"
            type="button"
            :class="[
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              form.start === template.starts_at && form.end === template.ends_at ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-fg hover:bg-highlight',
            ]"
            @click="useTemplate(template)"
          >
            <span class="size-2 rounded-full" :style="{ background: slotColor(template.color) }" aria-hidden="true" />
            {{ template.name }} <span class="tabular-nums text-muted">{{ template.starts_at }}–{{ template.ends_at }}</span>
          </button>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <FormField :label="t('attendance.roster.day')" class="col-span-2 sm:col-span-2"><DatePicker v-model="form.date" /></FormField>
        <FormField :label="t('attendance.roster.start')"><TimePicker v-model="form.start" :step="15" /></FormField>
        <FormField :label="t('attendance.roster.end')"><TimePicker v-model="form.end" :step="15" /></FormField>
      </div>
      <p class="-mt-2 text-xs text-muted">
        {{ t("attendance.roster.length", { d: fmt.duration(length) }) }}<template v-if="overnight"> · {{ t("attendance.roster.overnight") }}</template>
      </p>
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('attendance.roster.break')"><NumberInput v-model="form.breakMinutes" :min="0" :max="480" :step="15" :suffix="t('attendance.unit.min')" /></FormField>
        <FormField v-if="branchOptions.length > 1" :label="t('attendance.branch')"><SelectBox v-model="form.branch" :options="branchOptions" /></FormField>
      </div>
      <FormField v-if="form.member === OPEN" :label="t('attendance.roster.position')" :hint="t('attendance.roster.positionHint')">
        <SelectBox v-model="form.position" :options="positionOptions" />
      </FormField>
      <FormField :label="t('attendance.roster.note')" optional>
        <TextInput v-model="form.note" :maxlength="200" :placeholder="t('attendance.roster.notePlaceholder')" />
      </FormField>
      <CheckBox v-if="!editing" v-model="form.publish" :label="t('attendance.roster.publishNow')" :description="t('attendance.roster.publishNowHint')" />
    </form>
    <template #footer>
      <UiButton v-if="editing" variant="ghost" :icon="Trash2" class="mr-auto text-danger" :disabled="busy || draft?.shift?.has_record" @click="destroy">{{ t("common.delete") }}</UiButton>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="CalendarPlus" :loading="busy" @click="save">{{ editing ? t("common.save") : t("attendance.roster.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
