<script setup lang="ts">
/**
 * "Hisobot tayyorlash" (v12): one PDF for a bank, a partner or a buyer with the profit and loss,
 * cash flow, balance sheet and notes. Pick who it is for, the period and the language; the server
 * builds it in the background (the bar follows its progress) and it downloads by itself when
 * ready, optionally also to the owner bot. The last few stay listed for seven days.
 */
import { BadgeDollarSign, Download, FileText, Handshake, Landmark } from "@lucide/vue";
import { computed, reactive, watch } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import CheckBox from "@/components/CheckBox.vue";
import FormField from "@/components/FormField.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import RadioCards from "@/components/RadioCards.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import { isApiError } from "@/api/http";
import { useFormat } from "@/lib/useFormat";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import {
  downloadPack,
  periodChoices,
  usePreparePack,
  useStatementOptions,
  useStatementPacks,
  type PackLanguage,
  type PackPeriod,
  type PackPurpose,
  type PeriodChoice,
  type StatementPack,
} from "../../statements";

const open = defineModel<boolean>("open", { default: false });
const props = withDefaults(defineProps<{ purpose?: PackPurpose }>(), { purpose: "bank" });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const cid = useCompanyId();
const options = useStatementOptions(() => open.value);
const packs = useStatementPacks(() => open.value);
const prepare = usePreparePack();

const form = reactive({
  purpose: props.purpose as PackPurpose | null,
  period: "month" as PackPeriod,
  key: null as string | null,
  language: "uz" as PackLanguage,
  branch: [] as number[],
  telegram: false,
});

const choices = computed<PeriodChoice[]>(() => {
  const o = options.data.value;
  return o ? periodChoices(form.period, o.today, o.books_start) : [];
});
/** A month that only just began isn't worth a report yet: start on the last full one. */
function defaultKey(list: PeriodChoice[]): string | null {
  if (!list.length) return null;
  const first = list[0];
  if (first.partial && form.period === "month" && list.length > 1) return list[1].key;
  return first.key;
}
watch(
  () => [open.value, options.data.value] as const,
  ([isOpen, o]) => {
    if (!isOpen || !o) return;
    form.language = o.language;
    form.purpose = props.purpose;
    form.key = defaultKey(choices.value);
  },
  { immediate: true },
);
watch(
  () => form.period,
  () => (form.key = defaultKey(choices.value)),
);

function label(choice: PeriodChoice): string {
  let text: string;
  if (choice.period === "month") text = fmt.day(choice.start, "monthYear");
  else if (choice.period === "quarter") text = t("finance.pack.quarterOf", { quarter: Number(choice.key.slice(-1)), year: Number(choice.start.slice(0, 4)) });
  else text = choice.key;
  return choice.partial ? t("finance.pack.toDate", { period: text, day: fmt.day(choice.end, "short") }) : text;
}
const periodOptions = computed(() => choices.value.map((choice) => ({ value: choice.key, label: label(choice) })));
const chosen = computed(() => choices.value.find((choice) => choice.key === form.key) ?? null);
const multiBranch = computed(() => (company.current?.branches.length ?? 0) > 1);
const blocked = computed(() => !!options.data.value && !options.data.value.may_prepare);
const empty = computed(() => !!options.data.value && !options.data.value.books_start);
const pack = computed(() => prepare.pack.value);
const stage = computed(() => {
  const value = pack.value?.progress ?? 0;
  if (value < 30) return t("finance.pack.stage.reading");
  if (value < 60) return t("finance.pack.stage.statements");
  if (value < 85) return t("finance.pack.stage.notes");
  return t("finance.pack.stage.pdf");
});
const failure = computed(() => {
  if (pack.value?.status === "failed") return pack.value.error || t("finance.pack.failed");
  const error = prepare.error.value;
  if (!error) return "";
  return isApiError(error) ? error.message : t("finance.pack.failed");
});

async function submit(): Promise<void> {
  if (!chosen.value || !form.purpose) return;
  await prepare.start({
    period: chosen.value.period,
    of: chosen.value.of,
    purpose: form.purpose,
    language: form.language,
    ...(form.branch.length ? { branch: form.branch } : {}),
    deliver_telegram: form.telegram,
  });
}
function again(): void {
  prepare.pack.value = null;
}
const recent = computed<StatementPack[]>(() => (packs.data.value ?? []).filter((row) => row.status === "ready").slice(0, 3));
function recentLabel(row: StatementPack): string {
  const purpose = t(`finance.pack.purpose.${row.purpose}`);
  return `${purpose} · ${fmt.day(row.start, "short")} – ${fmt.day(row.end, "short")}`;
}
watch(open, (isOpen) => {
  if (!isOpen && prepare.pack.value?.status !== "running") prepare.pack.value = null;
});
</script>

