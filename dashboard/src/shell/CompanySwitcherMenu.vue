<script setup lang="ts">
/**
 * The company switcher's menu (plan §13.1): "Portfolio" at the top, every company with a status
 * dot for red alerts and a count of what waits for you, "New company" at the bottom. Switching keeps
 * the current page when the other company has it. Loaded on first use (CompanySwitcher.vue).
 */
import { Check, LayoutGrid, Plus } from "@lucide/vue";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "reka-ui";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import CompanyLogo from "@/components/CompanyLogo.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useUiStore } from "@/stores/ui";

import { useCompanySwitcher, type SwitcherVariant } from "./companySwitcher";

/** `tooltip`: the company's name on hover, for the rail where the button is only its logo. */
withDefaults(defineProps<{ variant: SwitcherVariant; tooltip?: string }>(), { tooltip: undefined });
const open = defineModel<boolean>("open", { default: false });

const { t } = useI18n();
const router = useRouter();
const ui = useUiStore();
const { company, onPortfolio, hasPortfolio, canCreate, current, openCompany } = useCompanySwitcher();

const itemClass =
  "group flex h-11 cursor-default select-none items-center gap-3 rounded-[8px] px-2 outline-none data-[highlighted]:bg-highlight";
</script>

<template>
  <DropdownMenuRoot v-model:open="open">
    <UiTooltip :content="tooltip" side="right" :disabled="!tooltip">
      <DropdownMenuTrigger as-child>
        <slot name="trigger" />
      </DropdownMenuTrigger>
    </UiTooltip>
    <DropdownMenuPortal>
      <DropdownMenuContent
        :side="variant === 'rail' ? 'right' : 'bottom'"
        :align="'start'"
        :side-offset="variant === 'rail' ? 10 : 6"
        :collision-padding="8"
        class="anim-pop z-[70] w-[300px] rounded-[14px] border border-line bg-surface p-1.5 text-fg shadow-pop outline-none"
      >
        <template v-if="hasPortfolio">
          <DropdownMenuItem :class="itemClass" @select="router.push({ name: 'portfolio' })">
            <span class="grid size-8 shrink-0 place-items-center rounded-[9px] bg-fg text-canvas">
              <LayoutGrid :size="16" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-base font-semibold">{{ t("shell.company.portfolio") }}</span>
              <span class="block truncate text-xs text-muted">{{ t("shell.company.portfolioHint") }}</span>
            </span>
            <Check v-if="onPortfolio" :size="16" class="text-primary" />
          </DropdownMenuItem>
          <DropdownMenuSeparator class="-mx-1.5 my-1.5 h-px bg-line" />
        </template>
        <DropdownMenuLabel class="px-2 pb-1 pt-1.5 text-xs font-medium text-muted">{{ t("shell.company.yours") }}</DropdownMenuLabel>
        <DropdownMenuItem v-for="item in company.companies" :key="item.id" :class="itemClass" @select="openCompany(item.id)">
          <CompanyLogo :name="item.name" :src="item.logo" :size="32" :alert="(item.alerts ?? 0) > 0" style="--logo-ring: var(--c-surface)" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-semibold">{{ item.name }}</span>
            <span class="block truncate text-xs text-muted">
              {{ item.role?.name }}<template v-if="item.alerts"> · <span class="text-danger">{{ t("shell.company.alerts", { n: item.alerts }) }}</span></template>
            </span>
          </span>
          <UiBadge v-if="item.pending > 0" :count="item.pending" tone="primary" :title="t('shell.company.waiting', { n: item.pending })" />
          <Check v-if="current?.id === item.id" :size="16" class="shrink-0 text-primary" />
        </DropdownMenuItem>
        <template v-if="canCreate">
          <DropdownMenuSeparator class="-mx-1.5 my-1.5 h-px bg-line" />
          <DropdownMenuItem :class="itemClass" @select="ui.newCompanyOpen = true">
            <span class="grid size-8 shrink-0 place-items-center rounded-[9px] border border-dashed border-line-strong text-muted group-data-[highlighted]:border-primary group-data-[highlighted]:text-primary">
              <Plus :size="16" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-base font-semibold">{{ t("shell.company.new") }}</span>
              <span class="block truncate text-xs text-muted">{{ t("shell.company.newHint") }}</span>
            </span>
          </DropdownMenuItem>
        </template>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenuRoot>
</template>
