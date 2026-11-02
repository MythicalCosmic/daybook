<script setup lang="ts">
/**
 * One disciplinary record in a side panel synced with `?record=`: what happened and when, who issued
 * it, the evidence, the fine proposed to payroll (its amount only for payroll.view), whether the
 * employee has read it, and their explanation in their own words. hr.discipline may propose a fine
 * afterwards or withdraw the record (with the reason).
 */
import { Banknote, CircleCheck, EllipsisVertical, FileText, Hourglass, LockKeyhole, MessageSquareQuote, Undo2 } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import type { Money } from "@/api/types";
import DescriptionList, { type DescriptionItem } from "@/components/DescriptionList.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDialog from "@/components/UiDialog.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { moneySign } from "@/lib/money";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { lifecycleApi, useLifecycleMutation, useRecord } from "../api";
import { KIND_TONES, lifecycleAccess, recordState, STATE_TONES } from "../lib";

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const company = useCompanyStore();
const confirm = useConfirm();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const id = computed(() => {
  const raw = route.query.record;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useRecord(id);
const record = computed(() => query.data.value ?? null);
const state = computed(() => (record.value ? recordState(record.value) : null));
const category = (value: string) => (te(`lifecycle.category.${value}`) ? t(`lifecycle.category.${value}`) : value);
const fineStatus = (value: string) => (te(`lifecycle.fineStatus.${value}`) ? t(`lifecycle.fineStatus.${value}`) : value);

const items = computed<DescriptionItem[]>(() => {
  const r = record.value;
  if (!r) return [];
  return [
    { key: "category", label: t("lifecycle.field.category"), value: category(r.category) },
    { key: "incident", label: t("lifecycle.field.incidentOn"), value: fmt.day(r.incident_on, "long") },
    { key: "issued", label: t("lifecycle.field.issued"), value: r.issued_by ? `${r.issued_by.name} · ${fmt.day(r.issued_on, "medium")}` : fmt.day(r.issued_on, "medium") },
    // A withdrawn record counts for nothing, so its "counts until" would only mislead.
    ...(r.status === "withdrawn" ? [] : [{ key: "expires", label: t("lifecycle.field.expiresOn"), value: r.expires_on ? fmt.day(r.expires_on, "long") : t("lifecycle.record.noExpiry"), hint: t("lifecycle.record.expiresHint") }]),
  ];
});

const live = computed(() => !!record.value && record.value.status !== "withdrawn");
const mayAct = computed(() => !!record.value?.can_edit && access.value.discipline && live.value);
/** A fine goes to payroll: only where payroll is on and the person may propose one. */
const mayFine = computed(() => mayAct.value && !record.value?.fine_id && company.enabled("payroll") && company.can(["payroll.propose", "payroll.manage"]));

const withdraw = useLifecycleMutation((cid, input: { id: number; reason: string }) => lifecycleApi.withdrawRecord(cid, input.id, input.reason));
async function runWithdraw(): Promise<void> {
  const r = record.value;
  if (!r) return;
  const answer = await confirm({
    title: t("lifecycle.record.withdrawTitle"),
    message: t("lifecycle.record.withdrawBody", { name: r.member.name }),
    tone: "danger",
    reason: "required",
    reasonLabel: t("lifecycle.record.withdrawReason"),
    confirmLabel: t("lifecycle.record.withdraw"),
    icon: Undo2,
    onConfirm: (reason) => withdraw.mutateAsync({ id: r.id, reason }),
  });
  if (answer) toast.success(t("lifecycle.record.withdrawn"));
}

// Propose a fine afterwards.
const fining = ref(false);
const amount = ref<Money | null>(null);
const fineError = ref<string | null>(null);
const fine = useLifecycleMutation((cid, input: { id: number; amount: Money }) => lifecycleApi.proposeFine(cid, input.id, input.amount));
function openFine(): void {
  amount.value = null;
  fineError.value = null;
  fining.value = true;
}
async function submitFine(): Promise<void> {
  const r = record.value;
  if (!r) return;
  if (moneySign(amount.value) !== 1) {
    fineError.value = t("lifecycle.form.amount");
    return;
  }
  try {
    await fine.mutateAsync({ id: r.id, amount: amount.value! });
    toast.success(t("lifecycle.record.fineProposed", { name: r.member.name }));
    fining.value = false;
  } catch {
    // The HTTP layer showed why (payroll off, a fine already proposed).
  }
}

const menu = computed<MenuEntry[]>(() => {
  if (!mayAct.value) return [];
  return [
    ...(mayFine.value ? [{ label: t("lifecycle.record.proposeFineButton"), icon: Banknote, onSelect: openFine }] : []),
    ...(mayFine.value ? [{ type: "separator" as const }] : []),
    { label: t("lifecycle.record.withdraw"), icon: Undo2, danger: true, onSelect: () => void runWithdraw() },
  ];
});
</script>

<template>
  <UiDrawer query-key="record" size="md" :title="record ? t(`lifecycle.kind.${record.kind}`) : t('lifecycle.record.one')">
    <template #header-actions>
      <DropdownMenu v-if="menu.length" :items="menu" align="end">
        <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </template>
    <div class="p-5">
      <div v-if="query.isPending.value && id" class="flex flex-col gap-4">
        <SkeletonBlock height="56px" />
        <SkeletonBlock v-for="n in 5" :key="n" height="16px" />
      </div>
      <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
      <div v-else-if="record && state" class="flex flex-col gap-5">
        <header class="flex items-start gap-3">
          <RouterLink :to="`/c/${company.currentId}/people/${record.member.id}`" class="shrink-0" :aria-label="record.member.name">
            <UserAvatar :name="record.member.name" :src="record.member.photo_url" :size="44" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${company.currentId}/people/${record.member.id}`" class="block truncate text-base font-semibold text-fg hover:text-primary hover:underline">{{ record.member.name }}</RouterLink>
            <p v-if="record.position" class="truncate text-sm text-muted">{{ record.position }}</p>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusPill :tone="KIND_TONES[record.kind]" size="sm" :label="t(`lifecycle.kind.${record.kind}`)" />
              <StatusPill :tone="STATE_TONES[state]" size="sm" variant="outline" :label="t(`lifecycle.status.${state}`)" />
            </div>
          </div>
        </header>

        <div v-if="record.status === 'withdrawn'" class="rounded-[10px] bg-surface-2 px-3.5 py-2.5" data-record-withdrawn>
          <p class="text-sm font-semibold text-fg">{{ t("lifecycle.record.withdrawnOn", { date: record.withdrawn_at ? fmt.day(record.withdrawn_at.slice(0, 10), "medium") : "—" }) }}</p>
          <p v-if="record.withdraw_reason" class="mt-0.5 whitespace-pre-line text-sm text-muted">{{ record.withdraw_reason }}</p>
        </div>

        <section class="flex flex-col gap-1.5">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.field.description") }}</h3>
          <p class="whitespace-pre-line rounded-[10px] bg-surface-2 px-3.5 py-3 text-base text-fg">{{ record.description }}</p>
        </section>

        <DescriptionList :items="items" :columns="2" />

        <!-- The fine proposed to payroll; its amount only for payroll.view -->
        <section v-if="record.fine_id" class="flex items-center gap-3 rounded-[12px] border border-line px-3.5 py-3" data-record-fine>
          <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-warning-soft text-warning" aria-hidden="true"><Banknote :size="18" /></span>
          <div v-if="record.fine" class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-fg">{{ t("lifecycle.record.fine") }}: <MoneyText :value="record.fine.amount" :currency="record.fine.currency" /></p>
            <p class="text-xs text-muted">{{ t("lifecycle.record.fineStatus", { status: fineStatus(record.fine.status) }) }}</p>
          </div>
          <div v-else class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-fg">{{ t("lifecycle.record.fine") }}</p>
            <p class="flex items-center gap-1 text-xs text-muted"><LockKeyhole :size="12" aria-hidden="true" />{{ t("lifecycle.record.fineHidden") }}</p>
          </div>
        </section>
        <UiButton v-else-if="mayFine" variant="secondary" class="w-fit" :icon="Banknote" @click="openFine">{{ t("lifecycle.record.proposeFineButton") }}</UiButton>

        <!-- Read and explained by the employee -->
        <section class="flex flex-col gap-2" data-record-response>
          <div :class="['flex items-center gap-2 text-sm', record.acknowledged_at ? 'text-success' : 'text-muted']">
            <CircleCheck v-if="record.acknowledged_at" :size="16" aria-hidden="true" />
            <Hourglass v-else :size="16" aria-hidden="true" />
            {{ record.acknowledged_at ? t("lifecycle.record.acknowledgedOn", { date: fmt.instant(record.acknowledged_at, "datetime") }) : record.read_at ? t("lifecycle.record.readNotConfirmed") : t("lifecycle.record.notAcknowledged") }}
          </div>
          <figure v-if="record.employee_response" class="rounded-[12px] border-l-4 border-[var(--c-info)] bg-info-soft/50 px-4 py-3">
            <figcaption class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-info">
              <MessageSquareQuote :size="14" aria-hidden="true" />{{ t("lifecycle.record.explanation") }}<template v-if="record.responded_at"> · {{ fmt.instant(record.responded_at, "short") }}</template>
            </figcaption>
            <blockquote class="whitespace-pre-line text-base text-fg">{{ record.employee_response }}</blockquote>
          </figure>
          <p v-else class="rounded-[10px] border border-dashed border-line-strong px-3.5 py-3 text-sm text-muted">{{ t("lifecycle.record.noExplanation") }}</p>
        </section>

        <!-- Evidence: opened on purpose (a link; the file isn't fetched with the drawer) -->
        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-semibold text-fg">{{ t("lifecycle.field.evidence") }}</h3>
          <UiButton v-if="record.evidence" :href="record.evidence" target="_blank" :icon="FileText" class="w-fit">{{ t("lifecycle.record.openEvidence") }}</UiButton>
          <p v-else class="text-sm text-subtle">{{ t("lifecycle.record.noEvidence") }}</p>
        </section>
      </div>
    </div>

    <UiDialog v-model:open="fining" size="sm" :title="t('lifecycle.record.proposeFineButton')" :description="t('lifecycle.record.proposeFineHint')">
      <FormField :label="t('lifecycle.field.fine')" :error="fineError" required>
        <MoneyInput v-model="amount" :currencies="[company.currency]" :invalid="!!fineError" />
      </FormField>
      <template #footer>
        <UiButton variant="ghost" @click="fining = false">{{ t("common.cancel") }}</UiButton>
        <UiButton variant="primary" :icon="Banknote" :loading="fine.isPending.value" @click="submitFine">{{ t("lifecycle.record.proposeFineButton") }}</UiButton>
      </template>
    </UiDialog>
  </UiDrawer>
</template>
