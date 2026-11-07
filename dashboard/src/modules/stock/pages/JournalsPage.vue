<script setup lang="ts">
/**
 * The journals an inspector asks for, made from the stock records:
 * - the controlled-substance register of a month at a branch licensed for narcotics and
 *   psychotropics (opening, received, issued, written off, closing), closed with the counted
 *   balance by the close day; a difference is reported to the authorities and marked here;
 * - the prescription log (when Settings › Stock keeps it), with the invalid prescriptions.
 * Both print as PDF pages laid out like the paper books, which stay the legal record.
 */
import { FileText, Lock, Stamp } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import DatePicker from "@/components/DatePicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import NumberInput from "@/components/NumberInput.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextArea from "@/components/TextArea.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addMonths } from "@/lib/dates";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useControlled, useRefresh, useRxJournal, useStockSettings } from "../api";
import { num, packsAndParts, previousMonth } from "../lib";
import type { ControlledRow } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();
const refresh = useRefresh();
const settings = useStockSettings();

const tab = useRouteState("tab", rs.string("controlled"));
const month = useRouteState("month", rs.string(previousMonth(today.value)));
const branchParam = useRouteState("branch", rs.optionalNumber());

const scopedBranches = computed(() => company.current?.branches ?? []);
const branch = computed(() => branchParam.value ?? scopedBranches.value[0]?.id ?? null);
const params = computed(() => ({ branch: branch.value ?? undefined, month: month.value }));
const register = useControlled(params, () => tab.value === "controlled" && branch.value !== null);
const rx = useRxJournal(params, () => tab.value === "rx" && branch.value !== null && !!settings.data.value?.rx_log);

// The register answers with the licensed branches in scope: start at the first of them.
watch(
  () => register.data.value,
  (data) => {
    if (!data || !data.branches.length) return;
    if (!data.branches.some((row) => row.id === branch.value)) branchParam.value = data.branches[0]!.id;
  },
);

const tabs = computed(() => [
  { value: "controlled", label: t("stock.journals.controlled") },
  ...(settings.data.value?.rx_log ? [{ value: "rx", label: t("stock.journals.rx") }] : []),
]);
const branchOptions = computed(() => {
  const licensed = register.data.value?.branches;
  const rows = tab.value === "controlled" && licensed?.length ? licensed : scopedBranches.value;
  return rows.map((row) => ({ value: row.id, label: row.name }));
});
const branchModel = computed({ get: () => branch.value, set: (value: number | null) => (branchParam.value = value) });
const monthOptions = computed(() => {
  const first = `${today.value.slice(0, 7)}-01`;
  return Array.from({ length: 13 }, (_, index) => {
    const day = addMonths(first, -index);
    return { value: day.slice(0, 7), label: fmt.day(day, "monthYear") };
  });
});
const noLicence = computed(() => tab.value === "controlled" && register.data.value && !register.data.value.branches.length);
const rows = computed(() => register.data.value?.rows ?? []);
const isPast = computed(() => month.value < today.value.slice(0, 7));
const canClose = computed(() => isPast.value && rows.value.length > 0 && !rows.value.some((row) => row.reported_on));

const qty = (value: string | null) => (value === null ? "—" : packsAndParts(value, 1, "", t));

const closing = reactive({ open: false, note: "", counted: {} as Record<number, number | null> });
function startClose(): void {
  closing.counted = Object.fromEntries(rows.value.map((row) => [row.product_id, num(row.counted ?? row.closing)]));
  closing.note = "";
  closing.open = true;
}
const busy = ref(false);
async function close(): Promise<void> {
  if (branch.value === null) return;
  busy.value = true;
  try {
    const answer = await stockApi.closeMonth(company.currentId ?? 0, {
      branch: branch.value,
      month: `${month.value}-01`,
      counted: Object.entries(closing.counted).map(([product, counted]) => ({ product: Number(product), counted: String(counted ?? 0) })),
      note: closing.note.trim(),
    });
    const differences = answer.rows.filter((row) => num(row.difference) !== 0).length;
    if (differences) toast.error(t("stock.journals.differences", { n: differences }, differences));
    else toast.success(t("stock.journals.closedToast"));
    refresh();
    closing.open = false;
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    busy.value = false;
  }
}

const reporting = reactive({ open: false, period: 0, day: null as string | null, product: "" });
function startReport(row: ControlledRow): void {
  if (!row.period_id) return;
  Object.assign(reporting, { open: true, period: row.period_id, day: today.value, product: row.product });
}
async function report(): Promise<void> {
  if (!reporting.day) return;
  busy.value = true;
  try {
    await stockApi.reported(company.currentId ?? 0, reporting.period, reporting.day);
    toast.success(t("stock.journals.reportedToast"));
    refresh();
    reporting.open = false;
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    busy.value = false;
  }
}

