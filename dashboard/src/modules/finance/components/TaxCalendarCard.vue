<script setup lang="ts">
/**
 * The tax calendar (plan §1.6 "a template set of recurring obligations with editable due days";
 * §14.8 "one set per regime"): the company's own regime first, each set's taxes with how often
 * and on which day they are usually due, which are already on the calendar, and "Add to my
 * calendar" for the rest. The rules it adds are bills whose amount changes each time, owed to the
 * tax office, editable afterwards; the due days are typical ones to confirm with an accountant.
 */
import { CalendarCheck, CalendarPlus, Check, ChevronDown, Landmark } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useCompanyId, useCompanyStore } from "@/stores/company";

import { financeApi, useRefresh, useTaxTemplates } from "../api";
import { scheduleText, taxSetsInOrder } from "../lib";
import type { TaxTemplateSet } from "../types";

const { t } = useI18n();
const company = useCompanyStore();
const cid = useCompanyId();
const refresh = useRefresh();
const query = useTaxTemplates();
const canManage = computed(() => company.can("finance.manage"));
const sets = computed(() => taxSetsInOrder(query.data.value ?? []));
const others = ref(false);
const applying = ref<string | null>(null);

// A template's due day reads like a rule's ("Monthly, day 25"); a yearly one needs no month here.
const when = (item: TaxTemplateSet["items"][number]) => scheduleText({ frequency: item.frequency, interval: 1, day: item.day, starts_on: "2026-01-01" }, t, () => t("finance.recurring.dayN", { day: item.day }));
const missing = (set: TaxTemplateSet) => set.items.filter((item) => !item.applied).length;

async function apply(set: TaxTemplateSet): Promise<void> {
  applying.value = set.key;
  try {
    const added = await financeApi.applyTaxTemplate(cid.value, set.key);
    if (added.length) toast.success(t("finance.taxCalendar.added", { n: added.length }, added.length));
    else toast.info(t("finance.taxCalendar.nothingAdded"));
    refresh();
  } catch {
    // The HTTP layer has said what went wrong.
  } finally {
    applying.value = null;
  }
}
</script>

<template>
  <section class="ui-card flex flex-col p-4" :aria-label="t('finance.taxCalendar.title')" data-tax-calendar>
    <header class="mb-1 flex items-start gap-2">
      <Landmark :size="16" class="mt-0.5 shrink-0 text-subtle" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h3 class="text-sm font-semibold text-fg">{{ t("finance.taxCalendar.title") }}</h3>
        <p class="text-xs text-muted">{{ t("finance.taxCalendar.hint") }}</p>
      </div>
    </header>

    <div v-if="query.isPending.value" class="mt-3 flex flex-col gap-2"><SkeletonBlock v-for="n in 4" :key="n" height="28px" /></div>
    <ErrorState v-else-if="query.isError.value" compact class="mt-3" :error="query.error.value" :retry="() => query.refetch()" />
    <template v-else>
      <template v-for="(set, index) in sets" :key="set.key">
        <button
          v-if="index === 1"
          type="button"
          class="mt-3 inline-flex w-fit items-center gap-1 text-sm font-semibold text-accent-fg hover:underline"
          :aria-expanded="others"
          @click="others = !others"
        >
          {{ t("finance.taxCalendar.otherRegimes") }}<ChevronDown :size="14" :class="['transition-transform', others && 'rotate-180']" aria-hidden="true" />
        </button>
        <div v-if="index === 0 || others" :class="['mt-3 flex flex-col gap-2 rounded-[10px] border border-line p-3', set.current && 'border-line-strong']" :data-set="set.key">
          <div class="flex items-center gap-2">
            <p class="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{{ set.label }}</p>
            <StatusPill v-if="set.current" tone="primary" size="sm" :label="t('finance.taxCalendar.yours')" />
          </div>
          <ul class="flex flex-col">
            <li v-for="item in set.items" :key="item.template_key" class="flex items-center gap-2 py-1 text-sm">
              <component :is="item.applied ? Check : CalendarCheck" :size="14" :class="['shrink-0', item.applied ? 'text-success' : 'text-subtle']" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate text-fg" :title="item.name">{{ item.name }}</span>
              <span class="shrink-0 text-xs text-muted">{{ when(item) }}</span>
            </li>
          </ul>
          <div class="flex flex-wrap items-center gap-2">
            <UiButton v-if="canManage && missing(set)" size="sm" :variant="set.current ? 'primary' : 'secondary'" :icon="CalendarPlus" :loading="applying === set.key" :disabled="!!applying && applying !== set.key" data-apply @click="apply(set)">
              {{ t("finance.taxCalendar.apply") }}
            </UiButton>
            <span v-else-if="!missing(set)" class="inline-flex items-center gap-1 text-xs font-medium text-success"><Check :size="13" aria-hidden="true" />{{ t("finance.taxCalendar.allAdded") }}</span>
          </div>
          <p class="text-xs text-subtle">{{ set.note || t("finance.taxCalendar.note") }}</p>
        </div>
      </template>
      <p v-if="!sets.length" class="mt-3 text-sm text-muted">{{ t("finance.taxCalendar.none") }}</p>
    </template>
  </section>
</template>
