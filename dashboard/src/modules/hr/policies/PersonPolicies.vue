<script setup lang="ts">
/**
 * Person 360 › HR › Policies: the rules that apply to the person and where they stand on each
 * (signed when, waiting until when, late since when, or only to read), and how many signatures
 * they gave to earlier versions. A row opens the policy.
 */
import { ScrollText } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { usePersonPolicies } from "./api";
import { CATEGORY_ICONS, CATEGORY_TINTS, policyPath, STANDING_TONES } from "./lib";
import type { PersonPolicyStanding } from "./types";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const query = usePersonPolicies(() => props.memberId);
const rows = computed(() => query.data.value?.current ?? []);
const earlier = computed(() => {
  const current = new Set(rows.value.filter((row) => row.state === "signed").map((row) => `${row.policy.id}:${row.signed_at}`));
  return (query.data.value?.history ?? []).filter((row) => !current.has(`${row.policy.id}:${row.signed_at}`)).length;
});

function detail(row: PersonPolicyStanding): string {
  if (row.state === "signed" && row.signed_at) return t("hr.policy.signedOn", { date: fmt.instant(row.signed_at, "date") });
  if (row.state === "late" && row.due_on) return t("hr.policy.lateSince", { date: fmt.day(row.due_on, "short") });
  if (row.state === "waiting" && row.due_on) return t("hr.policy.dueOn", { date: fmt.day(row.due_on, "short") });
  return t("hr.policy.version", { n: row.number });
}
</script>

<template>
  <section class="ui-card overflow-hidden" data-hr-policies>
    <header class="flex items-center gap-2 border-b border-line px-5 py-3">
      <ScrollText :size="16" class="text-subtle" aria-hidden="true" />
      <h2 class="flex-1 text-md font-semibold text-fg">{{ t("hr.nav.policies") }}</h2>
    </header>
    <div v-if="query.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 2" :key="n" height="40px" /></div>
    <ErrorState v-else-if="query.isError.value" compact class="m-4" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="!rows.length" size="sm" tone="neutral" :icon="ScrollText" :title="t('hr.policy.person.empty')" />
    <template v-else>
      <ul class="divide-y divide-[var(--c-border)]">
        <li v-for="row in rows" :key="row.policy.id">
          <RouterLink :to="policyPath(company.currentId ?? 0, row.policy.id)" class="flex min-h-12 items-center gap-3 px-5 py-2.5 transition-colors hover:bg-highlight">
            <span :class="['grid size-8 shrink-0 place-items-center rounded-[8px]', CATEGORY_TINTS[row.policy.category]]" aria-hidden="true">
              <component :is="CATEGORY_ICONS[row.policy.category]" :size="15" />
            </span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium text-fg">{{ row.policy.title }}</p>
              <p class="truncate text-xs text-muted">{{ detail(row) }}</p>
            </div>
            <StatusPill :tone="STANDING_TONES[row.state]" size="sm" :label="t(`hr.policy.state.${row.state}`)" />
          </RouterLink>
        </li>
      </ul>
      <p v-if="earlier" class="border-t border-line px-5 py-2.5 text-xs text-subtle">{{ t("hr.policy.person.history", { n: earlier }, earlier) }}</p>
    </template>
  </section>
</template>
