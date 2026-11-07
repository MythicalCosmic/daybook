<script setup lang="ts">
/**
 * One goods receipt (Kirim): the distributor's invoice, the nakladnoy file, its lines with series,
 * expiry, packs and prices, and every warning a line raised (short shelf life, a cost jump, a
 * recalled series, the legal price cap...). A draft is filled in, sent for posting, and posted by
 * someone with stock.manage: posting puts the batches on stock and opens the payable, which this
 * page links to. Void only while none of its goods moved and nothing was paid.
 */
import { Ban, FileSpreadsheet, FileUp, Pencil, Plus, Send, Stamp, Trash2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { isApiError } from "@/api/http";
import DescriptionList from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { stockApi, useReceipt, useRefresh } from "../api";
import ProductBadges from "../components/ProductBadges.vue";
import LineImportDialog from "../components/LineImportDialog.vue";
import ReceiptLineDialog from "../components/ReceiptLineDialog.vue";
import { expiryTone, packsAndParts, RECEIPT_TONES, WARNING_TONES } from "../lib";
import type { ReceiptLine } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const route = useRoute();
const today = useCompanyToday();
const refresh = useRefresh();
const confirm = useConfirm();

const id = computed(() => Number(route.params.receiptId ?? 0));
const query = useReceipt(id);
const receipt = computed(() => query.data.value?.receipt ?? null);
const lines = computed(() => query.data.value?.lines ?? []);
const showCost = computed(() => receipt.value?.total !== undefined);
const editable = computed(() => receipt.value?.status === "draft" || receipt.value?.status === "submitted");
const canOperate = computed(() => company.can(["stock.manage", "stock.operate"]));
const canManage = computed(() => company.can("stock.manage"));
const blocked = computed(() => lines.value.some((line) => line.warnings.includes("not_licensed_branch")));

const title = computed(() => (receipt.value?.number ? t("stock.receipt.titleNumber", { number: receipt.value.number }) : t("stock.receipt.titleDraft", { id: id.value })));
const facts = computed(() => {
  const r = receipt.value;
  if (!r) return [];
  return [
    { key: "supplier", label: t("stock.field.supplier"), value: r.supplier.name },
    { key: "invoice", label: t("stock.field.invoiceNumber"), value: r.supplier_invoice_number ? `${r.supplier_invoice_number} · ${fmt.day(r.supplier_invoice_date)}` : fmt.day(r.supplier_invoice_date) },
    { key: "branch", label: t("stock.field.branch"), value: r.branch.name },
    { key: "due", label: t("stock.field.dueOn"), value: r.due_on ? fmt.day(r.due_on) : t("stock.receipt.dueByTerms") },
    { key: "received", label: t("stock.receipt.receivedBy"), value: r.received_by?.name ?? "—" },
    { key: "posted", label: t("stock.receipt.postedBy"), value: r.posted_by ? `${r.posted_by.name} · ${r.posted_at ? fmt.instant(r.posted_at, "short") : ""}` : "—" },
  ];
});

const lineOpen = ref(false);
const importOpen = ref(false);
const editingLine = ref<ReceiptLine | null>(null);
function addLine(): void {
  editingLine.value = null;
  lineOpen.value = true;
}
function editLine(line: ReceiptLine): void {
  editingLine.value = line;
  lineOpen.value = true;
}

const busy = ref<string | null>(null);
async function act(kind: "submit" | "post", run: () => Promise<unknown>, done: string): Promise<void> {
  busy.value = kind;
  try {
    await run();
    toast.success(done);
    refresh();
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    busy.value = null;
  }
}
const cid = () => company.currentId ?? 0;
const submit = () => act("submit", () => stockApi.submitReceipt(cid(), id.value), t("stock.receipt.submitted"));
const post = () => act("post", () => stockApi.postReceipt(cid(), id.value), t("stock.receipt.posted"));

async function voidIt(): Promise<void> {
  await confirm({
    title: t("stock.receipt.voidTitle"),
    message: receipt.value?.status === "posted" ? t("stock.receipt.voidPosted") : t("stock.receipt.voidDraft"),
    tone: "danger",
    reason: "required",
    confirmLabel: t("stock.receipt.void"),
    onConfirm: async (reason) => {
      await stockApi.voidReceipt(cid(), id.value, reason);
      toast.success(t("stock.receipt.voided"));
      refresh();
    },
  });
}

async function removeLine(line: ReceiptLine): Promise<void> {
  await stockApi.removeLine(cid(), id.value, line.id);
  refresh();
}

const fileInput = ref<HTMLInputElement | null>(null);
async function upload(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    await stockApi.uploadReceiptFile(cid(), id.value, file);
    toast.success(t("stock.receipt.fileSaved"));
    refresh();
  } catch (error) {
    toast.error(isApiError(error) ? error.message : t("common.error.generic"));
  } finally {
    if (fileInput.value) fileInput.value.value = "";
  }
}
</script>

