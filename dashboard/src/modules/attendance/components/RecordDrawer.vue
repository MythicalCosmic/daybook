<script setup lang="ts">
/**
 * One check-in record in a drawer synced with `?record=` (plan §6.2: full detail without leaving the
 * page): the day as a timeline, where the taps happened against the branch's geofence, the minutes
 * it earned, the selfie, and for managers the audited actions: correct the times, excuse an
 * absence, decide overtime. The History tab reads the audit log.
 */
import { Camera, Check, Clock3, LogIn, LogOut, PencilLine, ShieldCheck } from "@lucide/vue";
import { DialogTitle } from "reka-ui";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import AuditTrail from "@/components/AuditTrail.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useNow } from "@/lib/useNow";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { editRecord, excuseRecord, useCompanyId, useOvertimeDecision, useRecord, useRefresh } from "../api";
import { clockOf, formatDistance, localDateTime } from "../lib";
import type { RecordDetail } from "../types";

const MapView = defineAsyncComponent(() => import("@/components/MapView.vue"));

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const companyId = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();
const overtime = useOvertimeDecision();

const recordId = useRouteState("record", rs.optionalNumber(), { push: true });
const query = useRecord(recordId);
const record = computed<RecordDetail | undefined>(() => query.data.value);
const canManage = computed(() => company.can("attendance.manage"));
const tab = ref<"day" | "history">("day");
const lightbox = ref(false);
watch(recordId, () => {
  tab.value = "day";
  editing.value = false;
});

const STATUS_TONES: Record<RecordDetail["status"], StatusTone> = {
  open: "success",
  closed: "neutral",
  auto_closed: "warning",
  absent: "danger",
  excused: "info",
};
const units = computed(() => ({ m: t("attendance.unit.m"), km: t("attendance.unit.km") }));

const events = computed<TimelineEvent[]>(() => {
  const value = record.value;
  if (!value) return [];
  const list: TimelineEvent[] = [];
  if (value.shift) {
    list.push({
      key: "shift",
      at: value.shift.starts_at,
      title: t("attendance.record.planned", { start: value.shift.start, end: value.shift.end }),
      body: value.shift.branch?.name,
      icon: Clock3,
      tone: "neutral",
    });
  }
  if (value.check_in_at) {
    const where = value.in_distance_m !== null ? t("attendance.record.distance", { d: formatDistance(value.in_distance_m, units.value), branch: value.branch?.name ?? "" }) : t("attendance.flag.no_location");
    list.push({
      key: "in",
      at: value.check_in_at,
      title: value.is_late ? t("attendance.record.inLate", { late: fmt.duration(value.late_minutes) }) : t("attendance.record.in"),
      body: where,
      meta: t(`attendance.source.${value.in_source || "app"}`),
      icon: LogIn,
      tone: value.is_late ? "warning" : "success",
    });
  }
  if (value.check_out_at) {
    list.push({
      key: "out",
      at: value.check_out_at,
      title: value.status === "auto_closed" ? t("attendance.record.autoClosed") : t("attendance.record.out"),
      body: value.out_distance_m !== null ? t("attendance.record.distance", { d: formatDistance(value.out_distance_m, units.value), branch: value.branch?.name ?? "" }) : undefined,
      meta: value.out_source ? t(`attendance.source.${value.out_source}`) : undefined,
      icon: LogOut,
      tone: value.status === "auto_closed" ? "warning" : "neutral",
    });
  }
  return list;
});

const now = useNow();
/** Minutes since the check-in of a record still open (the break isn't known yet). */
const soFar = computed(() => {
  const value = record.value;
  if (value?.status !== "open" || !value.check_in_at) return 0;
  return Math.max(0, Math.floor((now.value - Date.parse(value.check_in_at)) / 60_000));
});
/** An absent or excused day has no times: one sentence says so instead of a grid of dashes. */
const noTimes = computed(() => record.value?.status === "absent" || record.value?.status === "excused");

const facts = computed<DescriptionItem[]>(() => {
  const value = record.value;
  if (!value || noTimes.value) return [];
  const finished = value.worked_minutes ? fmt.duration(value.worked_minutes) : "—";
  const running = soFar.value ? t("attendance.record.soFar", { d: fmt.duration(soFar.value) }) : "—";
  const items: DescriptionItem[] = [
    { key: "worked", label: t("attendance.record.worked"), value: value.status === "open" ? running : finished },
    { key: "late", label: t("attendance.record.late"), value: value.is_late ? fmt.duration(value.late_minutes) : "—" },
    { key: "early", label: t("attendance.record.early"), value: value.early_leave_minutes ? fmt.duration(value.early_leave_minutes) : "—" },
    {
      key: "overtime",
      label: t("attendance.record.overtime"),
      value: value.overtime_minutes ? `${fmt.duration(value.overtime_minutes)} · ${t(`attendance.overtime.${value.overtime_status}`)}` : "—",
    },
  ];
  if (value.in_accuracy_m !== null) items.push({ key: "accuracy", label: t("attendance.record.accuracy"), value: `± ${value.in_accuracy_m} ${t("attendance.unit.m")}` });
  if (value.edited_by) items.push({ key: "edited", label: t("attendance.record.editedBy"), value: value.edited_by });
  return items;
});

