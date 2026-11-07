<script setup lang="ts">
/**
 * Above the roster grid (the slot `attendance.roster.coverage`, plan §14.5, §14.9): the week's
 * hours without a qualified pharmacist at the pharmacies shown, drafts counted, so whoever builds
 * the roster sees what to fill before publishing. Silent while the rule is off or there is no
 * pharmacy to check; a short prompt while nobody has said who counts as a pharmacist.
 */
import { CircleCheck, ShieldAlert } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import InlineAlert from "@/components/InlineAlert.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useCoverage } from "../api";
import { allGaps, coverageTotals, hoursOf, weekParams } from "../coverage";

const props = defineProps<{ context: { companyId: number; branchId?: number | null; week: string } }>();

const SHOWN = 6;
const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const params = computed(() => (props.context.week ? weekParams(props.context.week, props.context.branchId ?? null, true) : null));
const query = useCoverage(params);
const data = computed(() => query.data.value ?? null);
const totals = computed(() => coverageTotals(data.value?.branches ?? []));
const gaps = computed(() => allGaps(data.value?.branches ?? []));
const several = computed(() => (data.value?.branches.length ?? 0) > 1);
const coverageLink = computed(() => ({
  path: `/c/${props.context.companyId}/hr/coverage`,
  query: { week: params.value?.from, ...(props.context.branchId ? { branch: String(props.context.branchId) } : {}) },
}));

function when(gap: { start: string; end: string }): string {
  return `${fmt.day(gap.start.slice(0, 10), "weekdayShort")}, ${fmt.instant(gap.start, "time")}–${fmt.instant(gap.end, "time")}`;
}
</script>

<template>
  <div v-if="data" data-roster-coverage>
    <InlineAlert
      v-if="data.state === 'setup' && company.can('hr.manage')"
      tone="info"
      size="sm"
      :title="t('hr.coverage.slot.setupTitle')"
      :description="t('hr.coverage.slot.setupBody')"
    >
      <template #actions>
        <UiButton size="sm" :to="`/c/${context.companyId}/settings/hr`">{{ t("hr.coverage.setup.button") }}</UiButton>
      </template>
    </InlineAlert>
    <template v-else-if="data.state === 'ok' && totals.branches">
      <InlineAlert
        v-if="gaps.length"
        tone="warning"
        size="sm"
        :icon="ShieldAlert"
        :title="t('hr.coverage.slot.gapsTitle', { n: gaps.length, h: hoursOf(totals.minutes) }, gaps.length)"
      >
        <p>{{ t("hr.coverage.slot.gapsBody") }}</p>
        <ul class="mt-1.5 flex flex-col gap-0.5 text-sm" data-gap-list>
          <li v-for="gap in gaps.slice(0, SHOWN)" :key="`${gap.branch_id}-${gap.start}`" class="tabular-nums text-fg">
            <span v-if="several" class="font-semibold">{{ gap.branchName }} · </span>{{ when(gap) }}
            <span v-if="gap.have" class="text-muted"> · {{ t("hr.coverage.haveOfNeed", { have: gap.have, need: gap.need }) }}</span>
          </li>
          <li v-if="gaps.length > SHOWN" class="text-muted">{{ t("hr.coverage.slot.more", { n: gaps.length - SHOWN }, gaps.length - SHOWN) }}</li>
        </ul>
        <template #actions>
          <UiButton size="sm" variant="secondary" :to="coverageLink">{{ t("hr.coverage.slot.open") }}</UiButton>
        </template>
      </InlineAlert>
      <p v-else class="flex items-center gap-1.5 px-1 text-sm text-success" data-covered>
        <CircleCheck :size="15" aria-hidden="true" />{{ t("hr.coverage.slot.covered") }}
        <RouterLink :to="coverageLink" class="text-muted underline-offset-2 hover:underline">{{ t("hr.coverage.slot.details") }}</RouterLink>
      </p>
    </template>
  </div>
</template>
