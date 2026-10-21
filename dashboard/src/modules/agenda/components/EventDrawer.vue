<script setup lang="ts">
/**
 * A company event (?event=12): when and where, how it repeats, who is coming and who isn't yet
 * sure, and the reminder. Attendees answer here; managers edit, remind everyone now, or cancel it.
 */
import { Ban, BellRing, Building2, CalendarDays, Clock, Eye, Lock, MapPin, Pencil, Repeat, UserCheck } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PersonCell from "@/components/PersonCell.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { agendaApi, agendaKeys, useEvent } from "../api";
import { remindKey, tokenColor } from "../lib";
import type { AgendaEvent, AttendeeResponse } from "../types";

const emit = defineEmits<{ edit: [event: AgendaEvent] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const client = useQueryClient();
const company = useCompanyStore();
const confirm = useConfirm();

const eventId = computed(() => {
  const raw = route.query.event;
  const value = Number(Array.isArray(raw) ? raw[0] : raw);
  return Number.isFinite(value) && value > 0 ? value : null;
});
const query = useEvent(eventId);
const event = computed(() => query.data.value ?? null);
const busy = ref<string | null>(null);

const when = computed(() => {
  const current = event.value;
  if (!current) return "";
  if (current.all_day) {
    const first = fmt.day(current.start, "weekday");
    return current.end && current.end !== current.start ? `${fmt.day(current.start, "medium")} – ${fmt.day(current.end, "medium")}` : first;
  }
  const day = fmt.day(current.start.slice(0, 10), "weekday");
  const start = fmt.instant(current.start, "time");
  return current.end ? `${day} · ${start} – ${fmt.instant(current.end, "time")}` : `${day} · ${start}`;
});

const reminder = computed(() => {
  const { key, n } = remindKey(event.value?.remind_before ?? null);
  return n !== undefined ? t(key, { n }, n) : t(key);
});

const groups = computed(() => {
  const list = event.value?.attendees ?? [];
  return (["going", "pending", "declined"] as const)
    .map((response) => ({ response, people: list.filter((attendee) => attendee.response === response) }))
    .filter((group) => group.people.length);
});

const answer = computed({
  get: () => (event.value?.my_response === "pending" ? "" : (event.value?.my_response ?? "")),
  set: (value: string) => void respond(value as Exclude<AttendeeResponse, "pending">),
});

async function respond(response: Exclude<AttendeeResponse, "pending">): Promise<void> {
  const current = event.value;
  if (!current) return;
  const key = agendaKeys.event(company.currentId ?? 0, current.id);
  const before = client.getQueryData<AgendaEvent>(key);
  if (before) client.setQueryData<AgendaEvent>(key, { ...before, my_response: response });
  try {
    await agendaApi.respond(company.currentId ?? 0, current.id, response);
    void client.invalidateQueries({ queryKey: key });
    toast.success(response === "going" ? t("agenda.drawer.going") : t("agenda.drawer.declined"));
  } catch {
    if (before) client.setQueryData(key, before);
  }
}

async function remind(): Promise<void> {
  if (!event.value) return;
  busy.value = "remind";
  try {
    const { reminded } = await agendaApi.remind(company.currentId ?? 0, event.value.id);
    toast.success(t("agenda.drawer.reminded", { n: reminded }, reminded));
  } catch {
    // Shown by the HTTP layer.
  } finally {
    busy.value = null;
  }
}

async function cancel(): Promise<void> {
  if (!event.value) return;
  const result = await confirm({
    title: t("agenda.drawer.cancelTitle", { title: event.value.title }),
    message: event.value.attendees.length ? t("agenda.drawer.cancelBody", { n: event.value.attendees.length }, event.value.attendees.length) : t("agenda.drawer.cancelBodyNone"),
    confirmLabel: t("agenda.drawer.cancel"),
    tone: "danger",
    reason: "optional",
    reasonLabel: t("agenda.drawer.cancelReason"),
  });
  if (!result) return;
  busy.value = "cancel";
  try {
    const saved = await agendaApi.cancel(company.currentId ?? 0, event.value.id, result.reason);
    client.setQueryData(agendaKeys.event(company.currentId ?? 0, saved.id), saved);
    void client.invalidateQueries({ queryKey: agendaKeys.all(company.currentId ?? 0) });
    toast.success(t("agenda.drawer.cancelled"));
  } catch {
    // The HTTP layer showed why.
  } finally {
    busy.value = null;
  }
}

const tones = { going: "success", pending: "neutral", declined: "danger" } as const;
</script>

<template>
  <UiDrawer query-key="event" :title="t('agenda.drawer.title')" size="md">
    <div v-if="query.isError.value" class="p-5"><ErrorState compact :error="query.error.value" :retry="() => query.refetch()" /></div>
    <div v-else-if="!event" class="flex flex-col gap-3 p-5">
      <SkeletonBlock width="70%" height="24px" />
      <SkeletonBlock width="50%" />
      <SkeletonBlock height="120px" radius="12px" />
    </div>
    <div v-else class="flex flex-col gap-5 p-5">
      <div class="flex items-start gap-3">
        <span class="mt-1 h-10 w-1.5 shrink-0 rounded-full" :style="{ background: tokenColor(event.color) ?? undefined }" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <StatusPill size="sm" tone="neutral" :dot="false" :label="t(`agenda.kind.${event.kind}`)" />
            <StatusPill v-if="event.cancelled" size="sm" tone="danger" :label="t('agenda.drawer.isCancelled')" />
            <StatusPill v-if="event.visibility === 'attendees'" size="sm" tone="info" :icon="Lock" :dot="false" :label="t('agenda.visibility.attendees')" />
          </div>
          <h2 class="mt-1.5 text-lg font-semibold text-fg">{{ event.title }}</h2>
        </div>
      </div>

      <InlineAlert v-if="event.cancelled" tone="danger" :title="t('agenda.drawer.isCancelled')" :description="event.cancel_reason || t('agenda.drawer.cancelledHint')" />

      <dl class="flex flex-col gap-2.5 text-base">
        <div class="flex items-start gap-3"><dt class="sr-only">{{ t("agenda.drawer.when") }}</dt><CalendarDays :size="17" class="mt-0.5 shrink-0 text-subtle" /><dd class="text-fg">{{ when }}</dd></div>
        <div v-if="event.repeat !== 'none'" class="flex items-start gap-3">
          <dt class="sr-only">{{ t("agenda.dialog.repeat") }}</dt><Repeat :size="17" class="mt-0.5 shrink-0 text-subtle" />
          <dd class="text-fg">{{ t(`agenda.repeat.${event.repeat}`) }}<template v-if="event.repeat_until"> · {{ t("agenda.drawer.until", { day: fmt.day(event.repeat_until, "medium") }) }}</template></dd>
        </div>
        <div v-if="event.place" class="flex items-start gap-3"><dt class="sr-only">{{ t("agenda.dialog.place") }}</dt><MapPin :size="17" class="mt-0.5 shrink-0 text-subtle" /><dd class="text-fg">{{ event.place }}</dd></div>
        <div v-if="event.branch" class="flex items-start gap-3"><dt class="sr-only">{{ t("agenda.dialog.branch") }}</dt><Building2 :size="17" class="mt-0.5 shrink-0 text-subtle" /><dd class="text-fg">{{ event.branch.name }}</dd></div>
        <div class="flex items-start gap-3"><dt class="sr-only">{{ t("agenda.dialog.remind") }}</dt><Clock :size="17" class="mt-0.5 shrink-0 text-subtle" /><dd class="text-muted">{{ t("agenda.drawer.reminder", { when: reminder }) }}</dd></div>
        <div v-if="event.visibility === 'company'" class="flex items-start gap-3"><dt class="sr-only">{{ t("agenda.dialog.visibility") }}</dt><Eye :size="17" class="mt-0.5 shrink-0 text-subtle" /><dd class="text-muted">{{ t("agenda.visibility.companyHint") }}</dd></div>
      </dl>

      <p v-if="event.description" class="whitespace-pre-line rounded-[12px] bg-surface-2/60 px-4 py-3 text-base text-fg dark:bg-surface-2">{{ event.description }}</p>

      <section v-if="event.my_response && !event.cancelled" class="ui-card flex flex-col gap-2.5 p-4" :aria-label="t('agenda.drawer.yourAnswer')">
        <p class="flex items-center gap-2 text-sm font-semibold text-fg"><UserCheck :size="15" class="text-subtle" />{{ t("agenda.drawer.yourAnswer") }}</p>
        <SegmentedControl
          v-model="answer"
          :options="[
            { value: 'going', label: t('agenda.drawer.answerGoing') },
            { value: 'declined', label: t('agenda.drawer.answerDecline') },
          ]"
          block
        />
      </section>

      <section :aria-label="t('agenda.dialog.attendees')">
        <div class="mb-2 flex items-center gap-2">
          <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("agenda.dialog.attendees") }}</h3>
          <span class="text-xs text-muted">{{ t("agenda.drawer.counts", { going: event.responses.going, pending: event.responses.pending, declined: event.responses.declined }) }}</span>
        </div>
        <p v-if="!event.attendees.length" class="text-sm text-muted">{{ t("agenda.drawer.noAttendees") }}</p>
        <div v-for="group in groups" :key="group.response" class="mb-3 last:mb-0">
          <p class="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-subtle">{{ t(`agenda.response.${group.response}`) }} · {{ group.people.length }}</p>
          <ul class="flex flex-col">
            <li v-for="attendee in group.people" :key="attendee.member.id" class="flex items-center gap-2 py-1.5">
              <PersonCell :person="attendee.member" :subtitle="attendee.member.position" size="sm" class="min-w-0 flex-1" />
              <StatusPill size="sm" :tone="tones[attendee.response]" :label="t(`agenda.response.${attendee.response}`)" />
            </li>
          </ul>
        </div>
      </section>

      <p v-if="event.created_by" class="text-xs text-subtle">{{ t("agenda.drawer.createdBy", { name: event.created_by.name, when: fmt.relative(event.created_at) }) }}</p>

    </div>
    <template v-if="event?.can_edit" #footer>
      <div class="flex w-full flex-wrap items-center gap-2">
        <UiButton variant="primary" :icon="Pencil" @click="emit('edit', event)">{{ t("common.edit") }}</UiButton>
        <UiButton v-if="event.attendees.length && !event.cancelled" :icon="BellRing" :loading="busy === 'remind'" @click="remind">{{ t("agenda.drawer.remindNow") }}</UiButton>
        <span class="flex-1" />
        <UiButton v-if="!event.cancelled" variant="ghost" :icon="Ban" class="text-danger" :loading="busy === 'cancel'" @click="cancel">{{ t("agenda.drawer.cancel") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
