<script setup lang="ts">
/**
 * Advances (plan §6.2 "Advances & loans with repayment schedule"): requests to decide, approved ones
 * to pay out (method and account), ones being repaid from payslips month by month, and the closed
 * ones (repaid, rejected, cancelled). "Give an advance" (`?new=1` from the palette) for someone who
 * asked in person. A row opens its drawer on `?advance=`.
 */
import { HandCoins, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ApproveRejectButtons from "@/components/ApproveRejectButtons.vue";
import DataTable from "@/components/DataTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import StatusPill from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { payrollApi, useAdvances, useRefresh } from "../api";
import AdvanceDialog from "../components/AdvanceDialog.vue";
import AdvanceDrawer from "../components/AdvanceDrawer.vue";
import PayAdvanceDialog from "../components/PayAdvanceDialog.vue";
import PayAmount from "../components/PayAmount.vue";
import { ADVANCE_TAB_STATUSES, ADVANCE_TONES, repaidShare, type AdvanceTab } from "../lib";
import type { Advance } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const refresh = useRefresh();
const canManage = computed(() => company.can("payroll.manage"));
const canPay = computed(() => company.can("payroll.pay"));

const TABS = ["requests", "to_pay", "repaying", "closed"] as const;
const tab = useRouteState<AdvanceTab>("tab", rs.enum(TABS, "requests"));
const table = useDataTable({ id: "payroll.advances", url: true });
table.resetPageOn(() => [tab.value]);
const params = computed(() => ({ status: ADVANCE_TAB_STATUSES[tab.value].join(","), ...table.params.value }));
const list = useAdvances(params);
const requests = useAdvances(() => ({ status: "requested", page_size: 1 }));
const toPay = useAdvances(() => ({ status: "approved", page_size: 1 }));
const rows = computed(() => list.data.value?.results ?? []);

const tabs = computed(() => [
  { id: "requests", label: t("payroll.advances.tab.requests"), count: requests.data.value?.count || undefined },
  { id: "to_pay", label: t("payroll.advances.tab.to_pay"), count: toPay.data.value?.count || undefined },
  { id: "repaying", label: t("payroll.advances.tab.repaying") },
  { id: "closed", label: t("payroll.advances.tab.closed") },
]);

const columns = computed<TableColumn<Advance>[]>(() => [
  { id: "person", header: t("payroll.payslips.person"), minWidth: 210, sticky: true, hideable: false, value: (row) => row.member.name },
  { id: "amount", header: t("payroll.field.amount"), width: 150, numeric: true, value: (row) => row.amount ?? null },
  { id: "plan", header: t("payroll.advances.plan"), width: 190, value: (row) => planText(row) },
  { id: "reason", header: t("payroll.adjustments.reason"), minWidth: 180, value: (row) => row.reason },
  ...(tab.value === "repaying" ? [{ id: "repaid", header: t("payroll.advances.repaid"), width: 150, value: (row: Advance) => row.repaid ?? null }] : []),
  { id: "requested", header: t("payroll.advances.requested"), width: 130, value: (row) => row.created_at },
  ...(tab.value === "requests" && canManage.value ? [{ id: "decide", header: "", width: 96, hideable: false, value: () => "" }] : []),
  ...(tab.value === "to_pay" && canPay.value ? [{ id: "pay", header: "", width: 110, hideable: false, value: () => "" }] : []),
  ...(tab.value === "closed" ? [{ id: "status", header: t("payroll.payslips.status"), width: 130, value: (row: Advance) => t(`payroll.advanceStatus.${row.status}`) }] : []),
]);

function planText(row: Advance): string {
  return row.installments > 1
    ? t("payroll.advances.planMany", { n: row.installments, month: fmt.day(row.first_period, "monthYear") }, row.installments)
    : t("payroll.advances.planOne", { month: fmt.day(row.first_period, "monthYear") });
}

function open(row: Advance): void {
  void router.push({ query: { ...route.query, advance: String(row.id) } });
}
const activeKey = computed(() => (typeof route.query.advance === "string" ? route.query.advance : null));

async function decide(row: Advance, decision: "approve" | "reject", note = ""): Promise<void> {
  await payrollApi.decideAdvance(company.currentId ?? 0, row.id, decision, note);
  toast.success(decision === "approve" ? t("payroll.advances.approved") : t("payroll.advances.rejected"));
  refresh();
}

const paying = ref<Advance | null>(null);
const payOpen = ref(false);
function pay(row: Advance): void {
  paying.value = row;
  payOpen.value = true;
}

const giveOpen = ref(false);
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (canManage.value) giveOpen.value = true;
  },
  { immediate: true },
);
</script>

