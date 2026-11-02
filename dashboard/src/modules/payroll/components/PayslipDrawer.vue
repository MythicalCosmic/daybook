<script setup lang="ts">
/**
 * One payslip in a side panel synced with `?payslip=` (a bottom sheet on phones): whose and which
 * month, net in large type, the days and hours it was worked out from, every line with how it was
 * worked out, a manual line while the run is a draft, the PDF, and "Mark paid" for this one.
 */
import { CircleCheck, Eye, FileDown, HandCoins, Plus } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import type { DescriptionItem } from "@/components/DescriptionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { dec } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { openPayslipPdf, payrollApi, usePayslip, useRefresh } from "../api";
import { isPayable, PAYSLIP_TONES, quantityText } from "../lib";
import type { PayslipLine, Run } from "../types";
import PayAmount from "./PayAmount.vue";
import PayslipLines from "./PayslipLines.vue";

const props = defineProps<{ run: Run }>();
const emit = defineEmits<{ pay: [id: number] }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const refresh = useRefresh();

const id = computed(() => {
  const raw = route.query.payslip;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = usePayslip(id);
const slip = computed(() => query.data.value ?? null);
const editable = computed(() => props.run.status === "draft" && company.can("payroll.manage"));
const canPay = computed(() => !!slip.value && company.can("payroll.pay") && isPayable(slip.value, props.run.status));

const facts = computed<DescriptionItem[]>(() => {
  const s = slip.value;
  if (!s) return [];
  const items: DescriptionItem[] = [{ key: "type", label: t("payroll.payslip.payType"), value: t(`payroll.payType.${s.pay_type}`) }];
  if (s.scheduled_days !== null && s.paid_days !== null) {
    items.push({ key: "days", label: t("payroll.payslip.days"), value: t("payroll.payslip.daysValue", { paid: quantityText(s.paid_days, fmt.lang.value), scheduled: quantityText(s.scheduled_days, fmt.lang.value) }) });
  }
  if (s.absent_days && !dec(s.absent_days).isZero()) items.push({ key: "absent", label: t("payroll.payslip.absent"), value: quantityText(s.absent_days, fmt.lang.value) });
  if (s.worked_minutes) items.push({ key: "worked", label: t("payroll.payslip.worked"), value: fmt.duration(s.worked_minutes) });
  if (s.overtime_minutes) items.push({ key: "overtime", label: t("payroll.payslip.overtime"), value: fmt.duration(s.overtime_minutes) });
  if (s.paid_at) items.push({ key: "paid", label: t("payroll.payslip.paidAt"), value: `${fmt.instant(s.paid_at, "date")}${s.payout_method ? ` · ${t(`payroll.method.${s.payout_method}`)}` : ""}` });
  return items;
});

// Manual lines (a draft run only): label and amount, added or taken off.
const adding = ref(false);
const draft = ref({ label: "", amount: null as string | null, sign: "plus" as "plus" | "minus" });
const saving = ref(false);
const removing = ref<number | null>(null);
watch(id, () => {
  adding.value = false;
  draft.value = { label: "", amount: null, sign: "plus" };
});

const manualLines = computed(() => (slip.value?.lines ?? []).filter((line) => line.kind === "manual").map((line) => ({ label: line.label, amount: line.amount })));

async function saveLines(lines: Array<{ label: string; amount: string }>, done: string): Promise<boolean> {
  if (!slip.value) return false;
  try {
    await payrollApi.setManualLines(company.currentId ?? 0, slip.value.id, lines);
    toast.success(done);
    refresh();
    return true;
  } catch {
    return false;
  }
}

async function addLine(): Promise<void> {
  if (!draft.value.label.trim() || !draft.value.amount || saving.value) return;
  saving.value = true;
  const amount = draft.value.sign === "minus" ? dec(draft.value.amount).negated().toFixed(2) : dec(draft.value.amount).toFixed(2);
  const ok = await saveLines([...manualLines.value, { label: draft.value.label.trim(), amount }], t("payroll.payslip.lineAdded"));
  saving.value = false;
  if (ok) {
    adding.value = false;
    draft.value = { label: "", amount: null, sign: "plus" };
  }
}

async function removeLine(line: PayslipLine): Promise<void> {
  removing.value = line.id;
  const rest = (slip.value?.lines ?? []).filter((row) => row.kind === "manual" && row.id !== line.id).map((row) => ({ label: row.label, amount: row.amount }));
  await saveLines(rest, t("payroll.payslip.lineRemoved"));
  removing.value = null;
}

const downloading = ref(false);
async function pdf(): Promise<void> {
  if (!slip.value || downloading.value) return;
  downloading.value = true;
  try {
    await openPayslipPdf(company.currentId ?? 0, slip.value.id, `payslip-${slip.value.period.slice(0, 7)}-${slip.value.member.name}.pdf`);
  } catch {
    // The HTTP layer said why.
  } finally {
    downloading.value = false;
  }
}
</script>

<template>
  <UiDrawer query-key="payslip" size="md" :title="t('payroll.payslip.title')">
    <template #default>
      <div class="p-5">
        <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
          <SkeletonBlock height="72px" radius="12px" />
          <SkeletonBlock v-for="n in 6" :key="n" height="44px" radius="10px" />
        </div>
        <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
        <div v-else-if="slip" class="flex flex-col gap-5">
          <header class="flex items-start gap-3">
            <UserAvatar :name="slip.member.name" :src="slip.member.photo_url" :size="44" shape="rounded" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-base font-semibold text-fg" :title="slip.member.name">{{ slip.member.name }}</p>
              <p class="truncate text-sm text-muted">{{ [slip.member.position, slip.member.branch, fmt.day(slip.period, "monthYear")].filter(Boolean).join(" · ") }}</p>
              <p class="mt-1 text-[1.625rem] font-semibold leading-8 tracking-[-0.02em] tabular-nums text-fg"><PayAmount :value="slip.net" :currency="slip.currency" /></p>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <StatusPill :tone="PAYSLIP_TONES[slip.status]" size="sm" :label="t(`payroll.payslipStatus.${slip.status}`)" />
                <StatusPill v-if="slip.received_at" tone="success" size="sm" variant="outline" :icon="CircleCheck" :dot="false" :label="t('payroll.payslip.received', { date: fmt.instant(slip.received_at, 'date') })" />
                <StatusPill v-else-if="slip.viewed_at" tone="info" size="sm" variant="outline" :icon="Eye" :dot="false" :label="t('payroll.payslip.viewed')" />
              </div>
            </div>
          </header>

          <!-- Two columns on a phone too: these are short facts, and the lines below matter more. -->
          <dl class="grid grid-cols-2 gap-x-4 gap-y-3" data-testid="payslip-facts">
            <div v-for="item in facts" :key="item.key" class="min-w-0">
              <dt class="text-xs text-muted">{{ item.label }}</dt>
              <dd class="mt-0.5 text-sm font-medium tabular-nums text-fg">{{ item.value }}</dd>
            </div>
          </dl>

          <PayslipLines
            :lines="slip.lines ?? []"
            :currency="slip.currency"
            :gross="slip.gross"
            :deductions="slip.deductions"
            :net="slip.net"
            :editable="editable"
            :removing="removing"
            @remove="removeLine"
          />

          <section v-if="editable" class="flex flex-col gap-2">
            <UiButton v-if="!adding" variant="ghost" size="sm" :icon="Plus" class="self-start" data-testid="add-line" @click="adding = true">{{ t("payroll.payslip.addLine") }}</UiButton>
            <div v-else class="flex flex-col gap-3 rounded-[12px] border border-line p-3">
              <p class="text-sm text-muted">{{ t("payroll.payslip.addLineHint") }}</p>
              <FormField :label="t('payroll.payslip.lineLabel')" required>
                <TextInput v-model="draft.label" :maxlength="200" :placeholder="t('payroll.payslip.lineLabelPlaceholder')" autofocus />
              </FormField>
              <SegmentedControl
                v-model="draft.sign"
                block
                size="sm"
                :options="[
                  { value: 'plus', label: t('payroll.payslip.linePlus'), icon: Plus },
                  { value: 'minus', label: t('payroll.payslip.lineMinus') },
                ]"
              />
              <FormField :label="t('payroll.field.amount')" required>
                <MoneyInput v-model="draft.amount" :currencies="[slip.currency]" />
              </FormField>
              <div class="flex justify-end gap-2">
                <UiButton variant="ghost" size="sm" @click="adding = false">{{ t("common.cancel") }}</UiButton>
                <UiButton variant="primary" size="sm" :loading="saving" :disabled="!draft.label.trim() || !draft.amount" @click="addLine">{{ t("payroll.payslip.saveLine") }}</UiButton>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="slip" class="flex w-full flex-wrap items-center gap-2">
        <UiButton size="sm" :icon="FileDown" :loading="downloading" data-testid="payslip-pdf" @click="pdf">{{ t("payroll.payslip.pdf") }}</UiButton>
        <span class="flex-1" />
        <UiButton v-if="canPay" variant="primary" size="sm" :icon="HandCoins" @click="emit('pay', slip.id)">{{ t("payroll.payslip.markPaid") }}</UiButton>
      </div>
    </template>
  </UiDrawer>
</template>