async function pdf(kind: "controlled" | "rx" | "rx_invalid"): Promise<void> {
  if (branch.value === null) return;
  try {
    const query = { branch: branch.value, month: month.value, invalid: kind === "rx_invalid" ? "true" : undefined };
    const link = kind === "controlled" ? await stockApi.controlledPdf(company.currentId ?? 0, query) : await stockApi.rxPdf(company.currentId ?? 0, query);
    window.open(link.url, "_blank", "noopener");
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  }
}
</script>

<template>
  <div>
    <PageHeader :title="t('stock.nav.journals')" :description="t('stock.journals.description')" />

    <div class="mb-4 flex flex-wrap items-center gap-2">
      <SegmentedControl v-if="tabs.length > 1" v-model="tab" :options="tabs" size="sm" />
      <SelectBox v-model="branchModel" :options="branchOptions" size="sm" class="w-48" :placeholder="t('stock.field.branch')" />
      <SelectBox v-model="month" :options="monthOptions" size="sm" class="w-44" />
      <span class="ms-auto flex flex-wrap gap-2">
        <template v-if="tab === 'controlled'">
          <UiButton size="sm" variant="secondary" :icon="FileText" :disabled="!rows.length" @click="pdf('controlled')">{{ t("stock.journals.print") }}</UiButton>
          <UiButton size="sm" variant="primary" :icon="Lock" :disabled="!canClose" data-testid="close-month" @click="startClose">{{ t("stock.journals.close") }}</UiButton>
        </template>
        <template v-else>
          <UiButton size="sm" variant="secondary" :icon="FileText" @click="pdf('rx')">{{ t("stock.journals.printRx") }}</UiButton>
          <UiButton size="sm" variant="secondary" :icon="FileText" @click="pdf('rx_invalid')">{{ t("stock.journals.printInvalid") }}</UiButton>
        </template>
      </span>
    </div>

    <template v-if="tab === 'controlled'">
      <div v-if="noLicence" class="ui-card">
        <EmptyState :icon="Lock" :title="t('stock.journals.noLicenceTitle')" :description="t('stock.journals.noLicenceBody')" />
      </div>
      <template v-else>
        <InlineAlert v-if="register.data.value && isPast && !register.data.value.closed && rows.length" class="mb-4" tone="warning">
          {{ t("stock.journals.closeBy", { day: fmt.day(register.data.value.close_by) }) }}
        </InlineAlert>
        <div class="ui-card overflow-x-auto">
          <table class="w-full min-w-[860px] text-sm" data-testid="controlled-rows">
            <thead class="text-xs text-muted">
              <tr class="border-b border-line">
                <th class="px-4 py-2 text-start font-medium">{{ t("stock.col.name") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.opening") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.received") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.issued") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.writtenOff") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.adjusted") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.closing") }}</th>
                <th class="px-3 py-2 text-end font-medium">{{ t("stock.journals.counted") }}</th>
                <th class="px-4 py-2 text-end font-medium">{{ t("stock.journals.difference") }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="row in rows" :key="row.product_id">
                <td class="px-4 py-2">
                  <span class="block text-fg">{{ row.product }}</span>
                  <span class="block text-xs text-muted">{{ t(`stock.control.${row.control_class}`) }}<template v-if="row.unrecorded_issues"> · <span class="text-warning">{{ t("stock.journals.unrecorded", { n: row.unrecorded_issues }, row.unrecorded_issues) }}</span></template></span>
                </td>
                <td class="px-3 py-2 text-end tabular-nums">{{ qty(row.opening) }}</td>
                <td class="px-3 py-2 text-end tabular-nums">{{ qty(row.received) }}</td>
                <td class="px-3 py-2 text-end tabular-nums">{{ qty(row.issued) }}</td>
                <td class="px-3 py-2 text-end tabular-nums">{{ qty(row.written_off) }}</td>
                <td class="px-3 py-2 text-end tabular-nums text-muted">{{ qty(row.adjusted) }}</td>
                <td class="px-3 py-2 text-end font-medium tabular-nums text-fg">{{ qty(row.closing) }}</td>
                <td class="px-3 py-2 text-end tabular-nums">{{ qty(row.counted) }}</td>
                <td class="px-4 py-2 text-end">
                  <span v-if="row.difference !== null && num(row.difference) !== 0" class="flex flex-col items-end gap-1">
                    <StatusPill tone="danger" size="sm" :label="qty(row.difference)" />
                    <span v-if="row.reported_on" class="text-xs text-muted">{{ t("stock.journals.reportedOn", { day: fmt.day(row.reported_on) }) }}</span>
                    <UiButton v-else size="sm" variant="secondary" :icon="Stamp" @click="startReport(row)">{{ t("stock.journals.markReported") }}</UiButton>
                  </span>
                  <span v-else-if="row.closed_at" class="text-xs text-success">{{ t("stock.journals.matches") }}</span>
                  <span v-else class="text-subtle">—</span>
                </td>
              </tr>
              <tr v-if="register.data.value && !rows.length">
                <td colspan="9" class="px-4 py-6 text-center text-muted">{{ t("stock.journals.empty") }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-3 text-xs text-muted">{{ t("stock.journals.paperNote") }}</p>
      </template>
    </template>

    <template v-else>
      <div class="ui-card overflow-x-auto">
        <table class="w-full min-w-[860px] text-sm" data-testid="rx-rows">
          <thead class="text-xs text-muted">
            <tr class="border-b border-line">
              <th class="px-4 py-2 text-start font-medium">{{ t("stock.rx.day") }}</th>
              <th class="px-3 py-2 text-start font-medium">{{ t("stock.rx.number") }}</th>
              <th class="px-3 py-2 text-start font-medium">{{ t("stock.col.name") }}</th>
              <th class="px-3 py-2 text-start font-medium">{{ t("stock.rx.prescriber") }}</th>
              <th class="px-3 py-2 text-start font-medium">{{ t("stock.rx.kind") }}</th>
              <th class="px-4 py-2 text-start font-medium">{{ t("stock.col.status") }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="row in rx.data.value?.rows ?? []" :key="row.id">
              <td class="px-4 py-2 text-xs text-muted">{{ fmt.instant(row.recorded_at, "short") }}</td>
              <td class="px-3 py-2 font-mono text-xs">{{ row.prescription_number || row.e_prescription_id || "—" }}</td>
              <td class="px-3 py-2 text-fg">{{ row.product.name }}<span v-if="row.series" class="text-xs text-muted"> · {{ row.series }}</span></td>
              <td class="px-3 py-2 text-muted">{{ [row.prescriber, row.facility].filter(Boolean).join(" · ") || "—" }}</td>
              <td class="px-3 py-2">{{ t(`stock.rxKind.${row.rx_kind}`) }}</td>
              <td class="px-4 py-2">
                <span class="flex flex-wrap gap-1">
                  <StatusPill :tone="row.status === 'invalid' ? 'danger' : 'success'" size="sm" :label="t(`stock.rxStatus.${row.status}`)" />
                  <StatusPill v-for="flag in row.flags" :key="flag" tone="warning" size="sm" :label="t(`stock.rxFlag.${flag}`)" />
                </span>
              </td>
            </tr>
            <tr v-if="rx.data.value && !rx.data.value.rows.length">
              <td colspan="6" class="px-4 py-6 text-center text-muted">{{ t("stock.rx.empty") }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <UiDialog v-model:open="closing.open" :title="t('stock.journals.closeTitle', { month: fmt.day(`${month}-01`, 'monthYear') })" :description="t('stock.journals.closeDescription')" size="md">
      <ul class="flex flex-col gap-2">
        <li v-for="row in rows" :key="row.product_id" class="flex items-center gap-3">
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm text-fg">{{ row.product }}</span>
            <span class="block text-xs text-muted">{{ t("stock.journals.byRegister", { qty: qty(row.closing) }) }}</span>
          </span>
          <NumberInput v-model="closing.counted[row.product_id]" :min="0" :decimals="3" size="sm" class="w-32" />
        </li>
      </ul>
      <FormField class="mt-3" :label="t('stock.field.note')" optional>
        <TextArea v-model="closing.note" :rows="2" />
      </FormField>
      <template #footer>
        <UiButton variant="ghost" @click="closing.open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" @click="close">{{ t("stock.journals.closeConfirm") }}</UiButton>
      </template>
    </UiDialog>

    <UiDialog v-model:open="reporting.open" :title="t('stock.journals.reportTitle')" :description="reporting.product" size="sm">
      <FormField :label="t('stock.journals.reportedDay')" :hint="t('stock.journals.reportHint')">
        <DatePicker v-model="reporting.day" :max="today" />
      </FormField>
      <template #footer>
        <UiButton variant="ghost" @click="reporting.open = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :loading="busy" :disabled="!reporting.day" @click="report">{{ t("common.save") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
