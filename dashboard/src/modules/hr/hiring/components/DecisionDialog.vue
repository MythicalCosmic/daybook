<script setup lang="ts">
/**
 * One step of an applicant's way, asked before it is taken:
 *
 * - **move** to another stage: whether the bot tells them (on by default for an interview and an
 *   offer) and what it adds, such as the day and the address of the interview;
 * - **reject**: the reason for the team (ready answers as chips) and whether they hear a polite
 *   refusal, with an optional word of yours;
 * - **hire**: what they become (the vacancy's position, branch and access), the branch when the
 *   vacancy has none and the company has several, and a message for their first day.
 *
 * `decision` null closes it; the parent gets `done` with the applicant as it now is, or `cancel`.
 */
import { ArrowRight, Building2, KeyRound, Send, UserCheck, UserX } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import { useScopedBranches } from "@/components/pickers";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useCompanyStore } from "@/stores/company";

import { hiringApi, useHiringMutation } from "../api";
import { STAGE_TONES, toldByDefault } from "../lib";
import type { Applicant, ApplicantDetail, PipelineStage, Vacancy } from "../types";

export type Decision =
  | { mode: "move"; applicant: Pick<Applicant, "id" | "name" | "stage">; stage: PipelineStage }
  | { mode: "reject"; applicant: Pick<Applicant, "id" | "name" | "stage"> }
  | { mode: "hire"; applicant: Pick<Applicant, "id" | "name" | "stage"> };

const decision = defineModel<Decision | null>("decision", { default: null });
const props = defineProps<{ vacancy: Vacancy | null }>();
const emit = defineEmits<{ done: [applicant: ApplicantDetail]; cancel: [] }>();

const { t } = useI18n();
const company = useCompanyStore();
const branches = useScopedBranches();

const REASONS = ["experience", "diploma", "noShow", "chosen", "pay"] as const;

const form = reactive({ notify: true, message: "", reason: "", chip: "" as string, branch: null as number | null });
const error = ref<string | null>(null);
const settled = ref(false);

const open = computed({
  get: () => decision.value !== null,
  set: (value: boolean) => {
    if (!value) close();
  },
});

watch(
  decision,
  (next) => {
    if (!next) return;
    settled.value = false;
    error.value = null;
    Object.assign(form, {
      notify: next.mode === "move" ? toldByDefault(next.stage) : true,
      message: "",
      reason: "",
      chip: "",
      branch: props.vacancy?.branch?.id ?? (branches.value.length === 1 ? branches.value[0]!.id : null),
    });
  },
  { immediate: true },
);

const name = computed(() => decision.value?.applicant.name ?? "");
const needsBranch = computed(() => decision.value?.mode === "hire" && !props.vacancy?.branch && branches.value.length > 1);
const title = computed(() => {
  const d = decision.value;
  if (!d) return "";
  if (d.mode === "move") return t("hr.hiring.decide.moveTitle", { name: name.value, stage: t(`hr.hiring.stage.${d.stage}`) });
  if (d.mode === "reject") return t("hr.hiring.decide.rejectTitle", { name: name.value });
  return t("hr.hiring.decide.hireTitle", { name: name.value });
});
/** The first line the bot sends, so the hirer knows what they will read. */
const preview = computed(() => {
  const d = decision.value;
  const companyName = company.current?.name ?? "";
  if (!d) return "";
  if (d.mode === "reject") return t("hr.hiring.decide.previewReject", { company: companyName });
  if (d.mode === "hire") return t("hr.hiring.decide.previewHire", { company: companyName });
  if (d.stage === "interview") return t("hr.hiring.decide.previewInterview", { company: companyName });
  if (d.stage === "offer") return t("hr.hiring.decide.previewOffer", { company: companyName });
  return t("hr.hiring.decide.previewMessage", { company: companyName });
});
const placeholder = computed(() => {
  const d = decision.value;
  if (!d) return "";
  if (d.mode === "move") return t(`hr.hiring.decide.placeholder.${d.stage === "interview" || d.stage === "offer" ? d.stage : "other"}`);
  return t(`hr.hiring.decide.placeholder.${d.mode}`);
});
const confirmLabel = computed(() => {
  const d = decision.value;
  if (!d) return "";
  if (d.mode !== "move") return t(`hr.hiring.action.${d.mode}`);
  if (d.stage === "interview" && form.notify) return t("hr.hiring.action.invite");
  if (d.stage === "offer" && form.notify) return t("hr.hiring.action.offer");
  return t("hr.hiring.action.move");
});
/** A move to screening or back says nothing unless there's a message for them. */
const silentMove = computed(() => decision.value?.mode === "move" && !toldByDefault(decision.value.stage));

