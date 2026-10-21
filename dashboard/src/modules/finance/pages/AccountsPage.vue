<script setup lang="ts">
/**
 * Where the money is (plan §6.2 "Accounts as grouped cards with sparklines"): cash desks and safes,
 * banks and cards, e-wallets and terminals, money people hold; the total in so‘m at today's rate
 * with each currency apart, and the rate in use. `?setup=opening` (from "Get started") explains
 * opening balances and puts a button on every card.
 */
import { ArrowLeftRight, BookOpenCheck, CircleAlert, Plus, Wallet } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import MoneyText from "@/components/MoneyText.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBanner from "@/components/UiBanner.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useAccounts, useRefresh } from "../api";
import AccountCard from "../components/AccountCard.vue";
import AccountFormDialog from "../components/AccountFormDialog.vue";
import { ACCOUNT_GROUPS } from "../lib";
import { openQuickAdd } from "../quickAdd";
import type { Account } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();

const showArchived = useRouteState("archived", rs.boolean(false));
const setup = useRouteState("setup", rs.string(""));
const accounts = useAccounts(showArchived);
const data = computed(() => accounts.data.value);
const skeleton = useDelayedPending(computed(() => accounts.isPending.value));
const canManage = computed(() => company.can("finance.manage"));
const canRecord = computed(() => company.can("finance.record"));

const groups = computed(() =>
  ACCOUNT_GROUPS.map((group) => {
    const list = (data.value?.accounts ?? []).filter((account) => group.kinds.includes(account.kind));
    return { ...group, active: list.filter((a) => a.is_active), archived: list.filter((a) => !a.is_active) };
  }).filter((group) => group.active.length || group.archived.length),
);
const archivedCount = computed(() => (data.value?.accounts ?? []).filter((a) => !a.is_active).length);

const formOpen = ref(false);
const editing = ref<Account | null>(null);

function create(): void {
  editing.value = null;
  formOpen.value = true;
}

function edit(account: Account): void {
  editing.value = account;
  formOpen.value = true;
}

async function archive(account: Account): Promise<void> {
  const answer = await confirm({
    title: t("finance.accounts.archiveTitle", { name: account.name }),
    message: t("finance.accounts.archiveBody"),
    confirmLabel: t("finance.accounts.archive"),
    onConfirm: () => financeApi.archiveAccount(company.currentId ?? 0, account.id),
  });
  if (answer) {
    toast.success(t("finance.accounts.archived", { name: account.name }));
    refresh();
  }
}

async function reopen(account: Account): Promise<void> {
  await financeApi.reopenAccount(company.currentId ?? 0, account.id);
  toast.success(t("finance.accounts.reopened", { name: account.name }));
  refresh();
}
</script>

<template>
  <div>
    <PageHeader :title="t('finance.nav.accounts')" :description="t('finance.accounts.description')">
      <template #actions>
        <UiButton v-if="canRecord" variant="secondary" :icon="ArrowLeftRight" @click="openQuickAdd('transfer')">{{ t("finance.cmd.transferShort") }}</UiButton>
        <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="create">{{ t("finance.accounts.new") }}</UiButton>
      </template>
    </PageHeader>

    <UiBanner v-if="setup === 'opening'" tone="brand" class="mb-4" :icon="BookOpenCheck" :title="t('finance.accounts.setupTitle')" :message="t('finance.accounts.setupBody')" dismissible @dismiss="setup = ''" />

    <ErrorState v-if="accounts.isError.value" :error="accounts.error.value" :retry="() => accounts.refetch()" />

    <template v-else>
      <section class="ui-card mb-5 flex flex-wrap items-center gap-x-8 gap-y-3 px-5 py-4" :aria-label="t('finance.accounts.total')">
        <div class="min-w-0">
          <p class="text-sm font-medium text-muted">{{ t("finance.accounts.total") }}</p>
          <SkeletonBlock v-if="skeleton" class="mt-1" width="220px" height="32px" />
          <p v-else-if="data" class="text-2xl font-semibold tabular-nums text-fg"><MoneyText :value="data.totals.base" decimals="never" /></p>
        </div>
        <div v-if="data" class="flex flex-wrap gap-2">
          <span v-for="row in data.totals.by_currency" :key="row.currency" class="inline-flex items-baseline gap-1.5 rounded-[10px] bg-surface-2 px-3 py-1.5">
            <span class="text-base font-semibold tabular-nums text-fg"><MoneyText :value="row.amount" :currency="row.currency" :decimals="row.currency === 'USD' ? 'always' : 'never'" /></span>
          </span>
        </div>
        <p v-if="data?.rate.rate" class="flex items-center gap-1.5 text-sm text-muted sm:ml-auto">
          <CircleAlert v-if="data.rate.stale" :size="14" class="text-warning" />
          {{ t("finance.overview.rateLine", { rate: fmt.number(data.rate.rate, 2) }) }}
          <span v-if="data.rate.stale" class="font-medium text-warning">· {{ t("finance.rates.staleShort") }}</span>
        </p>
      </section>

      <div v-if="skeleton" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <SkeletonBlock v-for="n in 6" :key="n" height="132px" radius="12px" />
      </div>

      <div v-else-if="data && !groups.length" class="ui-card">
        <EmptyState :icon="Wallet" :title="t('finance.accounts.emptyTitle')" :description="t('finance.accounts.emptyBody')">
          <UiButton v-if="canManage" variant="primary" :icon="Plus" @click="create">{{ t("finance.accounts.new") }}</UiButton>
        </EmptyState>
      </div>

      <div v-else class="flex flex-col gap-6">
        <section v-for="group in groups" :key="group.id" :aria-labelledby="`group-${group.id}`">
          <h2 :id="`group-${group.id}`" class="mb-2.5 flex items-center gap-2 text-sm font-semibold text-muted">
            {{ t(`finance.accounts.group.${group.id}`) }}
            <span class="rounded-full bg-surface-2 px-2 text-xs">{{ group.active.length }}</span>
          </h2>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <AccountCard
              v-for="account in [...group.active, ...group.archived]"
              :key="account.id"
              :account="account"
              :setup="setup === 'opening'"
              @edit="edit"
              @archive="archive"
              @reopen="reopen"
              @record="(a) => openQuickAdd({ mode: 'expense', account: a.id })"
              @transfer="(a) => openQuickAdd({ mode: 'transfer', account: a.id })"
              @opening="(a) => openQuickAdd({ mode: 'opening', account: a.id })"
            />
          </div>
        </section>
        <div class="flex justify-center">
          <UiButton v-if="canManage || archivedCount || showArchived" variant="ghost" size="sm" @click="showArchived = !showArchived">
            {{ showArchived ? t("finance.accounts.hideArchived") : t("finance.accounts.showArchived") }}
          </UiButton>
        </div>
      </div>
    </template>

    <AccountFormDialog v-model:open="formOpen" :account="editing" />
  </div>
</template>
