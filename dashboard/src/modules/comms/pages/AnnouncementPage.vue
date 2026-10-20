<script setup lang="ts">
/**
 * One announcement (plan §6.2): the bubble people got, who it went to, how many read it and who
 * hasn't, "Remind unread now", pin or unpin, and for a scheduled one: edit or cancel. Receipts are
 * a table with Unread / Read tabs in the URL.
 */
import { BellRing, CalendarClock, CalendarX2, Pencil, Pin, PinOff, Timer } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import DataTable from "@/components/DataTable.vue";
import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import PersonCell from "@/components/PersonCell.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TimePicker from "@/components/TimePicker.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { addDays, todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useAnnouncement, useAnnouncementAction, useReceipts, useRemind } from "../api";
import AudienceChips from "../components/AudienceChips.vue";
import TelegramBubble from "../components/TelegramBubble.vue";
import type { AnnouncementStatus, Receipt } from "../types";
import { zonedIso } from "../when";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();

const id = computed(() => Number(route.params.announcementId));
const query = useAnnouncement(id);
const row = computed(() => query.data.value ?? null);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const state = useRouteState<"unread" | "read" | "all">("state", rs.enum(["unread", "read", "all"] as const, "unread"));
const table = useDataTable({ id: "comms.receipts", url: "r", pageSize: 50 });
watch(state, () => table.resetPage());
const receipts = useReceipts(id, computed(() => ({ state: state.value === "all" ? undefined : state.value, ...table.params.value })));

const TONES: Record<AnnouncementStatus, StatusTone> = { draft: "neutral", scheduled: "info", sent: "success", cancelled: "neutral" };
const readPercent = computed(() => (row.value?.recipients_count ? (row.value.read_count / row.value.recipients_count) * 100 : 0));
const unread = computed(() => (row.value ? row.value.recipients_count - row.value.read_count : 0));

const kpis = computed(() => {
  const r = row.value;
  return [
    { id: "recipients", label: t("comms.detail.recipients"), value: r?.recipients_count ?? null },
    { id: "read", label: t("comms.detail.read"), value: r?.read_count ?? null },
    { id: "unread", label: t("comms.detail.unread"), value: r ? unread.value : null },
  ];
});

const columns = computed<TableColumn<Receipt>[]>(() => [
  { id: "member", header: t("comms.col.person"), minWidth: 220, hideable: false, value: (r) => r.member.name },
  { id: "branch", header: t("comms.col.branch"), width: 140, value: (r) => r.home_branch?.name ?? "" },
  { id: "read_at", header: t("comms.col.readAt"), width: 170, value: (r) => r.read_at ?? "", format: (v) => (v ? fmt.instant(String(v), "short") : t("comms.detail.notYet")) },
  { id: "reminded_at", header: t("comms.col.reminded"), width: 150, value: (r) => r.reminded_at ?? "", format: (v) => (v ? fmt.relative(String(v)) : "—") },
]);

// Actions ---------------------------------------------------------------------------------
const act = useAnnouncementAction();
const remind = useRemind();

async function remindNow(): Promise<void> {
  const r = row.value;
  if (!r) return;
  const answer = await confirm({ title: t("comms.detail.remindTitle", { n: unread.value }, unread.value), message: t("comms.detail.remindBody"), confirmLabel: t("comms.detail.remind"), icon: BellRing });
  if (!answer) return;
  try {
    const result = await remind.mutateAsync(r.id);
    toast.success(t("comms.detail.reminded", { n: result.reminded }, result.reminded));
  } catch {
    // Shown.
  }
}

async function cancel(): Promise<void> {
  const r = row.value;
  if (!r) return;
  const answer = await confirm({ title: t("comms.detail.cancelTitle"), message: t("comms.detail.cancelBody"), tone: "danger", confirmLabel: t("comms.detail.cancel") });
  if (!answer) return;
  try {
    await act.mutateAsync({ id: r.id, action: "cancel" });
    toast.success(t("comms.detail.cancelled"));
  } catch {
    // Shown.
  }
}

