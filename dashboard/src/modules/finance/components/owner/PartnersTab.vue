<script setup lang="ts">
/**
 * Partners and dividends: who owns how much (one bar of the shares, each partner with their part),
 * each partner's part of a period's net profit with what they were paid for it, and the dividend
 * rounds with their lines: pay, change a draft, cancel, take a payment back.
 */
import { Ban, Handshake, MoreHorizontal, Pencil, Plus, Undo2, UsersRound, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import type { MenuEntry } from "@/components/menuTypes";
import MoneyText from "@/components/MoneyText.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";

import { lastQuarter, ownerMoneyApi, useDividends, useOwnerMoneyWrite, usePartners, useProfitShare, type Dividend, type DividendStatus, type OwnerMoney } from "../../ownerMoney";
import DividendDialog from "./DividendDialog.vue";
import PartnersDialog from "./PartnersDialog.vue";
import PayDividendDialog from "./PayDividendDialog.vue";

const props = defineProps<{ data: OwnerMoney; canWrite: boolean }>();

const { t } = useI18n();
const fmt = useFormat();
const confirm = useConfirm();
const partners = usePartners();
const dividends = useDividends();
const COLORS = ["var(--c-chart-1)", "var(--c-chart-3)", "var(--c-chart-2)", "var(--c-chart-4)", "var(--c-chart-5)", "var(--c-chart-6)"];
const TONES: Record<DividendStatus, "neutral" | "warning" | "success" | "danger"> = { draft: "neutral", partly_paid: "warning", paid: "success", cancelled: "danger" };

const current = computed(() => partners.data.value?.current ?? []);
const firstDay = computed(() => `${props.data.today.slice(0, 4)}-01-01`);

type Span = "year" | "quarter" | "lastQuarter";
const span = ref<Span>("year");
const range = computed(() => {
  const today = props.data.today;
  if (span.value === "lastQuarter") return lastQuarter(today);
  if (span.value === "quarter") {
    const month = Number(today.slice(5, 7));
    const start = String(3 * Math.floor((month - 1) / 3) + 1).padStart(2, "0");
    return { from: `${today.slice(0, 4)}-${start}-01`, to: today };
  }
  return { from: `${today.slice(0, 4)}-01-01`, to: today };
});
const share = useProfitShare(range);

const editingPartners = ref(false);
const newDividend = ref(false);
const editing = ref<Dividend | null>(null);
const editOpen = computed({
  get: () => editing.value !== null,
  set: (value: boolean) => {
    if (!value) editing.value = null;
  },
});
const paying = ref<Dividend | null>(null);
const payOpen = computed({
  get: () => paying.value !== null,
  set: (value: boolean) => {
    if (!value) paying.value = null;
  },
});

const cancel = useOwnerMoneyWrite((cid: number, input: { id: number; reason: string }) => ownerMoneyApi.cancelDividend(cid, input.id, input.reason));
const undo = useOwnerMoneyWrite((cid: number, input: { id: number; line: number; reason: string }) => ownerMoneyApi.undoLine(cid, input.id, input.line, input.reason));

function menu(row: Dividend): MenuEntry[] {
  if (!props.canWrite) return [];
  const items: MenuEntry[] = [];
  if (row.status === "draft") {
    items.push({ label: t("finance.dividends.edit"), icon: Pencil, onSelect: () => (editing.value = row) });
    items.push({ label: t("finance.dividends.cancel"), icon: Ban, danger: true, onSelect: () => void cancelRound(row) });
  }
  return items;
}
async function cancelRound(row: Dividend): Promise<void> {
  const answer = await confirm({ title: t("finance.dividends.cancelTitle"), message: t("finance.dividends.cancelBody"), tone: "danger", reason: "required", confirmLabel: t("finance.dividends.cancel") });
  if (!answer) return;
  await cancel.mutateAsync({ id: row.id, reason: answer.reason });
  toast.success(t("finance.dividends.cancelled"));
}
async function undoLine(row: Dividend, line: Dividend["lines"][number]): Promise<void> {
  const answer = await confirm({
    title: t("finance.dividends.undoTitle", { name: line.partner.name }),
    message: t("finance.dividends.undoBody"),
    tone: "danger",
    reason: "required",
    confirmLabel: t("finance.dividends.undo"),
  });
  if (!answer) return;
  await undo.mutateAsync({ id: row.id, line: line.id, reason: answer.reason });
  toast.success(t("finance.dividends.undone"));
}
function partnerColor(index: number): string {
  return COLORS[index % COLORS.length]!;
}
</script>

<template>
  <div class="grid grid-cols-1 gap-4 xl:grid-cols-5">
    <section class="ui-card flex flex-col p-4 sm:p-5 xl:col-span-2" :aria-label="t('finance.partners.title')" data-partners>
      <header class="mb-3 flex items-center gap-2">
        <Handshake :size="16" class="text-subtle" aria-hidden="true" />
        <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.partners.title") }}</h3>
        <UiButton v-if="canWrite && current.length" size="sm" variant="ghost" :icon="Pencil" data-edit-partners @click="editingPartners = true">{{ t("finance.partners.change") }}</UiButton>
      </header>
      <ErrorState v-if="partners.isError.value" :error="partners.error.value" :retry="() => partners.refetch()" />
      <div v-else-if="partners.isPending.value" class="flex flex-col gap-2"><SkeletonBlock height="12px" /><SkeletonBlock v-for="n in 2" :key="n" height="44px" /></div>
      <EmptyState v-else-if="!current.length" size="md" :icon="UsersRound" :title="t('finance.partners.emptyTitle')" :description="t('finance.partners.emptyBody')">
        <UiButton v-if="canWrite" variant="primary" :icon="Plus" data-add-partners @click="editingPartners = true">{{ t("finance.partners.add") }}</UiButton>
      </EmptyState>
      <template v-else>
        <div class="flex h-3 w-full overflow-hidden rounded-full bg-surface-2" role="img" :aria-label="t('finance.partners.sharesLabel')">
          <span v-for="(row, index) in current" :key="row.id" class="h-full first:rounded-l-full last:rounded-r-full" :style="{ width: `${row.share}%`, background: partnerColor(index) }" />
        </div>
        <ul class="mt-3 flex flex-col">
          <li v-for="(row, index) in current" :key="row.id" class="flex items-center gap-3 py-2" :data-partner="row.id">
            <span class="grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold text-white" :style="{ background: partnerColor(index) }" aria-hidden="true">{{ row.name.slice(0, 1) }}</span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-semibold text-fg">{{ row.name }}</p>
              <p class="text-xs text-muted">{{ row.member ? t("finance.partners.member") : t("finance.partners.outside") }}</p>
            </div>
            <span class="text-lg font-semibold tabular-nums text-fg">{{ fmt.number(row.share, 2) }}%</span>
          </li>
        </ul>
        <p v-if="partners.data.value?.since" class="mt-2 border-t border-line pt-2.5 text-xs text-muted">{{ t("finance.partners.since", { date: fmt.day(partners.data.value.since, "medium") }) }}</p>
      </template>
    </section>

    <section class="ui-card flex flex-col p-4 sm:p-5 xl:col-span-3" :aria-label="t('finance.partners.profitTitle')" data-profit-share>
      <header class="mb-3 flex flex-wrap items-center gap-2">
        <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.partners.profitTitle") }}</h3>
        <SegmentedControl
          v-model="span"
          size="sm"
          :options="[
            { value: 'year', label: t('finance.dividends.thisYear') },
            { value: 'quarter', label: t('finance.partners.thisQuarter') },
            { value: 'lastQuarter', label: t('finance.dividends.lastQuarter') },
          ]"
        />
      </header>
      <div v-if="share.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 3" :key="n" height="36px" /></div>
      <EmptyState v-else-if="share.data.value && !share.data.value.partners.length" size="sm" tone="neutral" :title="t('finance.partners.profitEmpty')" />
      <template v-else-if="share.data.value">
        <p class="mb-2 text-sm text-muted">
          {{ t("finance.partners.periodProfit") }}
          <span class="font-semibold tabular-nums" :class="Number(share.data.value.profit) < 0 ? 'text-danger' : 'text-fg'"><MoneyText :value="share.data.value.profit" /></span>
        </p>
        <div class="-mx-1 overflow-x-auto">
          <table class="w-full min-w-[460px] text-sm">
            <thead>
              <tr class="text-left text-xs text-muted">
                <th class="px-1 py-1.5 font-medium">{{ t("finance.partners.partner") }}</th>
                <th class="px-1 py-1.5 text-right font-medium">{{ t("finance.partners.share") }}</th>
                <th class="px-1 py-1.5 text-right font-medium">{{ t("finance.partners.profitPart") }}</th>
                <th class="px-1 py-1.5 text-right font-medium">{{ t("finance.partners.paidOut") }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="row in share.data.value.partners" :key="row.key">
                <td class="truncate px-1 py-2 font-medium text-fg">{{ row.name }}</td>
                <td class="px-1 py-2 text-right tabular-nums text-muted">{{ fmt.number(row.share, 2) }}%</td>
                <td class="px-1 py-2 text-right font-semibold tabular-nums" :class="Number(row.profit) < 0 ? 'text-danger' : 'text-fg'"><MoneyText :value="row.profit" compact /></td>
                <td class="px-1 py-2 text-right tabular-nums text-fg">
                  <MoneyText :value="row.dividends_paid" compact />
                  <span v-if="Number(row.dividends_due) > 0" class="block text-xs text-warning">{{ t("finance.partners.due", { amount: fmt.money(row.dividends_due, undefined, { compact: true }) }) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="Number(share.data.value.unassigned_share) > 0" class="mt-2 text-xs text-warning">{{ t("finance.partners.unassigned", { n: fmt.number(share.data.value.unassigned_share, 2) }) }}</p>
      </template>
    </section>

    <section class="ui-card flex flex-col p-4 sm:p-5 xl:col-span-5" :aria-label="t('finance.dividends.title')" data-dividends>
      <header class="mb-3 flex items-center gap-2">
        <Wallet :size="16" class="text-subtle" aria-hidden="true" />
        <h3 class="flex-1 text-sm font-semibold text-fg">{{ t("finance.dividends.title") }}</h3>
        <UiButton v-if="canWrite && current.length" size="sm" variant="primary" :icon="Plus" data-new-dividend @click="newDividend = true">{{ t("finance.dividends.new") }}</UiButton>
      </header>
      <div v-if="dividends.isPending.value" class="flex flex-col gap-2"><SkeletonBlock v-for="n in 2" :key="n" height="72px" /></div>
      <EmptyState
        v-else-if="!(dividends.data.value ?? []).length"
        size="sm"
        tone="neutral"
        :icon="Wallet"
        :title="t('finance.dividends.emptyTitle')"
        :description="current.length ? t('finance.dividends.emptyBody') : t('finance.dividends.emptyNoPartners')"
      />
      <ul v-else class="flex flex-col gap-3">
        <li v-for="row in dividends.data.value" :key="row.id" class="rounded-[12px] border border-line p-3 sm:p-4" :data-dividend="row.id">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p class="min-w-0 flex-1 text-sm font-semibold text-fg">
              {{ fmt.day(row.period_start, "medium") }} – {{ fmt.day(row.period_end, "medium") }}
              <span v-if="row.note" class="ms-1 font-normal text-muted">· {{ row.note }}</span>
            </p>
            <StatusPill :tone="TONES[row.status]" :label="t(`finance.dividends.status.${row.status}`)" size="sm" />
            <span class="text-md font-semibold tabular-nums text-fg"><MoneyText :value="row.amount" /></span>
            <UiButton v-if="canWrite && (row.status === 'draft' || row.status === 'partly_paid')" size="sm" variant="secondary" :icon="Wallet" data-pay-dividend @click="paying = row">{{ t("finance.dividends.pay") }}</UiButton>
            <DropdownMenu v-if="menu(row).length" :items="menu(row)" width="220px">
              <template #trigger>
                <IconButton :icon="MoreHorizontal" :label="t('finance.dividends.actions')" size="sm" />
              </template>
            </DropdownMenu>
          </div>
          <p v-if="row.profit !== null" class="mt-0.5 text-xs text-muted">{{ t("finance.dividends.profitWas", { amount: fmt.money(row.profit, undefined, { compact: true }) }) }}</p>
          <ul class="mt-2 grid gap-1.5 sm:grid-cols-2">
            <li v-for="line in row.lines" :key="line.id" class="group flex items-center gap-2 rounded-[8px] bg-surface-2/60 px-2.5 py-1.5 text-sm dark:bg-surface-3/40">
              <span class="min-w-0 flex-1 truncate text-fg">{{ line.partner.name }} <span class="text-xs text-muted">· {{ fmt.number(line.share, 2) }}%</span></span>
              <span class="font-semibold tabular-nums text-fg"><MoneyText :value="line.amount" compact /></span>
              <UiBadge v-if="line.paid" size="sm" tone="success">{{ t("finance.dividends.linePaid", { date: fmt.day(line.paid_on!, "short") }) }}</UiBadge>
              <UiBadge v-else-if="row.status !== 'cancelled'" size="sm" tone="warning">{{ t("finance.dividends.lineDue") }}</UiBadge>
              <IconButton v-if="canWrite && line.paid" :icon="Undo2" :label="t('finance.dividends.undo')" size="sm" class="sm:opacity-0 sm:group-hover:opacity-100" @click="undoLine(row, line)" />
            </li>
          </ul>
        </li>
      </ul>
    </section>

    <PartnersDialog v-if="partners.data.value" v-model:open="editingPartners" :partners="partners.data.value" :today="data.today" :first-day="firstDay" />
    <DividendDialog v-model:open="newDividend" :today="data.today" />
    <DividendDialog v-model:open="editOpen" :today="data.today" :dividend="editing" />
    <PayDividendDialog v-if="paying" v-model:open="payOpen" :dividend="paying" :accounts="data.accounts" :today="data.today" />
  </div>
</template>
