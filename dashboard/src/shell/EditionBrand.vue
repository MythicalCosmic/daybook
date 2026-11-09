<script setup lang="ts">
/**
 * Davomat's sidebar head (and the phone's top bar): one install is one organization, so instead of
 * the company switcher the organization's logo (Davomat's mark without one), its name and the
 * product. It leads home.
 */
import { computed } from "vue";

import CompanyLogo from "@/components/CompanyLogo.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { davomatMark } from "@/core/brand";
import { editionInfo } from "@/core/edition";
import { useCompanyStore } from "@/stores/company";

const props = withDefaults(defineProps<{ variant?: "sidebar" | "rail" | "compact" }>(), { variant: "sidebar" });

const company = useCompanyStore();
const current = computed(() => company.current);
const name = computed(() => current.value?.name ?? editionInfo.value.organization?.name ?? editionInfo.value.product);
const logo = computed(() => current.value?.logo ?? editionInfo.value.organization?.logo_url ?? null);
const home = computed(() => (company.currentId ? `/c/${company.currentId}` : "/"));
const size = computed(() => (props.variant === "compact" ? 28 : 32));
// A static mark drawn here (core/brand.ts), never from input: safe for v-html.
const mark = davomatMark();
</script>

<template>
  <UiTooltip :content="name" side="right" :disabled="variant !== 'rail'">
    <RouterLink
      :to="home"
      :class="[
        'pressable flex min-w-0 items-center outline-offset-0',
        variant === 'rail' && 'size-10 justify-center rounded-[10px] hover:bg-[var(--c-nav-hover)]',
        variant === 'sidebar' && 'h-11 w-full gap-2.5 rounded-[10px] pl-1.5 pr-2 hover:bg-[var(--c-nav-hover)]',
        variant === 'compact' && 'h-9 max-w-[64vw] gap-2 rounded-[10px] pl-1 pr-1.5 hover:bg-highlight',
      ]"
      :aria-label="name"
      data-testid="edition-brand"
    >
      <CompanyLogo v-if="logo" :name="name" :src="logo" :size="size" />
      <span v-else class="brand-mark shrink-0" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true" v-html="mark" />
      <span v-if="variant !== 'rail'" class="min-w-0 flex-1">
        <span class="block truncate text-base font-semibold leading-5 text-fg">{{ name }}</span>
        <span v-if="variant === 'sidebar'" class="block truncate text-xs text-muted">{{ editionInfo.product }}</span>
      </span>
    </RouterLink>
  </UiTooltip>
</template>

<style scoped>
.brand-mark :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