<template>
  <div>
    <PageHeader v-model:tab="tab" :title="t('payroll.nav.advances')" :description="t('payroll.advances.description')" :tabs="tabs">
      <template v-if="canManage" #actions>
        <UiButton variant="primary" :icon="Plus" data-testid="give-advance" @click="giveOpen = true">{{ t("payroll.advances.give") }}</UiButton>
      </template>
    </PageHeader>

    <DataTable
      :state="table"
      :columns="columns"
      :rows="rows"
      :total="list.data.value?.count"
      row-key="id"
      :loading="list.isPending.value"
      :fetching="list.isFetching.value"
      :error="list.error.value"
      :retry="() => list.refetch()"
      clickable
      :active-key="activeKey"
      csv-name="advances"
      @row-click="open"
    >
      <template #empty>
        <EmptyState :icon="HandCoins" :tone="tab === 'requests' || tab === 'to_pay' ? 'success' : 'primary'" :title="t(`payroll.advances.empty.${tab}`)" :description="t(`payroll.advances.emptyBody.${tab}`)">
          <UiButton v-if="canManage && tab === 'requests'" variant="primary" :icon="Plus" @click="giveOpen = true">{{ t("payroll.advances.give") }}</UiButton>
        </EmptyState>
      </template>
      <template #cell-person="{ row }">
        <div class="flex min-w-0 items-center gap-2.5">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="30" />
          <div class="min-w-0">
            <p class="truncate text-base font-medium text-fg" :title="row.member.name">{{ row.member.name }}</p>
            <p v-if="row.member.position" class="truncate text-xs text-muted">{{ row.member.position }}</p>
          </div>
        </div>
      </template>
      <template #cell-amount="{ row }"><PayAmount cell strong :value="row.amount" :currency="row.currency" /></template>
      <template #cell-plan="{ row }"><span class="truncate text-sm text-muted">{{ planText(row) }}</span></template>
      <template #cell-reason="{ row }"><span class="truncate text-sm text-fg" :title="row.reason">{{ row.reason || "—" }}</span></template>
      <template #cell-repaid="{ row }">
        <div class="flex w-full items-center gap-2">
          <ProgressBar :value="repaidShare(row) ?? 0" :max="100" size="xs" tone="success" class="min-w-0 flex-1" />
          <span class="w-9 shrink-0 text-right text-xs tabular-nums text-muted">{{ repaidShare(row) === null ? "—" : fmt.percent(repaidShare(row)) }}</span>
        </div>
      </template>
      <template #cell-requested="{ row }"><span class="text-sm text-muted">{{ fmt.instant(row.created_at, "date") }}</span></template>
      <template #cell-decide="{ row }">
        <ApproveRejectButtons
          compact
          reason="optional"
          :reject-title="t('payroll.advances.rejectTitle', { name: row.member.name })"
          :on-approve="() => decide(row, 'approve')"
          :on-reject="(reason: string) => decide(row, 'reject', reason)"
          @click.stop
        />
      </template>
      <template #cell-pay="{ row }">
        <UiButton size="sm" variant="primary" :icon="HandCoins" @click.stop="pay(row)">{{ t("payroll.advances.pay") }}</UiButton>
      </template>
      <template #cell-status="{ row }"><StatusPill :tone="ADVANCE_TONES[row.status]" size="sm" :label="t(`payroll.advanceStatus.${row.status}`)" /></template>
      <template #card="{ row }">
        <div class="flex items-start gap-3">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="34" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-base font-semibold text-fg">{{ row.member.name }}</p>
            <p class="truncate text-xs text-muted">{{ planText(row) }}</p>
            <p v-if="row.reason" class="line-clamp-2 text-sm text-fg">{{ row.reason }}</p>
            <ProgressBar v-if="tab === 'repaying'" :value="repaidShare(row) ?? 0" :max="100" size="xs" tone="success" class="mt-1.5" />
          </div>
          <div class="flex shrink-0 flex-col items-end gap-1">
            <PayAmount cell strong :value="row.amount" :currency="row.currency" />
            <StatusPill :tone="ADVANCE_TONES[row.status]" size="sm" :label="t(`payroll.advanceStatus.${row.status}`)" />
          </div>
        </div>
      </template>
    </DataTable>

    <AdvanceDrawer @pay="pay" />
    <AdvanceDialog v-model:open="giveOpen" />
    <PayAdvanceDialog v-if="paying" v-model:open="payOpen" :advance="paying" />
  </div>
</template>
