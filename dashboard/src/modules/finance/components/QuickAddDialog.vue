<script setup lang="ts">
/**
 * Record an expense, an income, a transfer, owner money or an opening balance in a few taps (plan
 * §6.2 "global quick add"): the amount with live digit grouping and a currency toggle, the account
 * as chips (the last one used comes first), a category, a counterparty (found or created inline),
 * the day, a note and receipts dropped in, which upload at once so the `finance.quickadd.receipt`
 * slot (AI reading) can fill the form from them. ⌘/Ctrl+Enter saves.
 */
import { ArrowLeftRight, CalendarDays, ChevronDown, Crown, FileText, Paperclip, Plus, TrendingDown, TrendingUp, X } from "@lucide/vue";
import { computed, nextTick, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import type { Currency } from "@/api/types";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KbdKey from "@/components/KbdKey.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import type { SelectOption } from "@/components/options";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { addDays } from "@/lib/dates";
import { dec } from "@/lib/decimal";
import { readStored, writeStored } from "@/lib/storage";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, searchCounterparties, useCategories, useOptions, useRefresh } from "../api";
import { categoryOptions, findCategory, pickerOrder } from "../lib";
import type { QuickAddMode, QuickAddRequest } from "../quickAdd";
import type { Receipt } from "../types";
import AccountChips from "./AccountChips.vue";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ request: QuickAddRequest }>();

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions();
const categories = useCategories();

const canManage = computed(() => company.can("finance.manage"));
const mode = ref<QuickAddMode>(props.request.mode);
const direction = ref<"in" | "out">("in");
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});

interface UploadedReceipt {
  key: string;
  name: string;
  status: "uploading" | "done" | "error";
  receipt?: Receipt;
}

const form = reactive({
  amount: props.request.amount ?? (null as string | null),
  currency: null as Currency | null,
  account: props.request.account ?? (null as number | null),
  toAccount: props.request.toAccount ?? (null as number | null),
  amountIn: null as string | null,
  fee: null as string | null,
  category: props.request.category ?? (null as number | null),
  counterparty: props.request.counterparty?.id ?? (null as number | null),
  occurredOn: null as string | null,
  description: props.request.description ?? "",
  branch: null as number | null,
});
const counterpartyOption = ref<SelectOption<number> | null>(props.request.counterparty ? { value: props.request.counterparty.id, label: props.request.counterparty.name } : null);
const files = ref<File[]>([]);
const receipts = ref<UploadedReceipt[]>([]);
const showFee = ref(false);

const today = computed(() => options.data.value?.today ?? null);
const minDay = computed(() => (options.data.value?.locked_until ? addDays(options.data.value.locked_until, 1) : null));
watch(
  today,
  (day) => {
    if (day && !form.occurredOn) form.occurredOn = day;
  },
  { immediate: true },
);

// Modes -------------------------------------------------------------------------------------

const MODE_ICONS = { expense: TrendingDown, income: TrendingUp, transfer: ArrowLeftRight, owner: Crown, opening: FileText } as const;
const segmentOptions = computed(() => {
  const base: QuickAddMode[] = ["expense", "income", "transfer"];
  if (!base.includes(mode.value)) base.push(mode.value);
  return base.map((value) => ({ value, label: t(`finance.quick.mode.${value}`), icon: MODE_ICONS[value] }));
});
const moreMenu = computed<MenuEntry[]>(() => [
  { label: t("finance.quick.mode.owner"), description: t("finance.quick.ownerHint"), icon: Crown, onSelect: () => (mode.value = "owner") },
  { label: t("finance.quick.mode.opening"), description: t("finance.quick.openingHint"), icon: FileText, onSelect: () => (mode.value = "opening") },
]);
const isTransfer = computed(() => mode.value === "transfer");
const signed = computed(() => mode.value === "owner" || mode.value === "opening");
const categoryKind = computed(() => (mode.value === "income" ? "income" : mode.value === "expense" ? "expense" : null));
const title = computed(() => t(`finance.quick.title.${mode.value}`));

// Accounts and currency ---------------------------------------------------------------------------

