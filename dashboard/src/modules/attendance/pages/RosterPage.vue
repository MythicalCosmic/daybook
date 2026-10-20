<script setup lang="ts">
/**
 * The roster builder (plan §6.2): a week per branch in the ShiftGrid, drag shifts between people and
 * days, drop templates, add open shifts, copy last week or fill it from schedules, and publish: new
 * and moved shifts stay drafts (only managers see them) until "Publish" sends each person their
 * week. The week and branch live in the URL (`?week=`, `?branch=`).
 */
import { CalendarPlus, ChevronLeft, ChevronRight, ClipboardCopy, Ellipsis, Eraser, Send, Wand2 } from "@lucide/vue";
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DropdownMenu from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addDays, formatRange, startOfWeek, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { bulkRoster, publishRoster, useCompanyId, useRefresh, useRoster, useShiftCreate, useShiftUpdate } from "../api";
import AttendanceHeader from "../components/AttendanceHeader.vue";
import BranchSwitch from "../components/BranchSwitch.vue";
import ShiftDialog, { type ShiftDraft } from "../components/ShiftDialog.vue";
import ShiftGrid from "../components/ShiftGrid.vue";
import type { BulkAction, RosterMember, Shift, ShiftTemplate } from "../types";

const PersonMonth = defineAsyncComponent(() => import("../components/PersonMonth.vue"));

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const companyId = useCompanyId();
const confirm = useConfirm();
const refresh = useRefresh();
const create = useShiftCreate();
const update = useShiftUpdate();

const today = computed(() => todayIn(company.timezone));
const thisWeek = computed(() => startOfWeek(today.value));
const weekParam = useRouteState("week", rs.day());
const week = computed({
  get: () => startOfWeek(weekParam.value ?? thisWeek.value),
  set: (value: string) => (weekParam.value = value === thisWeek.value ? null : value),
});
const branch = useRouteState("branch", rs.optionalNumber());
const personId = useRouteState("person", rs.optionalNumber(), { push: true });

const query = useRoster(() => ({ week: week.value, branch: branch.value }));
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const roster = computed(() => query.data.value);
const canManage = computed(() => company.can("attendance.manage"));
const weekLabel = computed(() => formatRange({ from: week.value, to: addDays(week.value, 6) }, fmt.lang.value));

// Dialog ---------------------------------------------------------------------------------

const dialogOpen = ref(false);
const draft = ref<ShiftDraft | null>(null);

function add(target: { memberId: number | null; date: string }): void {
  draft.value = { memberId: target.memberId, date: target.date };
  dialogOpen.value = true;
}

function edit(shift: Shift): void {
  if (!canManage.value) return;
  draft.value = { shift, date: shift.date };
  dialogOpen.value = true;
}

async function move(shift: Shift, target: { memberId: number | null; date: string }): Promise<void> {
  try {
    await update.mutateAsync({
      shift,
      patch: { member_id: target.memberId, date: target.date },
      optimistic: { member_id: target.memberId, date: target.date, status: target.memberId ? "planned" : "open" },
    });
    const who = target.memberId ? roster.value?.members.find((m) => m.id === target.memberId)?.name : t("attendance.roster.openShift");
    toast.success(t("attendance.roster.moved", { who: who ?? "", day: fmt.day(target.date, "weekdayShort") }));
  } catch {
    // Rolled back; the HTTP client shows why.
  }
}

async function place(template: ShiftTemplate, target: { memberId: number | null; date: string }): Promise<void> {
  try {
    await create.mutateAsync({
      member_id: target.memberId,
      date: target.date,
      start: template.starts_at,
      end: template.ends_at,
      break_minutes: template.break_minutes,
      branch_id: branch.value,
    });
    toast.success(t("attendance.roster.added"));
  } catch {
    // Shown by the HTTP client.
  }
}

// Week actions ---------------------------------------------------------------------------

const publishing = ref(false);

async function publish(): Promise<void> {
  const count = roster.value?.unpublished ?? 0;
  if (!count) return;
  const answer = await confirm({
    title: t("attendance.roster.publishTitle", { n: count }),
    message: t("attendance.roster.publishBody"),
    confirmLabel: t("attendance.roster.publish"),
    icon: Send,
  });
  if (!answer) return;
  publishing.value = true;
  try {
    const result = await publishRoster(companyId.value, { start: week.value, end: addDays(week.value, 6), branch_id: branch.value });
    toast.success(t("attendance.roster.published", { n: result.count }));
    refresh();
  } catch {
    // Shown by the HTTP client.
  } finally {
    publishing.value = false;
  }
}

