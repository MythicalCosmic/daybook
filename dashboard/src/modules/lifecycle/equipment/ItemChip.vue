<script setup lang="ts">
/**
 * Something a person holds, as a chip: its photo (or the category's icon), name, number, whether
 * they confirmed it in the app, and the deduction proposed for it. The chip opens its menu: it came
 * back, it is lost, propose a deduction, see it in the register.
 */
import { ArrowUpRight, CircleCheck, Clock, HandCoins, PackageCheck, PackageX } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import DropdownMenu from "@/components/DropdownMenu.vue";
import type { MenuEntry } from "@/components/menuTypes";
import UiTooltip from "@/components/UiTooltip.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";
import type { Currency } from "@/api/types";

import { categoryIcon, confirmation, returnOptions } from "./lib";
import type { EquipmentCan, HeldItem, Holder } from "./types";

const props = defineProps<{ holder: Pick<Holder, "person">; item: HeldItem; can: EquipmentCan; today: string }>();
const emit = defineEmits<{ action: [kind: "returned" | "lost" | "deduct", item: HeldItem] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const router = useRouter();

const state = computed(() => confirmation(props.item, props.today));
const options = computed(() => returnOptions(props.holder, props.item, props.can));
const confirmText = computed(() =>
  props.item.acknowledged_at ? t("lifecycle.equipment.confirmedAt", { date: fmt.instant(props.item.acknowledged_at, "datetime") }) : t("lifecycle.equipment.notConfirmedSince", { date: fmt.day(props.item.issued_on, "short") }),
);
const deductionText = computed(() => {
  const deduction = props.item.deduction;
  if (!deduction) return null;
  const status = t(`lifecycle.equipment.deduction.status.${deduction.status}`);
  return deduction.amount ? `${status}: ${fmt.money(deduction.amount, deduction.currency as Currency)}` : status;
});

const menu = computed<MenuEntry[]>(() => {
  const items: MenuEntry[] = [
    { label: t("lifecycle.equipment.action.returned"), icon: PackageCheck, onSelect: () => emit("action", "returned", props.item) },
    {
      label: t("lifecycle.equipment.action.lost"),
      icon: PackageX,
      danger: true,
      disabled: !options.value.writeOff,
      description: options.value.writeOff ? undefined : t("lifecycle.equipment.return.deviceNote"),
      onSelect: () => emit("action", "lost", props.item),
    },
  ];
  if (props.can.deduct)
    items.push({
      label: t("lifecycle.equipment.action.deduct"),
      icon: HandCoins,
      disabled: !options.value.deduct,
      description: options.value.deductWhy ? t(`lifecycle.equipment.deduction.why.${options.value.deductWhy}`) : undefined,
      onSelect: () => emit("action", "deduct", props.item),
    });
  if (props.can.register) {
    items.push({ type: "separator" });
    items.push({ label: t("lifecycle.equipment.action.register"), icon: ArrowUpRight, onSelect: () => void router.push(`/c/${company.currentId}/assets/items/${props.item.asset_id}`) });
  }
  return items;
});
</script>

<template>
  <DropdownMenu :items="menu" align="start" width="260px">
    <template #trigger>
      <button
        type="button"
        class="group/chip inline-flex max-w-full items-center gap-2 rounded-[10px] border border-line bg-surface py-1 pl-1 pr-2.5 text-left transition-[border-color,box-shadow] hover:border-line-strong hover:shadow-[var(--sh-xs)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--c-ring)]"
        :aria-label="t('lifecycle.equipment.itemLabel', { name: item.name, number: item.number })"
        :data-item="item.assignment_id"
      >
        <img v-if="item.photo_url" :src="item.photo_url" alt="" class="size-7 shrink-0 rounded-[7px] object-cover" />
        <span v-else class="grid size-7 shrink-0 place-items-center rounded-[7px] bg-surface-2 text-muted dark:bg-surface-3"><component :is="categoryIcon(item.category.icon)" :size="14" aria-hidden="true" /></span>
        <span class="min-w-0 leading-tight">
          <span class="block truncate text-sm font-medium text-fg">{{ item.name }}</span>
          <span class="block truncate text-[11px] tabular-nums text-muted">{{ [item.number, item.notes].filter(Boolean).join(" · ") }}</span>
        </span>
        <UiTooltip :content="confirmText">
          <span class="shrink-0" :data-confirmed="item.acknowledged_at ? 'true' : 'false'">
            <CircleCheck v-if="state.state === 'confirmed'" :size="14" class="text-success" :aria-label="confirmText" role="img" />
            <Clock v-else :size="14" :class="state.state === 'late' ? 'text-warning' : 'text-subtle'" :aria-label="confirmText" role="img" />
          </span>
        </UiTooltip>
        <UiTooltip v-if="deductionText" :content="deductionText">
          <HandCoins :size="14" class="shrink-0 text-info" :aria-label="deductionText" role="img" />
        </UiTooltip>
      </button>
    </template>
  </DropdownMenu>
</template>
