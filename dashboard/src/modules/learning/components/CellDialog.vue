<script setup lang="ts">
/**
 * One cell of an unchangeable list: a topic × a student. Empty, it writes a line (the day, today
 * unless changed and never in the future, and an optional note), after saying the line stays for
 * good. Holding a line, it shows it (its number, day, note, who wrote it and when) and the cell's
 * history, corrected lines struck through with their reasons; "Correct…" asks for a reason, then
 * for a confirm, and takes the line back with a new, visible one.
 */
import { Check, CornerDownRight, Undo2 } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError, unshownFieldError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyToday } from "@/stores/company";

import { learningApi, useApplyList } from "../api";
import { cellKey, cellsOf, dottedDay, shortDigest, standingLine, studentLine } from "../lists";
import type { StudyListDetail, StudyMark } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ list: StudyListDetail; topicId: number; studentId: number; canWrite: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const cid = useCompanyId();
const today = useCompanyToday();
const apply = useApplyList();

const REASON_MIN = 3;
const REASON_MAX = 300;

const topic = computed(() => props.list.topics.find((row) => row.id === props.topicId) ?? null);
const student = computed(() => props.list.students.find((row) => row.id === props.studentId) ?? null);
const cell = computed(() => cellsOf(props.list.marks).get(cellKey(props.topicId, props.studentId)) ?? null);
const standing = computed(() => cell.value?.standing ?? null);
const history = computed(() => cell.value?.history ?? []);
const byId = computed(() => new Map(props.list.marks.map((mark) => [mark.id, mark])));

const correcting = ref(false);
const mode = computed<"mark" | "line" | "correct" | "history">(() => {
  if (standing.value) return correcting.value && props.canWrite ? "correct" : "line";
  return props.canWrite ? "mark" : "history";
});
/** The history is worth showing when it says more than the line on screen. */
const showHistory = computed(() => history.value.length > (standing.value ? 1 : 0));

const title = computed(() => {
  if (mode.value === "mark") return t("learning.lists.mark.title");
  if (mode.value === "history") return t("learning.lists.cell.historyTitle");
  return t("learning.lists.cell.lineTitle", { n: standing.value?.number ?? "" });
});

// The forms ---------------------------------------------------------------------------------

const day = ref<string | null>(null);
const note = ref("");
const reason = ref("");
const errors = ref<{ studied_on?: string; note?: string; reason?: string }>({});
const formError = ref<string | null>(null);
const busy = ref(false);

watch(
  [open, () => props.topicId, () => props.studentId],
  () => {
    if (!open.value) return;
    day.value = today.value;
    note.value = "";
    reason.value = "";
    correcting.value = false;
    errors.value = {};
    formError.value = null;
  },
  { immediate: true },
);

function failed(error: unknown, fields: readonly ("studied_on" | "note" | "reason")[]): void {
  const found = isApiError(error) ? error.fieldErrors : {};
  errors.value = Object.fromEntries(fields.map((field) => [field, found[field]?.[0]]).filter((entry) => entry[1]));
  formError.value = unshownFieldError(error, [...fields]);
}

async function write(): Promise<void> {
  if (busy.value || mode.value !== "mark") return;
  errors.value = {};
  formError.value = null;
  if (day.value && day.value > today.value) {
    errors.value = { studied_on: t("learning.lists.mark.future") };
    return;
  }
  busy.value = true;
  try {
    const detail = apply(
      await learningApi.mark(cid.value, props.list.id, {
        topic_id: props.topicId,
        student_id: props.studentId,
        ...(day.value ? { studied_on: day.value } : {}),
        ...(note.value.trim() ? { note: note.value.trim() } : {}),
      }),
    );
    const line = standingLine(detail.marks, props.topicId, props.studentId);
    toast.success(t("learning.lists.mark.done", { n: line?.number ?? "" }));
    open.value = false;
  } catch (error) {
    failed(error, ["studied_on", "note"]);
  } finally {
    busy.value = false;
  }
}

function startCorrecting(): void {
  correcting.value = true;
  reason.value = "";
  errors.value = {};
  formError.value = null;
}

