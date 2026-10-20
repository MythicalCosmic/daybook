<script setup lang="ts">
/** Kitchen: every input and picker, in FormFields, with valid, invalid and disabled states. */
import { BrainCircuit, CalendarDays, Coins, Gauge, Rows3, Search, SquareKanban, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import type { Currency } from "@/api/types";
import BranchPicker from "@/components/BranchPicker.vue";
import CheckBox from "@/components/CheckBox.vue";
import ComboBox from "@/components/ComboBox.vue";
import DatePicker from "@/components/DatePicker.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import FileDrop from "@/components/FileDrop.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MultiSelect from "@/components/MultiSelect.vue";
import NumberInput from "@/components/NumberInput.vue";
import type { SelectOption } from "@/components/options";
import PersonPicker from "@/components/PersonPicker.vue";
import PositionPicker from "@/components/PositionPicker.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import TextArea from "@/components/TextArea.vue";
import TextInput from "@/components/TextInput.vue";
import TimePicker from "@/components/TimePicker.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import WeekdayPicker from "@/components/WeekdayPicker.vue";
import { rangeValue } from "@/lib/dateRange";
import { addDays, todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { BRANCHES, PEOPLE, POSITIONS } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});
const company = useCompanyStore();
const today = computed(() => todayIn(company.timezone));

const name = ref("Chilonzor-2");
const search = ref("");
const phone = ref("");
const note = ref("The fridge on the left is warmer than it should be. Moved the milk to the back one.");
const minutes = ref<number | null>(45);
const percent = ref<number | null>(12.5);
const amount = ref<string | null>("1250000.00");
const usd = ref<string | null>(null);
const currency = ref<Currency>("UZS");
const status = ref<string | null>("open");
const category = ref<string | null>("supplies");
const counterparty = ref<number | null>(2);
const tags = ref<string[]>(["open", "late"]);
const assignee = ref<number | null>(14);
const reviewers = ref<number[]>([12, 13]);
const positions = ref<number[]>([1]);
const branch = ref<number | null>(1);
const branchesPicked = ref<number[]>([]);
const notify = ref(true);
const all = ref(false);
const autoApprove = ref(false);
const ai = ref(true);
const payType = ref<"monthly" | "hourly" | "piece">("monthly");
const view = ref("table");
const due = ref<string | null>(null);
const period = ref(rangeValue("month", company.timezone, "prev"));
const opens = ref<string | null>("09:00");
const weekdays = ref([0, 1, 2, 3, 4, 5]);
const files = ref<File[]>([]);

const statusOptions = computed<SelectOption<string>[]>(() => [
  { value: "open", label: k("status.open"), color: "var(--c-info)" },
  { value: "late", label: k("status.late"), color: "var(--c-danger)" },
  { value: "review", label: k("status.review"), color: "var(--c-warning)" },
  { value: "done", label: k("status.done"), color: "var(--c-success)" },
]);
const categoryOptions = computed<SelectOption<string>[]>(() => [
  { value: "rent", label: "Rent", group: k("expenses") },
  { value: "supplies", label: "Supplies", group: k("expenses"), description: "Cleaning, packaging, stationery" },
  { value: "utilities", label: "Utilities", group: k("expenses") },
  { value: "sales", label: "Sales", group: k("income") },
  { value: "other", label: "Other income", group: k("income") },
]);

