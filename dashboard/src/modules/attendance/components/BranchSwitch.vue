<script setup lang="ts">
/**
 * "All branches · Chilonzor · Yunusobod" as a segmented control (a select from five branches up).
 * Only branches in the person's scope; hidden when they see just one.
 */
import { Building2 } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useScopedBranches } from "@/components/pickers";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SelectBox from "@/components/SelectBox.vue";

const model = defineModel<number | null>({ required: true });
withDefaults(defineProps<{ size?: "sm" | "md"; allowAll?: boolean }>(), { size: "sm", allowAll: true });

const { t } = useI18n();
const branches = useScopedBranches();
const ALL = 0;

const options = computed(() => [
  { value: ALL, label: t("attendance.allBranches") },
  ...branches.value.map((branch) => ({ value: branch.id, label: branch.name })),
]);
const value = computed({
  get: () => model.value ?? ALL,
  set: (next: number) => (model.value = next === ALL ? null : next),
});
</script>

<template>
  <template v-if="branches.length > 1">
    <SegmentedControl v-if="branches.length <= 4" v-model="value" :options="options" :size="size" :aria-label="t('attendance.branch')" />
    <div v-else class="flex items-center gap-1.5">
      <Building2 :size="14" class="text-subtle" aria-hidden="true" />
      <SelectBox v-model="value" :options="options" size="sm" class="w-44" />
    </div>
  </template>
</template>