async function bulk(action: BulkAction): Promise<void> {
  const titles: Record<BulkAction, string> = {
    copy_week: t("attendance.roster.copyTitle"),
    apply_schedule: t("attendance.roster.applyTitle"),
    clear: t("attendance.roster.clearTitle"),
  };
  const bodies: Record<BulkAction, string> = {
    copy_week: t("attendance.roster.copyBody"),
    apply_schedule: t("attendance.roster.applyBody"),
    clear: t("attendance.roster.clearBody"),
  };
  const answer = await confirm({ title: titles[action], message: bodies[action], tone: action === "clear" ? "danger" : "primary", confirmLabel: t("common.confirm") });
  if (!answer) return;
  try {
    const result = await bulkRoster(companyId.value, { action, week: week.value, branch_id: branch.value });
    toast.success(t(`attendance.roster.bulkDone.${action}`, { n: result.count }));
    refresh();
  } catch {
    // Shown by the HTTP client.
  }
}

const menu = computed(() => [
  { label: t("attendance.roster.copyLastWeek"), icon: ClipboardCopy, onSelect: () => void bulk("copy_week") },
  { label: t("attendance.roster.applySchedules"), icon: Wand2, onSelect: () => void bulk("apply_schedule") },
  { type: "separator" as const },
  { label: t("attendance.roster.clearWeek"), icon: Eraser, danger: true, onSelect: () => void bulk("clear") },
]);

function person(member: RosterMember): void {
  personId.value = member.id;
}
const personName = computed(() => roster.value?.members.find((m) => m.id === personId.value)?.name ?? "");

// Palette commands land here with ?add=1 or ?publish=1.
onMounted(() => {
  const { add: addFlag, publish: publishFlag, ...rest } = route.query;
  if (addFlag || publishFlag) {
    void router.replace({ query: rest });
    if (addFlag && canManage.value) add({ memberId: null, date: today.value >= week.value ? today.value : week.value });
    if (publishFlag) setTimeout(() => void publish(), 600);
  }
});
</script>

<template>
  <div class="flex flex-col gap-4">
    <AttendanceHeader :title="t('attendance.roster.title')" :description="t('attendance.roster.description')">
      <template v-if="canManage" #actions>
        <DropdownMenu :items="menu">
          <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" variant="secondary" /></template>
        </DropdownMenu>
        <UiButton :icon="CalendarPlus" @click="add({ memberId: null, date: today >= week ? today : week })">{{ t("attendance.roster.addShift") }}</UiButton>
        <UiButton variant="primary" :icon="Send" :loading="publishing" :disabled="!roster?.unpublished" @click="publish">
          {{ roster?.unpublished ? t("attendance.roster.publishCount", { n: roster.unpublished }) : t("attendance.roster.publish") }}
        </UiButton>
      </template>
    </AttendanceHeader>

    <div class="flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-1">
        <IconButton :icon="ChevronLeft" :label="t('common.calendar.prevWeek')" size="sm" variant="secondary" @click="week = addDays(week, -7)" />
        <span class="min-w-44 text-center text-base font-semibold tabular-nums text-fg">{{ weekLabel }}</span>
        <IconButton :icon="ChevronRight" :label="t('common.calendar.nextWeek')" size="sm" variant="secondary" @click="week = addDays(week, 7)" />
        <UiButton v-if="week !== thisWeek" size="sm" variant="ghost" @click="week = thisWeek">{{ t("attendance.roster.thisWeek") }}</UiButton>
      </div>
      <span class="flex-1" />
      <BranchSwitch v-model="branch" />
    </div>

    <InlineAlert v-if="canManage && roster?.unpublished" tone="warning" :title="t('attendance.roster.draftsTitle', { n: roster.unpublished })" :description="t('attendance.roster.draftsBody')" />

    <div v-if="skeleton" class="ui-card flex flex-col gap-2 p-3">
      <SkeletonBlock height="44px" radius="8px" />
      <SkeletonBlock v-for="n in 6" :key="n" height="58px" radius="8px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="roster && !roster.members.length" :icon="CalendarPlus" :title="t('attendance.roster.emptyTitle')" :description="t('attendance.roster.emptyBody')" />
    <ShiftGrid v-else-if="roster" :roster="roster" :editable="canManage" :today="today" @add="add" @edit="edit" @move="move" @place="place" @person="person" />

    <ShiftDialog v-if="roster" v-model:open="dialogOpen" :draft="draft" :members="roster.members" :templates="roster.templates" :branch-id="branch" />

    <UiDrawer query-key="person" size="lg" :title="personName || t('attendance.person.title')">
      <template #default="{ value }">
        <PersonMonth v-if="value" class="p-5" :member-id="Number(value)" />
      </template>
    </UiDrawer>
  </div>
</template>