async function correct(): Promise<void> {
  const line = standing.value;
  if (busy.value || !line || mode.value !== "correct") return;
  const text = reason.value.trim();
  errors.value = {};
  formError.value = null;
  if (text.length < REASON_MIN) {
    errors.value = { reason: t("learning.lists.correct.tooShort", { n: REASON_MIN }) };
    return;
  }
  busy.value = true;
  try {
    apply(await learningApi.correct(cid.value, props.list.id, line.id, text));
    toast.success(t("learning.lists.correct.done", { n: line.number }));
    open.value = false;
  } catch (error) {
    failed(error, ["reason"]);
  } finally {
    busy.value = false;
  }
}

// The history -------------------------------------------------------------------------------

const correctedIds = computed(() => new Set(history.value.flatMap((mark) => (mark.kind === "correction" && mark.corrects_id !== null ? [mark.corrects_id] : []))));
const takenBack = (mark: StudyMark) => mark.kind === "studied" && (mark.corrected_by_id !== null || correctedIds.value.has(mark.id));
const target = (mark: StudyMark) => (mark.corrects_id !== null ? (byId.value.get(mark.corrects_id) ?? null) : null);
</script>

<template>
  <UiDialog v-model:open="open" :title="title" size="md" :dismissable="!busy">
    <div class="flex flex-col gap-4" data-testid="cell-dialog">
      <!-- Where: the student and the topic. -->
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 rounded-[10px] border border-line bg-surface-2/50 px-3.5 py-3 text-sm dark:bg-surface-3/30">
        <dt class="text-muted">{{ t("learning.lists.student.label") }}</dt>
        <dd class="min-w-0 font-medium text-fg">
          {{ student?.name ?? "—" }}<span v-if="student && studentLine(student)" class="font-normal text-muted"> · {{ studentLine(student) }}</span>
        </dd>
        <dt class="text-muted">{{ t("learning.lists.topic.label") }}</dt>
        <dd class="min-w-0 font-medium text-fg">
          <span v-if="topic" class="tabular-nums">{{ topic.number }}. </span>{{ topic?.title ?? "—" }}
        </dd>
      </dl>

      <InlineAlert v-if="formError" tone="danger" :description="formError" />

      <!-- The line the cell holds. -->
      <div v-if="standing && mode === 'line'" class="flex items-start gap-3 rounded-[12px] border border-[color-mix(in_srgb,var(--c-success)_26%,transparent)] bg-success-soft/60 p-3.5" data-testid="cell-line">
        <span class="grid size-9 shrink-0 place-items-center rounded-full bg-success text-white" aria-hidden="true"><Check :size="18" :stroke-width="3" /></span>
        <div class="min-w-0 flex-1">
          <p class="text-base font-semibold text-fg">{{ t("learning.lists.cell.studiedOn", { day: standing.studied_on ? fmt.day(standing.studied_on, "long") : "—" }) }}</p>
          <p v-if="standing.note" class="mt-1 whitespace-pre-line text-sm text-fg">{{ standing.note }}</p>
          <p class="mt-1.5 text-xs text-muted">
            {{ t("learning.lists.cell.writtenBy", { name: standing.written_by || "—", when: fmt.instant(standing.written_at) }) }}
          </p>
          <p class="mt-0.5 text-xs text-subtle">
            {{ t("learning.lists.lineNo", { n: standing.number }) }} ·
            <span class="font-mono" :title="standing.digest">{{ shortDigest(standing.digest, 12) }}</span>
          </p>
        </div>
      </div>

      <!-- Writing a line. -->
      <form v-if="mode === 'mark'" class="flex flex-col gap-4" data-testid="mark-form" @submit.prevent="write">
        <div class="grid gap-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
          <FormField :label="t('learning.lists.mark.day')" :error="errors.studied_on" required>
            <DatePicker v-model="day" :max="today" />
          </FormField>
          <FormField :label="t('learning.lists.mark.note')" :error="errors.note" optional>
            <TextInput v-model="note" :maxlength="300" :placeholder="t('learning.lists.mark.notePlaceholder')" />
          </FormField>
        </div>
        <InlineAlert tone="warning" :title="t('learning.lists.mark.warningTitle')" :description="t('learning.lists.mark.warning')" />
        <button type="submit" class="hidden" tabindex="-1" aria-hidden="true" />
      </form>

      <!-- Correcting it: a reason, then the confirm. -->
      <form v-if="mode === 'correct' && standing" class="flex flex-col gap-4" data-testid="correct-form" @submit.prevent="correct">
        <InlineAlert tone="danger" :icon="Undo2" :title="t('learning.lists.correct.title', { n: standing.number })" :description="t('learning.lists.correct.body')" />
        <FormField :label="t('learning.lists.correct.reason')" :error="errors.reason" :count="reason.length" :max="REASON_MAX" required>
          <TextArea v-model="reason" :rows="2" :maxlength="REASON_MAX" autofocus :placeholder="t('learning.lists.correct.reasonPlaceholder')" @submit="correct" />
        </FormField>
      </form>

      <!-- The cell's history, oldest first. -->
      <section v-if="showHistory" class="flex flex-col gap-2" data-testid="cell-history">
        <h3 class="text-xs font-semibold uppercase tracking-[0.04em] text-muted">{{ t("learning.lists.cell.history") }}</h3>
        <ol class="flex flex-col divide-y divide-line rounded-[10px] border border-line">
          <li v-for="mark in history" :key="mark.id" class="flex items-start gap-2.5 px-3 py-2.5 text-sm">
            <span class="w-9 shrink-0 font-mono text-xs leading-5 text-subtle tabular-nums">#{{ mark.number }}</span>
            <div v-if="mark.kind === 'studied'" class="min-w-0 flex-1">
              <p :class="['leading-5', takenBack(mark) ? 'text-subtle line-through decoration-[color-mix(in_srgb,var(--c-danger)_70%,transparent)]' : 'text-fg']" :data-struck="takenBack(mark) || undefined">
                {{ t("learning.lists.cell.studiedShort", { day: dottedDay(mark.studied_on) }) }}<template v-if="mark.note"> · {{ mark.note }}</template>
              </p>
              <p class="text-xs text-muted">{{ mark.written_by || "—" }} · {{ fmt.instant(mark.written_at, "short") }}</p>
            </div>
            <div v-else class="min-w-0 flex-1">
              <p class="flex items-start gap-1 leading-5 text-warning">
                <CornerDownRight :size="14" class="mt-[3px] shrink-0" aria-hidden="true" />
                <span class="min-w-0">
                  <span class="font-semibold">{{ t("learning.lists.correctsLine", { n: target(mark)?.number ?? "?" }) }}</span>
                  <span class="text-fg">: {{ mark.note }}</span>
                </span>
              </p>
              <p class="pl-[18px] text-xs text-muted">{{ mark.written_by || "—" }} · {{ fmt.instant(mark.written_at, "short") }}</p>
            </div>
          </li>
        </ol>
      </section>
    </div>

    <template #footer>
      <template v-if="mode === 'mark'">
        <UiButton variant="ghost" :disabled="busy" @click="open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" data-testid="mark-write" @click="write">{{ t("learning.lists.mark.write") }}</UiButton>
      </template>
      <template v-else-if="mode === 'correct'">
        <UiButton variant="ghost" :disabled="busy" @click="correcting = false">{{ t("common.back") }}</UiButton>
        <UiButton variant="danger" :loading="busy" :disabled="reason.trim().length < REASON_MIN" data-testid="correct-confirm" @click="correct">
          {{ t("learning.lists.correct.confirm") }}
        </UiButton>
      </template>
      <template v-else>
        <UiButton v-if="mode === 'line' && canWrite" variant="secondary" :icon="Undo2" class="mr-auto" data-testid="cell-correct" @click="startCorrecting">
          {{ t("learning.lists.correct.start") }}
        </UiButton>
        <UiButton variant="ghost" @click="open = false">{{ t("common.close") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