const accounts = computed(() => options.data.value?.accounts ?? []);
const currencies = computed<Currency[]>(() => [...new Set(accounts.value.map((a) => a.currency))].sort((a) => (a === company.currency ? -1 : 1)));
const currency = computed<Currency>(() => form.currency ?? currencies.value[0] ?? company.currency);
const chipAccounts = computed(() => {
  const list = accounts.value.filter((a) => a.currency === currency.value || isTransfer.value);
  const last = readStored<number | null>(`finance.quick.last.${mode.value}`, null);
  return pickerOrder(list, { id: last });
});
const fromAccount = computed(() => accounts.value.find((a) => a.id === form.account) ?? null);
const targets = computed(() => (options.data.value?.transfer_targets ?? []).filter((a) => a.id !== form.account));
const toAccount = computed(() => targets.value.find((a) => a.id === form.toAccount) ?? null);
const crossCurrency = computed(() => !!fromAccount.value && !!toAccount.value && fromAccount.value.currency !== toAccount.value.currency);
const impliedRate = computed(() => {
  if (!crossCurrency.value || !form.amount || !form.amountIn || dec(form.amountIn).isZero() || dec(form.amount).isZero()) return null;
  const outIsBase = fromAccount.value!.currency === company.currency;
  const som = outIsBase ? dec(form.amount) : dec(form.amountIn);
  const foreign = outIsBase ? dec(form.amountIn) : dec(form.amount);
  return som.div(foreign).toDecimalPlaces(2).toString();
});
const branches = computed(() => options.data.value?.branches ?? []);
const showBranch = computed(() => !isTransfer.value && !!fromAccount.value && !fromAccount.value.branch_id && branches.value.length > 1);

watch(currency, () => {
  if (fromAccount.value && fromAccount.value.currency !== currency.value && !isTransfer.value) form.account = null;
});
watch(
  [chipAccounts, () => options.isSuccess.value],
  () => {
    if (form.account === null && chipAccounts.value.length && !isTransfer.value) form.account = chipAccounts.value[0]!.id;
    if (form.account !== null && props.request.account && !form.currency) {
      const picked = accounts.value.find((a) => a.id === form.account);
      if (picked) form.currency = picked.currency;
    }
  },
  { immediate: true },
);
watch(mode, (next) => {
  if (categoryKind.value && form.category) {
    const picked = findCategory(categories.data.value, form.category);
    if (picked && picked.kind !== categoryKind.value) form.category = null;
  }
  if (next === "transfer") form.category = null;
  for (const key of Object.keys(errors)) delete errors[key];
});

// Category and counterparty ------------------------------------------------------------------------

const categoryChoices = computed(() => categoryOptions(categories.data.value, categoryKind.value, { activeOnly: true }));

async function counterpartySource(query: string, signal: AbortSignal): Promise<SelectOption<number>[]> {
  const rows = await searchCounterparties(company.currentId ?? 0, query, signal);
  return rows.map((row) => ({
    value: row.id,
    label: row.name,
    description: [row.kind_label, row.phone].filter(Boolean).join(" · "),
    keywords: [row.phone, row.tin].filter(Boolean),
    avatar: { name: row.name },
    _default: row.default_category?.id ?? null,
  })) as SelectOption<number>[];
}

function pickCounterparty(option: (SelectOption<number> & { _default?: number | null }) | null): void {
  counterpartyOption.value = option;
  if (option?._default && !form.category && categoryKind.value) {
    const picked = findCategory(categories.data.value, option._default);
    if (picked?.kind === categoryKind.value) form.category = picked.id;
  }
}

async function createCounterparty(name: string): Promise<void> {
  try {
    const created = await financeApi.createCounterparty(company.currentId ?? 0, { name, kind: mode.value === "income" ? "customer" : "supplier" });
    const option = { value: created.id, label: created.name, avatar: { name: created.name } };
    counterpartyOption.value = option;
    form.counterparty = created.id;
    toast.success(t("finance.quick.partyCreated", { name: created.name }));
  } catch {
    // The HTTP layer showed why.
  }
}

// Receipts ---------------------------------------------------------------------------------------

watch(files, (list) => {
  for (const file of list) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (receipts.value.some((r) => r.key === key)) continue;
    const entry = reactive<UploadedReceipt>({ key, name: file.name, status: "uploading" });
    receipts.value = [...receipts.value, entry];
    financeApi
      .uploadReceipt(company.currentId ?? 0, file)
      .then((receipt) => {
        entry.status = "done";
        entry.receipt = receipt;
      })
      .catch(() => {
        entry.status = "error";
      });
  }
});

function removeReceipt(key: string): void {
  receipts.value = receipts.value.filter((r) => r.key !== key);
  files.value = files.value.filter((file) => `${file.name}:${file.size}:${file.lastModified}` !== key);
}

