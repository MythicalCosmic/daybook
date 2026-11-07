<script setup lang="ts">
/**
 * Invoices (plan §11.4, §14.7): sales by invoice to clinics, pharmacies and companies. The list
 * shows status and what is overdue; the drawer shows the lines (one per batch once issued, with
 * series, expiry, MXIK code and VAT), the Rx wholesale cap warnings and the payments, and does
 * the work: issue, record a payment, the PDF, send it to the customer, void before payment.
 * A new invoice starts as a draft with lines picked from the catalogue.
 */
import { Ban, FileText, Plus, Send, Stamp, Trash2, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ComboBox from "@/components/ComboBox.vue";
import DataTable from "@/components/DataTable.vue";
import FilterBar from "@/components/FilterBar.vue";
import { useUrlFilters, type FilterDef } from "@/components/filters";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import type { OptionSource, SelectOption } from "@/components/options";
import PageHeader from "@/components/PageHeader.vue";
import SelectBox from "@/components/SelectBox.vue";
import StatusPill, { type StatusTone } from "@/components/StatusPill.vue";
import type { TableColumn } from "@/components/table";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { useDataTable } from "@/components/useDataTable";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { salesApi, useInvoice, useInvoices, useOptions, useSalesMutation } from "../api";
import type { InvoiceRow, InvoiceStatus } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const confirm = useConfirm();
const options = useOptions();
const canWrite = computed(() => company.can("sales.invoices"));
const canPay = computed(() => company.can("finance.record"));
const STATUSES: InvoiceStatus[] = ["draft", "issued", "partly_paid", "paid", "void"];
const TONES: Record<InvoiceStatus, StatusTone> = { draft: "neutral", issued: "info", partly_paid: "warning", paid: "success", void: "neutral" };

const defs = computed<FilterDef[]>(() => [
  { key: "status", label: t("sales.filter.status"), type: "multi", options: STATUSES.map((value) => ({ value, label: t(`sales.invoices.status.${value}`) })) },
  { key: "overdue", label: t("sales.invoices.overdueOnly"), type: "boolean" },
  { key: "day", label: t("sales.invoices.issued"), type: "date-range", params: ["from", "to"] },
]);
const filters = useUrlFilters(defs);
const search = useRouteState<string>("q", rs.string(""));
const opened = useRouteState<number | null>("invoice", rs.optionalNumber());
const table = useDataTable({ id: "sales.invoices", url: true });
table.resetPageOn(() => [filters.params.value, search.value]);
const query = useInvoices(computed(() => ({ ...filters.params.value, ...(search.value ? { q: search.value } : {}), ...table.params.value })));
const detail = useInvoice(opened);
const invoice = computed(() => detail.data.value);
const drawer = computed({ get: () => opened.value !== null, set: (value: boolean) => !value && (opened.value = null) });

const columns = computed<TableColumn<InvoiceRow>[]>(() => [
  { id: "number", header: t("sales.invoices.number"), width: 150, value: (row) => row.number || t("sales.invoices.draft") },
  { id: "customer", header: t("sales.invoices.customer"), minWidth: 200, value: (row) => row.customer.name },
  { id: "status", header: t("sales.filter.status"), width: 130 },
  { id: "issued_on", header: t("sales.invoices.issued"), width: 120, format: (v) => (v ? fmt.day(String(v)) : "—") },
  { id: "due_on", header: t("sales.invoices.due"), width: 120, format: (v) => (v ? fmt.day(String(v)) : "—") },
  { id: "total", header: t("sales.invoices.total"), width: 150, numeric: true, csv: (row) => row.total },
  { id: "left", header: t("sales.invoices.left"), width: 150, numeric: true, csv: (row) => row.left },
]);

const run = useSalesMutation((_cid, job: () => Promise<unknown>) => job());
async function issue(): Promise<void> {
  if (!invoice.value) return;
  const id = invoice.value.id;
  await run.mutateAsync(() => salesApi.issueInvoice(cid.value, id));
  toast.success(t("sales.invoices.issuedToast"));
}
async function voidIt(): Promise<void> {
  if (!invoice.value) return;
  const id = invoice.value.id;
  const answer = await confirm({ title: t("sales.invoices.voidTitle"), message: t("sales.invoices.voidBody"), confirmLabel: t("sales.invoices.void"), tone: "danger", reason: "required" });
  if (!answer) return;
  await run.mutateAsync(() => salesApi.voidInvoice(cid.value, id, answer.reason));
  toast.success(t("sales.invoices.voided"));
}
async function pdf(): Promise<void> {
  if (!invoice.value) return;
  const { url } = await salesApi.invoicePdf(cid.value, invoice.value.id);
  window.open(url, "_blank", "noopener");
}
async function send(): Promise<void> {
  if (!invoice.value) return;
  const id = invoice.value.id;
  const sent = (await run.mutateAsync(() => salesApi.sendInvoice(cid.value, id))) as { delivered: string; url?: string };
  if (sent.delivered === "telegram") toast.success(t("sales.invoices.sentTelegram"));
  else if (sent.url) {
    const link = new URL(sent.url, window.location.origin).toString();
    await navigator.clipboard?.writeText(link).catch(() => undefined);
    toast.success(t("sales.invoices.sentLink"));
  }
}

// A payment -----------------------------------------------------------------------------------
const paying = ref(false);
const payment = ref({ account: null as number | null, amount: null as string | null, paid_on: "" });
const accounts = computed(() => (options.data.value?.accounts ?? []).map((row) => ({ value: row.id, label: row.name })));
function startPayment(): void {
  payment.value = { account: accounts.value[0]?.value ?? null, amount: invoice.value?.left ?? null, paid_on: options.data.value?.today ?? "" };
  paying.value = true;
}
async function pay(): Promise<void> {
  if (!invoice.value || !payment.value.account || !payment.value.amount) return;
  const id = invoice.value.id;
  const input = { account_id: payment.value.account, amount: payment.value.amount, paid_on: payment.value.paid_on };
  await run.mutateAsync(() => salesApi.payInvoice(cid.value, id, input));
  paying.value = false;
  toast.success(t("sales.invoices.paidToast"));
}

// A new invoice -------------------------------------------------------------------------------
const creating = ref(false);
type DraftLine = { product: number | null; picked: SelectOption<number> | null; name: string; quantity: string; price: string | null };
const draft = ref({ customer: null as number | null, customerPicked: null as SelectOption<number> | null, branch: null as number | null, lines: [] as DraftLine[] });
const emptyLine = (): DraftLine => ({ product: null, picked: null, name: "", quantity: "1", price: null });
function startCreate(): void {
  draft.value = { customer: null, customerPicked: null, branch: options.data.value?.branches[0]?.id ?? null, lines: [emptyLine()] };
  creating.value = true;
}
const customerSource: OptionSource<number> = async (q) => {
  const found = await salesApi.customers(cid.value, { q, page_size: 20 });
  return found.results.map((row) => ({ value: row.id, label: row.name, description: row.phone || undefined }));
};
const productSource: OptionSource<number> = async (q, signal) => {
  const found = await salesApi.products(cid.value, q, signal);
  return found.results.map((row) => ({ value: row.id, label: row.name, description: [row.barcode, row.rx_required ? t("sales.lines.rx") : ""].filter(Boolean).join(" · "), keywords: [row.sale_price] }));
};
const branches = computed(() => (options.data.value?.branches ?? []).map((row) => ({ value: row.id, label: row.name })));
const canSave = computed(() => !!draft.value.customer && draft.value.lines.some((line) => (line.product || line.name.trim()) && Number(line.quantity) > 0 && line.price !== null));
async function save(): Promise<void> {
  const lines = draft.value.lines
    .filter((line) => (line.product || line.name.trim()) && Number(line.quantity) > 0 && line.price !== null)
    .map((line) => ({ product_id: line.product, name: line.name.trim(), quantity: line.quantity, price: line.price ?? "0" }));
  const made = (await run.mutateAsync(() => salesApi.createInvoice(cid.value, { customer_id: draft.value.customer!, branch_id: draft.value.branch, lines }))) as { id: number };
  creating.value = false;
  opened.value = made.id;
  toast.success(t("sales.invoices.draftSaved"));
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('sales.invoices.title')" :description="t('sales.invoices.description')" class="!mb-0">
      <template v-if="canWrite" #actions>
        <UiButton variant="primary" :icon="Plus" @click="startCreate">{{ t("sales.invoices.new") }}</UiButton>
      </template>
    </PageHeader>
    <DataTable
      :state="table"
      :columns="columns"
      :rows="query.data.value?.results"
      :total="query.data.value?.count"
      row-key="id"
      clickable
      :loading="query.isPending.value"
      :fetching="query.isFetching.value"
      :error="query.error.value"
      :retry="() => query.refetch()"
      :filtered="filters.active.value > 0 || !!search"
      :empty-title="t('sales.invoices.emptyTitle')"
      :empty-description="t('sales.invoices.emptyBody')"
      :empty-icon="FileText"
      csv-name="invoices"
      @row-click="(row: InvoiceRow) => (opened = row.id)"
      @clear-filters="(filters.clear(), (search = ''))"
    >
      <template #toolbar><FilterBar v-model="filters.values.value" v-model:search="search" :defs="defs" searchable /></template>
      <template #cell-status="{ row }">
        <StatusPill size="sm" :tone="row.overdue ? 'danger' : TONES[row.status]" :label="row.overdue ? t('sales.invoices.overdue') : t(`sales.invoices.status.${row.status}`)" />
      </template>
      <template #cell-total="{ row }"><MoneyText :value="row.total" :currency="row.currency" class="tabular-nums" /></template>
      <template #cell-left="{ row }">
        <span :class="['tabular-nums', Number(row.left) > 0 ? 'font-semibold text-fg' : 'text-subtle']"><MoneyText :value="row.left" :currency="row.currency" /></span>
      </template>
    </DataTable>

    <UiDrawer v-model:open="drawer" size="lg" :title="invoice ? invoice.number || t('sales.invoices.draft') : t('sales.invoices.title')" :description="invoice?.customer.name">
      <div v-if="invoice" class="flex flex-col gap-4 p-5 max-sm:p-4">
        <div class="flex flex-wrap items-center gap-2">
          <StatusPill :tone="invoice.overdue ? 'danger' : TONES[invoice.status]" :label="invoice.overdue ? t('sales.invoices.overdue') : t(`sales.invoices.status.${invoice.status}`)" />
          <span v-if="invoice.issued_on" class="text-sm text-muted">{{ t("sales.invoices.issuedOn", { day: fmt.day(invoice.issued_on) }) }}</span>
          <span v-if="invoice.due_on" class="text-sm text-muted">· {{ t("sales.invoices.dueOn", { day: fmt.day(invoice.due_on) }) }}</span>
        </div>
        <InlineAlert v-for="warning in invoice.warnings" :key="warning.line" tone="warning" size="sm" :description="t('sales.invoices.capWarning', { product: warning.product, price: fmt.money(warning.price), cap: fmt.money(warning.cap) })" />
        <ul class="flex flex-col divide-y divide-line rounded-xl border border-line">
          <li v-for="line in invoice.lines" :key="line.id" class="flex items-center justify-between gap-3 px-3 py-2 text-sm">
            <span class="min-w-0">
              <span class="block truncate text-fg">{{ line.name }}</span>
              <span class="block text-xs text-muted">
                {{ t("sales.invoices.lineFacts", { quantity: fmt.number(line.quantity, 3), price: fmt.money(line.price) }) }}
                <template v-if="line.series"> · {{ t("sales.invoices.series", { series: line.series }) }}</template>
                <template v-if="line.expires_on"> · {{ t("sales.invoices.expires", { day: fmt.day(line.expires_on) }) }}</template>
                <template v-if="line.mxik_code"> · MXIK {{ line.mxik_code }}</template>
              </span>
            </span>
            <span class="shrink-0 tabular-nums font-semibold text-fg"><MoneyText :value="line.total" :currency="invoice.currency" /></span>
          </li>
        </ul>
        <div class="flex items-center justify-between text-md">
          <span class="text-muted">{{ t("sales.invoices.total") }}</span>
          <span class="font-semibold tabular-nums"><MoneyText :value="invoice.total" :currency="invoice.currency" /></span>
        </div>
        <section v-if="invoice.payments.length">
          <h3 class="mb-2 text-sm font-semibold text-fg">{{ t("sales.invoices.payments") }}</h3>
          <ul class="flex flex-col gap-1 text-sm">
            <li v-for="row in invoice.payments" :key="row.id" class="flex justify-between">
              <span class="text-muted">{{ fmt.day(row.paid_on) }} · {{ row.account?.name }}</span>
              <MoneyText :value="row.amount" :currency="row.currency" class="tabular-nums" />
            </li>
          </ul>
        </section>
        <p v-if="invoice.void_reason" class="text-sm text-muted">{{ t("sales.invoices.voidedBecause", { reason: invoice.void_reason }) }}</p>
        <p class="text-xs text-subtle">{{ t("sales.invoices.notEInvoice") }}</p>
      </div>
      <template v-if="invoice" #footer>
        <IconButton :icon="FileText" :label="t('sales.invoices.pdf')" @click="pdf" />
        <UiButton v-if="canWrite && invoice.status !== 'void' && invoice.status !== 'paid' && invoice.status !== 'partly_paid'" variant="ghost" :icon="Ban" @click="voidIt">{{ t("sales.invoices.void") }}</UiButton>
        <UiButton v-if="canWrite && !['draft', 'void'].includes(invoice.status)" variant="secondary" :icon="Send" :loading="run.isPending.value" @click="send">{{ t("sales.invoices.send") }}</UiButton>
        <UiButton v-if="canPay && ['issued', 'partly_paid'].includes(invoice.status)" variant="secondary" :icon="Wallet" @click="startPayment">{{ t("sales.invoices.pay") }}</UiButton>
        <UiButton v-if="canWrite && invoice.status === 'draft'" variant="primary" :icon="Stamp" :loading="run.isPending.value" @click="issue">{{ t("sales.invoices.issue") }}</UiButton>
      </template>
    </UiDrawer>

    <UiDialog v-model:open="paying" :title="t('sales.invoices.payTitle')" size="sm">
      <div class="flex flex-col gap-4">
        <FormField :label="t('sales.invoices.account')" required><SelectBox v-model="payment.account" :options="accounts" /></FormField>
        <FormField :label="t('sales.invoices.amount')" required><MoneyInput v-model="payment.amount" /></FormField>
        <FormField :label="t('sales.invoices.paidOn')" required><TextInput v-model="payment.paid_on" placeholder="2026-11-07" /></FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="paying = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :disabled="!payment.account || !payment.amount" :loading="run.isPending.value" @click="pay">{{ t("sales.invoices.pay") }}</UiButton>
      </template>
    </UiDialog>

    <UiDialog v-model:open="creating" :title="t('sales.invoices.newTitle')" size="lg">
      <div class="flex flex-col gap-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('sales.invoices.customer')" required>
            <ComboBox v-model="draft.customer" :source="customerSource" :selected="draft.customerPicked" @change="(value: SelectOption<number> | null) => (draft.customerPicked = value)" />
          </FormField>
          <FormField :label="t('sales.invoices.branch')" :hint="t('sales.invoices.branchHint')"><SelectBox v-model="draft.branch" :options="branches" /></FormField>
        </div>
        <FormField :label="t('sales.invoices.lines')" required>
          <div class="flex flex-col gap-2">
            <div v-for="(line, index) in draft.lines" :key="index" class="grid grid-cols-[minmax(0,1fr)_90px_140px_32px] items-center gap-2">
              <ComboBox v-model="line.product" :source="productSource" :selected="line.picked" :placeholder="t('sales.match.search')" clearable @change="(value: SelectOption<number> | null) => ((line.picked = value), value && (line.name = value.label))" />
              <TextInput v-model="line.quantity" :aria-label="t('sales.invoices.packs')" inputmode="decimal" />
              <MoneyInput v-model="line.price" />
              <IconButton v-if="draft.lines.length > 1" :icon="Trash2" :label="t('common.delete')" size="sm" @click="draft.lines.splice(index, 1)" />
            </div>
            <UiButton variant="link" size="sm" :icon="Plus" @click="draft.lines.push(emptyLine())">{{ t("sales.invoices.addLine") }}</UiButton>
          </div>
        </FormField>
      </div>
      <template #footer>
        <UiButton variant="ghost" @click="creating = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :disabled="!canSave" :loading="run.isPending.value" @click="save">{{ t("sales.invoices.saveDraft") }}</UiButton>
      </template>
    </UiDialog>
  </div>
</template>