<template>
  <div>
    <ErrorState v-if="query.error.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.isPending.value" class="flex flex-col gap-3"><SkeletonBlock class="h-16" /><SkeletonBlock class="h-48" /></div>
    <template v-else-if="receipt">
      <PageHeader :title="title" :back="`/c/${company.currentId}/stock/receipts`">
        <template #meta><StatusPill :tone="RECEIPT_TONES[receipt.status]" :label="t(`stock.receiptStatus.${receipt.status}`)" /></template>
        <template #actions>
          <UiButton v-if="editable && canOperate" variant="secondary" :icon="FileSpreadsheet" data-testid="receipt-import-lines" @click="importOpen = true">{{ t("stock.lineImport.button") }}</UiButton>
          <UiButton v-if="editable && canOperate" variant="secondary" :icon="Plus" data-testid="receipt-add-line" @click="addLine">{{ t("stock.receipt.addLine") }}</UiButton>
          <UiButton v-if="receipt.status === 'draft' && canOperate" variant="secondary" :icon="Send" :loading="busy === 'submit'" :disabled="!lines.length" @click="submit">{{ t("stock.receipt.submit") }}</UiButton>
          <UiButton v-if="editable && canManage" variant="primary" :icon="Stamp" :loading="busy === 'post'" :disabled="!lines.length || blocked" data-testid="receipt-post" @click="post">{{ t("stock.receipt.post") }}</UiButton>
          <UiButton v-if="receipt.status !== 'void' && canManage" variant="ghost" :icon="Ban" @click="voidIt">{{ t("stock.receipt.void") }}</UiButton>
        </template>
      </PageHeader>

      <InlineAlert v-if="receipt.status === 'void'" class="mb-4" tone="neutral">{{ t("stock.receipt.voidNote", { reason: receipt.void_reason }) }}</InlineAlert>
      <InlineAlert v-if="blocked" class="mb-4" tone="danger">{{ t("stock.receipt.blocked") }}</InlineAlert>
      <InlineAlert v-else-if="receipt.status === 'submitted' && canManage" class="mb-4" tone="info">{{ t("stock.receipt.waitingHint") }}</InlineAlert>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <PageSection :title="t('stock.receipt.lines')" :count="lines.length" variant="card" flush>
          <ul class="divide-y divide-line" data-testid="receipt-lines">
            <li v-for="line in lines" :key="line.id" class="flex flex-col gap-1.5 px-4 py-3">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-fg">{{ line.product.name }}</span>
                <ProductBadges :rx="line.rx_required" :control="line.control_class" />
                <span class="ms-auto flex items-center gap-1">
                  <IconButton v-if="editable && canOperate" :icon="Pencil" size="sm" :label="t('common.edit')" @click="editLine(line)" />
                  <IconButton v-if="editable && canOperate" :icon="Trash2" size="sm" :label="t('common.delete')" @click="removeLine(line)" />
                </span>
              </div>
              <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                <span>{{ t("stock.batch.series", { series: line.series }) }}</span>
                <StatusPill :tone="expiryTone(line.expires_on, today)" variant="plain" size="sm" :label="t('stock.batch.until', { day: fmt.day(line.expires_on) })" />
                <span>{{ packsAndParts(line.quantity, line.units_per_pack, "", t) }}</span>
                <span v-if="line.unit_cost !== undefined">{{ t("stock.batch.cost") }}: <MoneyText :value="line.unit_cost" decimals="never" /></span>
                <span v-if="line.total !== undefined">{{ t("stock.col.total") }}: <MoneyText :value="line.total" decimals="never" /></span>
                <span v-if="line.retail_price">{{ t("stock.batch.price") }}: <MoneyText :value="line.retail_price" decimals="never" /></span>
                <span v-if="line.price_cap">{{ t("stock.batch.cap") }}: <MoneyText :value="line.price_cap" decimals="never" /></span>
              </div>
              <div v-if="line.warnings.length" class="flex flex-wrap gap-1.5">
                <StatusPill v-for="warning in line.warnings" :key="warning" :tone="WARNING_TONES[warning]" size="sm" :label="t(`stock.warning.${warning}`)" :data-warning="warning" />
              </div>
            </li>
            <li v-if="!lines.length" class="px-4 py-6 text-center text-sm text-muted">{{ t("stock.receipt.noLines") }}</li>
          </ul>
        </PageSection>

        <div class="flex flex-col gap-4">
          <PageSection :title="t('stock.receipt.facts')" variant="card">
            <DescriptionList :items="facts" layout="rows" />
            <div v-if="receipt.total !== undefined" class="mt-3 flex items-center justify-between border-t border-line pt-3 text-sm">
              <span class="text-muted">{{ t("stock.col.total") }}</span>
              <span class="text-end">
                <span class="block font-semibold text-fg"><MoneyText :value="receipt.total" /></span>
                <span v-if="receipt.vat_total && Number(receipt.vat_total) > 0" class="block text-xs text-muted">{{ t("stock.receipt.vatIncluded") }} <MoneyText :value="receipt.vat_total" /></span>
              </span>
            </div>
            <div v-if="receipt.debt_id" class="mt-3 flex items-center justify-between text-sm" data-testid="receipt-payable">
              <span class="text-muted">{{ t("stock.receipt.payable") }}</span>
              <RouterLink class="font-medium text-accent-fg hover:underline" :to="`/c/${company.currentId}/finance/debts?debt=${receipt.debt_id}`">
                {{ t(`stock.debtStatus.${receipt.debt_status ?? "open"}`) }}<template v-if="receipt.debt_paid && Number(receipt.debt_paid) > 0"> · <MoneyText :value="receipt.debt_paid" /></template>
              </RouterLink>
            </div>
          </PageSection>
          <PageSection :title="t('stock.receipt.file')" variant="card">
            <p v-if="receipt.file_url" class="mb-2 text-sm"><a class="font-medium text-accent-fg hover:underline" :href="receipt.file_url" target="_blank" rel="noopener">{{ t("stock.receipt.openFile") }}</a></p>
            <p v-else class="mb-2 text-sm text-muted">{{ t("stock.receipt.noFile") }}</p>
            <template v-if="editable && canOperate">
              <input ref="fileInput" type="file" class="hidden" accept="image/*,.pdf,.xlsx,.csv" @change="upload" />
              <UiButton size="sm" variant="secondary" :icon="FileUp" @click="fileInput?.click()">{{ receipt.file_url ? t("stock.receipt.replaceFile") : t("stock.receipt.addFile") }}</UiButton>
            </template>
          </PageSection>
          <p v-if="receipt.note" class="text-sm text-muted">{{ receipt.note }}</p>
        </div>
      </div>

      <ReceiptLineDialog v-model:open="lineOpen" :receipt-id="receipt.id" :line="editingLine" :show-cost="showCost" />
      <LineImportDialog v-model:open="importOpen" :receipt-id="receipt.id" />
    </template>
  </div>
</template>
