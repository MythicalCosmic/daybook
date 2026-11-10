<script setup lang="ts">
/**
 * One job change in a side panel synced with `?change=`: from which day, what it was and what it
 * becomes (the pay only for payroll.view; the access role once it applied), why, who proposed and
 * decided it, and what happened when. Whoever may decide it approves or rejects it here; it is
 * cancelled until it applies; "Try again" when it couldn't apply on its day.
 */
import { ArrowRight, CalendarClock, CircleCheck, EllipsisVertical, LockKeyhole, RotateCcw, Shuffle, Undo2, UserRoundCheck, XCircle } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TimelineList, { type TimelineEvent } from "@/components/TimelineList.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { lifecycleApi, useChange, useLifecycleMutation } from "../api";
import { CHANGE_TONES, partSides } from "../lib";
import type { ChangePart, JobPay } from "../types";
import CountdownText from "./CountdownText.vue";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();

const id = computed(() => {
  const raw = route.query.change;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useChange(id);
const change = computed(() => query.data.value ?? null);
const done = computed(() => change.value?.status === "applied");

interface Row {
  part: ChangePart | "role";
  was: string | null;
  now: string | null;
  pay?: { was: JobPay | null; now: JobPay | null };
}
const rows = computed<Row[]>(() => {
  const c = change.value;
  if (!c) return [];
  const list: Row[] = c.parts
    .filter((part): part is Exclude<ChangePart, "pay"> => part !== "pay")
    .map((part) => {
      const { was, now } = partSides(c, part);
      const none = part === "department" ? t("lifecycle.changes.noDepartment") : part === "position" ? t("lifecycle.changes.noPosition") : "—";
      return { part, was: was ?? none, now: now ?? none };
    });
  if (c.parts.includes("pay")) list.push({ part: "pay", was: null, now: null, pay: { was: c.before.pay, now: c.after.pay } });
  // The access that came with a new job title, once it applied.
  if (c.status === "applied" && c.before.role?.id !== c.after.role?.id) list.push({ part: "role", was: c.before.role?.name ?? "—", now: c.after.role?.name ?? "—" });
  return list;
});

const approve = useLifecycleMutation((cid) => lifecycleApi.approveChange(cid, change.value!.id));
const reject = useLifecycleMutation((cid, reason: string) => lifecycleApi.rejectChange(cid, change.value!.id, reason));
const cancel = useLifecycleMutation((cid, reason: string) => lifecycleApi.cancelChange(cid, change.value!.id, reason));
const retry = useLifecycleMutation((cid) => lifecycleApi.retryChange(cid, change.value!.id));

async function runApprove(): Promise<void> {
  const result = await approve.mutateAsync(undefined);
  toast.success(result.status === "applied" ? t("lifecycle.changes.appliedNow", { name: result.member.name }) : t("lifecycle.changes.approved", { name: result.member.name }));
}
async function runReject(reason: string): Promise<void> {
  const result = await reject.mutateAsync(reason);
  toast.success(t("lifecycle.changes.rejected", { name: result.member.name }));
}
async function runCancel(): Promise<void> {
  const c = change.value;
  if (!c) return;
  const answer = await confirm({
    title: t("lifecycle.changes.cancelTitle"),
    message: t("lifecycle.changes.cancelBody", { name: c.member.name }),
    tone: "danger",
    reason: "optional",
    reasonLabel: t("lifecycle.changes.cancelReason"),
    confirmLabel: t("lifecycle.changes.cancel"),
    icon: Undo2,
    onConfirm: (reason) => cancel.mutateAsync(reason),
  });
  if (answer) toast.success(t("lifecycle.changes.cancelled"));
}
async function runRetry(): Promise<void> {
  try {
    const result = await retry.mutateAsync(undefined);
    toast.success(t("lifecycle.changes.appliedNow", { name: result.member.name }));
  } catch {
    // The HTTP layer showed why it still can't.
  }
}

const menu = computed<MenuEntry[]>(() => (change.value?.can.cancel ? [{ label: t("lifecycle.changes.cancel"), icon: Undo2, danger: true, onSelect: () => void runCancel() }] : []));

const events = computed<TimelineEvent[]>(() => {
  const c = change.value;
  if (!c) return [];
  const list: TimelineEvent[] = [
    { key: "proposed", at: c.created_at, title: t("lifecycle.changeEvent.proposed", { name: c.proposed_by?.name ?? t("lifecycle.event.system") }), icon: Shuffle, tone: "warning" },
  ];
  if (c.decided_at && c.decided_by) {
    const rejected = c.status === "rejected";
    list.push({
      key: "decided",
      at: c.decided_at,
      title: t(rejected ? "lifecycle.changeEvent.rejected" : "lifecycle.changeEvent.approved", { name: c.decided_by.name }),
      body: rejected ? c.decision_note || undefined : undefined,
      icon: rejected ? XCircle : UserRoundCheck,
      tone: rejected ? "danger" : "primary",
    });
  }
  if (c.applied_at) list.push({ key: "applied", at: c.applied_at, title: t("lifecycle.changeEvent.applied"), icon: CircleCheck, tone: "success" });
  return list;
});
</script>

<template>
  <UiDrawer query-key="change" size="md" :title="change ? change.member.name : t('lifecycle.changes.one')">
    <template #header-actions>
      <DropdownMenu v-if="menu.length" :items="menu" align="end">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="56px" />
        <SkeletonBlock height="140px" radius="14px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="change" class="flex flex-col gap-5" data-change>
        <header class="flex items-start gap-3">
          <RouterLink :to="`/c/${company.currentId}/people/${change.member.id}`" class="shrink-0" :aria-label="change.member.name">
            <UserAvatar :name="change.member.name" :src="change.member.photo_url" :size="44" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${company.currentId}/people/${change.member.id}`" class="block truncate text-base font-semibold text-fg hover:text-primary hover:underline">
              {{ change.member.name }}
            </RouterLink>
            <p class="truncate text-sm text-muted">{{ [change.position_now, change.home_branch?.name].filter(Boolean).join(" · ") }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill size="sm" :tone="CHANGE_TONES[change.status]" :label="t(`lifecycle.changeStatus.${change.status}`)" />
            </div>
          </div>
        </header>

        <InlineAlert v-if="change.error" tone="danger" :title="t('lifecycle.changes.errorTitle')" :description="change.error" data-change-error>
          <template v-if="change.can.retry" #actions>
            <UiButton size="sm" :icon="RotateCcw" :loading="retry.isPending.value" @click="runRetry">{{ t("lifecycle.changes.retry") }}</UiButton>
          </template>
        </InlineAlert>

        <!-- From which day -->
        <section class="flex items-center gap-4 rounded-[14px] border border-line bg-surface-2/70 px-4 py-3.5">
          <span :class="['grid size-11 shrink-0 place-items-center rounded-[12px]', done ? 'bg-success-soft text-success' : 'bg-primary-soft text-primary']" aria-hidden="true">
            <CircleCheck v-if="done" :size="22" />
            <CalendarClock v-else :size="22" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-xs font-medium uppercase tracking-[0.04em] text-muted">{{ done ? t("lifecycle.changes.sinceLabel") : t("lifecycle.changes.fromLabel") }}</p>
            <p class="text-lg font-semibold tracking-[-0.01em] text-fg">{{ fmt.day(change.effective_on, "weekday") }}</p>
            <CountdownText v-if="change.status === 'approved' || change.status === 'proposed'" :day="change.effective_on" :today="today" class="text-sm text-muted" />
          </div>
          <ApproveRejectButtons
            v-if="change.can.decide"
            class="shrink-0"
            :on-approve="runApprove"
            :on-reject="runReject"
            :reject-title="t('lifecycle.changes.rejectTitle')"
          />
        </section>

        <!-- Was and becomes -->
        <section class="overflow-hidden rounded-[12px] border border-line" data-change-sides>
          <div class="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-3 border-b border-line bg-surface-2/60 px-3.5 py-2 text-xs font-medium uppercase tracking-[0.04em] text-muted">
            <span />
            <span>{{ t("lifecycle.changes.was") }}</span>
            <span />
            <span>{{ done ? t("lifecycle.changes.became") : t("lifecycle.changes.becomes") }}</span>
          </div>
          <div v-for="row in rows" :key="row.part" class="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-3 border-b border-line px-3.5 py-2.5 last:border-b-0">
            <span class="truncate text-sm text-muted">{{ t(`lifecycle.changePart.${row.part}`) }}</span>
            <template v-if="row.pay">
              <template v-if="row.pay.now">
                <span class="flex min-w-0 flex-col text-sm tabular-nums text-muted">
                  <span class="truncate"><MoneyText v-if="row.pay.was" :value="row.pay.was.amount" :currency="row.pay.was.currency" /><template v-else>—</template></span>
                  <span v-if="row.pay.was" class="truncate text-xs">{{ t(`lifecycle.payType.${row.pay.was.pay_type}`) }}</span>
                </span>
                <ArrowRight :size="14" class="text-subtle" aria-hidden="true" />
                <span class="flex min-w-0 flex-col tabular-nums">
                  <span class="truncate text-sm font-semibold text-fg"><MoneyText :value="row.pay.now.amount" :currency="row.pay.now.currency" /></span>
                  <span class="truncate text-xs text-muted">{{ t(`lifecycle.payType.${row.pay.now.pay_type}`) }}</span>
                </span>
              </template>
              <span v-else class="col-span-3 inline-flex items-center gap-1.5 text-sm text-muted"><LockKeyhole :size="13" aria-hidden="true" />{{ t("lifecycle.changes.payHidden") }}</span>
            </template>
            <template v-else>
              <span class="truncate text-sm text-muted" :title="row.was ?? ''">{{ row.was }}</span>
              <ArrowRight :size="14" class="text-subtle" aria-hidden="true" />
              <span class="truncate text-sm font-medium text-fg" :title="row.now ?? ''">{{ row.now }}</span>
            </template>
          </div>
        </section>
        <p v-if="change.parts.includes('position') && !done" class="-mt-3 text-xs text-subtle">{{ t("lifecycle.changes.roleNote") }}</p>

        <section class="flex flex-col gap-1.5">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.changes.reason") }}</h3>
          <p class="whitespace-pre-line rounded-[10px] bg-surface-2 px-3.5 py-3 text-base text-fg">{{ change.reason }}</p>
        </section>

        <section v-if="change.status === 'rejected' || change.status === 'cancelled'" class="rounded-[10px] bg-surface-2 px-3.5 py-2.5">
          <p class="text-sm font-semibold text-fg">{{ t(`lifecycle.changeStatus.${change.status}`) }}</p>
          <p v-if="change.decision_note" class="mt-0.5 text-sm text-muted">{{ change.decision_note }}</p>
        </section>

        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.leaving.history") }}</h3>
          <TimelineList :events="events" dense />
        </section>
      </div>
    </div>
  </UiDrawer>
</template>