const COUNTERPARTIES: SelectOption<number>[] = [
  { value: 1, label: "Korzinka", description: "Supermarket chain" },
  { value: 2, label: "Makro", description: "Wholesale" },
  { value: 3, label: "Coca-Cola Ichimligi", description: "Drinks supplier" },
  { value: 4, label: "Kapitalbank", description: "Bank" },
  { value: 5, label: "Uzbektelecom", description: "Internet" },
];
/** A pretend server search: 300 ms later, filtered. */
const searchCounterparties = (query: string, signal: AbortSignal) =>
  new Promise<SelectOption<number>[]>((resolve, reject) => {
    const timer = setTimeout(() => resolve(COUNTERPARTIES.filter((c) => c.label.toLowerCase().includes(query.toLowerCase()))), 300);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

const payOptions = computed(() => [
  { value: "monthly" as const, label: k("pay.monthly"), description: k("pay.monthlyHint"), icon: CalendarDays },
  { value: "hourly" as const, label: k("pay.hourly"), description: k("pay.hourlyHint"), icon: Gauge, badge: "18 000 so‘m/h" },
  { value: "piece" as const, label: k("pay.piece"), description: k("pay.pieceHint"), icon: Coins },
]);
const viewOptions = computed(() => [
  { value: "table", label: k("view.table"), icon: Rows3 },
  { value: "board", label: k("view.board"), icon: SquareKanban, count: 12 },
  { value: "calendar", label: k("view.calendar"), icon: CalendarDays },
]);
const aiOptions = computed(() => [
  { value: "standard", label: k("ai.standard"), description: k("ai.standardHint"), icon: BrainCircuit, badge: "≈ 90 so‘m" },
  { value: "deep", label: k("ai.deep"), description: k("ai.deepHint"), icon: Wallet, badge: "≈ 1 400 so‘m" },
]);
const aiModel = ref("standard");
</script>

<template>
  <KitchenSection id="inputs" :title="k('section.inputs')" :description="k('section.inputsHint')">
    <KitchenSpecimen name="FormField.vue · TextInput.vue · TextArea.vue">
      <div class="flex flex-col gap-4">
        <FormField :label="k('branchName')" :hint="k('branchNameHint')" required>
          <TextInput v-model="name" :maxlength="60" />
        </FormField>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="t('common.search')">
            <TextInput v-model="search" type="search" :icon="Search" clearable :placeholder="k('searchPeople')" />
          </FormField>
          <FormField :label="k('phone')" :error="phone && phone.length < 9 ? k('phoneError') : null">
            <TextInput v-model="phone" type="tel" prefix="+998" inputmode="tel" placeholder="90 123 45 67" />
          </FormField>
        </div>
        <FormField :label="k('note')" optional :count="(note ?? '').length" :max="280">
          <TextArea v-model="note" :rows="2" />
        </FormField>
        <FormField :label="k('disabled')" disabled>
          <TextInput model-value="RENO-14" mono />
        </FormField>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="MoneyInput.vue · NumberInput.vue" :note="k('moneyNote')">
      <div class="flex flex-col gap-4">
        <FormField :label="k('amount')" :hint="amount ? `API: ${amount}` : undefined" required>
          <MoneyInput v-model="amount" />
        </FormField>
        <FormField :label="k('amountCurrency')" :hint="usd ? `API: ${usd} ${currency}` : undefined">
          <MoneyInput v-model="usd" v-model:currency="currency" :currencies="['UZS', 'USD']" :placeholder="k('typeAmount')" />
        </FormField>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="k('graceMinutes')">
            <NumberInput v-model="minutes" :min="0" :max="240" :step="5" :suffix="k('min')" />
          </FormField>
          <FormField :label="k('taxRate')" error="Must be 12% or less">
            <NumberInput v-model="percent" :min="0" :max="100" :step="0.5" :decimals="1" suffix="%" />
          </FormField>
        </div>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="SelectBox.vue · ComboBox.vue · MultiSelect.vue">
      <div class="flex flex-col gap-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="k('statusLabel')">
            <SelectBox v-model="status" :options="statusOptions" clearable />
          </FormField>
          <FormField :label="k('category')">
            <SelectBox v-model="category" :options="categoryOptions" />
          </FormField>
        </div>
        <FormField :label="k('counterparty')" :hint="k('counterpartyHint')">
          <ComboBox v-model="counterparty" :source="searchCounterparties" :selected="COUNTERPARTIES[1]" creatable clearable />
        </FormField>
        <FormField :label="k('statuses')">
          <MultiSelect v-model="tags" :options="statusOptions" />
        </FormField>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="PersonPicker.vue · PositionPicker.vue · BranchPicker.vue">
      <div class="flex flex-col gap-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="k('assignee')">
            <PersonPicker v-model="assignee" :people="PEOPLE" />
          </FormField>
          <FormField :label="k('branch')">
            <BranchPicker v-model="branch" :branches="BRANCHES" />
          </FormField>
        </div>
        <FormField :label="k('reviewers')">
          <PersonPicker v-model="reviewers" multiple :people="PEOPLE" />
        </FormField>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="k('positions')">
            <PositionPicker v-model="positions" multiple :positions="POSITIONS" />
          </FormField>
          <FormField :label="k('branches')">
            <BranchPicker v-model="branchesPicked" multiple :branches="BRANCHES" />
          </FormField>
        </div>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="DatePicker.vue · DateRangePicker.vue · TimePicker.vue · WeekdayPicker.vue">
      <div class="flex flex-col gap-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <FormField :label="k('due')">
            <DatePicker v-model="due" :min="today" clearable :placeholder="k('noDue')" />
          </FormField>
          <FormField :label="k('opensAt')">
            <TimePicker v-model="opens" :step="15" />
          </FormField>
        </div>
        <FormField :label="k('period')">
          <DateRangePicker v-model="period" />
        </FormField>
        <FormField :label="k('weekdays')">
          <WeekdayPicker v-model="weekdays" presets />
        </FormField>
        <p class="text-xs text-muted">{{ due ?? "—" }} · {{ opens ?? "—" }} · {{ period.range.from }} → {{ period.range.to }} · [{{ weekdays.join(", ") }}] · {{ addDays(today, 0) }}</p>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="CheckBox.vue · ToggleSwitch.vue · SegmentedControl.vue">
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-3">
          <CheckBox v-model="notify" :label="k('notify')" :description="k('notifyHint')" />
          <CheckBox v-model="all" :indeterminate="!all" :label="k('selectSome')" />
          <CheckBox :model-value="false" disabled :label="k('disabled')" />
        </div>
        <div class="flex flex-col divide-y divide-[var(--c-border)] rounded-[10px] border border-line px-3">
          <div class="py-3"><ToggleSwitch v-model="autoApprove" layout="row" :label="k('autoApprove')" :description="k('autoApproveHint')" /></div>
          <div class="py-3"><ToggleSwitch v-model="ai" layout="row" :label="k('aiOn')" :description="k('aiOnHint')" /></div>
          <div class="py-3"><ToggleSwitch :model-value="true" layout="row" loading :label="k('saving')" /></div>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <SegmentedControl v-model="view" :options="viewOptions" :aria-label="k('viewLabel')" />
          <SegmentedControl v-model="view" :options="viewOptions.map((o) => ({ ...o, iconOnly: true, count: undefined }))" size="sm" :aria-label="k('viewLabel')" />
        </div>
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="RadioCards.vue">
      <div class="flex flex-col gap-4">
        <RadioCards v-model="payType" :options="payOptions" :columns="3" />
        <RadioCards v-model="aiModel" :options="aiOptions" :columns="2" />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="FileDrop.vue">
      <div class="flex flex-col gap-4">
        <FormField :label="k('receipts')">
          <FileDrop v-model="files" accept="image/*,application/pdf" multiple :max-size="10 * 1024 * 1024" />
        </FormField>
        <FileDrop :model-value="[]" accept="application/pdf" compact :title="k('contractPdf')" />
      </div>
    </KitchenSpecimen>
  </KitchenSection>
</template>
