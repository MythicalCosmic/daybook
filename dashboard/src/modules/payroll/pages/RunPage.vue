<script setup lang="ts">
/**
 * One payroll run (plan §6.2 "Run detail"): warnings first, the totals per currency (sticky under
 * the top bar on a phone), everyone's payslip (base, bonuses, fines, advances, net, status), and
 * the actions its status allows, each with a clear confirmation: calculate, finalize, send
 * payslips, mark paid, reopen, cancel, export. The payslip drawer opens on `?payslip=`.
 * The `payroll.run.toolbar` slot sits beside the actions.
 */
import { Ban, Calculator, CircleCheck, Ellipsis, HandCoins, Lock, LockOpen, RotateCcw, Search, Send, UsersRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import DataTable from "@/components/DataTable.vue";
import DeltaBadge from "@/components/DeltaBadge.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { normalize } from "@/components/options";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, usePayslips, useRefresh, useRun } from "../api";
import MarkPaidDialog from "../components/MarkPaidDialog.vue";
import PayAmount from "../components/PayAmount.vue";
import PayslipDrawer from "../components/PayslipDrawer.vue";
import RunWarnings from "../components/RunWarnings.vue";
import { PAYSLIP_TONES, quantityText, RUN_TONES, runActions, type Can } from "../lib";
import type { Payslip, RunAction } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const { isPhone } = useBreakpoints();

const runId = computed(() => Number(route.params.runId));
const query = useRun(runId);
const run = computed(() => query.data.value ?? null);
const slipsQuery = usePayslips(runId);
const payslips = computed(() => slipsQuery.data.value ?? []);
const skeleton = useDelayedPending(computed(() => query.isPending.value));

const title = computed(() => {
  const r = run.value;
  if (!r) return t("payroll.run.title");
  return r.kind === "final" ? t("payroll.run.finalTitle", { name: r.member?.name ?? "—" }) : fmt.day(r.period, "monthYear");
});
usePageTitle(() => (run.value ? title.value : undefined));

const can: Can = (perm) => company.can(perm);
const actions = computed<RunAction[]>(() => (run.value ? runActions(run.value, can, slipsQuery.data.value) : []));
const has = (action: RunAction) => actions.value.includes(action);
const totals = computed(() => run.value?.totals?.currencies ?? []);
const peopleCount = computed(() => run.value?.totals?.people ?? payslips.value.length);

// Payslips table -----------------------------------------------------------------------------

const table = useDataTable({ id: "payroll.payslips", pageSize: 500, hidden: ["gross", "deductions", "days"] });
const search = ref("");
const show = ref<"all" | "waiting" | "paid">("all");
const visible = computed(() => {
  const needle = normalize(search.value.trim());
  return payslips.value
    .filter((slip) => (show.value === "all" ? true : show.value === "paid" ? slip.status === "paid" : slip.status !== "paid"))
    .filter((slip) => !needle || normalize(`${slip.member.name} ${slip.member.position ?? ""} ${slip.member.branch ?? ""}`).includes(needle))
    .sort((a, b) => a.member.name.localeCompare(b.member.name));
});
const selectable = computed(() => run.value?.status === "finalized" && has("mark_paid"));

const columns = computed<TableColumn<Payslip>[]>(() => [
  { id: "person", header: t("payroll.payslips.person"), minWidth: 220, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "days", header: t("payroll.payslips.days"), width: 96, numeric: true, value: (row) => row.paid_days ?? "" },
  { id: "base", header: t("payroll.payslips.base"), width: 140, numeric: true, value: (row) => row.base_pay ?? null },
  { id: "bonuses", header: t("payroll.payslips.bonuses"), width: 130, numeric: true, value: (row) => row.bonuses ?? null },
  { id: "fines", header: t("payroll.payslips.fines"), width: 130, numeric: true, value: (row) => row.fines ?? null },
  { id: "advances", header: t("payroll.payslips.advances"), width: 130, numeric: true, value: (row) => row.advances ?? null },
  { id: "gross", header: t("payroll.totals.gross"), width: 140, numeric: true, value: (row) => row.gross ?? null },
  { id: "deductions", header: t("payroll.totals.deductions"), width: 140, numeric: true, value: (row) => row.deductions ?? null },
  { id: "net", header: t("payroll.totals.net"), width: 150, numeric: true, value: (row) => row.net ?? null },
  { id: "change", header: t("payroll.payslips.change"), width: 104, numeric: true, hint: t("payroll.payslips.changeHint"), value: (row) => row.change_percent ?? null },
  { id: "status", header: t("payroll.payslips.status"), width: 120, value: (row) => t(`payroll.payslipStatus.${row.status}`) },
]);

const activeKey = computed(() => (typeof route.query.payslip === "string" ? route.query.payslip : null));
function openSlip(slip: Payslip): void {
  void router.push({ query: { ...route.query, payslip: String(slip.id) } });
}

// Actions ------------------------------------------------------------------------------------

const busy = ref<RunAction | null>(null);
const monthText = computed(() => (run.value ? fmt.day(run.value.period, "monthYear") : ""));

async function act(action: "calculate" | "finalize" | "reopen" | "cancel" | "publish", body: Record<string, unknown> = {}, done?: string): Promise<boolean> {
  if (!run.value || busy.value) return false;
  busy.value = action;
  try {
    await payrollApi.runAction(company.currentId ?? 0, run.value.id, action, body);
    if (done) toast.success(done);
    refresh();
    return true;
  } catch {
    return false;
  } finally {
    busy.value = null;
  }
}

const calculate = () => act("calculate", {}, t("payroll.run.calculated"));

async function finalize(): Promise<void> {
  const r = run.value;
  if (!r) return;
  const answer = await confirm({
    title: t("payroll.run.finalizeTitle", { month: monthText.value }),
    message: r.warnings.length ? `${t("payroll.run.finalizeBody")} ${t("payroll.run.finalizeWarnings", { n: r.warnings.length }, r.warnings.length)}` : t("payroll.run.finalizeBody"),
    confirmLabel: t("payroll.run.finalize"),
    icon: Lock,
  });
  if (answer) await act("finalize", {}, t("payroll.run.finalized"));
}

async function publish(): Promise<void> {
  const waiting = payslips.value.filter((slip) => slip.status === "draft").length || peopleCount.value;
  const answer = await confirm({
    title: t("payroll.run.publishTitle", { n: waiting }, waiting),
    message: t("payroll.run.publishBody"),
    confirmLabel: t("payroll.run.publish"),
    icon: Send,
  });
  if (answer) await act("publish", {}, t("payroll.run.published", { n: waiting }, waiting));
}

async function reopen(): Promise<void> {
  const answer = await confirm({
    title: t("payroll.run.reopenTitle", { month: monthText.value }),
    message: t("payroll.run.reopenBody"),
    confirmLabel: t("payroll.run.reopen"),
    tone: "danger",
    reason: "optional",
    reasonLabel: t("payroll.run.reopenReason"),
    icon: LockOpen,
  });
  if (answer) await act("reopen", answer.reason ? { reason: answer.reason } : {}, t("payroll.run.reopened"));
}

async function cancel(): Promise<void> {
  const answer = await confirm({
    title: t("payroll.run.cancelTitle", { month: monthText.value }),
    message: t("payroll.run.cancelBody"),
    confirmLabel: t("payroll.run.cancel"),
    tone: "danger",
    reason: "optional",
    reasonLabel: t("common.reason"),
    icon: Ban,
  });
  if (answer && (await act("cancel", answer.reason ? { reason: answer.reason } : {}, t("payroll.run.cancelled")))) {
    void router.push(`/c/${company.currentId}/payroll`);
  }
}

const payOpen = ref(false);
const payIds = ref<number[] | null>(null);
function startPay(ids: number[] | null): void {
  payIds.value = ids;
  payOpen.value = true;
}

/** The one main action for the status; the rest go in the More menu. */
const primary = computed<RunAction | null>(() => {
  const r = run.value;
  if (!r) return null;
  if (r.status === "draft") return has("finalize") ? "finalize" : has("calculate") ? "calculate" : null;
  if (r.status === "finalized") return has("publish") ? "publish" : has("mark_paid") ? "mark_paid" : null;
  return null;
});
const secondary = computed<RunAction[]>(() => {
  const r = run.value;
  if (!r) return [];
  const list: RunAction[] = [];
  if (r.status === "draft" && has("calculate") && primary.value !== "calculate") list.push("calculate");
  if (r.status === "finalized" && has("mark_paid") && primary.value !== "mark_paid") list.push("mark_paid");
  return list;
});
const ICONS: Record<RunAction, typeof Calculator> = { calculate: Calculator, finalize: Lock, publish: Send, mark_paid: HandCoins, reopen: RotateCcw, cancel: Ban, export: CircleCheck };
const LABELS = computed<Record<RunAction, string>>(() => ({
  calculate: run.value?.calculated_at ? t("payroll.run.recalculate") : t("payroll.run.calculate"),
  finalize: t("payroll.run.finalize"),
  publish: t("payroll.run.publish"),
  mark_paid: t("payroll.run.markPaid"),
  reopen: t("payroll.run.reopen"),
  cancel: t("payroll.run.cancel"),
  export: t("common.export"),
}));
function run_(action: RunAction): void {
  if (action === "calculate") void calculate();
  else if (action === "finalize") void finalize();
  else if (action === "publish") void publish();
  else if (action === "mark_paid") startPay(null);
  else if (action === "reopen") void reopen();
  else if (action === "cancel") void cancel();
}
const menu = computed<MenuEntry[]>(() => {
  const list: MenuEntry[] = [];
  if (has("reopen")) list.push({ label: t("payroll.run.reopen"), description: t("payroll.run.reopenHint"), icon: RotateCcw, onSelect: () => void reopen() });
  if (has("cancel")) list.push({ label: t("payroll.run.cancel"), description: t("payroll.run.cancelHint"), icon: Ban, danger: true, onSelect: () => void cancel() });
  return list;
});

const metaLine = computed(() => {
  const r = run.value;
  if (!r) return "";
  if (r.status === "paid" && r.paid_at) return t("payroll.runs.paidOn", { date: fmt.instant(r.paid_at, "date") });
  if (r.finalized_at) return r.finalized_by ? t("payroll.run.finalizedBy", { date: fmt.instant(r.finalized_at, "date"), name: r.finalized_by.name }) : t("payroll.runs.finalizedOn", { date: fmt.instant(r.finalized_at, "date") });
  if (r.calculated_at) return t("payroll.runs.calculatedAt", { date: fmt.relative(r.calculated_at) });
  return t("payroll.runs.notCalculated");
});
const exportParams = computed(() => ({ run: runId.value }));
const statusNote = computed(() => {
  const r = run.value;
  if (!r) return null;
  if (r.status === "draft") return { tone: "info" as const, text: t("payroll.run.draftNote") };
  if (r.status === "finalized") return { tone: "info" as const, text: t("payroll.run.finalizedNote") };
  if (r.status === "cancelled") return { tone: "neutral" as const, text: t("payroll.run.cancelledNote") };
  return null;
});
</script>

<template>
  <div>
    <PageHeader :title="title" :back="`/c/${company.currentId}/payroll`" :back-label="t('payroll.nav.runs')">
      <template v-if="run" #meta>
        <StatusPill :tone="RUN_TONES[run.status]" :label="t(`payroll.runStatus.${run.status}`)" />
        <span class="inline-flex items-center gap-1 text-sm text-muted"><UsersRound :size="14" />{{ t("payroll.runs.peopleCount", { n: peopleCount }, peopleCount) }}</span>
        <span class="text-sm text-muted">{{ metaLine }}</span>
      </template>
      <template v-if="run" #actions>
        <ExtensionSlot name="payroll.run.toolbar" as="none" :context="{ run, companyId: company.currentId }" />
        <ExportButton v-if="has('export')" kind="payroll.run" :params="exportParams" sensitive variant="ghost" />
        <UiButton v-for="action in secondary" :key="action" :icon="ICONS[action]" :loading="busy === action" :data-testid="`run-${action}`" @click="run_(action)">{{ LABELS[action] }}</UiButton>
        <UiButton v-if="primary" variant="primary" :icon="ICONS[primary]" :loading="busy === primary" :data-testid="`run-${primary}`" @click="run_(primary)">{{ LABELS[primary] }}</UiButton>
        <DropdownMenu v-if="menu.length" :items="menu" width="280px">
          <template #trigger>
            <IconButton :icon="Ellipsis" :label="t('payroll.run.more')" variant="secondary" data-testid="run-more" />
          </template>
        </DropdownMenu>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="flex flex-col gap-4">
      <SkeletonBlock height="88px" radius="12px" />
      <SkeletonBlock v-for="n in 6" :key="n" height="52px" radius="10px" />
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="run" class="flex flex-col gap-4">
      <RunWarnings v-if="run.warnings.length && run.status === 'draft'" :warnings="run.warnings" :final="run.kind === 'final'" />
      <InlineAlert v-if="statusNote" :tone="statusNote.tone" size="sm" :description="statusNote.text" />

      <!-- Totals per currency; on a phone they stay under the top bar while the list scrolls. -->
      <section
        v-for="row in totals"
        :key="row.currency"
        class="ui-card sticky top-[calc(var(--topbar-h)+var(--safe-top))] z-10 grid grid-cols-3 gap-x-3 gap-y-1 px-4 py-3 md:static md:grid-cols-4 md:px-5 md:py-4"
        :aria-label="t('payroll.totals.title')"
        data-testid="run-totals"
      >
        <div class="hidden md:block">
          <p class="kpi-label">{{ t("payroll.runs.people") }}</p>
          <p class="mt-1 text-xl font-semibold tabular-nums text-fg">{{ row.people }}</p>
        </div>
        <div class="min-w-0">
          <p class="kpi-label">{{ t("payroll.totals.gross") }}</p>
          <p class="mt-1 truncate text-base font-semibold tabular-nums text-fg md:text-xl"><PayAmount :value="row.gross" :currency="row.currency" :compact="isPhone" /></p>
        </div>
        <div class="min-w-0">
          <p class="kpi-label">{{ t("payroll.totals.deductions") }}</p>
          <p class="mt-1 truncate text-base font-semibold tabular-nums text-fg md:text-xl"><PayAmount :value="row.deductions" :currency="row.currency" :compact="isPhone" /></p>
        </div>
        <div class="min-w-0">
          <p class="kpi-label">{{ t("payroll.totals.net") }}</p>
          <p class="mt-1 truncate text-base font-semibold tabular-nums text-accent-fg md:text-xl" data-testid="run-net"><PayAmount :value="row.net" :currency="row.currency" :compact="isPhone" /></p>
        </div>
      </section>

      <DataTable
        :state="table"
        :columns="columns"
        :rows="visible"
        row-key="id"
        :loading="slipsQuery.isPending.value"
        :fetching="slipsQuery.isFetching.value"
        :error="slipsQuery.error.value"
        :retry="() => slipsQuery.refetch()"
        clickable
        :selectable="selectable"
        :active-key="activeKey"
        :filtered="!!search || show !== 'all'"
        hide-pagination
        csv-name="payslips"
        @row-click="openSlip"
        @clear-filters="
          search = '';
          show = 'all';
        "
      >
        <template #toolbar>
          <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <TextInput v-model="search" :icon="Search" size="sm" clearable :placeholder="t('payroll.payslips.search')" class="w-full sm:w-64" />
            <SegmentedControl
              v-if="run.status !== 'draft'"
              v-model="show"
              size="sm"
              :options="[
                { value: 'all', label: t('payroll.payslips.showAll') },
                { value: 'waiting', label: t('payroll.payslips.showWaiting') },
                { value: 'paid', label: t('payroll.payslips.showPaid') },
              ]"
            />
          </div>
        </template>
        <template #bulk="{ selected }">
          <UiButton size="sm" variant="primary" :icon="HandCoins" @click="startPay(selected.map(Number))">{{ t("payroll.run.markPaidSome", { n: selected.length }, selected.length) }}</UiButton>
        </template>
        <template #empty>
          <EmptyState
            :icon="UsersRound"
            :title="search || show !== 'all' ? t('payroll.payslips.noMatch') : run.calculated_at ? t('payroll.payslips.empty') : t('payroll.payslips.notCalculated')"
            :description="search || show !== 'all' ? undefined : run.calculated_at ? t('payroll.payslips.emptyBody') : t('payroll.payslips.notCalculatedBody')"
          >
            <UiButton v-if="!run.calculated_at && has('calculate')" variant="primary" :icon="Calculator" :loading="busy === 'calculate'" @click="calculate">{{ t("payroll.run.calculate") }}</UiButton>
          </EmptyState>
        </template>
        <template #cell-person="{ row }">
          <div class="flex min-w-0 items-center gap-2.5">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="30" />
            <div class="min-w-0">
              <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
              <p class="truncate text-xs text-muted">{{ [row.member.position, row.member.branch].filter(Boolean).join(" · ") || t(`payroll.payType.${row.pay_type}`) }}</p>
            </div>
          </div>
        </template>
        <template #cell-days="{ row }">
          <span v-if="row.paid_days !== null && row.scheduled_days !== null" class="tabular-nums text-fg">{{ quantityText(row.paid_days, fmt.lang.value) }}<span class="text-muted">/{{ quantityText(row.scheduled_days, fmt.lang.value) }}</span></span>
          <span v-else class="text-subtle">—</span>
        </template>
        <template #cell-base="{ row }"><PayAmount cell :value="row.base_pay" :currency="row.currency" /></template>
        <template #cell-bonuses="{ row }"><PayAmount cell :value="row.bonuses" :currency="row.currency" sign="always" colored /></template>
        <template #cell-fines="{ row }"><PayAmount cell :value="row.fines" :currency="row.currency" colored /></template>
        <template #cell-advances="{ row }"><PayAmount cell :value="row.advances" :currency="row.currency" colored /></template>
        <template #cell-gross="{ row }"><PayAmount cell :value="row.gross" :currency="row.currency" /></template>
        <template #cell-deductions="{ row }"><PayAmount cell :value="row.deductions" :currency="row.currency" /></template>
        <template #cell-net="{ row }"><PayAmount cell strong :value="row.net" :currency="row.currency" /></template>
        <template #cell-change="{ row }">
          <DeltaBadge v-if="row.change_percent !== null && row.change_percent !== undefined" :value="row.change_percent" />
          <span v-else class="text-sm text-subtle">—</span>
        </template>
        <template #cell-status="{ row }">
          <StatusPill :tone="PAYSLIP_TONES[row.status]" size="sm" :label="t(`payroll.payslipStatus.${row.status}`)" />
        </template>
        <template #card="{ row }">
          <div class="flex items-start gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
              <p class="truncate text-xs text-muted">{{ [row.member.position, row.member.branch].filter(Boolean).join(" · ") || t(`payroll.payType.${row.pay_type}`) }}</p>
              <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
                <span>{{ t("payroll.payslips.base") }}: <PayAmount :value="row.base_pay" :currency="row.currency" /></span>
                <span v-if="row.bonuses && row.bonuses !== '0.00'" class="text-success"><PayAmount :value="row.bonuses" :currency="row.currency" sign="always" /></span>
                <span v-if="row.fines && row.fines !== '0.00'" class="text-danger"><PayAmount :value="row.fines" :currency="row.currency" /></span>
                <span v-if="row.advances && row.advances !== '0.00'">{{ t("payroll.payslips.advances") }}: <PayAmount :value="row.advances" :currency="row.currency" /></span>
              </div>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-1">
              <PayAmount cell strong :value="row.net" :currency="row.currency" />
              <StatusPill :tone="PAYSLIP_TONES[row.status]" size="sm" :label="t(`payroll.payslipStatus.${row.status}`)" />
            </div>
          </div>
        </template>
      </DataTable>

      <PayslipDrawer :run="run" @pay="(id) => startPay([id])" />
      <MarkPaidDialog v-model:open="payOpen" :run="run" :payslips="payslips" :preselected="payIds" />
    </div>
  </div>
</template>
