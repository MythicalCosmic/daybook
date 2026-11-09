<script setup lang="ts">
/**
 * Today's tile "Mandatory training": how much of it is done and who is late with it (the first
 * three, the most days late first), linking to the people grid. Branch-scoped like the module.
 */
import { ArrowUpRight, GraduationCap } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import type { Range } from "@/api/types";
import ErrorState from "@/components/ErrorState.vue";
import ProgressRing from "@/components/ProgressRing.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import { useCompanyStore } from "@/stores/company";

import { useOverview } from "../api";

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();

const { t } = useI18n();
const company = useCompanyStore();
const branch = computed(() => (company.branchFilter.length === 1 ? company.branchFilter[0] : undefined));
const overview = useOverview(computed(() => ({ branch: branch.value })));
const data = computed(() => overview.data.value);
const late = computed(() => (data.value?.late ?? []).slice(0, 3));
</script>

<template>
  <div class="ui-card flex h-full min-h-[148px] min-w-0 flex-col p-4" :aria-busy="overview.isPending.value || undefined" data-testid="learning-compliance-widget">
    <RouterLink :to="`/c/${props.companyId}/learning`" class="group flex items-start gap-2">
      <GraduationCap :size="15" class="mt-px shrink-0 text-subtle" aria-hidden="true" />
      <span class="kpi-label">{{ t("learning.overview.compliance") }}</span>
      <ArrowUpRight :size="15" class="mt-px shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
    </RouterLink>
    <ErrorState v-if="overview.isError.value" class="mt-2.5" compact bare :error="overview.error.value" :retry="() => overview.refetch()" />
    <template v-else-if="!data">
      <SkeletonBlock class="mt-2.5" height="16px" />
      <SkeletonBlock class="mt-2" width="70%" height="16px" />
    </template>
    <p v-else-if="!data.compliance.people" class="mt-2 text-sm text-muted">{{ t("learning.grid.noCourses") }}</p>
    <div v-else class="mt-2 flex min-w-0 items-start gap-3">
      <ProgressRing :value="data.compliance.percent" :max="100" :size="48" :stroke="6" tone="auto" show-value :label="t('learning.overview.compliance')" />
      <div class="min-w-0 flex-1 text-sm">
        <p class="text-muted">{{ t("learning.overview.complianceBody", { done: data.compliance.completed, people: data.compliance.people }) }}</p>
        <p v-if="!late.length" class="text-success">{{ t("learning.overview.nobodyLate") }}</p>
        <ul v-else class="mt-1.5 flex flex-col gap-1.5">
          <li v-for="row in late" :key="`${row.member.id}-${row.course.id}`" class="min-w-0">
            <RouterLink :to="`/c/${props.companyId}/learning/people/${row.member.id}`" class="block truncate text-fg hover:underline">
              {{ row.member.name }}
            </RouterLink>
            <span class="block truncate text-xs text-muted">
              <span class="text-danger tabular-nums">{{ t("learning.daysLate", { n: row.days_late }, row.days_late) }}</span> · {{ row.course.title }}
            </span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
