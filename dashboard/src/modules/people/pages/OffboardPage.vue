<script setup lang="ts">
/**
 * The one offboarding wizard (plan §6.2): 1) when and why, 2) one card per step other modules
 * registered (cash held, shifts, contract, unused leave, final payslip…) with what will happen,
 * what blocks it and the questions it asks, 3) confirm. Blockers stop it unless an owner goes
 * ahead anyway; the answers reach every module in `member_left`.
 */
import { AlertTriangle, ArrowLeft, ArrowRight, CircleCheck, Lock, LogOut } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import CheckBox from "@/components/CheckBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import RadioCards from "@/components/RadioCards.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import WizardSteps from "@/components/WizardSteps.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { getOffboardPreview, offboardPerson, peopleKeys, useCompanyId, usePerson, usePersonMutation } from "../api";
import OffboardField from "../components/OffboardField.vue";
import type { OffboardInput, OffboardReason } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();

const memberId = computed(() => Number(route.params.memberId));
const person = usePerson(memberId);
const preview = useQuery({
  queryKey: computed(() => peopleKeys.offboard(cid.value, memberId.value)),
  queryFn: ({ signal }) => getOffboardPreview(cid.value, memberId.value, signal),
  enabled: computed(() => cid.value > 0 && memberId.value > 0),
  staleTime: 0,
});
const skeleton = useDelayedPending(computed(() => preview.isPending.value || person.isPending.value));
const steps = computed(() => preview.data.value?.steps ?? []);
const blockers = computed(() => steps.value.flatMap((step) => step.blockers.map((text) => ({ step: step.label, text }))));

// Answers ------------------------------------------------------------------------------------
const lastDay = ref<string | null>(null);
const reason = ref<OffboardReason | null>(null);
const note = ref("");
const answers = reactive<Record<string, Record<string, unknown>>>({});
const override = ref(false);
const errors = ref<Record<string, string>>({});
watch(
  () => preview.data.value,
  (data) => {
    if (!data) return;
    lastDay.value ??= data.today;
    for (const step of data.steps) answers[step.key] ??= { ...step.defaults };
  },
  { immediate: true },
);

const reasons = computed(() =>
  (preview.data.value?.reasons ?? []).map((value) => ({ value, label: t(`people.offboard.reason.${value}`), description: t(`people.offboard.reasonHint.${value}`) })),
);

// Wizard -------------------------------------------------------------------------------------
type StepId = "when" | "steps" | "confirm";
const current = ref<StepId>("when");
const wizard = computed(() => [
  { id: "when", label: t("people.offboard.when") },
  { id: "steps", label: t("people.offboard.handover"), description: t("people.offboard.handoverHint", { n: steps.value.length }, steps.value.length) },
  { id: "confirm", label: t("people.offboard.confirm") },
]);
const completed = ref<StepId[]>([]);

function checkWhen(): boolean {
  const next: Record<string, string> = {};
  if (!lastDay.value) next.lastDay = t("common.form.required");
  if (!reason.value) next.reason = t("people.offboard.reasonRequired");
  errors.value = next;
  return Object.keys(next).length === 0;
}

function checkSteps(): boolean {
  const next: Record<string, string> = {};
  for (const step of steps.value) {
    for (const field of step.fields) {
      const value = answers[step.key]?.[field.name];
      if (field.required && (value === null || value === undefined || value === "")) next[`${step.key}.${field.name}`] = t("common.form.required");
    }
  }
  errors.value = next;
  return Object.keys(next).length === 0;
}

function go(next: StepId): void {
  if (current.value === "when" && next !== "when" && !checkWhen()) return;
  if (current.value === "steps" && next === "confirm" && !checkSteps()) return;
  if (!completed.value.includes(current.value)) completed.value = [...completed.value, current.value];
  current.value = next;
  window.scrollTo?.({ top: 0, behavior: "smooth" });
}

const canFinish = computed(() => !blockers.value.length || (preview.data.value?.can_override && override.value));
const finish = usePersonMutation((id, body: OffboardInput) => offboardPerson(id, memberId.value, body));