async function unpin(): Promise<void> {
  const r = row.value;
  if (!r) return;
  try {
    await act.mutateAsync({ id: r.id, action: "unpin" });
    toast.success(t("comms.detail.unpinned"));
  } catch {
    // Shown.
  }
}

const pinning = ref(false);
const pinDay = ref<string | null>(null);
const pinTime = ref<string | null>("20:00");
function openPin(): void {
  pinDay.value = addDays(todayIn(company.timezone), 3);
  pinning.value = true;
}
async function savePin(): Promise<void> {
  const r = row.value;
  if (!r || !pinDay.value || !pinTime.value) return;
  try {
    await act.mutateAsync({ id: r.id, action: "pin", until: zonedIso(pinDay.value, pinTime.value, company.timezone) });
    pinning.value = false;
    toast.success(t("comms.detail.pinned", { date: fmt.day(pinDay.value, "medium") }));
  } catch {
    // Shown.
  }
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <div v-if="skeleton && !row" class="flex flex-col gap-4"><SkeletonBlock width="40%" height="28px" /><SkeletonBlock height="96px" radius="12px" /><SkeletonBlock height="240px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else-if="row">
      <PageHeader :title="row.title" :back="`/c/${company.currentId}/announcements`" :back-label="t('comms.nav.announcements')">
        <template #actions>
          <template v-if="row.status === 'scheduled'">
            <UiButton :icon="CalendarX2" class="hover:!text-danger" :loading="act.isPending.value && act.variables.value?.action === 'cancel'" @click="cancel">{{ t("comms.detail.cancel") }}</UiButton>
            <UiButton variant="primary" :icon="Pencil" :to="{ path: `/c/${company.currentId}/announcements/new`, query: { edit: String(row.id) } }">{{ t("common.edit") }}</UiButton>
          </template>
          <template v-else-if="row.status === 'sent' && !row.is_expired">
            <UiButton v-if="row.is_pinned" :icon="PinOff" :loading="act.isPending.value" @click="unpin">{{ t("comms.detail.unpin") }}</UiButton>
            <UiButton v-else :icon="Pin" @click="openPin">{{ t("comms.detail.pin") }}</UiButton>
            <UiButton variant="primary" :icon="BellRing" :disabled="!unread" :loading="remind.isPending.value" @click="remindNow">{{ t("comms.detail.remindN", { n: unread }, unread) }}</UiButton>
          </template>
        </template>
        <template #meta>
          <StatusPill :tone="row.is_expired ? 'neutral' : TONES[row.status]" :label="row.is_expired ? t('comms.status.expired') : t(`comms.status.${row.status}`)" />
          <StatusPill v-if="row.is_pinned" :icon="Pin" tone="primary" :label="t('comms.detail.pinnedUntil', { date: fmt.instant(row.pinned_until!, 'short') })" />
          <StatusPill v-if="row.expires_at && !row.is_expired" :icon="Timer" tone="neutral" :label="t('comms.detail.expiresAt', { date: fmt.instant(row.expires_at, 'short') })" />
          <span class="text-sm text-muted">
            <template v-if="row.status === 'scheduled' && row.scheduled_for">{{ t("comms.detail.goesOut", { when: fmt.instant(row.scheduled_for, "datetime") }) }}</template>
            <template v-else-if="row.sent_at">{{ t("comms.detail.sentBy", { name: row.author?.name ?? "—", when: fmt.instant(row.sent_at, "datetime") }) }}</template>
          </span>
        </template>
      </PageHeader>

      <div class="grid grid-cols-1 gap-5 lg:grid-cols-[400px_minmax(0,1fr)]">
        <div class="flex min-w-0 flex-col gap-5">
          <TelegramBubble :text="row.text" :author="row.author?.name" :time="row.sent_at ? fmt.instant(row.sent_at, 'time') : row.scheduled_for ? fmt.instant(row.scheduled_for, 'time') : ''" />
          <section class="ui-card flex flex-col gap-3 p-4">
            <h2 class="text-sm font-semibold text-fg">{{ t("comms.detail.audience") }}</h2>
            <AudienceChips :announcement="row" :max="10" />
          </section>
          <section class="ui-card p-4">
            <h2 class="mb-3 text-sm font-semibold text-fg">{{ t("comms.detail.history") }}</h2>
            <AuditTrail target-type="announcement" :target-id="row.id" :page-size="10" />
          </section>
        </div>

        <div class="flex min-w-0 flex-col gap-5">
          <section v-if="row.status === 'sent'" class="ui-card flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
            <ProgressRing :value="readPercent" :size="96" :stroke="9" tone="auto" show-value :label="t('comms.detail.readRate')" />
            <KpiStrip :items="kpis" :columns="3" class="min-w-0 flex-1 !border-0 !shadow-none" />
          </section>
          <section v-else-if="row.status === 'scheduled'" class="ui-card flex items-center gap-3 p-5">
            <span class="grid size-11 place-items-center rounded-[12px] bg-info-soft text-info"><CalendarClock :size="20" /></span>
            <div>
              <p class="text-base font-semibold text-fg">{{ t("comms.detail.scheduledTitle") }}</p>
              <p class="text-sm text-muted">{{ t("comms.detail.scheduledBody") }}</p>
            </div>
          </section>

          <template v-if="row.status === 'sent'">
            <SegmentedControl
              v-model="state"
              class="w-fit"
              :options="[
                { value: 'unread', label: t('comms.detail.tabUnread'), count: unread },
                { value: 'read', label: t('comms.detail.tabRead'), count: row.read_count },
                { value: 'all', label: t('comms.detail.tabAll'), count: row.recipients_count },
              ]"
            />
            <DataTable
              :state="table"
              :columns="columns"
              :rows="receipts.data.value?.results"
              :total="receipts.data.value?.count"
              row-key="id"
              :loading="receipts.isPending.value"
              :fetching="receipts.isFetching.value"
              :error="receipts.error.value"
              :retry="() => receipts.refetch()"
              :empty-title="state === 'unread' ? t('comms.detail.allReadTitle') : t('comms.detail.noneReadTitle')"
              :empty-description="state === 'unread' ? t('comms.detail.allReadBody') : t('comms.detail.noneReadBody')"
              csv-name="Receipts"
            >
              <template #cell-member="{ row: receipt }">
                <PersonCell :person="receipt.member" :subtitle="receipt.position" size="sm" link />
              </template>
              <template #cell-read_at="{ row: receipt }">
                <StatusPill v-if="receipt.read_at" size="sm" tone="success" :label="fmt.instant(receipt.read_at, 'short')" />
                <StatusPill v-else size="sm" tone="warning" :label="t('comms.detail.notYet')" />
              </template>
              <template #card="{ row: receipt }">
                <div class="flex items-center justify-between gap-3">
                  <PersonCell :person="receipt.member" :subtitle="receipt.position" />
                  <StatusPill size="sm" :tone="receipt.read_at ? 'success' : 'warning'" :label="receipt.read_at ? fmt.relative(receipt.read_at) : t('comms.detail.notYet')" />
                </div>
              </template>
            </DataTable>
          </template>
        </div>
      </div>

      <UiDialog v-model:open="pinning" :title="t('comms.detail.pinTitle')" :description="t('comms.detail.pinBody')" size="sm">
        <div class="flex flex-wrap items-end gap-3">
          <FormField :label="t('comms.compose.pinUntil')"><DatePicker v-model="pinDay" :min="todayIn(company.timezone)" /></FormField>
          <FormField :label="t('comms.compose.time')"><TimePicker v-model="pinTime" :step="15" /></FormField>
        </div>
        <template #footer>
          <UiButton variant="ghost" @click="pinning = false">{{ t("common.cancel") }}</UiButton>
          <UiButton variant="primary" :icon="Pin" :loading="act.isPending.value" @click="savePin">{{ t("comms.detail.pin") }}</UiButton>
        </template>
      </UiDialog>
    </template>
  </div>
</template>