function pick(chip: string): void {
  form.chip = form.chip === chip ? "" : chip;
}
const reasonText = computed(() => [form.chip ? t(`hr.hiring.reason.${form.chip}`) : "", form.reason.trim()].filter(Boolean).join(". "));

const act = useHiringMutation(async (cid, d: Decision) => {
  const message = form.notify ? form.message.trim() : "";
  if (d.mode === "move") return hiringApi.move(cid, d.applicant.id, { stage: d.stage, message, notify: silentMove.value ? !!message : form.notify });
  if (d.mode === "reject") return hiringApi.reject(cid, d.applicant.id, { reason: reasonText.value, message, notify: form.notify });
  return hiringApi.hire(cid, d.applicant.id, { message: form.message.trim(), branch_id: needsBranch.value ? form.branch : null });
});

async function confirm(): Promise<void> {
  const d = decision.value;
  if (!d) return;
  error.value = null;
  if (d.mode === "reject" && !reasonText.value) {
    error.value = t("hr.hiring.decide.reasonRequired");
    return;
  }
  if (needsBranch.value && !form.branch) {
    error.value = t("hr.hiring.problem.branch");
    return;
  }
  try {
    const applicant = await act.mutateAsync(d);
    settled.value = true;
    toast.success(
      d.mode === "hire"
        ? t("hr.hiring.decide.hired", { name: applicant.name })
        : d.mode === "reject"
          ? t("hr.hiring.decide.rejected", { name: applicant.name })
          : t("hr.hiring.decide.moved", { name: applicant.name, stage: t(`hr.hiring.stage.${applicant.stage}`) }),
    );
    emit("done", applicant);
    decision.value = null;
  } catch (failure) {
    error.value = isApiError(failure) ? (failure.detail ?? Object.values(failure.fieldErrors)[0]?.[0] ?? null) : null;
  }
}

function close(): void {
  if (!settled.value) emit("cancel");
  decision.value = null;
}
</script>

