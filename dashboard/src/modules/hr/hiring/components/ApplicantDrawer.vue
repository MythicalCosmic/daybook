<script setup lang="ts">
/**
 * One applicant in a side panel synced with `?applicant=`: who they are and how to reach them
 * (call, Telegram), where they are on the way (New → Screening → Interview → Offer → Hired, or
 * turned down and why), their answers, the diploma photo they sent, the team's notes and the whole
 * history. The footer takes the next step: move on, turn down or hire (the page asks first).
 */
import { ArrowRight, CircleCheck, Copy, FileImage, MessageCircle, NotebookPen, Phone, QrCode, RotateCcw, Send, UserCheck, UserPlus, UserX } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { hiringApi, useApplicant, useHiringMutation } from "../api";
import { STAGE_TONES, formatPhone, nextStage, telLink } from "../lib";
import { PIPELINE, type ApplicantDetail, type ApplicantEvent, type Vacancy } from "../types";
import type { Decision } from "./DecisionDialog.vue";

const ImageLightbox = defineAsyncComponent(() => import("@/components/ImageLightbox.vue"));

const props = defineProps<{ vacancy: Vacancy | null }>();
const emit = defineEmits<{ decide: [decision: Decision] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();

const id = computed(() => {
  const raw = route.query.applicant;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useApplicant(id);
const applicant = computed(() => query.data.value ?? null);
/** The applicant inside the panel's body, which only renders once there is one. */
const current = computed(() => applicant.value!);
const next = computed(() => (applicant.value ? nextStage(applicant.value.stage) : null));
const track = [...PIPELINE, "hired"] as const;
const reached = computed(() => {
  const stage = applicant.value?.stage;
  if (!stage || stage === "rejected") return -1;
  return track.indexOf(stage as (typeof track)[number]);
});
const lightbox = ref(false);
const note = ref("");
watch(id, () => (note.value = ""));

const sourceLine = computed(() => {
  const a = applicant.value;
  if (!a) return "";
  return t(a.source === "qr" ? "hr.hiring.drawer.appliedQr" : "hr.hiring.drawer.appliedLink", { when: fmt.relative(a.created_at) });
});

function answerText(kind: string, answer: string): string {
  if (!answer) return t("hr.hiring.drawer.skipped");
  if (kind === "yes_no") return answer === "yes" ? t("common.yes") : t("common.no");
  return answer;
}

function eventTitle(event: ApplicantEvent, name: string): string {
  if (event.kind === "applied") return t("hr.hiring.event.applied", { name });
  if (event.kind === "note") return t("hr.hiring.event.note");
  if (event.to_stage === "hired") return t("hr.hiring.event.hired");
  if (event.to_stage === "rejected") return t("hr.hiring.event.rejected");
  return t("hr.hiring.event.moved", { stage: t(`hr.hiring.stage.${event.to_stage}`) });
}

const events = computed<TimelineEvent[]>(() => {
  const a = applicant.value;
  if (!a) return [];
  return a.events.map((event) => {
    const parts = [event.kind === "note" ? event.text : event.to_stage === "rejected" ? t("hr.hiring.event.reason", { reason: event.text }) : ""];
    if (event.notified) parts.push(event.message ? t("hr.hiring.event.told", { message: event.message }) : t("hr.hiring.event.toldPlain"));
    return {
      key: event.id,
      at: event.created_at,
      title: eventTitle(event, a.name),
      body: parts.filter(Boolean).join("\n") || undefined,
      actor: event.by,
      icon: event.kind === "note" ? NotebookPen : event.kind === "applied" ? (a.source === "qr" ? QrCode : Send) : event.to_stage === "hired" ? UserCheck : event.to_stage === "rejected" ? UserX : ArrowRight,
      tone: event.to_stage === "hired" ? "success" : event.to_stage === "rejected" ? "danger" : event.kind === "note" ? "warning" : "info",
    };
  });
});

const addNote = useHiringMutation((cid, args: { id: number; text: string }) => hiringApi.note(cid, args.id, args.text));
async function saveNote(): Promise<void> {
  const a = applicant.value;
  const text = note.value.trim();
  if (!a || !text) return;
  await addNote.mutateAsync({ id: a.id, text });
  note.value = "";
  toast.success(t("hr.hiring.drawer.noted"));
}

async function copyPhone(phone: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(phone);
    toast.success(t("common.copied"));
  } catch {
    toast.info(formatPhone(phone));
  }
}

function decide(mode: "move" | "reject" | "hire", target?: (typeof PIPELINE)[number]): void {
  const a = applicant.value as ApplicantDetail | null;
  if (!a) return;
  if (mode === "move") emit("decide", { mode, applicant: a, stage: target ?? "screening" });
  else emit("decide", { mode, applicant: a });
}
</script>

<template>
  <UiDrawer query-key="applicant" size="lg" :title="vacancy ? t('hr.hiring.drawer.titleFor', { vacancy: vacancy.title }) : t('hr.hiring.drawer.title')">
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="56px" />
        <SkeletonBlock height="40px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="18px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="applicant" class="flex flex-col gap-5" data-applicant-drawer>
        <!-- Who, and how to reach them -->
        <header class="flex items-start gap-3">
          <UserAvatar :name="current.name" :size="48" />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="min-w-0 truncate text-md font-semibold text-fg">{{ current.name }}</h3>
              <StatusPill :tone="STAGE_TONES[current.stage]" size="sm" :label="t(`hr.hiring.stage.${current.stage}`)" />
            </div>
            <p class="mt-0.5 text-sm text-muted">{{ sourceLine }}<template v-if="current.language !== 'uz'"> · {{ t(`hr.hiring.language.${current.language}`) }}</template></p>
            <div class="mt-2.5 flex flex-wrap gap-2">
              <UiButton v-if="current.phone" size="sm" :icon="Phone" :href="telLink(current.phone)" data-call>{{ formatPhone(current.phone) }}</UiButton>
              <UiTooltip v-if="current.phone" :content="t('common.copy')">
                <UiButton size="sm" variant="ghost" :icon="Copy" :aria-label="t('common.copy')" @click="copyPhone(current.phone)" />
              </UiTooltip>
              <UiButton v-if="current.telegram_username" size="sm" variant="ghost" :icon="MessageCircle" :href="`https://t.me/${current.telegram_username}`" target="_blank">@{{ current.telegram_username }}</UiButton>
            </div>
          </div>
        </header>

        <!-- Where they are -->
        <section :aria-label="t('hr.hiring.drawer.progress')">
          <div v-if="current.stage === 'rejected'" class="flex items-start gap-3 rounded-[12px] bg-danger-soft/60 p-3" data-rejected>
            <UserX :size="18" class="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
            <div class="min-w-0 flex-1">
              <p class="text-sm font-semibold text-fg">{{ t("hr.hiring.drawer.rejectedTitle") }}</p>
              <p class="text-sm text-muted">{{ current.rejected_reason || "—" }}</p>
            </div>
          </div>
          <ol v-else class="flex items-center gap-1" data-track>
            <li v-for="(stage, index) in track" :key="stage" class="flex min-w-0 flex-1 flex-col gap-1.5">
              <span :class="['h-1.5 rounded-full transition-colors', index <= reached ? (current.stage === 'hired' ? 'bg-success' : 'bg-primary') : 'bg-surface-2 dark:bg-surface-3']" />
              <span :class="['truncate text-[11px] font-semibold max-sm:hidden', index === reached ? 'text-fg' : 'text-subtle']">{{ t(`hr.hiring.stage.${stage}`) }}</span>
            </li>
          </ol>
          <p v-if="current.stage !== 'rejected' && reached >= 0" class="mt-1.5 text-xs font-semibold text-fg sm:hidden" data-step>
            {{ t("hr.hiring.drawer.stepOf", { n: reached + 1, total: track.length, stage: t(`hr.hiring.stage.${current.stage}`) }) }}
          </p>
          <RouterLink
            v-if="current.member"
            :to="`/c/${company.currentId}/people/${current.member.id}`"
            class="mt-3 flex items-center gap-2 rounded-[12px] bg-success-soft/70 px-3 py-2.5 text-sm font-semibold text-success hover:underline"
            data-member
          >
            <CircleCheck :size="16" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate">{{ t("hr.hiring.drawer.onTeam", { name: current.member.name }) }}</span>
            <ArrowRight :size="15" aria-hidden="true" />
          </RouterLink>
        </section>

        <!-- Answers -->
        <section class="flex flex-col gap-2" :aria-label="t('hr.hiring.drawer.answers')">
          <h4 class="text-sm font-semibold text-fg">{{ t("hr.hiring.drawer.answers") }}</h4>
          <ol v-if="current.answers.length" class="flex flex-col divide-y divide-[var(--c-border)] rounded-[12px] border border-line" data-answers>
            <li v-for="(row, index) in current.answers" :key="row.id || index" class="flex flex-col gap-0.5 px-3 py-2.5">
              <span class="text-xs text-muted">{{ index + 1 }}. {{ row.text }}</span>
              <span v-if="row.kind === 'yes_no' && row.answer" :class="['w-fit rounded-full px-2 py-0.5 text-xs font-semibold', row.answer === 'yes' ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger']">{{ answerText(row.kind, row.answer) }}</span>
              <span v-else :class="['whitespace-pre-line text-sm', row.answer ? 'text-fg' : 'text-subtle']">{{ answerText(row.kind, row.answer) }}</span>
            </li>
          </ol>
          <p v-else class="text-sm text-muted">{{ t("hr.hiring.drawer.noAnswers") }}</p>
        </section>

        <!-- The diploma photo -->
        <section v-if="current.document" class="flex flex-col gap-2" :aria-label="t('hr.hiring.drawer.document')">
          <h4 class="text-sm font-semibold text-fg">{{ t("hr.hiring.drawer.document") }}</h4>
          <button type="button" class="group relative w-fit overflow-hidden rounded-[12px] border border-line" data-document @click="lightbox = true">
            <img :src="current.document" :alt="t('hr.hiring.drawer.document')" class="h-36 w-auto max-w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]" />
            <span class="absolute bottom-2 left-2 inline-flex items-center gap-1 rounded-full bg-surface/90 px-2 py-0.5 text-xs font-semibold text-fg shadow-xs"><FileImage :size="12" />{{ t("hr.hiring.drawer.openPhoto") }}</span>
          </button>
          <ImageLightbox v-if="lightbox" v-model:open="lightbox" :images="[{ src: current.document, alt: t('hr.hiring.drawer.document'), caption: current.name }]" />
        </section>
        <p v-else-if="vacancy?.asks_document" class="text-sm text-muted">{{ t("hr.hiring.drawer.noDocument") }}</p>

        <!-- Notes and history -->
        <section class="flex flex-col gap-2" :aria-label="t('hr.hiring.drawer.notes')">
          <h4 class="text-sm font-semibold text-fg">{{ t("hr.hiring.drawer.notes") }}</h4>
          <div class="flex flex-col gap-2">
            <TextArea v-model="note" :rows="2" :max-rows="6" autosize :maxlength="2000" :placeholder="t('hr.hiring.drawer.notePlaceholder')" data-note @submit="saveNote" />
            <UiButton size="sm" class="self-end" :icon="NotebookPen" :disabled="!note.trim()" :loading="addNote.isPending.value" data-add-note @click="saveNote">{{ t("hr.hiring.drawer.addNote") }}</UiButton>
          </div>
        </section>
        <section class="flex flex-col gap-2" :aria-label="t('hr.hiring.drawer.history')">
          <h4 class="text-sm font-semibold text-fg">{{ t("hr.hiring.drawer.history") }}</h4>
          <TimelineList :events="events" dense data-history />
        </section>
      </div>
    </div>
    <template v-if="applicant" #footer>
      <template v-if="current.stage === 'rejected'">
        <UiButton :icon="RotateCcw" data-reconsider @click="decide('move', 'screening')">{{ t("hr.hiring.action.reconsider") }}</UiButton>
      </template>
      <template v-else-if="current.stage !== 'hired'">
        <UiButton variant="ghost" class="text-danger" :icon="UserX" data-reject @click="decide('reject')">{{ t("hr.hiring.action.reject") }}</UiButton>
        <span class="flex-1" />
        <UiButton v-if="next && next !== 'hired'" :icon="ArrowRight" data-next @click="decide('move', next)">{{ t("hr.hiring.card.moveTo", { stage: t(`hr.hiring.stage.${next}`) }) }}</UiButton>
        <UiTooltip :content="vacancy?.hire_blocker ?? ''" :disabled="!vacancy?.hire_blocker">
          <UiButton variant="primary" :icon="UserPlus" :disabled="!!vacancy?.hire_blocker" data-hire @click="decide('hire')">{{ t("hr.hiring.action.hire") }}</UiButton>
        </UiTooltip>
      </template>
    </template>
  </UiDrawer>
</template>