const uploading = computed(() => receipts.value.some((r) => r.status === "uploading"));
const receiptIds = computed(() => receipts.value.filter((r) => r.status === "done" && r.receipt).map((r) => r.receipt!.id));

/** What the receipt slot (AI reading, package K) may fill in. */
function applyPrefill(prefill: { amount?: string; occurred_on?: string; category?: number; counterparty?: { id: number; name: string }; description?: string }): void {
  if (prefill.amount) form.amount = prefill.amount;
  if (prefill.occurred_on) form.occurredOn = prefill.occurred_on;
  if (prefill.category) form.category = prefill.category;
  if (prefill.description && !form.description) form.description = prefill.description;
  if (prefill.counterparty) {
    form.counterparty = prefill.counterparty.id;
    counterpartyOption.value = { value: prefill.counterparty.id, label: prefill.counterparty.name };
  }
}

const receiptThreshold = computed(() => options.data.value?.receipt_required_over ?? null);
const needsReceipt = computed(() => {
  if (mode.value !== "expense" || !receiptThreshold.value || !form.amount || receiptIds.value.length || uploading.value) return false;
  let value = dec(form.amount);
  if (currency.value !== company.currency) {
    const rate = options.data.value?.rate.rate;
    if (!rate) return false;
    value = company.currency === "UZS" ? value.times(rate) : value.div(rate);
  }
  return value.gt(receiptThreshold.value);
});

// Saving -----------------------------------------------------------------------------------------

function validate(): boolean {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.amount || dec(form.amount).lte(0)) errors.amount = t("finance.quick.errAmount");
  if (!form.account) errors.account = t("finance.quick.errAccount");
  if (isTransfer.value) {
    if (!form.toAccount) errors.toAccount = t("finance.quick.errTo");
    if (crossCurrency.value && (!form.amountIn || dec(form.amountIn).lte(0))) errors.amountIn = t("finance.quick.errAmountIn");
  } else if (categoryKind.value && !form.category) errors.category = t("finance.quick.errCategory");
  if (!form.occurredOn) errors.occurredOn = t("finance.quick.errDay");
  return Object.keys(errors).length === 0;
}

async function save(another = false): Promise<void> {
  if (saving.value || uploading.value || !validate()) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  try {
    let openUrl: string;
    if (isTransfer.value) {
      const moved = await financeApi.createTransfer(cid, {
        from_account: form.account!,
        to_account: form.toAccount!,
        amount_out: form.amount!,
        amount_in: crossCurrency.value ? form.amountIn : null,
        fee: showFee.value && form.fee ? form.fee : "0",
        occurred_on: form.occurredOn!,
        description: form.description,
      });
      openUrl = `/c/${cid}/finance/accounts/${moved.from_account.id}`;
      toast.success(t("finance.quick.savedTransfer"), { description: `${moved.from_account.name} → ${moved.to_account.name}` });
    } else {
      const row = await financeApi.createTransaction(cid, {
        kind: mode.value as "income" | "expense" | "owner" | "opening",
        direction: signed.value ? direction.value : "in",
        amount: form.amount!,
        occurred_on: form.occurredOn!,
        account: form.account!,
        category: categoryKind.value ? form.category : null,
        counterparty: form.counterparty,
        branch: showBranch.value ? form.branch : null,
        description: form.description,
        receipt_ids: receiptIds.value,
      });
      openUrl = `/c/${cid}/finance/transactions?txn=${row.id}`;
      toast.success(t(`finance.quick.saved.${mode.value}`), {
        description: fmt.money(row.amount, row.currency, { sign: "always" }),
        action: { label: t("finance.quick.view"), onClick: () => void router.push(openUrl) },
      });
    }
    writeStored(`finance.quick.last.${mode.value}`, form.account);
    refresh();
    if (another) {
      form.amount = null;
      form.amountIn = null;
      form.description = "";
      form.counterparty = null;
      counterpartyOption.value = null;
      files.value = [];
      receipts.value = [];
    } else {
      open.value = false;
    }
  } catch (error) {
    if (isApiError(error)) {
      const map: Record<string, string> = { amount_out: "amount", amount_in: "amountIn", to_account: "toAccount", from_account: "account", occurred_on: "occurredOn" };
      for (const [field, messages] of Object.entries(error.fieldErrors)) errors[map[field] ?? field] = messages[0];
    }
  } finally {
    saving.value = false;
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    void save(false);
  }
}

