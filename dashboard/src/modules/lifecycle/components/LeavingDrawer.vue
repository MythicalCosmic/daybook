<script setup lang="ts">
/**
 * One leaving in a side panel synced with `?termination=`: the last day and how far it is, what
 * happens on its evening, the handover list to tick off (equipment from Equipment, open tasks,
 * keys, documents, HR's own items), what would still stop an offboarding, the person's own words
 * and answers, HR's notes and the rehire answer, the final payslip once prepared (its amount for
 * payroll.view), and what happened when. hr.terminate agrees, moves the day, declines, calls off,
 * ticks items off and presses "Try again" when the evening job was refused.
 */
import {
  ArrowUpRight,
  Banknote,
  CalendarCheck2,
  CalendarClock,
  CircleAlert,
  CircleCheck,
  ClipboardList,
  DoorOpen,
  EllipsisVertical,
  FileText,
  KeyRound,
  ListTodo,
  LockKeyhole,
  MessageSquareQuote,
  Package,
  Plus,
  RotateCcw,
  Undo2,
  UserRoundMinus,
  X,
} from "@lucide/vue";
import { computed, ref, watch, type Component } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import CheckBox from "@/components/CheckBox.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useLeaving, useLifecycleMutation } from "../api";
import { itemTitle, LEAVING_KIND_TONES, LEAVING_TONES, NOTICE_DAYS, shortNotice } from "../lib";
import type { HandoverItem, LeaveUpdateInput, Rehire } from "../types";
import AgreeDialog from "./AgreeDialog.vue";
import CountdownText from "./CountdownText.vue";

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();

