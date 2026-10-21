<script setup lang="ts">
/**
 * Overview KPI `overview.routines`: today's routine work, from `routines/day/` (the Routines
 * page's Today): runs finished out of those made, with what is late and what waits for a check.
 * Routine work is kept apart from one-off tasks, whose tiles say so (plan §15.2).
 */
import { Repeat } from "@lucide/vue";
import { useQuery } from "@tanstack/vue-query";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Range } from "@/api/types";
import KpiCard from "@/components/KpiCard.vue";

/** What this tile reads of `routines/day/` (apps.tasks.dashboard, the routines' `RoutineDay`). */
interface RoutineDayTotals {
  done: number;
  review: number;
  late: number;
  missed: number;
  total: number;
  /** Done or waiting for a check. */
  finished: number;
  routines: number;
}
interface RoutineDay {
  day: string;
  holiday: boolean;
  totals: RoutineDayTotals;
}

const props = defineProps<{ companyId: number; range?: Range; compare?: Range | null }>();
const { t } = useI18n();

// The Routines page's Today query (`useRoutineDay({})`): the same key, so one request feeds both,
// and the routines module's pulse keys refresh it.
const query = useQuery({
  queryKey: computed(() => qk(props.companyId, "routines", "day", {})),
  queryFn: ({ signal }) => http.get<RoutineDay>(ownerPath(props.companyId, "routines/day/"), {}, { signal }),
  enabled: computed(() => props.companyId > 0),
  staleTime: 15_000,
});
const totals = computed(() => query.data.value?.totals ?? null);

const hint = computed(() => {
  const day = query.data.value;
  if (!day) return undefined;
  if (day.holiday) return t("overview.routines.holiday");
  if (!day.totals.total) return t("overview.routines.none");
  const late = day.totals.late + day.totals.missed;
  const parts = [late ? t("overview.routines.late", { n: late }) : null, day.totals.review ? t("overview.routines.toConfirm", { n: day.totals.review }) : null].filter(Boolean);
  return parts.length ? parts.join(" · ") : t("overview.routines.onTrack");
});
</script>

<template>
  <KpiCard
    :error="query.isError.value ? query.error.value : undefined"
    :retry="() => query.refetch()"
    class="h-full"
    :icon="Repeat"
    :label="t('overview.routines.title')"
    :value="totals?.finished ?? null"
    :format="(value: number) => (totals ? t('overview.routines.ofTotal', { done: value, total: totals.total }) : String(value))"
    :hint="hint"
    :loading="query.isPending.value"
    :to="`/c/${props.companyId}/routines`"
  />
</template>
