<script setup lang="ts">
/**
 * Pay distributors (plan §14.8 "Payables": open payables grouped by distributor and due date —
 * overdue, this week, later — select several and pay from one account): every distributor with
 * what it is owed and the overdue part, each open debt with its bucket and what is left, a tick to
 * pick it and the amount to pay (all that is left unless changed), and "Pay selected" at the
 * bottom. Goods-receipt payables are marked "Bank transfer". `?select=44` (from the payments
 * calendar) ticks that debt; one that isn't a distributor's payable opens in the debt drawer.
 */
import { ArrowUpRight, HandCoins, Landmark, Search, Truck, Wallet } from "@lucide/vue";
import { computed, nextTick, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import BulkActionBar from "@/components/BulkActionBar.vue";
import CheckBox from "@/components/CheckBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import MoneyInput from "@/components/MoneyInput.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import TextInput from "@/components/TextInput.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { matchOption } from "@/components/options";
import { dec, toMoney } from "@/lib/decimal";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { usePayables } from "../api";
import DebtDrawer from "../components/DebtDrawer.vue";
import PayPayablesDialog, { type PayablePick } from "../components/PayPayablesDialog.vue";
import { BUCKET_TONES, bucketTotals, dayStyle, isZeroMoney, validPayment } from "../lib";
import type { PayableBucket, PayableDebt, PayableGroup } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const cid = useCompanyId();
const canPay = computed(() => company.can("finance.record"));

const query = usePayables();
const data = computed(() => query.data.value ?? null);
const bucket = useRouteState<"all" | PayableBucket>("bucket", rs.enum(["all", "overdue", "week", "later"] as const, "all"));
const search = useRouteState("q", rs.string(""));

/** The groups and debts the filters leave, a distributor without any left out. */
const groups = computed<PayableGroup[]>(() => {
  const list = data.value?.groups ?? [];
  return list
    .filter((group) => !search.value || matchOption({ value: group.counterparty.id, label: group.counterparty.name }, search.value))
    .map((group) => ({ ...group, debts: bucket.value === "all" ? group.debts : group.debts.filter((debt) => debt.bucket === bucket.value) }))
    .filter((group) => group.debts.length);
});
const totals = computed(() => data.value?.totals ?? null);

const kpis = computed(() => {
  const all = totals.value;
  return [
    { id: "overdue", label: t("finance.payables.bucket.overdue"), value: all?.overdue ?? null, format: "money" as const, compact: true, icon: HandCoins },
    { id: "week", label: t("finance.payables.bucket.week"), value: all?.week ?? null, format: "money" as const, compact: true, icon: Wallet },
    { id: "later", label: t("finance.payables.bucket.later"), value: all?.later ?? null, format: "money" as const, compact: true, icon: Truck },
    { id: "all", label: t("finance.payables.bucket.all"), value: all?.all ?? null, format: "money" as const, compact: true, icon: Landmark },
  ];
});

// Selection ----------------------------------------------------------------------------------

/** Ticked debts and the amount to pay on each (what is left until someone types another). */
const picked = reactive<Record<number, string | null>>({});
const debtsById = computed(() => new Map((data.value?.groups ?? []).flatMap((group) => group.debts.map((debt) => [debt.id, debt] as const))));
// `in`, not hasOwnProperty: only `in` is tracked on a reactive object, so a tick re-renders.
const isPicked = (debt: PayableDebt) => debt.id in picked;

function toggle(debt: PayableDebt, on: boolean): void {
  if (on) picked[debt.id] = debt.outstanding;
  else delete picked[debt.id];
}
function groupState(group: PayableGroup): boolean | "some" {
  const count = group.debts.filter(isPicked).length;
  return count === 0 ? false : count === group.debts.length ? true : "some";
}
function toggleGroup(group: PayableGroup, on: boolean): void {
  for (const debt of group.debts) toggle(debt, on);
}
function clear(): void {
  for (const key of Object.keys(picked)) delete picked[Number(key)];
}

// A debt that was paid or left the list in the meantime drops out of the selection.
watch(debtsById, (byId) => {
  for (const key of Object.keys(picked)) if (!byId.has(Number(key))) delete picked[Number(key)];
});

const picks = computed<PayablePick[]>(() =>
  Object.entries(picked)
    .map(([id, amount]) => ({ debt: debtsById.value.get(Number(id)), amount: amount ?? "" }))
    .filter((pick): pick is PayablePick => !!pick.debt),
);
const invalid = computed(() => picks.value.filter((pick) => !validPayment(pick.amount, pick.debt.outstanding)).map((pick) => pick.debt.id));
const pickedTotal = computed(() => {
  // Shown in the base currency; a dollar debt counts at its share of the base amount left.
  let sum = dec(0);
  for (const pick of picks.value) {
    const { debt } = pick;
    if (debt.currency === company.currency) sum = sum.plus(dec(pick.amount));
    else if (!dec(debt.outstanding).isZero()) sum = sum.plus(dec(debt.base_outstanding).times(dec(pick.amount)).div(dec(debt.outstanding)));
  }
  return toMoney(sum);
});
const barLabel = computed(() => t("finance.payables.selected", { n: picks.value.length, amount: fmt.money(pickedTotal.value, undefined, { compact: true }) }, picks.value.length));

const payOpen = ref(false);
function startPay(): void {
  if (invalid.value.length || !picks.value.length) return;
  payOpen.value = true;
}
function onPaid(): void {
  clear();
}

// `?select=` from the calendar: tick it and bring it into view, or open a debt that isn't here.
const select = useRouteState("select", rs.optionalNumber());
watch(
  [select, data],
  async ([id, loaded]) => {
    if (!id || !loaded) return;
    const debt = debtsById.value.get(id);
    if (!debt) {
      await router.replace({ query: { ...route.query, select: undefined, debt: String(id) } });
      return;
    }
    select.value = null;
    bucket.value = "all";
    search.value = "";
    if (canPay.value) toggle(debt, true);
    await nextTick();
    const row = document.querySelector<HTMLElement>(`[data-debt="${id}"]`);
    if (typeof row?.scrollIntoView === "function") row.scrollIntoView({ block: "center", behavior: "smooth" });
  },
  { immediate: true },
);

function openDebt(debt: PayableDebt): void {
  void router.push({ query: { ...route.query, debt: String(debt.id) } });
}
const buckets = computed(() =>
  (["all", "overdue", "week", "later"] as const).map((value) => ({
    value,
    label: t(`finance.payables.bucket.${value}`),
    count: value === "all" ? undefined : (data.value?.groups ?? []).reduce((n, group) => n + group.debts.filter((debt) => debt.bucket === value).length, 0) || undefined,
  })),
);
const groupBuckets = (group: PayableGroup) => bucketTotals(group.debts);
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.payables')" :description="t('finance.payables.description')" />

    <ErrorState v-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :loading="query.isPending.value" :columns="4" phone="grid" />

      <div class="flex flex-wrap items-center gap-2">
        <SegmentedControl v-model="bucket" size="sm" :options="buckets" :aria-label="t('finance.payables.filter')" />
        <span class="flex-1" />
        <TextInput v-model="search" size="sm" :icon="Search" clearable class="w-full sm:w-64" :placeholder="t('finance.payables.search')" :aria-label="t('finance.payables.search')" />
      </div>

      <div v-if="query.isPending.value" class="flex flex-col gap-3">
        <SkeletonBlock v-for="n in 3" :key="n" height="120px" radius="12px" />
      </div>
      <div v-else-if="data && !data.groups.length" class="ui-card">
        <EmptyState :icon="Truck" tone="success" :title="t('finance.payables.emptyTitle')" :description="t('finance.payables.emptyBody')" />
      </div>
      <div v-else-if="data && !groups.length" class="ui-card">
        <EmptyState size="sm" :icon="Search" :title="t('finance.tx.noMatch')" :description="t('finance.payables.noMatchBody')">
          <UiButton
            size="sm"
            variant="secondary"
            @click="
              bucket = 'all';
              search = '';
            "
          >
            {{ t("finance.payables.showAll") }}
          </UiButton>
        </EmptyState>
      </div>

      <section v-for="group in groups" :key="group.counterparty.id" class="ui-card overflow-hidden" :aria-label="group.counterparty.name" :data-group="group.counterparty.id">
        <header class="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <CheckBox
            v-if="canPay"
            :model-value="groupState(group) === true"
            :indeterminate="groupState(group) === 'some'"
            :aria-label="t('finance.payables.selectGroup', { name: group.counterparty.name })"
            @update:model-value="(on) => toggleGroup(group, on)"
          />
          <UserAvatar :name="group.counterparty.name" :size="32" shape="rounded" />
          <div class="min-w-0 flex-1">
            <RouterLink :to="`/c/${cid}/finance/counterparties/${group.counterparty.id}`" class="group inline-flex max-w-full items-center gap-1 text-base font-semibold text-fg hover:underline">
              <span class="truncate">{{ group.counterparty.name }}</span><ArrowUpRight :size="14" class="shrink-0 text-subtle opacity-0 group-hover:opacity-100" aria-hidden="true" />
            </RouterLink>
            <p class="flex flex-wrap gap-x-3 text-xs text-muted">
              <span>{{ t("finance.overview.debtCount", { n: group.debts.length }, group.debts.length) }}</span>
              <span v-if="!isZeroMoney(groupBuckets(group).overdue)" class="font-semibold text-danger">{{ t("finance.overview.overdue", { amount: fmt.money(groupBuckets(group).overdue, undefined, { compact: true }) }) }}</span>
              <span v-if="!isZeroMoney(groupBuckets(group).week)" class="text-warning">{{ t("finance.payables.thisWeek", { amount: fmt.money(groupBuckets(group).week, undefined, { compact: true }) }) }}</span>
            </p>
          </div>
          <div class="text-right">
            <p class="text-lg font-semibold tabular-nums text-fg"><MoneyText :value="groupBuckets(group).all" decimals="never" /></p>
          </div>
        </header>
        <ul class="flex flex-col divide-y divide-line">
          <li v-for="debt in group.debts" :key="debt.id" :class="['flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5', isPicked(debt) && 'bg-accent-soft/30']" :data-debt="debt.id">
            <CheckBox
              v-if="canPay"
              :model-value="isPicked(debt)"
              :aria-label="t('finance.payables.selectDebt', { name: debt.description || group.counterparty.name })"
              @update:model-value="(on) => toggle(debt, on)"
            />
            <button type="button" class="min-w-0 flex-1 basis-48 text-left" @click="openDebt(debt)">
              <p class="truncate text-sm font-medium text-fg hover:underline" :title="debt.description || t(`finance.debtKind.${debt.kind}`)">{{ debt.description || t(`finance.debtKind.${debt.kind}`) }}</p>
              <p class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
                <span>{{ t("finance.payables.issuedOn", { date: fmt.day(debt.issued_on, dayStyle(debt.issued_on)) }) }}</span>
                <span v-if="debt.due_on" :class="debt.bucket === 'overdue' && 'font-semibold text-danger'">
                  {{ t("finance.payables.dueOn", { date: fmt.day(debt.due_on, dayStyle(debt.due_on)) }) }}<template v-if="debt.days_overdue"> · {{ t("finance.debts.late", { n: debt.days_overdue }, debt.days_overdue) }}</template>
                </span>
              </p>
            </button>
            <div class="flex shrink-0 items-center gap-1.5">
              <StatusPill :tone="BUCKET_TONES[debt.bucket]" size="sm" :label="t(`finance.payables.bucketShort.${debt.bucket}`)" />
              <StatusPill v-if="debt.bank_only" tone="info" size="sm" variant="outline" :icon="Landmark" :label="t('finance.payables.bankOnly')" :title="t('finance.payables.bankOnlyHint')" />
            </div>
            <div class="flex shrink-0 items-center gap-2 max-sm:w-full max-sm:justify-end">
              <span class="text-sm font-semibold tabular-nums text-fg" :title="t('finance.debts.left')"><MoneyText :value="debt.outstanding" :currency="debt.currency" decimals="never" /></span>
              <MoneyInput
                v-if="isPicked(debt)"
                :model-value="picked[debt.id] ?? null"
                :currencies="[debt.currency]"
                size="sm"
                class="w-40"
                :invalid="invalid.includes(debt.id)"
                :aria-label="t('finance.payables.amountFor', { name: debt.description || group.counterparty.name })"
                @update:model-value="(value) => (picked[debt.id] = value)"
              />
            </div>
            <p v-if="isPicked(debt) && invalid.includes(debt.id)" class="w-full text-right text-xs text-danger">{{ t("finance.payables.amountError", { amount: fmt.money(debt.outstanding, debt.currency) }) }}</p>
          </li>
        </ul>
      </section>
    </div>

    <!-- Room under the last card while the bar floats over the bottom of the page. -->
    <div v-if="picks.length" class="h-16" aria-hidden="true" />
    <BulkActionBar v-if="canPay" :count="picks.length" :label="barLabel" @clear="clear">
      <UiButton size="sm" variant="ghost" :icon="Wallet" :disabled="!!invalid.length" data-pay-selected @click="startPay">{{ t("finance.payables.paySelected") }}</UiButton>
    </BulkActionBar>

    <PayPayablesDialog v-if="payOpen" v-model:open="payOpen" :picks="picks" @paid="onPaid" />
    <DebtDrawer />
  </div>
</template>
