<script setup lang="ts">
/**
 * The actions on a piece of equipment someone still holds while they leave, where it is listed:
 * the leaving's handover list and the offboarding wizard's equipment step. It came back (with its
 * condition and a photo), it is lost (written off), or a deduction from their pay goes to payroll.
 * Shown to whoever runs the equipment (assets.manage or hr.manage) while the assets module is on.
 *
 * With `assetId` it acts on that one thing; without, it lists everything the person holds.
 */
import { HandCoins, PackageCheck, PackageX } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useAssetsOn, useEquipmentPerson } from "./api";
import DeductionDialog from "./DeductionDialog.vue";
import { categoryIcon, returnOptions } from "./lib";
import ReturnDialog from "./ReturnDialog.vue";
import type { HeldItem } from "./types";

const props = withDefaults(defineProps<{ memberId: number; assetId?: number | null }>(), { assetId: null });

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const assetsOn = useAssetsOn();
const allowed = computed(() => assetsOn.value && company.can(["assets.manage", "hr.manage"]));
const page = useEquipmentPerson(computed(() => (allowed.value ? props.memberId : null)));
const data = computed(() => page.data.value ?? null);
const items = computed(() => (data.value?.holder.items ?? []).filter((item) => props.assetId === null || item.asset_id === props.assetId));

let key = 0;
const returning = ref<{ item: HeldItem; start: "returned" | "lost"; key: number } | null>(null);
const deducting = ref<{ item: HeldItem; key: number } | null>(null);
const returnOpen = computed({ get: () => returning.value !== null, set: (value: boolean) => !value && (returning.value = null) });
const deductOpen = computed({ get: () => deducting.value !== null, set: (value: boolean) => !value && (deducting.value = null) });
</script>

<template>
  <div v-if="allowed && data && items.length" :class="assetId === null ? 'flex flex-col gap-2' : 'mt-2'" data-handover-equipment>
    <div v-for="item in items" :key="item.assignment_id" :class="assetId === null ? 'flex flex-col gap-2 rounded-[12px] border border-line p-3 sm:flex-row sm:items-center' : 'flex flex-wrap items-center gap-1.5'">
      <div v-if="assetId === null" class="flex min-w-0 flex-1 items-center gap-2.5">
        <img v-if="item.photo_url" :src="item.photo_url" alt="" class="size-10 shrink-0 rounded-[9px] object-cover ring-1 ring-line" />
        <span v-else class="grid size-10 shrink-0 place-items-center rounded-[9px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(item.category.icon)" :size="16" aria-hidden="true" /></span>
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-fg">{{ item.number }} {{ item.name }}</p>
          <p class="truncate text-xs text-muted">{{ t("lifecycle.equipment.givenOn", { date: fmt.day(item.issued_on, "medium") }) }}<template v-if="!item.acknowledged_at"> · {{ t("lifecycle.equipment.notConfirmed") }}</template></p>
        </div>
        <StatusPill v-if="item.deduction" size="sm" tone="info" :icon="HandCoins" :label="t(`lifecycle.equipment.deduction.status.${item.deduction.status}`)" />
      </div>
      <div class="flex flex-wrap gap-1.5">
        <UiButton size="sm" variant="secondary" :icon="PackageCheck" data-handover-return @click="returning = { item, start: 'returned', key: ++key }">{{ t("lifecycle.equipment.action.returnedShort") }}</UiButton>
        <UiButton v-if="item.may_write_off" size="sm" variant="ghost" :icon="PackageX" data-handover-lost @click="returning = { item, start: 'lost', key: ++key }">{{ t("lifecycle.equipment.action.lostShort") }}</UiButton>
        <UiButton v-if="returnOptions(data.holder, item, data.can).deduct" size="sm" variant="ghost" :icon="HandCoins" data-handover-deduct @click="deducting = { item, key: ++key }">{{ t("lifecycle.equipment.action.deductShort") }}</UiButton>
        <StatusPill v-else-if="assetId !== null && item.deduction" size="sm" tone="info" :icon="HandCoins" :label="t(`lifecycle.equipment.deduction.status.${item.deduction.status}`)" />
      </div>
    </div>
    <ReturnDialog v-if="returning" :key="returning.key" v-model:open="returnOpen" :holder="data.holder" :item="returning.item" :can="data.can" :start="returning.start" />
    <DeductionDialog v-if="deducting" :key="deducting.key" v-model:open="deductOpen" :holder="data.holder" :item="deducting.item" />
  </div>
</template>