<template>
  <UiDialog v-model:open="open" :title="t('finance.pack.title')" :description="t('finance.pack.description')" size="lg">
    <InlineAlert v-if="blocked" tone="warning" :description="t('finance.pack.noPermission')" class="mb-4" />
    <InlineAlert v-else-if="empty" tone="info" :description="t('finance.pack.empty')" class="mb-4" />

    <div v-if="pack && (prepare.running.value || pack.status === 'ready')" class="flex flex-col gap-4 py-2" data-progress>
      <template v-if="pack.status === 'ready'">
        <div class="flex items-start gap-3 rounded-[12px] bg-success-soft p-4">
          <FileText :size="22" class="mt-0.5 shrink-0 text-success" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="font-semibold text-fg">{{ t("finance.pack.ready") }}</p>
            <p class="text-sm text-muted">{{ t("finance.pack.readyHint", { n: pack.pages ?? 0 }, pack.pages ?? 0) }}<template v-if="pack.deliver_telegram"> · {{ t("finance.pack.sentTelegram") }}</template></p>
          </div>
        </div>
      </template>
      <template v-else>
        <ProgressBar :value="pack.progress" :max="100" size="md" :label="stage" show-value />
        <p class="text-xs text-muted">{{ t("finance.pack.wait") }}</p>
      </template>
    </div>

    <div v-else class="flex flex-col gap-5" data-dialog-body>
      <FormField :label="t('finance.pack.forWhom')">
        <RadioCards
          v-model="form.purpose"
          :columns="3"
          :options="[
            { value: 'bank', label: t('finance.pack.purpose.bank'), description: t('finance.pack.purposeHint.bank'), icon: Landmark },
            { value: 'partner', label: t('finance.pack.purpose.partner'), description: t('finance.pack.purposeHint.partner'), icon: Handshake },
            { value: 'sale', label: t('finance.pack.purpose.sale'), description: t('finance.pack.purposeHint.sale'), icon: BadgeDollarSign },
          ]"
        />
      </FormField>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-[auto_minmax(0,1fr)]">
        <FormField :label="t('finance.pack.period')">
          <SegmentedControl
            v-model="form.period"
            :options="[
              { value: 'month', label: t('finance.pack.month') },
              { value: 'quarter', label: t('finance.pack.quarter') },
              { value: 'year', label: t('finance.pack.year') },
            ]"
          />
        </FormField>
        <FormField :label="t('finance.pack.which')">
          <SelectBox v-model="form.key" :options="periodOptions" :disabled="!periodOptions.length" data-period />
        </FormField>
      </div>
      <FormField :label="t('finance.pack.language')">
        <SegmentedControl
          v-model="form.language"
          :options="[
            { value: 'uz', label: 'O‘zbekcha' },
            { value: 'ru', label: 'Русский' },
            { value: 'en', label: 'English' },
          ]"
        />
      </FormField>
      <FormField v-if="multiBranch && options.data.value?.whole_company" :label="t('finance.pack.branches')" :hint="t('finance.pack.branchesHint')">
        <BranchPicker v-model="form.branch" multiple :placeholder="t('finance.reports.allBranches')" />
      </FormField>
      <p v-else-if="options.data.value && !options.data.value.whole_company" class="text-xs text-muted">{{ t("finance.pack.ownBranches") }}</p>
      <CheckBox
        v-model="form.telegram"
        :disabled="!options.data.value?.telegram"
        :label="t('finance.pack.telegram')"
        :description="options.data.value?.telegram ? t('finance.pack.telegramHint') : t('finance.pack.telegramOff')"
      />
      <div v-if="recent.length" class="flex flex-col gap-1 border-t border-line pt-3" data-recent>
        <p class="text-xs font-medium text-muted">{{ t("finance.pack.recent") }}</p>
        <button v-for="row in recent" :key="row.id" type="button" class="-mx-2 flex items-center gap-2 rounded-[8px] px-2 py-1.5 text-left text-sm hover:bg-highlight" @click="downloadPack(cid, row.id)">
          <Download :size="14" class="shrink-0 text-muted" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-fg">{{ recentLabel(row) }}</span>
          <span class="shrink-0 text-xs text-muted">{{ row.language.toUpperCase() }}</span>
        </button>
      </div>
    </div>
    <InlineAlert v-if="failure" tone="danger" :description="failure" class="mt-4" />

    <template #footer>
      <template v-if="pack?.status === 'ready'">
        <UiButton variant="ghost" @click="again">{{ t("finance.pack.another") }}</UiButton>
        <UiButton variant="primary" :icon="Download" data-download @click="downloadPack(cid, pack.id)">{{ t("finance.pack.download") }}</UiButton>
      </template>
      <template v-else>
        <UiButton variant="ghost" @click="open = false">{{ prepare.running.value ? t("finance.pack.hide") : t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :icon="FileText" :loading="prepare.running.value" :disabled="blocked || empty || !chosen || !form.purpose" data-prepare @click="submit">{{ t("finance.pack.prepare") }}</UiButton>
      </template>
    </template>
  </UiDialog>
</template>