<template>
  <UiDialog v-model:open="open" size="md" :title="title" mobile="sheet">
    <form v-if="decision" class="flex flex-col gap-4" data-decision @submit.prevent="confirm">
      <!-- Hire: what they become -->
      <template v-if="decision.mode === 'hire'">
        <ul class="flex flex-col gap-2 rounded-[12px] bg-surface-2/60 p-3 text-sm dark:bg-surface-2" data-hire-summary>
          <li class="flex items-center gap-2.5">
            <UserCheck :size="16" class="shrink-0 text-success" aria-hidden="true" />
            <span class="text-muted">{{ t("hr.hiring.field.position") }}:</span>
            <span class="font-semibold text-fg">{{ vacancy?.position?.name ?? t("hr.hiring.decide.positionLater") }}</span>
          </li>
          <li v-if="!needsBranch" class="flex items-center gap-2.5">
            <Building2 :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="text-muted">{{ t("hr.hiring.field.branch") }}:</span>
            <span class="font-semibold text-fg">{{ vacancy?.branch?.name ?? branches[0]?.name ?? "—" }}</span>
          </li>
          <li class="flex items-center gap-2.5">
            <KeyRound :size="16" class="shrink-0 text-subtle" aria-hidden="true" />
            <span class="text-muted">{{ t("hr.hiring.field.access") }}:</span>
            <span class="font-semibold text-fg">{{ vacancy?.role?.name ?? t("hr.hiring.decide.defaultAccess") }}</span>
          </li>
        </ul>
        <FormField v-if="needsBranch" :label="t('hr.hiring.field.branch')" required>
          <BranchPicker v-model="form.branch" :branches="branches" :placeholder="t('hr.hiring.form.branchPlaceholder')" />
        </FormField>
        <p class="text-sm text-muted">{{ t("hr.hiring.decide.hireNext") }}</p>
      </template>

      <!-- Move: where to -->
      <div v-else-if="decision.mode === 'move'" class="flex items-center gap-2 text-sm">
        <StatusPill :tone="STAGE_TONES[decision.applicant.stage]" size="sm" :label="t(`hr.hiring.stage.${decision.applicant.stage}`)" />
        <ArrowRight :size="15" class="text-subtle" aria-hidden="true" />
        <StatusPill :tone="STAGE_TONES[decision.stage]" size="sm" :label="t(`hr.hiring.stage.${decision.stage}`)" />
      </div>

      <!-- Reject: why, for the team -->
      <FormField v-if="decision.mode === 'reject'" :label="t('hr.hiring.decide.reason')" :hint="t('hr.hiring.decide.reasonHint')" required>
        <div class="flex flex-col gap-2.5">
          <div class="flex flex-wrap gap-1.5" role="group" :aria-label="t('hr.hiring.decide.reason')" data-reason-chips>
            <button
              v-for="chip in REASONS"
              :key="chip"
              type="button"
              :aria-pressed="form.chip === chip"
              :class="[
                'pressable h-8 rounded-full border px-3 text-sm transition-colors',
                form.chip === chip ? 'border-primary bg-accent-soft font-semibold text-accent-fg' : 'border-line bg-surface text-fg hover:bg-highlight',
              ]"
              @click="pick(chip)"
            >
              {{ t(`hr.hiring.reason.${chip}`) }}
            </button>
          </div>
          <TextArea v-model="form.reason" :rows="2" :maxlength="200" :placeholder="form.chip ? t('hr.hiring.decide.reasonMore') : t('hr.hiring.decide.reasonPlaceholder')" />
        </div>
      </FormField>

      <!-- What the bot tells them -->
      <div class="flex flex-col gap-3 rounded-[12px] border border-line p-3" data-notify>
        <ToggleSwitch
          v-if="decision.mode !== 'hire'"
          v-model="form.notify"
          layout="row"
          :label="t('hr.hiring.decide.notify')"
          :description="decision.mode === 'reject' ? t('hr.hiring.decide.notifyReject') : silentMove ? t('hr.hiring.decide.notifySilent') : t('hr.hiring.decide.notifyMove')"
        />
        <template v-if="form.notify || decision.mode === 'hire'">
          <p class="flex items-start gap-2 rounded-[10px] bg-surface-2/60 px-3 py-2 text-sm text-fg dark:bg-surface-2" data-preview>
            <Send :size="14" class="mt-0.5 shrink-0 text-info" aria-hidden="true" />
            <span>{{ preview }}</span>
          </p>
          <FormField :label="t('hr.hiring.decide.message')" optional>
            <TextArea v-model="form.message" :rows="3" :max-rows="6" autosize :maxlength="1000" :placeholder="placeholder" />
          </FormField>
        </template>
      </div>

      <InlineAlert v-if="error" tone="danger" :description="error" data-decision-error />
    </form>
    <template #footer>
      <UiButton variant="ghost" :disabled="act.isPending.value" @click="close">{{ t("common.cancel") }}</UiButton>
      <UiButton
        :variant="decision?.mode === 'reject' ? 'danger' : 'primary'"
        :icon="decision?.mode === 'hire' ? UserCheck : decision?.mode === 'reject' ? UserX : ArrowRight"
        :loading="act.isPending.value"
        data-decide
        @click="confirm"
      >
        {{ confirmLabel }}
      </UiButton>
    </template>
  </UiDialog>
</template>
