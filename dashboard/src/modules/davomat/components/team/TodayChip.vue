<script setup lang="ts">
/**
 * Where someone is today, as one chip: in the building since 08:02 (a breathing dot), gone home at
 * 18:10, not in yet though their shift started, a day off, on leave; "Left the company" for a
 * former employee. Nothing at all when the server knows nothing about today.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";

import type { EmployeeStatus, EmployeeToday } from "../../types";
import { TODAY_TONES } from "./team";

const props = withDefaults(defineProps<{ today: EmployeeToday | null; status?: EmployeeStatus; size?: "sm" | "md" }>(), { status: "active", size: "sm" });

const { t } = useI18n();
const fmt = useFormat();

const chip = computed(() => {
  if (props.status === "left") return { tone: "neutral" as const, label: t("davomat.team.today.former"), live: false };
  const today = props.today;
  if (!today) return null;
  const time = today.since ? fmt.instant(today.since, "time") : "";
  if (today.state === "in") return { tone: TODAY_TONES.in, label: time ? t("davomat.team.today.in", { time }) : t("davomat.team.today.inNoTime"), live: true };
  if (today.state === "out") return { tone: TODAY_TONES.out, label: time ? t("davomat.team.today.out", { time }) : t("davomat.team.today.outNoTime"), live: false };
  return { tone: TODAY_TONES[today.state], label: t(`davomat.team.today.${today.state}`), live: false };
});
</script>

<template>
  <StatusPill v-if="chip" :tone="chip.tone" :label="chip.label" :live="chip.live" :size="size" class="tabular-nums" data-today-chip />
</template>