async function submit(): Promise<void> {
  if (!checkWhen() || !checkSteps() || !reason.value) return;
  try {
    await finish.mutateAsync({
      terminated_on: lastDay.value,
      reason: reason.value,
      note: note.value.trim(),
      steps: JSON.parse(JSON.stringify(answers)) as Record<string, Record<string, unknown>>,
      override_blockers: override.value,
    });
    toast.success(t("people.offboard.done", { name: person.data.value?.name ?? "" }), { description: t("people.offboard.doneHint") });
    void router.replace(`/c/${company.currentId}/people/${memberId.value}`);
  } catch {
    // The server's reason is shown; nothing changed.
  }
}

const personUrl = computed(() => `/c/${company.currentId}/people/${memberId.value}`);
</script>

<template>
  <div class="flex w-full max-w-[880px] flex-col gap-5">
    <!-- Left-aligned like every other page; the wizard keeps a readable width. -->
    <PageHeader class="!mb-0" :title="t('people.offboard.title')" :description="t('people.offboard.description')" :back="personUrl" :back-label="person.data.value?.name ?? t('people.title')" />

    <div v-if="skeleton" class="ui-card flex flex-col gap-4 p-5"><SkeletonBlock height="40px" /><SkeletonBlock :lines="4" /><SkeletonBlock height="120px" radius="12px" /></div>
    <ErrorState v-else-if="preview.isError.value" class="ui-card" :error="preview.error.value" :retry="() => preview.refetch()" />

    <template v-else-if="preview.data.value && person.data.value">
      <div class="ui-card flex items-center gap-3 p-4">
        <UserAvatar :name="person.data.value.name" :src="person.data.value.photo_url" :size="44" />
        <div class="min-w-0 flex-1">
          <p class="truncate text-md font-semibold text-fg">{{ person.data.value.name }}</p>
          <p class="truncate text-sm text-muted">{{ [person.data.value.position?.name, person.data.value.home_branch?.name].filter(Boolean).join(" · ") }}</p>
        </div>
        <span v-if="blockers.length" class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-danger-soft px-2.5 py-1 text-xs font-semibold text-danger">
          <AlertTriangle :size="13" aria-hidden="true" />{{ t("people.offboard.blockersCount", { n: blockers.length }, blockers.length) }}
        </span>
      </div>

      <WizardSteps v-model="current" :steps="wizard" :completed="completed" :errors="blockers.length && current === 'confirm' && !canFinish ? ['steps'] : []" />

      <!-- 1. When and why -->
      <section v-if="current === 'when'" class="ui-card flex flex-col gap-5 p-5">
        <FormField :label="t('people.offboard.lastDay')" :hint="t('people.offboard.lastDayHint')" :error="errors.lastDay" required class="max-w-[280px]">
          <DatePicker v-model="lastDay" :max="preview.data.value.today" format="long" />
        </FormField>
        <FormField :label="t('people.offboard.why')" :error="errors.reason" required>
          <RadioCards v-model="reason" :options="reasons" :columns="2" />
        </FormField>
        <FormField :label="t('people.offboard.note')" :hint="t('people.offboard.noteHint')" optional>
          <TextArea v-model="note" :rows="3" :maxlength="1000" :placeholder="t('people.offboard.notePlaceholder')" />
        </FormField>
      </section>

      <!-- 2. What each module needs -->
      <div v-else-if="current === 'steps'" class="flex flex-col gap-4">
        <section v-for="step in steps" :key="step.key" class="ui-card overflow-hidden">
          <header class="flex items-center gap-2 border-b border-line px-5 py-3">
            <h2 class="text-md font-semibold text-fg">{{ step.label }}</h2>
            <span v-if="step.restricted" class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted"><Lock :size="12" aria-hidden="true" />{{ t("people.offboard.noAccess") }}</span>
            <span class="flex-1" />
            <span v-if="step.blockers.length" class="inline-flex items-center gap-1 text-xs font-semibold text-danger"><AlertTriangle :size="13" />{{ t("people.offboard.blocked") }}</span>
            <span v-else class="inline-flex items-center gap-1 text-xs font-semibold text-success"><CircleCheck :size="13" />{{ t("people.offboard.ready") }}</span>
          </header>
          <div class="flex flex-col gap-4 px-5 py-4">
            <p v-if="step.restricted" class="text-sm text-muted">{{ t("people.offboard.restricted") }}</p>
            <ul v-if="step.lines.length" class="flex flex-col gap-1.5">
              <li v-for="line in step.lines" :key="line" class="flex gap-2 text-base text-fg"><span class="mt-[7px] size-1.5 shrink-0 rounded-full bg-subtle" aria-hidden="true" />{{ line }}</li>
            </ul>
            <InlineAlert v-for="blocker in step.blockers" :key="blocker" tone="danger" size="sm" :description="blocker" />
            <div v-if="step.fields.length" class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <OffboardField
                v-for="field in step.fields"
                :key="field.name"
                v-model="answers[step.key]![field.name]"
                :field="field"
                :error="errors[`${step.key}.${field.name}`]"
                :exclude="[memberId]"
              />
            </div>
          </div>
        </section>
        <p v-if="!steps.length" class="ui-card px-5 py-8 text-center text-sm text-muted">{{ t("people.offboard.noSteps") }}</p>
      </div>

      <!-- 3. Confirm -->
      <section v-else class="ui-card flex flex-col gap-5 p-5">
        <dl class="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <dt class="text-xs font-medium text-muted">{{ t("people.offboard.lastDay") }}</dt>
            <dd class="mt-1 text-base font-semibold text-fg">{{ lastDay ? fmt.day(lastDay, "long") : "—" }}</dd>
          </div>
          <div>
            <dt class="text-xs font-medium text-muted">{{ t("people.offboard.why") }}</dt>
            <dd class="mt-1 text-base font-semibold text-fg">{{ reason ? t(`people.offboard.reason.${reason}`) : "—" }}</dd>
          </div>
          <div>
            <dt class="text-xs font-medium text-muted">{{ t("people.offboard.note") }}</dt>
            <dd class="mt-1 text-base text-fg">{{ note.trim() || "—" }}</dd>
          </div>
        </dl>
        <div class="rounded-[12px] border border-line bg-surface-2/50 p-4 dark:bg-surface-2/60">
          <p class="mb-2 text-sm font-semibold text-fg">{{ t("people.offboard.whatHappens") }}</p>
          <ul class="flex flex-col gap-1.5">
            <li v-for="line in steps.flatMap((s) => s.lines)" :key="line" class="flex gap-2 text-sm text-muted"><CircleCheck :size="14" class="mt-0.5 shrink-0 text-success" aria-hidden="true" />{{ line }}</li>
          </ul>
        </div>
        <template v-if="blockers.length">
          <InlineAlert tone="danger" :title="t('people.offboard.blockersTitle')">
            <ul class="mt-1 list-disc pl-4">
              <li v-for="blocker in blockers" :key="blocker.text">{{ blocker.step }}: {{ blocker.text }}</li>
            </ul>
          </InlineAlert>
          <CheckBox v-if="preview.data.value.can_override" v-model="override" :label="t('people.offboard.override')" :description="t('people.offboard.overrideHint')" />
          <p v-else class="text-sm text-muted">{{ t("people.offboard.onlyOwner") }}</p>
        </template>
      </section>

      <div class="flex items-center gap-2">
        <UiButton v-if="current !== 'when'" variant="ghost" :icon="ArrowLeft" @click="current = current === 'confirm' ? 'steps' : 'when'">{{ t("common.back") }}</UiButton>
        <span class="flex-1" />
        <UiButton :to="personUrl" variant="ghost">{{ t("common.cancel") }}</UiButton>
        <UiButton v-if="current === 'when'" variant="primary" :icon-right="ArrowRight" @click="go('steps')">{{ t("common.continue") }}</UiButton>
        <UiButton v-else-if="current === 'steps'" variant="primary" :icon-right="ArrowRight" @click="go('confirm')">{{ t("common.continue") }}</UiButton>
        <UiButton v-else variant="danger" :icon="LogOut" :disabled="!canFinish" :loading="finish.isPending.value" @click="submit">
          {{ t("people.offboard.submit", { name: person.data.value.first_name || person.data.value.name }) }}
        </UiButton>
      </div>
    </template>
  </div>
</template>