const mapPoints = computed(() => {
  const value = record.value;
  if (!value) return [];
  const points = [];
  if (value.in_lat && value.in_lng) {
    points.push({ id: "in", lat: value.in_lat, lng: value.in_lng, tone: value.flags.includes("outside_geofence") ? ("bad" as const) : value.flags.includes("low_accuracy") ? ("warn" as const) : ("ok" as const), label: t("attendance.record.in") });
  }
  if (value.out_lat && value.out_lng) points.push({ id: "out", lat: value.out_lat, lng: value.out_lng, tone: "ok" as const, label: t("attendance.record.out") });
  return points;
});

// Correcting the times ------------------------------------------------------------------------

const editing = ref(false);
const form = ref({ in: "", out: "", reason: "" });
const saving = ref(false);
const error = ref<string | null>(null);

function startEdit(): void {
  const value = record.value;
  if (!value) return;
  form.value = {
    in: clockOf(value.check_in_at) || value.shift?.start || "",
    out: clockOf(value.check_out_at) || value.shift?.end || "",
    reason: "",
  };
  error.value = null;
  editing.value = true;
}

async function saveEdit(): Promise<void> {
  const value = record.value;
  if (!value) return;
  if (!form.value.reason.trim()) {
    error.value = t("attendance.record.reasonNeeded");
    return;
  }
  saving.value = true;
  try {
    await editRecord(companyId.value, value.id, {
      check_in_at: form.value.in ? localDateTime(value.date, form.value.in) : null,
      check_out_at: form.value.out ? localDateTime(value.date, form.value.out, form.value.in) : null,
      reason: form.value.reason.trim(),
    });
    toast.success(t("attendance.record.saved"));
    editing.value = false;
    refresh();
  } catch {
    // The error toast comes from the HTTP client.
  } finally {
    saving.value = false;
  }
}

async function excuse(): Promise<void> {
  const value = record.value;
  if (!value) return;
  await confirm({
    title: t("attendance.record.excuseTitle", { name: value.member.name }),
    message: t("attendance.record.excuseBody"),
    confirmLabel: t("attendance.record.excuse"),
    reason: "required",
    onConfirm: async (reason) => {
      await excuseRecord(companyId.value, value.id, reason);
      toast.success(t("attendance.record.excused"));
      refresh();
    },
  });
}

async function decide(approve: boolean, reason = ""): Promise<void> {
  const value = record.value;
  if (!value) return;
  await overtime.mutateAsync({ record: value, approve, reason });
  toast.success(approve ? t("attendance.overtime.approvedToast") : t("attendance.overtime.rejectedToast"));
}
</script>

