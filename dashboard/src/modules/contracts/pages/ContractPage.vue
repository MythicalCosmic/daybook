<script setup lang="ts">
/**
 * One contract: who with, what it costs and its term on one line (today, the notice deadline,
 * the end). What needs doing comes first (it ends soon: renew it; a renewal to decide: keep it
 * or give notice), then the details, what was paid under it (its recurring payment's bills and
 * other payments to the party while it was in force) with the next bill, the notes; on the side
 * the signed scan and annexes, its dates and the history.
 */
import { Ban, CalendarCheck2, CalendarClock, CalendarX2, CircleDot, FilePen, MoreHorizontal, Pencil, RefreshCw, Trash2, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import DescriptionList from "@/components/DescriptionList.vue";
import DropdownMenu from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import type { MenuEntry } from "@/components/menuTypes";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { contractsApi, useContract, useRefresh } from "../api";
import ContractActionDialog from "../components/ContractActionDialog.vue";
import ContractFormDialog from "../components/ContractFormDialog.vue";
import FilesPanel from "../components/FilesPanel.vue";
import TermBar from "../components/TermBar.vue";
import { daysUntil, KIND_ICONS, KIND_TILES, STATUS_TONES } from "../lib";
import type { DateKey } from "../types";

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const refresh = useRefresh();

const id = computed(() => Number(route.params.contractId) || 0);
const query = useContract(id);
const contract = computed(() => query.data.value ?? null);
const canManage = computed(() => Boolean(contract.value?.can.manage));
const inForce = computed(() => contract.value?.status === "active" || contract.value?.status === "ending");

const editing = ref(false);
const acting = ref<"renew" | "terminate" | null>(null);
const actionOpen = computed({ get: () => acting.value !== null, set: (value: boolean) => !value && (acting.value = null) });
const busy = ref<"keep" | "stop" | null>(null);

const menu = computed<MenuEntry[]>(() => {
  const row = contract.value;
  if (!row || !canManage.value) return [];
  const entries: MenuEntry[] = [];
  if (row.status !== "draft" && row.status !== "terminated") entries.push({ label: t("contracts.action.renew"), icon: CalendarCheck2, onSelect: () => (acting.value = "renew") });
  if (row.auto_renews && inForce.value) {
    if (!row.renewal_confirmed) entries.push({ label: t("contracts.action.keep"), icon: RefreshCw, onSelect: () => void decide("keep") });
    entries.push({ label: t("contracts.action.stop"), icon: CalendarX2, onSelect: () => void decide("stop") });
  }
  if (inForce.value) entries.push({ label: t("contracts.action.terminate"), icon: Ban, danger: true, onSelect: () => (acting.value = "terminate") });
  if (entries.length) entries.push({ type: "separator" });
  entries.push({ label: t("contracts.action.delete"), icon: Trash2, danger: true, onSelect: () => void remove() });
  return entries;
});

async function decide(answer: "keep" | "stop"): Promise<void> {
  const row = contract.value;
  if (!row) return;
  if (answer === "stop") {
    const ok = await confirm({
      title: t("contracts.action.stopTitle"),
      message: t("contracts.action.stopBody", { day: row.ends_on ? fmt.day(row.ends_on, "long") : "" }),
      confirmLabel: t("contracts.action.stop"),
      tone: "danger",
    });
    if (!ok) return;
  }
  busy.value = answer;
  try {
    const cid = company.currentId ?? 0;
    if (answer === "keep") await contractsApi.keepRenewing(cid, row.id);
    else await contractsApi.stopRenewing(cid, row.id);
    toast.success(answer === "keep" ? t("contracts.action.kept") : t("contracts.action.stopped"));
    refresh();
  } catch {
    // The HTTP layer shows why.
  } finally {
    busy.value = null;
  }
}

async function remove(): Promise<void> {
  const row = contract.value;
  if (!row) return;
  const answer = await confirm({
    title: t("contracts.action.deleteTitle", { name: row.title }),
    message: row.rule?.is_active ? t("contracts.action.deleteBodyRule") : t("contracts.action.deleteBody"),
    confirmLabel: t("contracts.action.delete"),
    tone: "danger",
    onConfirm: () => contractsApi.remove(company.currentId ?? 0, row.id),
  });
  if (answer) {
    toast.success(t("contracts.action.deleted"));
    refresh();
    void router.push({ name: "contracts.list" });
  }
}

/** What needs doing now, as one banner. */
const banner = computed(() => {
  const row = contract.value;
  if (!row) return null;
  if (row.attention === "notice" && row.notice_deadline && row.ends_on) {
    const n = daysUntil(row.notice_deadline, today.value);
    return {
      tone: "warning" as const,
      title: n === 0 ? t("contracts.banner.noticeToday") : t("contracts.banner.notice", { n, day: fmt.day(row.notice_deadline, "long") }, n),
      body: row.counterparty
        ? t("contracts.banner.noticeBodyParty", { day: fmt.day(row.ends_on, "long"), party: row.counterparty.name })
        : t("contracts.banner.noticeBody", { day: fmt.day(row.ends_on, "long") }),
      decide: true,
    };
  }
  if (row.attention === "ending" && row.ends_on) {
    const n = daysUntil(row.ends_on, today.value);
    return {
      tone: n <= 7 ? ("danger" as const) : ("warning" as const),
      title: n === 0 ? t("contracts.banner.endsToday") : t("contracts.banner.ends", { n, day: fmt.day(row.ends_on, "long") }, n),
      body: row.kind === "lease" ? t("contracts.banner.endsLease") : t("contracts.banner.endsBody"),
      renew: true,
    };
  }
  if (row.status === "ended" && row.ends_on) return { tone: "neutral" as const, title: t("contracts.banner.ended", { day: fmt.day(row.ends_on, "long") }), body: t("contracts.banner.endedBody"), renew: true };
  if (row.status === "terminated" && row.terminated_on)
    return { tone: "danger" as const, title: t("contracts.banner.terminated", { day: fmt.day(row.terminated_on, "long") }), body: row.termination_reason || undefined };
  if (row.status === "draft") return { tone: "info" as const, title: t("contracts.banner.draft"), body: t("contracts.banner.draftBody") };
  return null;
});

const details = computed(() => {
  const row = contract.value;
  if (!row) return [];
  const day = (value: string | null) => (value ? fmt.day(value, "long") : "—");
  const money = row.amount ? `${fmt.money(row.amount, row.currency, { decimals: "auto" })} ${t(`contracts.per.${row.period}`)}` : "—";
  return [
    { key: "kind", label: t("contracts.field.kind"), value: t(`contracts.kind.${row.kind}`) },
    { key: "counterparty", label: t("contracts.field.counterparty"), value: row.counterparty?.name ?? "—" },
    { key: "number", label: t("contracts.field.number"), value: row.number || "—", mono: Boolean(row.number), copy: Boolean(row.number) },
    { key: "branch", label: t("contracts.field.branch"), value: row.branch?.name ?? t("contracts.wholeCompany") },
    { key: "signed", label: t("contracts.field.signedOn"), value: day(row.signed_on) },
    { key: "starts", label: t("contracts.field.startsOn"), value: day(row.starts_on) },
    { key: "ends", label: row.auto_renews ? t("contracts.field.termEnds") : t("contracts.field.endsOn"), value: row.ends_on ? day(row.ends_on) : t("contracts.noEnd") },
    {
      key: "renewal",
      label: t("contracts.field.autoRenews"),
      value: row.auto_renews ? t("contracts.renewal.yes", { months: row.renewal_months, days: row.notice_days }) : t("contracts.renewal.no"),
    },
    { key: "money", label: t("contracts.field.amount"), value: money },
    { key: "payday", label: t("contracts.field.paymentDay"), value: row.payment_day ? t("contracts.paymentDay", { day: row.payment_day }) : "—" },
    { key: "responsible", label: t("contracts.field.responsible"), value: row.responsible?.name ?? "—" },
    { key: "renewed", label: t("contracts.field.lastRenewed"), value: day(row.last_renewed_on) },
  ].filter((item) => item.key !== "renewed" || row.last_renewed_on);
});

const DATE_ICONS: Record<DateKey, typeof CircleDot> = {
  signed: FilePen,
  starts: CircleDot,
  renewed: RefreshCw,
  notice: CalendarClock,
  renews: RefreshCw,
  ends: CalendarX2,
  terminated: Ban,
};

// The history in the reader's words: field names, kinds, statuses and days.
const auditLabels = computed(() => ({
  kind: t("contracts.field.kind"),
  title: t("contracts.field.title"),
  counterparty: t("contracts.field.counterparty"),
  number: t("contracts.field.number"),
  branch: t("contracts.field.branch"),
  signed_on: t("contracts.field.signedOn"),
  starts_on: t("contracts.field.startsOn"),
  ends_on: t("contracts.field.endsOn"),
  auto_renews: t("contracts.field.autoRenews"),
  renewal_months: t("contracts.field.renewalMonths"),
  notice_days: t("contracts.field.noticeDays"),
  amount: t("contracts.field.amount"),
  period: t("contracts.field.period"),
  currency: t("contracts.field.currency"),
  payment_day: t("contracts.field.paymentDay"),
  notes: t("contracts.field.notes"),
  status: t("contracts.field.status"),
  responsible: t("contracts.field.responsible"),
  in_forecast: t("contracts.field.inForecast"),
  label: t("contracts.field.label"),
  renewal_confirmed_for: t("contracts.audit.confirmed"),
  from: t("contracts.audit.from"),
  to: t("contracts.audit.to"),
  on: t("contracts.action.lastDay"),
  reason: t("contracts.action.reason"),
  auto: t("contracts.audit.auto"),
}));
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

function auditValue(field: string, value: unknown): string | null {
  if (typeof value === "boolean") return value ? t("contracts.audit.yes") : t("contracts.audit.no");
  if (typeof value !== "string") return null;
  if (ISO_DAY.test(value)) return fmt.day(value, "medium");
  if (field === "kind") return te(`contracts.kind.${value}`) ? t(`contracts.kind.${value}`) : te(`contracts.fileKind.${value}`) ? t(`contracts.fileKind.${value}`) : null;
  if ((field === "status" || field === "from" || field === "to") && te(`contracts.status.${value}`)) return t(`contracts.status.${value}`);
  if (field === "period" && te(`contracts.period.${value}`)) return t(`contracts.period.${value}`);
  return null;
}

const payments = computed(() => contract.value?.payments ?? null);
const nextBill = computed(() => payments.value?.next ?? null);
</script>

<template>
  <div>
    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <PageHeader :title="contract?.title ?? t('contracts.one.title')" :back="{ name: 'contracts.list' }" :back-label="t('contracts.title')">
        <template #actions>
          <UiButton v-if="canManage" variant="secondary" :icon="Pencil" data-testid="contract-edit" @click="editing = true">{{ t("contracts.action.edit") }}</UiButton>
          <DropdownMenu v-if="menu.length" :items="menu" width="250px">
            <template #trigger>
              <UiButton variant="secondary" :icon="MoreHorizontal" :aria-label="t('contracts.action.more')" data-testid="contract-menu">{{ t("contracts.action.more") }}</UiButton>
            </template>
          </DropdownMenu>
        </template>
      </PageHeader>

      <div v-if="query.isPending.value" class="grid gap-4">
        <SkeletonBlock height="160px" radius="14px" />
        <SkeletonBlock height="280px" radius="14px" />
      </div>

      <template v-else-if="contract">
        <section class="ui-card mb-4 flex flex-col gap-5 p-5" data-testid="contract-head">
          <div class="flex flex-wrap items-start gap-4">
            <span class="grid size-12 shrink-0 place-items-center rounded-[14px]" :class="KIND_TILES[contract.kind]">
              <component :is="KIND_ICONS[contract.kind]" :size="22" aria-hidden="true" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <StatusPill :tone="STATUS_TONES[contract.status]" :label="t(`contracts.status.${contract.status}`)" />
                <UiBadge>{{ t(`contracts.kind.${contract.kind}`) }}</UiBadge>
                <UiBadge v-if="contract.auto_renews && inForce" tone="info"><RefreshCw :size="12" class="mr-1 inline" aria-hidden="true" />{{ t("contracts.autoRenews") }}</UiBadge>
                <UiBadge v-if="contract.rule?.is_active" tone="success"><Wallet :size="12" class="mr-1 inline" aria-hidden="true" />{{ t("contracts.inForecast") }}</UiBadge>
              </div>
              <p class="mt-1.5 truncate text-sm text-muted">
                {{ [contract.counterparty?.name, contract.number ? `№ ${contract.number}` : "", contract.branch?.name ?? t("contracts.wholeCompany")].filter(Boolean).join(" · ") }}
              </p>
            </div>
            <div v-if="contract.amount" class="text-right">
              <p class="text-2xl font-semibold tabular-nums tracking-tight text-fg"><MoneyText :value="contract.amount" :currency="contract.currency" decimals="auto" /></p>
              <p class="text-xs text-muted">{{ t(`contracts.perLong.${contract.period}`) }}</p>
            </div>
          </div>
          <TermBar
            :starts-on="contract.term_starts_on"
            :renewed="contract.term_starts_on !== contract.starts_on"
            :ends-on="contract.ends_on"
            :today="today"
            :notice="contract.status === 'active' || contract.status === 'ending' ? contract.notice_deadline : null"
            :status="contract.status"
            :auto-renews="contract.auto_renews"
          />
        </section>

        <InlineAlert v-if="banner" class="mb-4" :tone="banner.tone" :title="banner.title" data-testid="contract-banner">
          {{ banner.body }}
          <template v-if="canManage && ('decide' in banner || 'renew' in banner)" #actions>
            <template v-if="'decide' in banner">
              <UiButton size="sm" variant="primary" :icon="RefreshCw" :loading="busy === 'keep'" data-testid="contract-keep" @click="decide('keep')">{{ t("contracts.action.keep") }}</UiButton>
              <UiButton size="sm" variant="secondary" :icon="CalendarX2" :loading="busy === 'stop'" @click="decide('stop')">{{ t("contracts.action.stop") }}</UiButton>
            </template>
            <template v-else>
              <UiButton size="sm" variant="primary" :icon="CalendarCheck2" @click="acting = 'renew'">{{ t("contracts.action.renew") }}</UiButton>
            </template>
          </template>
        </InlineAlert>

        <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div class="flex min-w-0 flex-col gap-4">
            <PageSection variant="card" :title="t('contracts.one.details')">
              <DescriptionList :items="details" :columns="2" />
            </PageSection>

            <PageSection variant="card" :title="t('contracts.payments.title')" :description="t('contracts.payments.description')" flush>
              <div v-if="!payments" class="px-4 pb-4 text-sm text-muted">{{ t("contracts.payments.financeOff") }}</div>
              <template v-else>
                <dl class="grid grid-cols-2 gap-px border-y border-line bg-line sm:grid-cols-4">
                  <div class="bg-surface px-4 py-3">
                    <dt class="text-xs text-muted">{{ t("contracts.payments.total") }}</dt>
                    <dd class="mt-0.5 font-semibold tabular-nums text-fg"><MoneyText :value="payments.total" :currency="payments.currency" compact /></dd>
                  </div>
                  <div class="bg-surface px-4 py-3">
                    <dt class="text-xs text-muted">{{ t("contracts.payments.thisYear") }}</dt>
                    <dd class="mt-0.5 font-semibold tabular-nums text-fg"><MoneyText :value="payments.this_year" :currency="payments.currency" compact /></dd>
                  </div>
                  <div class="bg-surface px-4 py-3">
                    <dt class="text-xs text-muted">{{ t("contracts.payments.last") }}</dt>
                    <dd class="mt-0.5 font-semibold tabular-nums text-fg">{{ payments.last_paid_on ? fmt.day(payments.last_paid_on, "medium") : "—" }}</dd>
                  </div>
                  <div class="bg-surface px-4 py-3">
                    <dt class="text-xs text-muted">{{ t("contracts.payments.next") }}</dt>
                    <dd class="mt-0.5 font-semibold tabular-nums" :class="nextBill?.due_on && nextBill.due_on < today ? 'text-danger' : 'text-fg'">
                      <template v-if="nextBill?.due_on">
                        {{ fmt.day(nextBill.due_on, "medium") }}
                        <span class="block text-xs font-normal text-muted"><MoneyText :value="nextBill.amount" :currency="nextBill.currency" decimals="auto" /></span>
                      </template>
                      <span v-else class="text-subtle">—</span>
                    </dd>
                  </div>
                </dl>
                <p v-if="contract.rule" class="flex items-center gap-1.5 px-4 pt-3 text-xs text-muted">
                  <Wallet :size="13" aria-hidden="true" />
                  {{ contract.rule.is_active ? t("contracts.payments.rule", { name: contract.rule.name, category: contract.rule.category.name }) : t("contracts.payments.ruleOff", { name: contract.rule.name }) }}
                </p>
                <ul v-if="payments.items.length" class="divide-y divide-line" data-testid="contract-payments">
                  <li v-for="row in payments.items" :key="row.id" class="flex items-center gap-3 px-4 py-2.5">
                    <span class="w-24 shrink-0 text-sm tabular-nums text-muted">{{ fmt.day(row.occurred_on, "medium") }}</span>
                    <span class="min-w-0 flex-1">
                      <span class="block truncate text-sm text-fg">{{ row.description || t("contracts.payments.noDescription") }}</span>
                      <span class="block truncate text-xs text-muted">{{ [row.account, row.by_rule ? t("contracts.payments.byRule") : ""].filter(Boolean).join(" · ") }}</span>
                    </span>
                    <span class="shrink-0 text-right text-sm font-semibold tabular-nums text-fg">
                      <MoneyText :value="row.amount" :currency="row.currency" decimals="auto" />
                      <span v-if="row.currency !== payments.currency" class="block text-xs font-normal text-muted"><MoneyText :value="row.base_amount" :currency="payments.currency" decimals="never" /></span>
                    </span>
                  </li>
                </ul>
                <p v-else class="px-4 py-5 text-sm text-muted">{{ t("contracts.payments.none") }}</p>
                <p v-if="payments.count > payments.items.length" class="border-t border-line px-4 py-2.5 text-xs text-muted">{{ t("contracts.payments.more", { n: payments.count - payments.items.length }, payments.count - payments.items.length) }}</p>
              </template>
            </PageSection>

            <PageSection v-if="contract.notes" variant="card" :title="t('contracts.field.notes')">
              <p class="whitespace-pre-line text-sm leading-relaxed text-fg">{{ contract.notes }}</p>
            </PageSection>
          </div>

          <aside class="flex min-w-0 flex-col gap-4">
            <FilesPanel :contract="contract" />

            <PageSection variant="card" :title="t('contracts.one.dates')" flush>
              <ol class="flex flex-col px-4 pb-3" data-testid="contract-dates">
                <li v-for="item in contract.dates" :key="item.key" class="relative flex items-center gap-3 py-2">
                  <span class="grid size-7 shrink-0 place-items-center rounded-full" :class="item.past ? 'bg-surface-2 text-subtle' : item.key === 'notice' ? 'bg-warning-soft text-warning' : 'bg-accent-soft text-accent-fg'">
                    <component :is="DATE_ICONS[item.key]" :size="14" aria-hidden="true" />
                  </span>
                  <span class="min-w-0 flex-1 text-sm" :class="item.past ? 'text-muted' : 'text-fg'">{{ t(`contracts.date.${item.key}`) }}</span>
                  <span class="shrink-0 text-right text-sm tabular-nums" :class="item.past ? 'text-muted' : 'font-medium text-fg'">
                    {{ fmt.day(item.day, "medium") }}
                    <span v-if="!item.past" class="block text-xs font-normal text-muted">{{ t("contracts.inDays", { n: daysUntil(item.day, today) }, daysUntil(item.day, today)) }}</span>
                  </span>
                </li>
              </ol>
            </PageSection>

            <PageSection variant="card" :title="t('contracts.one.history')">
              <AuditTrail target-type="businesscontract" :target-id="contract.id" :page-size="10" :field-labels="auditLabels" :format-value="auditValue" />
            </PageSection>
          </aside>
        </div>

        <ContractFormDialog v-model:open="editing" :contract="contract" />
        <ContractActionDialog v-if="acting" v-model:open="actionOpen" :contract="contract" :kind="acting" />
      </template>
    </template>
  </div>
</template>
