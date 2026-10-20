<script setup lang="ts">
/**
 * Company switcher (plan §13.1): "Portfolio" at the top, every company with a status dot for red
 * alerts and a count of what waits for you, "New company" at the bottom. Switching keeps the
 * current page when the other company has it.
 */
import { Check, ChevronsUpDown, LayoutGrid, Plus } from "@lucide/vue";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "reka-ui";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { pathInCompany } from "@/app/navigation";
import CompanyLogo from "@/components/CompanyLogo.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { hasExtension } from "@/core/extensions";
import { useCompanyStore } from "@/stores/company";
import { useUiStore } from "@/stores/ui";

const props = withDefaults(defineProps<{ variant?: "sidebar" | "rail" | "compact" }>(), { variant: "sidebar" });

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const ui = useUiStore();

const companyless = computed(() => route.matched.some((record) => record.meta.companyless));
const onPortfolio = computed(() => route.name === "portfolio");
const hasPortfolio = computed(() => router.hasRoute("portfolio"));
const canCreate = computed(() => hasExtension("shell.company.create", company.current ?? company.companies[0]));
const current = computed(() => (companyless.value ? null : company.current));
const label = computed(() => current.value?.name ?? (onPortfolio.value ? t("shell.company.portfolio") : t("shell.company.switch")));

function open(id: number): void {
  if (id === company.currentId && !companyless.value) return;
  void router.push(companyless.value ? `/c/${id}` : pathInCompany(router, route, id));
}

const itemClass =
  "group flex h-11 cursor-default select-none items-center gap-3 rounded-[8px] px-2 outline-none data-[highlighted]:bg-highlight";
</script>

<template>
  <DropdownMenuRoot>
    <UiTooltip :content="label" side="right" :disabled="props.variant !== 'rail'">
      <DropdownMenuTrigger
        :class="[
          'pressable group flex min-w-0 items-center text-left outline-offset-0',
          variant === 'rail' && 'size-10 justify-center rounded-[10px] hover:bg-[var(--c-nav-hover)] data-[state=open]:bg-[var(--c-nav-hover)]',
          variant === 'sidebar' && 'h-10 w-full gap-2.5 rounded-[10px] pl-1.5 pr-2 hover:bg-[var(--c-nav-hover)] data-[state=open]:bg-[var(--c-nav-hover)]',
          variant === 'compact' && 'h-9 max-w-[60vw] gap-2 rounded-[10px] pl-1 pr-1.5 hover:bg-highlight data-[state=open]:bg-highlight',
        ]"
        :aria-label="t('shell.company.switch')"
      >
        <span
          v-if="!current"
          class="grid shrink-0 place-items-center rounded-[8px] bg-fg text-canvas"
          :class="variant === 'compact' ? 'size-7' : 'size-[30px]'"
        >
          <LayoutGrid :size="15" />
        </span>
        <CompanyLogo
          v-else
          :name="current.name"
          :src="current.logo"
          :size="variant === 'compact' ? 28 : 30"
          :alert="current.alerts > 0"
        />
        <template v-if="variant !== 'rail'">
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-semibold leading-5 text-fg">{{ label }}</span>
            <span v-if="current && variant === 'sidebar'" class="block truncate text-xs text-muted">{{ current.role.name }}</span>
          </span>
          <UiBadge v-if="current && current.pending > 0 && variant === 'sidebar'" :count="current.pending" tone="primary" />
          <ChevronsUpDown :size="15" class="shrink-0 text-subtle transition-colors group-hover:text-muted" />
        </template>
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
        <DropdownMenuItem v-for="item in company.companies" :key="item.id" :class="itemClass" @select="open(item.id)">
          <CompanyLogo :name="item.name" :src="item.logo" :size="32" :alert="item.alerts > 0" style="--logo-ring: var(--c-surface)" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-base font-semibold">{{ item.name }}</span>
            <span class="block truncate text-xs text-muted">
              {{ item.role.name }}<template v-if="item.alerts > 0"> · <span class="text-danger">{{ t("shell.company.alerts", { n: item.alerts }) }}</span></template>
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