const id = computed(() => {
  const raw = route.query.termination;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useLeaving(id);
const leaving = computed(() => query.data.value ?? null);
const isOpen = computed(() => leaving.value?.status === "requested" || leaving.value?.status === "agreed");

// The facts ---------------------------------------------------------------------------------
const items = computed<DescriptionItem[]>(() => {
  const row = leaving.value;
  if (!row) return [];
  const list: DescriptionItem[] = [
    { key: "kind", label: t("lifecycle.leaving.kind"), value: t(`lifecycle.leavingKind.${row.kind}`) },
    {
      key: "asked",
      label: row.initiated_by === "employee" ? t("lifecycle.leaving.askedOn") : t("lifecycle.leaving.startedOn"),
      value: `${row.requested_by?.name ?? "—"} · ${fmt.instant(row.requested_at, "short")}`,
    },
  ];
  if (row.wished_last_day && row.initiated_by === "employee") list.push({ key: "wished", label: t("lifecycle.leaving.askedFor"), value: fmt.day(row.wished_last_day, "weekday") });
  if (row.notice_days !== null && row.status !== "withdrawn" && row.status !== "declined") {
    list.push({
      key: "notice",
      label: t("lifecycle.leaving.noticeLabel"),
      value: t("lifecycle.leaving.noticeDays", { n: row.notice_days }, row.notice_days),
      hint: shortNotice(row.notice_days) ? t("lifecycle.leaving.shortNotice", { n: NOTICE_DAYS }) : undefined,
    });
  }
  if (row.agreed_by && row.agreed_at) list.push({ key: "agreed", label: t("lifecycle.leaving.agreedBy"), value: `${row.agreed_by.name} · ${fmt.instant(row.agreed_at, "short")}` });
  if (company.enabled("payroll")) {
    list.push({
      key: "final",
      label: t("lifecycle.leaving.finalPayslip"),
      value: row.final_payslip ? t("lifecycle.leaving.finalPayslipOn", { n: Number(row.leave_days) }) : t("lifecycle.leaving.finalPayslipOff"),
    });
  }
  return list;
});

// The handover ------------------------------------------------------------------------------
const ITEM_ICONS: Record<HandoverItem["kind"], Component> = { equipment: Package, tasks: ListTodo, keys: KeyRound, documents: FileText, other: ClipboardList };
const progress = computed(() => leaving.value?.handover ?? { done: 0, total: 0 });
const itemName = (item: HandoverItem) => itemTitle(item) ?? t(`lifecycle.handover.kind.${item.kind}`);
function itemHint(item: HandoverItem): string | null {
  if (item.kind === "equipment" && item.held === false && !item.ticked) return t("lifecycle.handover.returned");
  if (item.kind === "equipment" && item.held) return item.ticked ? t("lifecycle.handover.takenBack") : t("lifecycle.handover.held");
  if (item.kind === "tasks" && item.open_tasks !== null) {
    return item.open_tasks ? t("lifecycle.handover.tasksOpen", { n: item.open_tasks }, item.open_tasks) : t("lifecycle.handover.noTasks");
  }
  if (item.ticked && item.done_by && item.done_at) return t("lifecycle.handover.doneBy", { name: item.done_by.name, date: fmt.day(item.done_at.slice(0, 10), "medium") });
  return null;
}

const setItem = useLifecycleMutation((cid, input: { item: number; done?: boolean; note?: string }) => lifecycleApi.setHandoverItem(cid, leaving.value!.id, input.item, { done: input.done, note: input.note }));
const removeItem = useLifecycleMutation((cid, item: number) => lifecycleApi.removeHandoverItem(cid, leaving.value!.id, item));
const addItem = useLifecycleMutation((cid, title: string) => lifecycleApi.addHandoverItem(cid, leaving.value!.id, { title }));
const newItem = ref("");
const adding = ref(false);
watch(id, () => {
  newItem.value = "";
  adding.value = false;
});

async function tick(item: HandoverItem, done: boolean): Promise<void> {
  try {
    await setItem.mutateAsync({ item: item.id, done });
  } catch {
    // The HTTP layer showed why.
  }
}
async function add(): Promise<void> {
  const title = newItem.value.trim();
  if (!title) return;
  try {
    await addItem.mutateAsync(title);
    newItem.value = "";
    adding.value = false;
  } catch {
    // The HTTP layer showed why.
  }
}
const removable = (item: HandoverItem) => !!leaving.value?.can.handover && !(item.kind === "equipment" && item.held);

// HR's side -----------------------------------------------------------------------------------
const notes = ref("");
const rehire = ref<Rehire | "">("");
watch(
  leaving,
  (row) => {
    if (!row) return;
    notes.value = row.notes;
    rehire.value = row.rehire;
  },
  { immediate: true },
);
const update = useLifecycleMutation((cid, input: LeaveUpdateInput) => lifecycleApi.updateLeaving(cid, leaving.value!.id, input));
const rehireOptions = computed(() => (["yes", "maybe", "no"] as const).map((value) => ({ value, label: t(`lifecycle.rehire.${value}`) })));
async function saveRehire(value: Rehire | ""): Promise<void> {
  rehire.value = value;
  try {
    await update.mutateAsync({ rehire: value });
  } catch {
    rehire.value = leaving.value?.rehire ?? "";
  }
}
async function saveNotes(): Promise<void> {
  if (!leaving.value || notes.value === leaving.value.notes) return;
  try {
    await update.mutateAsync({ notes: notes.value });
    toast.success(t("lifecycle.leaving.saved"));
  } catch {
    // The HTTP layer showed why.
  }
}

// Actions -------------------------------------------------------------------------------------
const agreeing = ref(false);
const decline = useLifecycleMutation((cid, reason: string) => lifecycleApi.declineLeaving(cid, leaving.value!.id, reason));
const withdraw = useLifecycleMutation((cid, reason: string) => lifecycleApi.withdrawLeaving(cid, leaving.value!.id, reason));
const retry = useLifecycleMutation((cid) => lifecycleApi.retryLeaving(cid, leaving.value!.id));

async function runDecline(): Promise<void> {
  const row = leaving.value;
  if (!row) return;
  const answer = await confirm({
    title: t("lifecycle.leaving.declineTitle"),
    message: t("lifecycle.leaving.declineBody", { name: row.member.name }),
    tone: "danger",
    reason: "required",
    reasonLabel: t("lifecycle.leaving.declineReason"),
    confirmLabel: t("lifecycle.leaving.decline"),
    icon: UserRoundMinus,
    onConfirm: (reason) => decline.mutateAsync(reason),
  });
  if (answer) toast.success(t("lifecycle.leaving.declined"));
}
async function runWithdraw(): Promise<void> {
  const row = leaving.value;
  if (!row) return;
  const answer = await confirm({
    title: t("lifecycle.leaving.withdrawTitle"),
    message: t("lifecycle.leaving.withdrawBody", { name: row.member.name }),
    tone: "danger",
    reason: "required",
    reasonLabel: t("lifecycle.leaving.withdrawReason"),
    confirmLabel: t("lifecycle.leaving.withdraw"),
    icon: Undo2,
    onConfirm: (reason) => withdraw.mutateAsync(reason),
  });
  if (answer) toast.success(t("lifecycle.leaving.withdrawn", { name: row.member.name }));
}
async function runRetry(): Promise<void> {
  try {
    const done = await retry.mutateAsync(undefined);
    toast.success(t("lifecycle.leaving.retried", { name: done.member.name }));
  } catch {
    // The HTTP layer showed why it still can't.
  }
}

const menu = computed<MenuEntry[]>(() => {
  const row = leaving.value;
  if (!row?.can.manage) return [];
  const entries: MenuEntry[] = [];
  if (row.status === "agreed") entries.push({ label: t("lifecycle.agree.move"), icon: CalendarClock, onSelect: () => (agreeing.value = true) });
  if (row.can.decline) entries.push({ label: t("lifecycle.leaving.decline"), icon: UserRoundMinus, onSelect: () => void runDecline() });
  if (row.can.withdraw && row.status === "agreed") {
    if (entries.length) entries.push({ type: "separator" });
    entries.push({ label: t("lifecycle.leaving.withdraw"), icon: Undo2, danger: true, onSelect: () => void runWithdraw() });
  }
  return entries;
});

// The timeline --------------------------------------------------------------------------------
const EVENT_ICONS: Record<string, Component> = { requested: DoorOpen, started: DoorOpen, agreed: CalendarCheck2, moved: CalendarClock, declined: UserRoundMinus, withdrawn: Undo2, completed: CircleCheck, left: CircleCheck };
const EVENT_TONES: Record<string, TimelineEvent["tone"]> = { requested: "warning", started: "primary", agreed: "primary", moved: "info", declined: "danger", withdrawn: "neutral", completed: "success", left: "success" };
const events = computed<TimelineEvent[]>(() =>
  (leaving.value?.events ?? []).map((event, index) => ({
    key: index,
    at: event.at,
    title: te(`lifecycle.event.${event.kind}`) ? t(`lifecycle.event.${event.kind}`, { name: event.name || t("lifecycle.event.system") }) : event.kind,
    body: [event.day ? t("lifecycle.event.day", { date: fmt.day(event.day, "weekday") }) : "", event.note].filter(Boolean).join(" · ") || undefined,
    icon: EVENT_ICONS[event.kind] ?? CircleCheck,
    tone: EVENT_TONES[event.kind] ?? "neutral",
  })),
);

const exitReason = (value: string) => (te(`lifecycle.exitReason.${value}`) ? t(`lifecycle.exitReason.${value}`) : value);
const runStatus = (value: string) => (te(`lifecycle.runStatus.${value}`) ? t(`lifecycle.runStatus.${value}`) : value);
const eveningTime = "20:00";
</script>

<template>
  <UiDrawer query-key="termination" size="lg" :title="leaving ? leaving.member.name : t('lifecycle.leaving.one')">
    <template #header-actions>
      <DropdownMenu v-if="menu.length" :items="menu" align="end">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="64px" />
        <SkeletonBlock height="120px" radius="14px" />
        <SkeletonBlock v-for="n in 4" :key="n" height="16px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="leaving" class="flex flex-col gap-5" data-leaving>
        <!-- Who -->
        <header class="flex items-start gap-3">
          <RouterLink :to="`/c/${company.currentId}/people/${leaving.member.id}`" class="shrink-0" :aria-label="leaving.member.name">
            <UserAvatar :name="leaving.member.name" :src="leaving.member.photo_url" :size="48" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${company.currentId}/people/${leaving.member.id}`" class="block truncate text-base font-semibold text-fg hover:text-primary hover:underline">
              {{ leaving.member.name }}
            </RouterLink>
            <p class="truncate text-sm text-muted">{{ [leaving.position, leaving.home_branch?.name].filter(Boolean).join(" · ") }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill size="sm" :tone="LEAVING_TONES[leaving.status]" :label="t(`lifecycle.leavingStatus.${leaving.status}`)" />
              <StatusPill size="sm" variant="outline" :tone="LEAVING_KIND_TONES[leaving.kind]" :label="t(`lifecycle.leavingKind.${leaving.kind}`)" />
            </div>
          </div>
        </header>

        <!-- The evening job was refused -->
        <InlineAlert v-if="leaving.error" tone="danger" :title="t('lifecycle.leaving.errorTitle')" :description="leaving.error" data-leaving-error>
          <template v-if="leaving.can.retry" #actions>
            <UiButton size="sm" :icon="RotateCcw" :loading="retry.isPending.value" @click="runRetry">{{ t("lifecycle.leaving.retry") }}</UiButton>
          </template>
        </InlineAlert>

        <!-- The day -->
        <section class="overflow-hidden rounded-[14px] border border-line" data-leaving-day>
          <div class="flex items-center gap-4 bg-surface-2/70 px-4 py-3.5">
            <span
              :class="[
                'grid size-11 shrink-0 place-items-center rounded-[12px]',
                leaving.status === 'completed' ? 'bg-success-soft text-success' : leaving.status === 'requested' ? 'bg-warning-soft text-warning' : 'bg-primary-soft text-primary',
              ]"
              aria-hidden="true"
            >
              <CircleCheck v-if="leaving.status === 'completed'" :size="22" />
              <CalendarClock v-else :size="22" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-xs font-medium uppercase tracking-[0.04em] text-muted">
                {{ leaving.status === "completed" ? t("lifecycle.leaving.leftOnLabel") : leaving.status === "requested" ? t("lifecycle.leaving.askedFor") : t("lifecycle.leaving.lastDay") }}
              </p>
              <p class="text-lg font-semibold tracking-[-0.01em] text-fg">
                {{ fmt.day((leaving.status === "completed" ? leaving.left_on : leaving.last_day ?? leaving.wished_last_day) ?? today, "weekday") }}
              </p>
              <CountdownText v-if="isOpen" :day="leaving.last_day ?? leaving.wished_last_day" :today="today" class="text-sm text-muted" />
            </div>
            <div v-if="leaving.status === 'requested' && leaving.can.agree" class="flex shrink-0 flex-col gap-2 sm:flex-row">
              <UiButton size="sm" variant="ghost" @click="runDecline">{{ t("lifecycle.leaving.decline") }}</UiButton>
              <UiButton size="sm" variant="primary" :icon="CalendarCheck2" @click="agreeing = true">{{ t("lifecycle.leaving.agreeDay") }}</UiButton>
            </div>
          </div>
          <p v-if="leaving.status === 'agreed' && leaving.last_day" class="border-t border-line px-4 py-3 text-sm text-muted" data-leaving-evening>
            {{ t("lifecycle.leaving.evening", { date: fmt.day(leaving.last_day, "medium"), time: eveningTime }) }}
          </p>
          <p v-else-if="(leaving.status === 'withdrawn' || leaving.status === 'declined') && leaving.closed_by" class="border-t border-line px-4 py-3 text-sm text-muted">
            {{ t(`lifecycle.leaving.closedBy.${leaving.status}`, { name: leaving.closed_by.name, date: fmt.day((leaving.closed_at ?? leaving.requested_at).slice(0, 10), "medium") }) }}
            <template v-if="leaving.close_reason"> · {{ leaving.close_reason }}</template>
          </p>
        </section>

        <DescriptionList :items="items" :columns="2" />

        <!-- In their words -->
        <section v-if="leaving.reason" class="flex flex-col gap-1.5">
          <h3 class="text-sm font-semibold text-fg">{{ leaving.initiated_by === "employee" ? t("lifecycle.leaving.theirWords") : t("lifecycle.leaving.reason") }}</h3>
          <blockquote class="whitespace-pre-line rounded-[12px] border-l-4 border-[var(--c-primary)] bg-primary-soft/40 px-4 py-3 text-base text-fg">{{ leaving.reason }}</blockquote>
        </section>

        <!-- What still stops an offboarding -->
        <InlineAlert v-if="leaving.blockers.length" tone="warning" :title="t('lifecycle.leaving.blockersTitle')" data-leaving-blockers>
          <ul class="list-disc pl-5 text-sm">
            <li v-for="line in leaving.blockers" :key="line">{{ line }}</li>
          </ul>
          <p class="mt-1.5 text-xs opacity-80">{{ t("lifecycle.leaving.blockersBody") }}</p>
        </InlineAlert>

        <!-- The handover -->
        <section v-if="leaving.items.length || isOpen" class="flex flex-col gap-3" data-leaving-handover>
          <div class="flex items-end justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.handover.title") }}</h3>
              <p class="text-xs text-muted">{{ isOpen ? t("lifecycle.handover.hint") : t("lifecycle.handover.closedNote") }}</p>
            </div>
            <span v-if="progress.total" class="shrink-0 text-sm font-medium tabular-nums text-fg">{{ t("lifecycle.handover.progress", { done: progress.done, total: progress.total }) }}</span>
          </div>
          <ProgressBar v-if="progress.total" :value="progress.done" :max="progress.total" size="sm" :tone="progress.done === progress.total ? 'success' : 'primary'" />
          <p v-if="!leaving.items.length" class="rounded-[12px] border border-dashed border-line-strong px-4 py-3 text-sm text-muted">{{ t("lifecycle.handover.empty") }}</p>
          <ul v-else class="flex flex-col divide-y divide-line overflow-hidden rounded-[12px] border border-line">
            <li v-for="item in leaving.items" :key="item.id" :class="['flex items-start gap-3 px-3.5 py-3', item.done ? 'bg-surface-2/40' : '']" data-handover-item>
              <CheckBox
                class="mt-0.5"
                :model-value="item.done"
                :disabled="!leaving.can.handover || item.auto || setItem.isPending.value"
                :aria-label="itemName(item)"
                @update:model-value="(value: boolean) => tick(item, value)"
              />
              <span
                :class="['grid size-8 shrink-0 place-items-center rounded-[9px]', item.done ? 'bg-success-soft text-success' : 'bg-surface-2 text-muted']"
                aria-hidden="true"
              >
                <component :is="ITEM_ICONS[item.kind]" :size="16" />
              </span>
              <div class="min-w-0 flex-1">
                <p :class="['text-sm font-medium', item.done ? 'text-muted line-through decoration-[var(--c-line-strong)]' : 'text-fg']">{{ itemName(item) }}</p>
                <p v-if="itemHint(item)" :class="['text-xs', item.kind === 'equipment' && item.held && !item.ticked ? 'text-warning' : 'text-muted']">{{ itemHint(item) }}</p>
                <p v-if="item.note" class="mt-0.5 text-xs text-muted">{{ item.note }}</p>
              </div>
              <IconButton v-if="removable(item)" size="sm" variant="ghost" :icon="X" :label="t('lifecycle.handover.remove')" @click="removeItem.mutate(item.id)" />
            </li>
          </ul>
          <p v-if="leaving.items.some((item) => item.kind === 'equipment') && isOpen" class="text-xs text-subtle">{{ t("lifecycle.handover.equipmentHint") }}</p>
          <template v-if="leaving.can.handover">
            <form v-if="adding" class="flex items-center gap-2" @submit.prevent="add">
              <TextInput v-model="newItem" class="flex-1" :maxlength="200" :placeholder="t('lifecycle.handover.addPlaceholder')" autofocus />
              <UiButton type="submit" size="sm" variant="primary" :loading="addItem.isPending.value" :disabled="!newItem.trim()">{{ t("lifecycle.handover.addButton") }}</UiButton>
              <IconButton size="sm" variant="ghost" :icon="X" :label="t('common.cancel')" @click="adding = false" />
            </form>
            <UiButton v-else variant="ghost" size="sm" class="w-fit" :icon="Plus" @click="adding = true">{{ t("lifecycle.handover.add") }}</UiButton>
          </template>
        </section>

        <!-- Still open when they left -->
        <InlineAlert v-if="leaving.status === 'completed' && leaving.left_open.length" tone="warning" :title="t('lifecycle.leaving.leftOpenTitle')" data-leaving-left-open>
          <ul class="mt-1 list-disc pl-5 text-sm">
            <li v-for="line in leaving.left_open" :key="line">{{ line }}</li>
          </ul>
        </InlineAlert>

        <!-- The final payslip -->
        <section v-if="leaving.status === 'completed' && company.enabled('payroll')" class="flex items-center gap-3 rounded-[12px] border border-line px-3.5 py-3" data-leaving-final>
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-success-soft text-success" aria-hidden="true"><Banknote :size="18" /></span>
          <div v-if="leaving.final_run" class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-fg">
              {{ t("lifecycle.leaving.finalPayslip") }}<template v-if="leaving.final_run.net">: <MoneyText :value="leaving.final_run.net" :currency="leaving.final_run.currency" /></template>
            </p>
            <p class="flex items-center gap-1 text-xs text-muted">
              <LockKeyhole v-if="!leaving.final_run.net" :size="12" aria-hidden="true" />{{ runStatus(leaving.final_run.status) }}
            </p>
          </div>
          <p v-else class="min-w-0 flex-1 text-sm text-muted">{{ t("lifecycle.leaving.finalPayslipNone") }}</p>
          <UiButton
            v-if="leaving.final_run && company.can('payroll.view')"
            size="sm"
            :to="`/c/${company.currentId}/payroll/runs/${leaving.final_run.id}`"
            :icon-right="ArrowUpRight"
          >
            {{ t("lifecycle.leaving.finalPayslipOpen") }}
          </UiButton>
        </section>

        <!-- Their answers before they go -->
        <section class="flex flex-col gap-2" data-leaving-exit>
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.exit.title") }}</h3>
          <div v-if="leaving.exit_interview" class="flex flex-col gap-2 rounded-[12px] border border-line px-4 py-3">
            <div class="flex flex-wrap items-center gap-2">
              <StatusPill size="sm" tone="info" :label="exitReason(leaving.exit_interview.reason)" />
              <StatusPill
                v-if="leaving.exit_interview.recommend"
                size="sm"
                variant="outline"
                :tone="leaving.exit_interview.recommend === 'yes' ? 'success' : leaving.exit_interview.recommend === 'no' ? 'danger' : 'neutral'"
                :label="t('lifecycle.exit.recommendValue', { answer: t(`lifecycle.rehire.${leaving.exit_interview.recommend}`) })"
              />
            </div>
            <p v-if="leaving.exit_interview.better" class="flex gap-2 text-sm text-fg">
              <MessageSquareQuote :size="15" class="mt-0.5 shrink-0 text-info" aria-hidden="true" />
              <span class="whitespace-pre-line">{{ leaving.exit_interview.better }}</span>
            </p>
          </div>
          <p v-else class="rounded-[12px] border border-dashed border-line-strong px-4 py-3 text-sm text-muted">{{ t("lifecycle.exit.none") }}</p>
        </section>

        <!-- HR's side -->
        <section v-if="leaving.can.manage || leaving.notes || leaving.rehire" class="flex flex-col gap-3 rounded-[12px] bg-surface-2/60 p-4" data-leaving-hr>
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.leaving.rehire") }}</h3>
            <SegmentedControl v-if="leaving.can.manage" size="sm" :model-value="rehire" :options="rehireOptions" @update:model-value="(value) => saveRehire(value as Rehire)" />
            <span v-else class="text-sm text-fg">{{ leaving.rehire ? t(`lifecycle.rehire.${leaving.rehire}`) : "—" }}</span>
          </div>
          <div class="flex flex-col gap-1.5">
            <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.leaving.notes") }}</h3>
            <TextArea v-if="leaving.can.manage" v-model="notes" :rows="3" :maxlength="4000" :placeholder="t('lifecycle.leaving.notesPlaceholder')" @blur="saveNotes" />
            <p v-else class="whitespace-pre-line text-sm text-fg">{{ leaving.notes || "—" }}</p>
            <p class="flex items-center gap-1 text-xs text-subtle"><LockKeyhole :size="12" aria-hidden="true" />{{ t("lifecycle.leaving.notesHint") }}</p>
          </div>
        </section>

        <!-- What happened -->
        <section v-if="events.length" class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.leaving.history") }}</h3>
          <TimelineList :events="events" dense />
        </section>

        <p v-if="leaving.status === 'agreed' && !leaving.can.manage" class="flex items-center gap-1.5 text-xs text-subtle">
          <CircleAlert :size="13" aria-hidden="true" />{{ t("lifecycle.leaving.readOnly") }}
        </p>
      </div>
    </div>

    <AgreeDialog v-if="leaving && agreeing" v-model:open="agreeing" :leaving="leaving" />
  </UiDrawer>
</template>
