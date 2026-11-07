<script setup lang="ts">
/**
 * The marks a pharmacist looks for on a medicine: prescription only (Rx), controlled substance
 * (subject-quantitative accounting), cold chain, the mandatory assortment, socially significant.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiBadge from "@/components/UiBadge.vue";

import { isCold, isControlled } from "../lib";
import type { ControlClass, Storage } from "../types";

const props = withDefaults(
  defineProps<{
    rx?: boolean;
    control?: ControlClass;
    storage?: Storage;
    mandatory?: boolean;
    social?: boolean;
    eRx?: boolean;
    inactive?: boolean;
  }>(),
  { rx: false, control: "none", storage: "room", mandatory: false, social: false, eRx: false, inactive: false },
);

const { t } = useI18n();

const badges = computed(() => {
  const found: Array<{ key: string; label: string; title: string; tone: "danger" | "warning" | "info" | "primary" | "neutral" }> = [];
  if (props.rx) found.push({ key: "rx", label: t("stock.badge.rx"), title: t("stock.badge.rxTitle"), tone: "primary" });
  if (isControlled(props.control)) found.push({ key: "control", label: t(`stock.control.${props.control}`), title: t("stock.badge.controlledTitle"), tone: "danger" });
  if (isCold(props.storage)) found.push({ key: "cold", label: t(`stock.badge.${props.storage}`), title: t(`stock.storage.${props.storage}`), tone: "info" });
  if (props.mandatory) found.push({ key: "mandatory", label: t("stock.badge.mandatory"), title: t("stock.badge.mandatoryTitle"), tone: "warning" });
  if (props.social) found.push({ key: "social", label: t("stock.badge.social"), title: t("stock.badge.socialTitle"), tone: "neutral" });
  if (props.eRx) found.push({ key: "erx", label: t("stock.badge.eRx"), title: t("stock.badge.eRxTitle"), tone: "neutral" });
  if (props.inactive) found.push({ key: "inactive", label: t("stock.badge.inactive"), title: t("stock.badge.inactive"), tone: "neutral" });
  return found;
});
</script>

<template>
  <span v-if="badges.length" class="inline-flex flex-wrap items-center gap-1">
    <UiBadge v-for="badge in badges" :key="badge.key" :tone="badge.tone" size="sm" :title="badge.title" :data-badge="badge.key">{{ badge.label }}</UiBadge>
  </span>
</template>
