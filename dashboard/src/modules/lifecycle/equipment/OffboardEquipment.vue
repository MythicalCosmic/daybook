<script setup lang="ts">
/**
 * In the offboarding wizard's equipment step (`people.offboard.step`): what the person still holds,
 * each with "It came back", "Lost" and "Deduct" acting now, before they go (a deduction can only
 * go to payroll while they still work here). What is left keeps the step's own choices below.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useCompanyStore } from "@/stores/company";

import { useAssetsOn, useEquipmentPerson } from "./api";
import HandoverEquipment from "./HandoverEquipment.vue";

const props = defineProps<{ context: { stepKey?: string; memberId?: number } }>();

const { t } = useI18n();
const company = useCompanyStore();
const assetsOn = useAssetsOn();
const memberId = computed(() => (props.context.stepKey === "assets" && assetsOn.value && company.can(["assets.manage", "hr.manage"]) ? (props.context.memberId ?? null) : null));
const page = useEquipmentPerson(memberId);
const shown = computed(() => memberId.value !== null && (page.data.value?.holder.items.length ?? 0) > 0);
</script>

<template>
  <div v-if="shown" class="flex flex-col gap-2" data-offboard-equipment>
    <p class="text-xs font-medium text-muted">{{ t("lifecycle.equipment.offboard.hint") }}</p>
    <HandoverEquipment :member-id="memberId!" />
  </div>
</template>
