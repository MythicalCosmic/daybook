<script setup lang="ts">
/**
 * The company switcher's button: this company's logo, name and your role in it, a dot when your
 * other companies have work waiting. Plain until its menu loads (CompanySwitcher.vue), then the
 * menu's trigger (reka-ui adds `data-state` and its listeners through the attributes).
 */
import { ChevronsUpDown, LayoutGrid } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import type { Company } from "@/api/types";
import CompanyLogo from "@/components/CompanyLogo.vue";

import type { SwitcherVariant } from "./companySwitcher";

defineProps<{ variant: SwitcherVariant; current: Company | null; label: string; elsewhere: number }>();

const { t } = useI18n();
</script>

<template>
  <button
    type="button"
    :class="[
      'pressable group flex min-w-0 items-center text-left outline-offset-0',
      variant === 'rail' && 'size-10 justify-center rounded-[10px] hover:bg-[var(--c-nav-hover)] data-[state=open]:bg-[var(--c-nav-hover)]',
      variant === 'sidebar' && 'h-10 w-full gap-2.5 rounded-[10px] pl-1.5 pr-2 hover:bg-[var(--c-nav-hover)] data-[state=open]:bg-[var(--c-nav-hover)]',
      variant === 'compact' && 'h-9 max-w-[60vw] gap-2 rounded-[10px] pl-1 pr-1.5 hover:bg-highlight data-[state=open]:bg-highlight',
    ]"
    :aria-label="t('shell.company.switch')"
  >
    <span v-if="!current" class="grid shrink-0 place-items-center rounded-[8px] bg-fg text-canvas" :class="variant === 'compact' ? 'size-7' : 'size-[30px]'">
      <LayoutGrid :size="15" />
    </span>
    <CompanyLogo v-else :name="current.name" :src="current.logo" :size="variant === 'compact' ? 28 : 30" :alert="(current.alerts ?? 0) > 0" />
    <template v-if="variant !== 'rail'">
      <span class="min-w-0 flex-1">
        <span class="block truncate text-base font-semibold leading-5 text-fg">{{ label }}</span>
        <span v-if="current && variant === 'sidebar'" class="block truncate text-xs text-muted">{{ current.role?.name }}</span>
      </span>
      <!-- This company's queue is the Inbox badge right below; the dot says another one has work waiting. -->
      <span v-if="elsewhere > 0" class="size-2 shrink-0 rounded-full bg-primary" :title="t('shell.company.waitingElsewhere', { n: elsewhere })" data-elsewhere>
        <span class="sr-only">{{ t("shell.company.waitingElsewhere", { n: elsewhere }) }}</span>
      </span>
      <ChevronsUpDown :size="15" class="shrink-0 text-subtle transition-colors group-hover:text-muted" />
    </template>
  </button>
</template>
