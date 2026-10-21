<script setup lang="ts">
/**
 * One ledger entry in a side panel synced with `?txn=` (plan §6.2: "drawer with receipts, source
 * link, audit history, void"): the amount and what it was, the receipts (pictures open in a
 * lightbox, PDFs in a new tab, new ones dropped in), the record it came from, and the corrections
 * the person may make: edit (an entry made by hand changes fully; others only their note) and void.
 */
import { Ban, Check, ExternalLink, EyeOff, FileText, History, Pencil, Receipt as ReceiptIcon, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import ImageLightbox from "@/components/ImageLightbox.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import type { SelectOption } from "@/components/options";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { companyUrl } from "@/lib/links";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, searchCounterparties, useCategories, useOptions, useRefresh, useTransaction } from "../api";
import { absolute, categoryLabel, categoryOptions, KIND_ICONS, STATUS_TONES } from "../lib";
import type { Transaction } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const props = withDefaults(defineProps<{ queryKey?: string }>(), { queryKey: "txn" });

const route = useRoute();
const id = computed(() => {
  const raw = route.query[props.queryKey];
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useTransaction(id);
const row = computed(() => query.data.value ?? null);
const tab = ref<"details" | "history">("details");
const editing = ref(false);
const saving = ref(false);
const lightbox = ref({ open: false, index: 0 });

watch(id, () => {
  tab.value = "details";
  editing.value = false;
});

const KindIcon = computed(() => (row.value ? (KIND_ICONS[row.value.kind] ?? ReceiptIcon) : ReceiptIcon));
const foreign = computed(() => !!row.value && row.value.currency !== company.currency);
const canRecord = computed(() => company.can("finance.record"));
const sourceUrl = computed(() => (row.value?.source?.url ? companyUrl(company.currentId ?? 0, row.value.source.url) : null));

const items = computed<DescriptionItem[]>(() => {
  const r = row.value;
  if (!r) return [];
  const list: DescriptionItem[] = [
    { key: "date", label: t("finance.field.date"), value: fmt.day(r.occurred_on, "weekday") },
    { key: "account", label: t("finance.field.account"), value: r.account?.name ?? "—" },
  ];
  if (r.category) list.push({ key: "category", label: t("finance.field.category"), value: categoryLabel(r.category) });
  if (r.counterparty) list.push({ key: "counterparty", label: t("finance.field.counterparty"), value: r.counterparty.name });
  if (r.membership) list.push({ key: "member", label: t("finance.field.person"), value: r.membership.name });
  if (r.branch) list.push({ key: "branch", label: t("finance.field.branch"), value: r.branch.name });
  if (r.project) list.push({ key: "project", label: t("finance.field.project"), value: r.project.name });
  if (foreign.value) {
    list.push({
      key: "rate",
      label: t("finance.field.rate"),
      value: `1 ${r.currency} = ${fmt.number(r.rate, 2)} ${company.currency}${r.rate_stale ? ` · ${t("finance.rates.staleShort")}` : ""}`,
      hint: t("finance.tx.rateFrozen"),
    });
  }
  list.push({ key: "recorded", label: t("finance.tx.recordedBy"), value: [r.created_by, fmt.instant(r.created_at, "short")].filter(Boolean).join(" · "), wide: true });
  if (r.approved_by) list.push({ key: "approved", label: t("finance.tx.approvedBy"), value: [r.approved_by, r.approved_at ? fmt.instant(r.approved_at, "short") : ""].filter(Boolean).join(" · "), wide: true });
  return list;
});

const images = computed(() =>
  (row.value?.receipts ?? []).filter((receipt) => receipt.is_image).map((receipt) => ({ src: receipt.url, thumb: receipt.thumb_url ?? receipt.url, alt: t("finance.tx.receipt") })),
);

function openReceipt(index: number): void {
  const receipt = row.value?.receipts[index];
  if (!receipt) return;
  if (!receipt.is_image) {
    window.open(receipt.url, "_blank", "noopener");
    return;
  }
  lightbox.value = { open: true, index: images.value.findIndex((image) => image.src === receipt.url) };
}

// Receipts ---------------------------------------------------------------------------------

const files = ref<File[]>([]);
const uploading = ref(false);
watch(files, async (list) => {
  if (!list.length || !row.value) return;
  uploading.value = true;
  try {
    for (const file of list) await financeApi.uploadReceipt(company.currentId ?? 0, file, row.value.id);
    toast.success(t("finance.tx.receiptAdded", { n: list.length }, list.length));
  } finally {
    files.value = [];
    uploading.value = false;
    refresh();
  }
});

async function removeReceipt(receiptId: number): Promise<void> {
  if (!row.value) return;
  const answer = await confirm({ title: t("finance.tx.removeReceipt"), message: t("finance.tx.removeReceiptBody"), tone: "danger", confirmLabel: t("common.file.remove") });
  if (!answer) return;
  await financeApi.removeReceipt(company.currentId ?? 0, row.value.id, receiptId);
  refresh();
}

// Editing ----------------------------------------------------------------------------------

const options = useOptions(editing);
const categories = useCategories(editing);
const draft = ref({ amount: null as string | null, occurred_on: null as string | null, account: null as number | null, category: null as number | null, counterparty: null as number | null, description: "" });
const counterpartySelected = ref<SelectOption<number> | null>(null);

function startEdit(): void {
  const r = row.value;
  if (!r) return;
  draft.value = {
    amount: absolute(r.amount),
    occurred_on: r.occurred_on,
    account: r.account?.id ?? null,
    category: r.category?.id ?? null,
    counterparty: r.counterparty?.id ?? null,
    description: r.description,
  };
  counterpartySelected.value = r.counterparty ? { value: r.counterparty.id, label: r.counterparty.name } : null;
  editing.value = true;
}

const editKind = computed(() => (row.value?.kind === "income" ? "income" : row.value?.kind === "expense" ? "expense" : null));
const categoryChoices = computed(() => categoryOptions(categories.data.value, editKind.value, { activeOnly: true }));
const accountChoices = computed(() => (options.data.value?.accounts ?? []).filter((a) => !row.value || a.currency === row.value.currency || row.value.kind === "owner" || row.value.kind === "opening").map((a) => ({ value: a.id, label: a.name, description: a.currency })));
const minDay = computed(() => (options.data.value?.locked_until ? addDays(options.data.value.locked_until, 1) : null));
// The currency of the account picked in the editor (owner and opening entries may move to an
// account in the other currency; the amount is then entered in that currency).
const draftCurrency = computed(() => options.data.value?.accounts.find((a) => a.id === draft.value.account)?.currency ?? row.value?.currency ?? company.currency);

async function counterpartySource(q: string, signal: AbortSignal): Promise<SelectOption<number>[]> {
  const rows = await searchCounterparties(company.currentId ?? 0, q, signal);
  return rows.map((p) => ({ value: p.id, label: p.name, description: p.kind_label }));
}

async function saveEdit(): Promise<void> {
  const r = row.value;
  if (!r) return;
  saving.value = true;
  try {
    const patch: Record<string, unknown> = { description: draft.value.description };
    if (r.is_manual) {
      const newCurrency = draftCurrency.value !== r.currency;
      if (draft.value.amount && (newCurrency || draft.value.amount !== absolute(r.amount))) patch.amount = draft.value.amount;
      if (draft.value.occurred_on && draft.value.occurred_on !== r.occurred_on) patch.occurred_on = draft.value.occurred_on;
      if (draft.value.account && draft.value.account !== r.account?.id) patch.account = draft.value.account;
      if (editKind.value && draft.value.category !== (r.category?.id ?? null)) patch.category = draft.value.category;
      if (draft.value.counterparty !== (r.counterparty?.id ?? null)) patch.counterparty = draft.value.counterparty;
    }
    await financeApi.updateTransaction(company.currentId ?? 0, r.id, patch);
    toast.success(t("finance.tx.saved"));
    editing.value = false;
    refresh();
  } finally {
    saving.value = false;
  }
}

// Waiting entries --------------------------------------------------------------------------

const deciding = ref(false);

async function approve(target: Transaction): Promise<void> {
  deciding.value = true;
  try {
    await financeApi.approveTransaction(company.currentId ?? 0, target.id);
    toast.success(t("finance.tx.approved"));
    refresh();
  } finally {
    deciding.value = false;
  }
}

async function reject(target: Transaction): Promise<void> {
  const answer = await confirm({
    title: t("finance.tx.rejectTitle"),
    message: t("finance.tx.rejectBody"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("finance.tx.rejectReason"),
    confirmLabel: t("finance.tx.reject"),
    onConfirm: (reason) => financeApi.rejectTransaction(company.currentId ?? 0, target.id, reason),
  });
  if (answer) {
    toast.success(t("finance.tx.rejected"));
    refresh();
  }
}

async function voidRow(target: Transaction): Promise<void> {
  const answer = await confirm({
    title: t("finance.tx.voidTitle"),
    message: t("finance.tx.voidBody"),
    tone: "danger",
    reason: "required",
    reasonLabel: t("finance.tx.voidReason"),
    confirmLabel: t("finance.tx.void"),
    onConfirm: (reason) => financeApi.voidTransaction(company.currentId ?? 0, target.id, reason),
  });
  if (answer) {
    toast.success(t("finance.tx.voided"));
    refresh();
  }
}

const fieldLabels = computed(() => ({
  amount: t("finance.field.amount"),
  occurred_on: t("finance.field.date"),
  account: t("finance.field.account"),
  category: t("finance.field.category"),
  counterparty: t("finance.field.counterparty"),
  membership: t("finance.field.person"),
  branch: t("finance.field.branch"),
  description: t("finance.field.note"),
  currency: t("finance.field.currency"),
  project: t("finance.field.project"),
}));
</script>

<template>
  <UiDrawer :query-key="props.queryKey" size="md" :title="row ? row.kind_label : t('finance.tx.entry')">
    <template #default>
      <div class="p-5">
        <div v-if="query.isPending.value && id" class="flex flex-col gap-4 p-1">
          <SkeletonBlock height="64px" />
          <SkeletonBlock height="18px" width="60%" />
          <SkeletonBlock v-for="n in 5" :key="n" height="16px" />
        </div>
        <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
        <div v-else-if="row" class="flex flex-col gap-5">
          <header class="flex items-start gap-3">
            <span
              :class="[
                'grid size-11 shrink-0 place-items-center rounded-[12px]',
                row.kind === 'income' ? 'bg-success-soft text-success' : row.kind === 'expense' ? 'bg-danger-soft text-danger' : 'bg-surface-2 text-muted',
              ]"
              aria-hidden="true"
            >
              <component :is="KindIcon" :size="20" />
            </span>
            <div class="min-w-0 flex-1">
              <p :class="['text-[1.625rem] font-semibold leading-8 tracking-[-0.02em] tabular-nums', row.status === 'void' && 'text-subtle line-through']">
                <MoneyText :value="row.amount" :currency="row.currency" sign="always" :colored="row.status !== 'void'" :decimals="row.currency === 'USD' ? 'always' : 'auto'" />
              </p>
              <p v-if="foreign" class="text-sm text-muted">≈ <MoneyText :value="row.base_amount" :decimals="company.currency === 'USD' ? 'always' : 'never'" /></p>
              <div v-if="row.status !== 'posted'" class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <StatusPill :tone="STATUS_TONES[row.status]" size="sm" :label="row.status_label" />
              </div>
            </div>
          </header>

          <SegmentedControl
            v-model="tab"
            size="sm"
            :options="[
              { value: 'details', label: t('finance.tx.details'), icon: ReceiptIcon },
              { value: 'history', label: t('finance.tx.history'), icon: History },
            ]"
          />

          <template v-if="tab === 'details'">
            <InlineAlert v-if="row.masked" tone="info" size="sm" :icon="EyeOff" :title="t('finance.tx.maskedTitle')" :description="t('finance.tx.maskedBody')" />
            <InlineAlert v-if="row.status === 'pending'" tone="warning" size="sm" :title="t('finance.tx.waitingTitle')" :description="row.can_approve ? t('finance.tx.waitingBody') : t('finance.tx.waitingOther')" />
            <InlineAlert
              v-if="row.status === 'void' || row.status === 'rejected'"
              tone="neutral"
              size="sm"
              :title="row.status === 'void' ? t('finance.tx.voidedBy', { name: row.voided_by ?? '—' }) : t('finance.tx.rejectedBy', { name: row.voided_by ?? '—' })"
              :description="row.void_reason"
            />

            <template v-if="!editing">
              <p v-if="row.description" class="rounded-[10px] bg-surface-2 px-3 py-2.5 text-base text-fg">{{ row.description }}</p>
              <!-- Names wrap here instead of cutting off: a drawer has the height for
                   "Transport va yetkazish › Kuryer yoqilg‘i" or a person's cash-on-hand account. -->
              <DescriptionList :items="items" :columns="2">
                <template #value-account="{ item }"><span class="min-w-0 break-words" data-testid="wrap-value">{{ item.value }}</span></template>
                <template #value-category="{ item }"><span class="min-w-0 break-words">{{ item.value }}</span></template>
                <template #value-counterparty="{ item }"><span class="min-w-0 break-words">{{ item.value }}</span></template>
                <template #value-member="{ item }"><span class="min-w-0 break-words">{{ item.value }}</span></template>
                <template #value-project="{ item }"><span class="min-w-0 break-words">{{ item.value }}</span></template>
              </DescriptionList>
              <RouterLink v-if="row.source && sourceUrl" :to="sourceUrl" class="inline-flex w-fit items-center gap-1.5 rounded-[8px] border border-line px-2.5 py-1.5 text-sm font-medium text-fg hover:bg-surface-2">
                <ExternalLink :size="14" class="text-subtle" />{{ t("finance.tx.openSource", { source: row.source.label, id: row.source.id }) }}
              </RouterLink>
              <p v-else-if="row.source" class="text-sm text-muted">{{ t("finance.tx.fromSource", { source: row.source.label }) }}</p>
            </template>

            <div v-else class="flex flex-col gap-3 rounded-[12px] border border-line p-3">
              <p v-if="!row.is_manual" class="text-sm text-muted">{{ t("finance.tx.onlyNote") }}</p>
              <template v-if="row.is_manual">
                <FormField :label="t('finance.field.amount')">
                  <MoneyInput v-model="draft.amount" :currencies="[draftCurrency]" />
                </FormField>
                <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <FormField :label="t('finance.field.date')">
                    <DatePicker v-model="draft.occurred_on" :min="minDay" :max="options.data.value?.today ?? null" />
                  </FormField>
                  <FormField :label="t('finance.field.account')">
                    <SelectBox v-model="draft.account" :options="accountChoices" />
                  </FormField>
                </div>
                <FormField v-if="editKind" :label="t('finance.field.category')">
                  <ComboBox v-model="draft.category" :options="categoryChoices" />
                </FormField>
                <FormField v-if="editKind" :label="t('finance.field.counterparty')" optional>
                  <ComboBox v-model="draft.counterparty" :source="counterpartySource" :selected="counterpartySelected" clearable />
                </FormField>
              </template>
              <FormField :label="t('finance.field.note')">
                <TextInput v-model="draft.description" :maxlength="300" />
              </FormField>
              <div class="flex justify-end gap-2">
                <UiButton variant="ghost" @click="editing = false">{{ t("common.cancel") }}</UiButton>
                <UiButton variant="primary" :loading="saving" @click="saveEdit">{{ t("common.save") }}</UiButton>
              </div>
            </div>

            <section v-if="!row.masked" class="flex flex-col gap-2">
              <h3 class="text-sm font-semibold text-fg">{{ t("finance.tx.receipts") }}</h3>
              <ul v-if="row.receipts.length" class="grid grid-cols-3 gap-2 sm:grid-cols-4">
                <li v-for="(receipt, index) in row.receipts" :key="receipt.id" class="group relative">
                  <button type="button" class="block aspect-[3/4] w-full overflow-hidden rounded-[10px] border border-line bg-surface-2 transition hover:border-line-strong" @click="openReceipt(index)">
                    <img v-if="receipt.is_image" :src="receipt.thumb_url ?? receipt.url" :alt="t('finance.tx.receipt')" class="size-full object-contain" loading="lazy" />
                    <span v-else class="flex size-full flex-col items-center justify-center gap-1 text-muted"><FileText :size="22" /><span class="text-xs font-semibold">PDF</span></span>
                  </button>
                  <button
                    v-if="row.can_edit"
                    type="button"
                    class="absolute right-1 top-1 hidden rounded-full bg-surface/90 px-1.5 text-xs font-semibold text-danger shadow-xs group-hover:block focus:block"
                    @click="removeReceipt(receipt.id)"
                  >
                    {{ t("common.file.remove") }}
                  </button>
                </li>
              </ul>
              <p v-else class="text-sm text-muted">{{ t("finance.tx.noReceipts") }}</p>
              <FileDrop v-if="canRecord && (row.status === 'posted' || row.status === 'pending')" v-model="files" compact multiple accept="image/*,application/pdf" :disabled="uploading" :title="t('finance.tx.attach')" :hint="t('finance.quick.dropHint')" />
            </section>
          </template>

          <AuditTrail v-else target-type="transaction" :target-id="row.id" :field-labels="fieldLabels" />
          <ImageLightbox v-model:open="lightbox.open" v-model:index="lightbox.index" :images="images" :title="t('finance.tx.receipts')" />
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="row && !editing && row.can_approve" class="flex w-full items-center gap-2">
        <UiButton v-if="row.can_edit" variant="ghost" :icon="Pencil" @click="startEdit">{{ t("common.edit") }}</UiButton>
        <span class="flex-1" />
        <UiButton variant="secondary" :icon="X" :disabled="deciding" @click="reject(row)">{{ t("finance.tx.reject") }}</UiButton>
        <UiButton variant="primary" :icon="Check" :loading="deciding" @click="approve(row)">{{ t("finance.tx.approve") }}</UiButton>
      </div>
      <div v-else-if="row && !editing && (row.can_edit || row.can_void)" class="flex w-full items-center gap-2">
        <UiButton v-if="row.can_void" variant="ghost" :icon="Ban" class="text-danger" @click="voidRow(row)">{{ t("finance.tx.void") }}</UiButton>
        <span class="flex-1" />
        <UiButton v-if="row.can_edit" :icon="Pencil" @click="startEdit">{{ row.is_manual ? t("common.edit") : t("finance.tx.editNote") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
