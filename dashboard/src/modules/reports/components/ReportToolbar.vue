<script setup lang="ts">
/** The reports' period (presets and comparison) and branch filter, both kept in the URL. */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import { useScopedBranches } from "@/components/pickers";
import DateRangePicker from "@/components/DateRangePicker.vue";
import type { DateRangeValue } from "@/lib/dateRange";

const period = defineModel<DateRangeValue>("period", { required: true });
const branches = defineModel<string[]>("branches", { default: () => [] });

const { t } = useI18n();
const scoped = useScopedBranches();
const picked = computed({
  get: () => branches.value.map(Number),
  set: (value: number[]) => (branches.value = value.map(String)),
});
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <DateRangePicker v-model="period" compare />
    <div v-if="scoped.length > 1" class="w-full sm:w-[240px]">
      <BranchPicker v-model="picked" multiple :placeholder="t('reports.allBranches')" />
    </div>
    <span class="flex-1" />
    <slot />
  </div>
</template>