<template>
  <UiDrawer query-key="record" size="md" :title="record?.member.name ?? t('attendance.record.title')">
    <template #title>
      <div v-if="record" class="flex min-w-0 items-center gap-3">
        <UserAvatar :name="record.member.name" :src="record.member.photo_url" :size="36" />
        <div class="min-w-0">
          <DialogTitle class="truncate text-md font-semibold text-fg">{{ record.member.name }}</DialogTitle>
          <p class="truncate text-xs text-muted">{{ fmt.day(record.date, "weekday") }}<template v-if="record.branch"> · {{ record.branch.name }}</template></p>
        </div>
      </div>
      <template v-else>
        <DialogTitle class="sr-only">{{ t("attendance.record.title") }}</DialogTitle>
        <SkeletonBlock width="60%" height="20px" />
      </template>
    </template>

    <div v-if="query.isPending.value" class="flex flex-col gap-4 p-5">
      <SkeletonBlock height="22px" width="40%" radius="999px" />
      <SkeletonBlock :lines="4" />
      <SkeletonBlock height="180px" radius="10px" />
    </div>
    <ErrorState v-else-if="query.isError.value" class="p-5" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="record" class="flex flex-col gap-5 p-5">
      <div class="flex flex-wrap items-center gap-1.5">
        <StatusPill :tone="STATUS_TONES[record.status]" :label="t(`attendance.status.${record.status}`)" :live="record.status === 'open'" />
        <StatusPill v-if="record.is_late" tone="warning" :label="t('attendance.record.lateBy', { late: fmt.duration(record.late_minutes) })" />
        <StatusPill v-for="flag in record.flags" :key="flag" size="sm" :tone="flag === 'outside_geofence' ? 'danger' : flag === 'edited' ? 'info' : 'neutral'" :label="t(`attendance.flag.${flag}`)" />
      </div>

      <SegmentedControl v-model="tab" size="sm" :options="[{ value: 'day', label: t('attendance.record.tabDay') }, { value: 'history', label: t('common.audit.title') }]" />

      <template v-if="tab === 'day'">
        <InlineAlert v-if="record.overtime_status === 'pending' && canManage" tone="warning" :title="t('attendance.overtime.pendingTitle', { extra: fmt.duration(record.overtime_minutes) })">
          <ApproveRejectButtons class="mt-2" :on-approve="() => decide(true)" :on-reject="(reason) => decide(false, reason)" :reject-title="t('attendance.overtime.rejectTitle')" />
        </InlineAlert>

        <TimelineList v-if="events.length" :events="events" :group="false" dense />
        <p v-if="noTimes" :class="['rounded-[10px] px-3 py-3 text-sm', record.status === 'absent' ? 'bg-danger-soft text-danger' : 'bg-info-soft text-info']">
          {{ record.status === "absent" ? t("attendance.record.absentNote") : t("attendance.record.excusedNote") }}
        </p>
        <p v-else-if="!events.length" class="rounded-[10px] bg-surface-2 px-3 py-3 text-sm text-muted">{{ t("attendance.record.noTimes") }}</p>

        <MapView v-if="mapPoints.length && record.branch_geo" :branches="[record.branch_geo]" :points="mapPoints" height="200px" :interactive="false" />

        <DescriptionList v-if="facts.length" :items="facts" :columns="2" />

        <div v-if="record.photo_url" class="flex items-center gap-3">
          <button type="button" class="overflow-hidden rounded-[10px] border border-line" @click="lightbox = true">
            <img :src="record.photo_url" :alt="t('attendance.record.selfie')" class="size-20 object-cover" />
          </button>
          <div class="text-xs text-muted"><Camera :size="12" class="mr-1 inline" />{{ t("attendance.record.selfie") }}</div>
          <ImageLightbox v-model:open="lightbox" :images="[{ src: record.photo_url, alt: t('attendance.record.selfie') }]" />
        </div>

        <p v-if="record.note" class="rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm text-fg">“{{ record.note }}”</p>

        <form v-if="editing" class="flex flex-col gap-3 rounded-[12px] border border-line p-3" @submit.prevent="saveEdit">
          <p class="text-sm font-semibold text-fg">{{ t("attendance.record.correctTitle") }}</p>
          <div class="grid grid-cols-2 gap-3">
            <FormField :label="t('attendance.record.came')"><TimePicker v-model="form.in" :step="5" /></FormField>
            <FormField :label="t('attendance.record.left')"><TimePicker v-model="form.out" :step="5" /></FormField>
          </div>
          <FormField :label="t('common.reason')" :error="error" required :hint="t('attendance.record.reasonHint')">
            <TextArea v-model="form.reason" :rows="2" :maxlength="300" :placeholder="t('attendance.record.reasonPlaceholder')" />
          </FormField>
          <div class="flex justify-end gap-2">
            <UiButton variant="ghost" size="sm" @click="editing = false">{{ t("common.cancel") }}</UiButton>
            <UiButton variant="primary" size="sm" type="submit" :loading="saving" :icon="Check">{{ t("common.save") }}</UiButton>
          </div>
        </form>
      </template>

      <AuditTrail v-else target-type="attendancerecord" :target-id="record.id" :field-labels="{ check_in_at: t('attendance.record.came'), check_out_at: t('attendance.record.left'), status: t('attendance.record.statusLabel'), note: t('attendance.record.note') }" />
    </div>

    <template v-if="record && canManage && tab === 'day' && !editing" #footer>
      <div class="flex w-full flex-wrap items-center justify-between gap-2">
        <span class="inline-flex items-center gap-1.5 text-xs text-muted"><ShieldCheck :size="13" aria-hidden="true" />{{ t("attendance.record.audited") }}</span>
        <div class="flex gap-2">
          <UiButton v-if="record.status === 'absent'" size="sm" @click="excuse">{{ t("attendance.record.excuse") }}</UiButton>
          <UiButton size="sm" variant="primary" :icon="PencilLine" @click="startEdit">{{ t("attendance.record.correct") }}</UiButton>
        </div>
      </div>
    </template>
  </UiDrawer>
</template>
