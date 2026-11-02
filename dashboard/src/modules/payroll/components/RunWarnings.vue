<script setup lang="ts">
/**
 * What to look at before finalizing (plan §6.2 "warnings panel with fix-it links"): people with no
 * pay setup, open disputes, bonuses and fines still waiting, advances to decide… in the server's
 * words, each with a link to where it is fixed. Shown first on a run's page.
 */
import { ArrowRight, TriangleAlert } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { useCompanyStore } from "@/stores/company";

import { warningLink } from "../lib";
import type { RunWarning } from "../types";

const props = withDefaults(defineProps<{ warnings: RunWarning[]; final?: boolean }>(), { final: false });

const { t } = useI18n();
const company = useCompanyStore();
const expanded = ref(false);
const LIMIT = 4;
const shown = computed(() => (expanded.value ? props.warnings : props.warnings.slice(0, LIMIT)));
const link = (warning: RunWarning) => {
  const to = warningLink(warning);
  return to ? `/c/${company.currentId}/${to}` : null;
};
</script>

<template>
  <section class="rounded-[12px] border border-warning/40 bg-warning-soft/60 dark:bg-warning-soft/40" :aria-label="t('payroll.warnings.title')" data-testid="run-warnings">
    <header class="flex items-start gap-2.5 px-4 pb-2 pt-3.5">
      <TriangleAlert :size="18" class="mt-px shrink-0 text-warning" aria-hidden="true" />
      <div class="min-w-0">
        <h2 class="text-base font-semibold text-fg">{{ t("payroll.warnings.title", { n: warnings.length }, warnings.length) }}</h2>
        <p class="text-sm text-muted">{{ final ? t("payroll.warnings.finalHint") : t("payroll.warnings.hint") }}</p>
      </div>
    </header>
    <ul class="flex flex-col px-2 pb-2">
      <li v-for="(warning, index) in shown" :key="`${warning.code}-${index}`">
        <component
          :is="link(warning) ? RouterLink : 'div'"
          :to="link(warning) ?? undefined"
          :class="['flex min-h-11 items-center gap-3 rounded-[8px] px-2 py-2', link(warning) && 'group hover:bg-surface/70']"
        >
          <span :class="['size-1.5 shrink-0 rounded-full', warning.level === 'info' ? 'bg-info' : 'bg-warning']" aria-hidden="true" />
          <span class="min-w-0 flex-1 text-sm text-fg">{{ warning.text }}</span>
          <!-- The whole row is the link: on a phone the arrow alone leaves the text its width. -->
          <span v-if="link(warning)" class="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-accent-fg">
            <span class="max-sm:hidden">{{ t("payroll.warnings.fix") }}</span><ArrowRight :size="16" class="transition-transform group-hover:translate-x-0.5" />
          </span>
        </component>
      </li>
    </ul>
    <button v-if="warnings.length > LIMIT" type="button" class="mx-4 mb-3 text-sm font-semibold text-accent-fg hover:underline" @click="expanded = !expanded">
      {{ expanded ? t("payroll.warnings.less") : t("payroll.warnings.more", { n: warnings.length - LIMIT }, warnings.length - LIMIT) }}
    </button>
  </section>
</template>
