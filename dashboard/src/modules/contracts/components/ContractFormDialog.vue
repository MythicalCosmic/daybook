<script setup lang="ts">
/**
 * Add or change a contract: what it is and who with (a party from the directory, or a new one
 * by name), where, its dates and auto-renewal (the notice deadline previewed), the money, and
 * whether its payment goes into the cash forecast (a new recurring payment, or one already in
 * Finance taken over so the rent isn't counted twice). A new contract can take its signed scan
 * and annexes right away (PDF or pictures).
 */
import { CalendarClock, Check, Paperclip, Wallet } from "@lucide/vue";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import { isApiError } from "@/api/http";
import BranchPicker from "@/components/BranchPicker.vue";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import NumberInput from "@/components/NumberInput.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { contractsApi, useOptions, useRefresh } from "../api";
import { KIND_ICONS, noticeDeadline } from "../lib";
import { KINDS, PERIODS, type ContractDetail, type ContractInput, type ContractKind, type ContractPeriod } from "../types";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ contract?: ContractDetail | null }>(), { contract: null });
const emit = defineEmits<{ saved: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const refresh = useRefresh();
const options = useOptions(computed(() => open.value));

const editing = computed(() => props.contract !== null);
const saving = ref(false);
const errors = reactive<Record<string, string | undefined>>({});
const files = ref<File[]>([]);
const created = ref<{ value: string; label: string }[]>([]);

const blank = () => ({
  kind: "lease" as ContractKind,
  title: "",
  party: null as string | null,
  number: "",
  branch: null as number | null,
  responsible: null as number | null,
  signed_on: null as string | null,
  starts_on: null as string | null,
  ends_on: null as string | null,
  auto_renews: false,
  renewal_months: 12 as number | null,
  notice_days: 30 as number | null,
  amount: null as string | null,
  currency: (company.currency ?? "UZS") as Currency,
  period: "monthly" as ContractPeriod,
  payment_day: null as number | null,
  in_forecast: false,
  source: "new" as "new" | "link",
  category: null as number | null,
  account: null as number | null,
  link_rule: null as number | null,
  draft: false,
  notes: "",
});
const form = reactive(blank());

function reset(): void {
  for (const key of Object.keys(errors)) delete errors[key];
  files.value = [];
  created.value = [];
  const row = props.contract;
  Object.assign(form, blank());
  if (!row) return;
  Object.assign(form, {
    kind: row.kind,
    title: row.title,
    party: row.counterparty ? `p:${row.counterparty.id}` : null,
    number: row.number,
    branch: row.branch?.id ?? null,
    responsible: row.responsible?.id ?? null,
    signed_on: row.signed_on,
    starts_on: row.starts_on,
    ends_on: row.ends_on,
    auto_renews: row.auto_renews,
    renewal_months: row.renewal_months,
    notice_days: row.notice_days,
    amount: row.amount,
    currency: row.currency,
    period: row.period,
    payment_day: row.payment_day,
    in_forecast: row.in_forecast,
    draft: row.status === "draft",
    notes: row.notes,
  });
  if (row.counterparty) created.value = [{ value: `p:${row.counterparty.id}`, label: row.counterparty.name }];
}

watch(open, (value) => value && reset(), { immediate: true });

const kindCards = computed(() => KINDS.map((value) => ({ value, label: t(`contracts.kind.${value}`), description: t(`contracts.kindHint.${value}`), icon: KIND_ICONS[value] })));
const periodOptions = computed(() => PERIODS.map((value) => ({ value, label: t(`contracts.period.${value}`) })));
const partyOptions = computed(() => [
  ...created.value.filter((option) => !(options.data.value?.parties ?? []).some((party) => `p:${party.id}` === option.value)),
  ...(options.data.value?.parties ?? []).map((party) => ({ value: `p:${party.id}`, label: party.name })),
]);
const finance = computed(() => options.data.value?.finance ?? false);
const repeats = computed(() => form.period !== "once");
const hasRule = computed(() => Boolean(props.contract?.rule));
const categoryOptions = computed(() => (options.data.value?.categories ?? []).map((row) => ({ value: row.id, label: row.name })));
const accountOptions = computed(() =>
  (options.data.value?.accounts ?? []).filter((row) => row.currency === form.currency).map((row) => ({ value: row.id, label: row.name, description: row.currency })),
);
const ruleOptions = computed(() =>
  (options.data.value?.rules ?? [])
    .filter((row) => row.currency === form.currency)
    .map((row) => ({ value: row.id, label: row.name, description: `${fmt.money(row.amount, row.currency, { decimals: "never" })} · ${t(`contracts.frequency.${row.frequency}`)}` })),
);
const deadline = computed(() => noticeDeadline(form.ends_on, form.notice_days, form.auto_renews));
const sources = computed(() => [
  { value: "new" as const, label: t("contracts.form.sourceNew") },
  { value: "link" as const, label: t("contracts.form.sourceLink"), disabled: !ruleOptions.value.length },
]);

function addParty(name: string): void {
  const clean = name.trim();
  if (!clean) return;
  const value = `new:${clean}`;
  created.value = [{ value, label: t("contracts.form.newParty", { name: clean }) }, ...created.value.filter((option) => option.value !== value)];
  form.party = value;
}

function input(): ContractInput {
  const body: ContractInput = {
    kind: form.kind,
    title: form.title.trim(),
    number: form.number.trim(),
    branch: form.branch,
    responsible: form.responsible,
    signed_on: form.signed_on,
    starts_on: form.starts_on,
    ends_on: form.ends_on,
    auto_renews: form.auto_renews,
    renewal_months: form.renewal_months ?? 12,
    notice_days: form.notice_days ?? 0,
    amount: form.amount || null,
    currency: form.currency,
    period: form.period,
    payment_day: repeats.value ? form.payment_day : null,
    notes: form.notes,
    status: form.draft ? "draft" : "active",
    in_forecast: finance.value && repeats.value && form.in_forecast,
  };
  if (form.party?.startsWith("p:")) body.counterparty = Number(form.party.slice(2));
  else if (form.party?.startsWith("new:")) {
    body.counterparty = null;
    body.counterparty_name = form.party.slice(4);
  } else body.counterparty = null;
  if (body.in_forecast && !hasRule.value) {
    if (form.source === "link" && form.link_rule) body.link_rule = form.link_rule;
    else {
      if (form.category) body.category = form.category;
      if (form.account) body.account = form.account;
    }
  }
  return body;
}

async function save(): Promise<void> {
  for (const key of Object.keys(errors)) delete errors[key];
  if (!form.title.trim()) errors.title = t("contracts.form.errTitle");
  if (!form.draft && !form.starts_on) errors.starts_on = t("contracts.form.errStart");
  if (form.auto_renews && !form.ends_on) errors.ends_on = t("contracts.form.errEndRenews");
  if (form.in_forecast && repeats.value && !Number(form.amount)) errors.amount = t("contracts.form.errAmount");
  if (Object.values(errors).some(Boolean)) return;
  saving.value = true;
  const cid = company.currentId ?? 0;
  try {
    const result = props.contract ? await contractsApi.update(cid, props.contract.id, input()) : await contractsApi.create(cid, input());
    for (const [index, file] of files.value.entries()) {
      try {
        await contractsApi.upload(cid, result.id, file, index === 0 ? "signed" : "annex");
      } catch {
        // The HTTP layer shows why; the contract itself is saved.
      }
    }
    toast.success(props.contract ? t("contracts.form.saved") : t("contracts.form.created"), { description: result.title });
    refresh();
    open.value = false;
    emit("saved", result.id);
  } catch (error) {
    if (isApiError(error)) for (const [field, messages] of Object.entries(error.fieldErrors)) errors[field] = messages[0];
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <UiDialog
    v-model:open="open"
    :title="editing ? t('contracts.form.editTitle') : t('contracts.form.newTitle')"
    :description="editing ? undefined : t('contracts.form.newDescription')"
    size="lg"
  >
    <div class="flex flex-col gap-6">
      <section class="flex flex-col gap-3">
        <h3 class="text-sm font-semibold text-fg">{{ t("contracts.form.what") }}</h3>
        <RadioCards v-model="form.kind" :options="kindCards" :columns="3" data-testid="contract-kind" />
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField class="sm:col-span-2" :label="t('contracts.field.title')" :error="errors.title" required>
            <TextInput v-model="form.title" :maxlength="200" :placeholder="t(`contracts.placeholder.${form.kind}`)" data-testid="contract-title" />
          </FormField>
          <FormField :label="t('contracts.field.counterparty')" :hint="t('contracts.form.partyHint')" :error="errors.counterparty ?? errors.counterparty_name" optional>
            <ComboBox
              v-model="form.party"
              :options="partyOptions"
              creatable
              clearable
              :placeholder="t('contracts.form.pickParty')"
              :search-placeholder="t('contracts.form.searchParty')"
              @create="addParty"
            />
          </FormField>
          <FormField :label="t('contracts.field.number')" optional>
            <TextInput v-model="form.number" :maxlength="64" mono />
          </FormField>
          <FormField :label="t('contracts.field.branch')" :hint="t('contracts.form.branchHint')" :error="errors.branch" optional>
            <BranchPicker v-model="form.branch" clearable :placeholder="t('contracts.wholeCompany')" />
          </FormField>
          <FormField :label="t('contracts.field.responsible')" :hint="t('contracts.form.responsibleHint')" :error="errors.responsible" optional>
            <PersonPicker v-model="form.responsible" clearable />
          </FormField>
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><CalendarClock :size="16" class="text-muted" aria-hidden="true" />{{ t("contracts.form.dates") }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <FormField :label="t('contracts.field.signedOn')" optional>
            <DatePicker v-model="form.signed_on" />
          </FormField>
          <FormField :label="t('contracts.field.startsOn')" :error="errors.starts_on" :required="!form.draft">
            <DatePicker v-model="form.starts_on" />
          </FormField>
          <FormField :label="t('contracts.field.endsOn')" :hint="form.ends_on ? undefined : t('contracts.form.noEndHint')" :error="errors.ends_on" optional>
            <DatePicker v-model="form.ends_on" :min="form.starts_on" />
          </FormField>
        </div>
        <ToggleSwitch v-model="form.auto_renews" layout="row" :label="t('contracts.field.autoRenews')" :description="t('contracts.form.autoRenewsHint')" />
        <div v-if="form.auto_renews" class="grid grid-cols-1 gap-3 rounded-[12px] border border-line bg-surface-2/50 p-3 sm:grid-cols-2">
          <FormField :label="t('contracts.field.noticeDays')" :error="errors.notice_days">
            <NumberInput v-model="form.notice_days" :min="0" :max="365" :suffix="t('contracts.form.days')" />
          </FormField>
          <FormField :label="t('contracts.field.renewalMonths')" :error="errors.renewal_months">
            <NumberInput v-model="form.renewal_months" :min="1" :max="120" :suffix="t('contracts.form.months')" />
          </FormField>
          <p v-if="deadline" class="text-sm text-muted sm:col-span-2" data-testid="contract-deadline">
            {{ t("contracts.form.deadlinePreview", { day: fmt.day(deadline, "long") }) }}
          </p>
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Wallet :size="16" class="text-muted" aria-hidden="true" />{{ t("contracts.form.money") }}</h3>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <FormField :label="t('contracts.field.amount')" :error="errors.amount" optional>
            <MoneyInput v-model="form.amount" v-model:currency="form.currency" :currencies="['UZS', 'USD']" />
          </FormField>
          <FormField :label="t('contracts.field.period')">
            <SelectBox v-model="form.period" :options="periodOptions" />
          </FormField>
          <FormField v-if="repeats" :label="t('contracts.field.paymentDay')" :hint="t('contracts.form.paymentDayHint')" :error="errors.payment_day" optional>
            <NumberInput v-model="form.payment_day" :min="1" :max="31" />
          </FormField>
        </div>

        <div v-if="finance && repeats" class="flex flex-col gap-3 rounded-[12px] border border-line p-3">
          <ToggleSwitch v-model="form.in_forecast" layout="row" :label="t('contracts.field.inForecast')" :description="t('contracts.form.inForecastHint')" data-testid="contract-forecast" />
          <template v-if="form.in_forecast">
            <InlineAlert v-if="hasRule && contract?.rule" tone="info" size="sm" :title="t('contracts.form.ruleLinked', { name: contract.rule.name })">
              {{ t("contracts.form.ruleLinkedBody") }}
            </InlineAlert>
            <template v-else>
              <SegmentedControl v-model="form.source" :options="sources" size="sm" />
              <div v-if="form.source === 'new'" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <FormField :label="t('contracts.field.category')" :hint="t('contracts.form.categoryHint')" :error="errors.category" optional>
                  <SelectBox v-model="form.category" :options="categoryOptions" clearable :placeholder="t('contracts.form.byKind')" />
                </FormField>
                <FormField :label="t('contracts.field.account')" :hint="form.currency === 'USD' ? t('contracts.form.accountUsdHint') : t('contracts.form.accountHint')" :error="errors.account" optional>
                  <SelectBox v-model="form.account" :options="accountOptions" clearable :placeholder="t('contracts.form.anyAccount')" />
                </FormField>
              </div>
              <FormField v-else :label="t('contracts.field.linkRule')" :hint="t('contracts.form.linkHint')" :error="errors.link_rule">
                <SelectBox v-model="form.link_rule" :options="ruleOptions" :placeholder="t('contracts.form.pickRule')" />
              </FormField>
            </template>
          </template>
        </div>
      </section>

      <section v-if="!editing" class="flex flex-col gap-3">
        <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><Paperclip :size="16" class="text-muted" aria-hidden="true" />{{ t("contracts.form.files") }}</h3>
        <FileDrop v-model="files" accept="application/pdf,image/*" multiple :max-files="10" :max-size="20 * 1024 * 1024" compact :hint="t('contracts.files.hint')" />
      </section>

      <section class="flex flex-col gap-3">
        <FormField :label="t('contracts.field.notes')" optional>
          <TextArea v-model="form.notes" :rows="3" :max-rows="8" :placeholder="t('contracts.form.notesPlaceholder')" />
        </FormField>
        <ToggleSwitch v-model="form.draft" layout="row" :label="t('contracts.field.draft')" :description="t('contracts.form.draftHint')" />
      </section>
    </div>

    <template #footer>
      <UiButton variant="ghost" @click="open = false">{{ t("common.cancel") }}</UiButton>
      <UiButton variant="primary" :icon="Check" :loading="saving" data-testid="contract-save" @click="save">{{ editing ? t("contracts.form.save") : t("contracts.form.add") }}</UiButton>
    </template>
  </UiDialog>
</template>
