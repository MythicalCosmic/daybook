<script setup lang="ts">
/**
 * Accounts as chips to tap (quick add, payments, transfers): an icon per kind, the name, the
 * currency when it isn't the base one. Arrow keys move between chips (a radio group).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useCompanyStore } from "@/stores/company";

import { ACCOUNT_ICONS } from "../lib";
import type { AccountRef } from "../types";

const model = defineModel<number | null>({ default: null });

const props = withDefaults(defineProps<{ accounts: AccountRef[]; label?: string; disabledIds?: number[]; invalid?: boolean }>(), {
  label: undefined,
  disabledIds: () => [],
  invalid: false,
});

const { t } = useI18n();
const company = useCompanyStore();
const list = computed(() => props.accounts);

function move(event: KeyboardEvent, index: number): void {
  const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
  if (!step) return;
  event.preventDefault();
  const buttons = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>("button:not([disabled])");
  if (!buttons?.length) return;
  const items = [...buttons];
  const current = items.indexOf(event.currentTarget as HTMLButtonElement);
  const next = items[(current + step + items.length) % items.length];
  next?.focus();
  const id = Number(next?.dataset.id);
  if (Number.isFinite(id)) model.value = id;
  void index;
}
</script>

<template>
  <div role="radiogroup" :aria-label="label ?? t('finance.field.account')" :class="['flex flex-wrap gap-1.5', invalid && 'rounded-[10px] ring-1 ring-danger/60 ring-offset-2 ring-offset-surface']">
    <button
      v-for="(account, index) in list"
      :key="account.id"
      type="button"
      role="radio"
      :data-id="account.id"
      :aria-checked="model === account.id"
      :tabindex="model === account.id || (model === null && index === 0) ? 0 : -1"
      :disabled="disabledIds.includes(account.id)"
      :class="[
        'chip inline-flex h-8 max-w-full items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-colors duration-120',
        model === account.id ? 'border-primary bg-accent-soft text-accent-fg' : 'border-line bg-surface text-fg hover:border-line-strong hover:bg-surface-2',
        'disabled:cursor-not-allowed disabled:opacity-45',
      ]"
      @click="model = account.id"
      @keydown="move($event, index)"
    >
      <component :is="ACCOUNT_ICONS[account.kind]" :size="14" class="shrink-0 opacity-80" aria-hidden="true" />
      <span class="truncate">{{ account.name }}</span>
      <span v-if="account.currency !== company.currency" class="rounded-full bg-surface-2 px-1.5 text-[11px] font-semibold text-muted">{{ account.currency }}</span>
    </button>
    <p v-if="!list.length" class="text-sm text-muted">{{ t("finance.quick.noAccounts") }}</p>
  </div>
</template>