const dayChips = computed(() => {
  if (!today.value) return [];
  return [
    { day: today.value, label: t("finance.quick.today") },
    { day: addDays(today.value, -1), label: t("finance.quick.yesterday") },
  ].filter((chip) => !minDay.value || chip.day >= minDay.value);
});
const branchOptions = computed(() => branches.value.map((b) => ({ value: b.id, label: b.name, description: b.code })));
const loading = computed(() => options.isPending.value || categories.isPending.value);

// The dialog focuses its first field when it opens; on a cold cache the fields come a moment later.
const amountInput = ref<InstanceType<typeof MoneyInput> | null>(null);
watch(
  [open, loading],
  ([isOpen, busy], [wasOpen, wasBusy]) => {
    if (isOpen && !busy && (wasBusy || !wasOpen)) void nextTick(() => amountInput.value?.focus());
  },
);
</script>

<template>
  <UiDialog v-model:open="open" :title="title" :description="t('finance.quick.description')" size="lg">
    <div class="flex flex-col gap-4" data-quick-add @keydown="onKeydown">
      <div class="flex items-center gap-2">
        <SegmentedControl v-model="mode" :options="segmentOptions" block class="min-w-0 flex-1" :aria-label="t('finance.quick.modeLabel')" />
        <DropdownMenu v-if="canManage" :items="moreMenu" align="end" width="260px">
          <template #trigger>
            <UiButton variant="ghost" size="sm" :icon-right="ChevronDown">{{ t("finance.quick.more") }}</UiButton>
          </template>
        </DropdownMenu>
      </div>

      <template v-if="loading">
        <SkeletonBlock height="44px" />
        <SkeletonBlock height="32px" width="80%" />
        <SkeletonBlock height="32px" />
      </template>

      <template v-else>
        <SegmentedControl
          v-if="signed"
          v-model="direction"
          size="sm"
          :options="[
            { value: 'in', label: t(mode === 'owner' ? 'finance.quick.ownerIn' : 'finance.quick.openingIn') },
            { value: 'out', label: t(mode === 'owner' ? 'finance.quick.ownerOut' : 'finance.quick.openingOut') },
          ]"
        />

        <FormField :label="isTransfer ? t('finance.quick.amountOut') : t('finance.field.amount')" :error="errors.amount" required>
          <MoneyInput
            ref="amountInput"
            v-model="form.amount"
            :currency="isTransfer ? (fromAccount?.currency ?? currency) : currency"
            :currencies="isTransfer ? [fromAccount?.currency ?? currency] : currencies"
            size="lg"
            class="quick-amount"
            :invalid="!!errors.amount"
            autofocus
            @update:currency="(value) => (form.currency = value ?? null)"
          />
        </FormField>

        <FormField :label="isTransfer ? t('finance.quick.from') : t('finance.field.account')" :error="errors.account" required>
          <AccountChips v-model="form.account" :accounts="chipAccounts" :invalid="!!errors.account" />
        </FormField>

        <template v-if="isTransfer">
          <FormField :label="t('finance.quick.to')" :error="errors.toAccount" required>
            <AccountChips v-model="form.toAccount" :accounts="targets" :label="t('finance.quick.to')" :invalid="!!errors.toAccount" />
          </FormField>
          <FormField v-if="crossCurrency" :label="t('finance.quick.amountIn')" :error="errors.amountIn" required :hint="impliedRate ? t('finance.quick.impliedRate', { rate: fmt.number(impliedRate, 2) }) : undefined">
            <MoneyInput v-model="form.amountIn" :currencies="[toAccount!.currency]" :invalid="!!errors.amountIn" />
          </FormField>
          <div>
            <button v-if="!showFee" type="button" class="inline-flex items-center gap-1 text-sm font-semibold text-accent-fg hover:underline" @click="showFee = true">
              <Plus :size="14" />{{ t("finance.quick.addFee") }}
            </button>
            <FormField v-else :label="t('finance.quick.fee')" :hint="t('finance.quick.feeHint')">
              <MoneyInput v-model="form.fee" :currencies="[fromAccount?.currency ?? currency]" />
            </FormField>
          </div>
        </template>

        <div v-else-if="categoryKind" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('finance.field.category')" :error="errors.category" required>
            <ComboBox v-model="form.category" :options="categoryChoices" :placeholder="t('finance.quick.categoryPlaceholder')" :invalid="!!errors.category" />
          </FormField>
          <FormField :label="mode === 'income' ? t('finance.quick.fromWhom') : t('finance.quick.toWhom')" optional>
            <ComboBox
              v-model="form.counterparty"
              :source="counterpartySource"
              :selected="counterpartyOption"
              creatable
              clearable
              :placeholder="t('finance.quick.partyPlaceholder')"
              @create="createCounterparty"
              @change="(option) => pickCounterparty(option as never)"
            />
          </FormField>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField :label="t('finance.field.date')" :error="errors.occurredOn" required>
            <DatePicker v-model="form.occurredOn" :min="minDay" :max="today" />
            <span class="mt-1.5 flex flex-wrap gap-1">
              <button
                v-for="chip in dayChips"
                :key="chip.day"
                type="button"
                :class="['inline-flex h-6 items-center gap-1 rounded-full border px-2 text-xs font-medium transition-colors', form.occurredOn === chip.day ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line text-muted hover:text-fg']"
                @click="form.occurredOn = chip.day"
              >
                <CalendarDays :size="12" />{{ chip.label }}
              </button>
            </span>
          </FormField>
          <FormField v-if="showBranch" :label="t('finance.field.branch')" optional>
            <SelectBox v-model="form.branch" :options="branchOptions" clearable :placeholder="t('finance.quick.branchPlaceholder')" />
          </FormField>
          <FormField :label="t('finance.field.note')" optional :class="showBranch && 'sm:col-span-2'">
            <TextInput v-model="form.description" :maxlength="300" :placeholder="t(`finance.quick.notePlaceholder.${mode}`)" />
          </FormField>
        </div>

        <div v-if="!isTransfer" class="flex flex-col gap-2">
          <div class="flex items-center gap-2 text-sm font-medium text-fg"><Paperclip :size="15" class="text-subtle" />{{ t("finance.quick.receipts") }}</div>
          <FileDrop v-model="files" compact multiple accept="image/*,application/pdf" :max-files="10" :title="t('finance.quick.dropTitle')" :hint="t('finance.quick.dropHint')" />
          <ul v-if="receipts.length" class="flex flex-wrap gap-2">
            <li v-for="item in receipts" :key="item.key" class="group relative">
              <div :class="['grid size-16 place-items-center overflow-hidden rounded-[10px] border bg-surface-2', item.status === 'error' ? 'border-danger' : 'border-line']">
                <img v-if="item.receipt?.thumb_url" :src="item.receipt.thumb_url" alt="" class="size-full object-cover" />
                <FileText v-else-if="item.status === 'done'" :size="22" class="text-muted" />
                <SkeletonBlock v-else-if="item.status === 'uploading'" height="100%" radius="0" />
                <span v-else class="px-1 text-center text-[10px] font-semibold leading-tight text-danger">{{ t("finance.quick.uploadFailed") }}</span>
              </div>
              <button
                type="button"
                class="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full border border-line bg-surface text-muted shadow-xs hover:text-danger"
                :aria-label="t('finance.quick.removeReceipt', { name: item.name })"
                @click="removeReceipt(item.key)"
              >
                <X :size="12" />
              </button>
            </li>
          </ul>
          <ExtensionSlot name="finance.quickadd.receipt" :context="{ receipts: receipts.filter((r) => r.receipt).map((r) => r.receipt), apply: applyPrefill, mode }" class="empty:hidden" />
        </div>

        <InlineAlert v-if="needsReceipt" tone="warning" size="sm" :title="t('finance.quick.needsReceipt')">
          <template #default>
            <span>{{ t("finance.quick.needsReceiptBody") }} <MoneyText :value="receiptThreshold" /></span>
          </template>
        </InlineAlert>
      </template>
    </div>

    <template #footer>
      <div class="flex w-full flex-wrap items-center gap-2">
        <span class="hidden items-center gap-1 text-xs text-subtle sm:inline-flex"><KbdKey :keys="['mod', 'Enter']" size="sm" />{{ t("finance.quick.toSave") }}</span>
        <span class="flex-1" />
        <UiButton variant="ghost" :disabled="saving || uploading" @click="save(true)">{{ t("finance.quick.saveAnother") }}</UiButton>
        <UiButton variant="primary" :loading="saving" :disabled="uploading" data-testid="quick-save" @click="save(false)">{{ t("finance.quick.save") }}</UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<style scoped>
.quick-amount :deep(input) {
  font-size: 1.375rem;
  font-weight: 600;
  letter-spacing: -0.015em;
}
</style>
