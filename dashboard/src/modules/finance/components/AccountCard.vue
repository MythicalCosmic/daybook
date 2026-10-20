<script setup lang="ts">
/**
 * One money account as a card: its colour, kind and branch, the balance (and its so‘m value for a
 * dollar account), the last 30 days as a sparkline, and quick actions. The whole card opens the
 * account's statement.
 */
import { ArrowLeftRight, Archive, ArchiveRestore, Ellipsis, FileText, Pencil, Plus } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import MoneyText from "@/components/MoneyText.vue";
import SparkLine from "@/components/SparkLine.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { ACCOUNT_ICONS, colorFor, isNegative } from "../lib";
import type { Account } from "../types";

const props = defineProps<{ account: Account; setup?: boolean }>();
const emit = defineEmits<{ edit: [account: Account]; archive: [account: Account]; reopen: [account: Account]; record: [account: Account]; transfer: [account: Account]; opening: [account: Account] }>();

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const canManage = computed(() => company.can("finance.manage"));
const color = computed(() => colorFor(props.account.id, props.account.color));
const foreign = computed(() => props.account.currency !== company.currency);
const to = computed(() => `/c/${company.currentId}/finance/accounts/${props.account.id}`);

const menu = computed<MenuEntry[]>(() => {
  const entries: MenuEntry[] = [{ label: t("finance.accounts.statement"), icon: FileText, onSelect: () => void router.push(to.value) }];
  if (props.account.can_record && props.account.is_active) {
    entries.push({ label: t("finance.cmd.record"), icon: Plus, onSelect: () => emit("record", props.account) });
    entries.push({ label: t("finance.cmd.transferShort"), icon: ArrowLeftRight, onSelect: () => emit("transfer", props.account) });
  }
  if (canManage.value) {
    entries.push({ type: "separator" });
    entries.push({ label: t("common.edit"), icon: Pencil, onSelect: () => emit("edit", props.account) });
    if (props.account.is_active) entries.push({ label: t("finance.accounts.archive"), icon: Archive, danger: true, onSelect: () => emit("archive", props.account) });
    else entries.push({ label: t("finance.accounts.reopen"), icon: ArchiveRestore, onSelect: () => emit("reopen", props.account) });
  }
  return entries;
});
</script>

<template>
  <article
    :class="[
      'account-card group relative flex min-w-0 flex-col overflow-hidden rounded-[12px] border border-line bg-surface transition-[border-color,box-shadow] duration-120 hover:border-line-strong hover:shadow-xs',
      !account.is_active && 'opacity-60',
    ]"
  >
    <span class="absolute inset-y-0 left-0 w-1" :style="{ background: color }" aria-hidden="true" />
    <RouterLink :to="to" class="flex flex-1 flex-col gap-3 p-4 pl-5 outline-none focus-visible:bg-surface-2/60">
      <div class="flex items-start gap-3">
        <span class="grid size-9 shrink-0 place-items-center rounded-[10px]" :style="{ background: `color-mix(in srgb, ${color} 14%, transparent)`, color }" aria-hidden="true">
          <component :is="ACCOUNT_ICONS[account.kind]" :size="18" />
        </span>
        <div class="min-w-0 flex-1 pr-7">
          <h3 class="truncate text-base font-semibold text-fg">{{ account.name }}</h3>
          <p class="truncate text-xs text-muted">
            {{ account.kind_label }}<template v-if="account.branch"> · {{ account.branch.name }}</template><template v-else-if="account.holder"> · {{ account.holder.name }}</template><template v-if="account.number_last4"> · •• {{ account.number_last4 }}</template>
          </p>
        </div>
      </div>
      <div class="flex items-end justify-between gap-3">
        <div class="min-w-0">
          <p :class="['truncate text-xl font-semibold tracking-[-0.015em] tabular-nums', isNegative(account.balance) ? 'text-danger' : 'text-fg']">
            <MoneyText :value="account.balance" :currency="account.currency" :decimals="foreign ? 'always' : 'never'" />
          </p>
          <p v-if="foreign && account.base_balance" class="truncate text-xs text-muted">≈ <MoneyText :value="account.base_balance" compact /></p>
          <p v-else class="truncate text-xs text-subtle">
            {{ account.last_activity ? t("finance.accounts.lastMove", { date: fmt.day(account.last_activity, "short") }) : t("finance.accounts.noMoves") }}
          </p>
        </div>
        <SparkLine v-if="account.spark.length > 1" :data="account.spark" :color="color" :width="96" :height="30" class="shrink-0" />
      </div>
    </RouterLink>
    <button
      v-if="setup && account.is_active && account.can_record"
      type="button"
      class="mx-4 mb-3 -mt-1 inline-flex h-7 items-center justify-center gap-1 rounded-[8px] border border-dashed border-primary/50 text-xs font-semibold text-accent-fg hover:bg-accent-soft"
      @click="emit('opening', account)"
    >
      <Plus :size="13" />{{ t("finance.accounts.setOpening") }}
    </button>
    <div v-if="menu.length" class="absolute right-2 top-2">
      <DropdownMenu :items="menu" width="200px">
        <template #trigger>
          <IconButton :icon="Ellipsis" :label="t('finance.accounts.actions', { name: account.name })" size="sm" />
        </template>
      </DropdownMenu>
    </div>
  </article>
</template>
