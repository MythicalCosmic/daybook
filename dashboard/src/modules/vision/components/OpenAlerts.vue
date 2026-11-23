<script setup lang="ts">
/**
 * The alerts open right now: what, where, for how long (ticking) and who said they are going. Each
 * opens its detail on the alerts page. Calm counters say so.
 */
import { ArrowRight, BellRing, CircleCheck, Hand, UsersRound, WifiOff } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import { useCompanyStore } from "@/stores/company";

import { useSecondClock } from "../lib/clock";
import { alertWeight } from "../lib/look";
import { formatClock } from "../lib/tracks";
import type { Alert } from "../types";

const props = defineProps<{ alerts: Alert[] }>();

const { t } = useI18n();
const company = useCompanyStore();
const clock = useSecondClock();

const items = computed(() =>
  [...props.alerts]
    .sort((a, b) => alertWeight(a.kind) - alertWeight(b.kind) || a.started_at.localeCompare(b.started_at))
    .map((alert) => ({ alert, since: formatClock(Math.max(0, (clock.value - new Date(alert.started_at).getTime()) / 1000)) })),
);
const base = computed(() => `/c/${company.currentId}/vision/alerts`);
</script>

<template>
  <section class="ui-card flex min-w-0 flex-col" :aria-label="t('vision.openAlerts.title')">
    <header class="flex items-center gap-2.5 px-4 pb-2 pt-4">
      <span :class="['grid size-7 place-items-center rounded-[9px]', items.length ? 'bg-warning-soft text-warning' : 'bg-success-soft text-success']"><BellRing :size="15" /></span>
      <h2 class="flex-1 text-base font-semibold text-fg">{{ t("vision.openAlerts.title") }}</h2>
      <RouterLink :to="base" class="inline-flex items-center gap-1 text-xs font-semibold text-muted transition-colors hover:text-fg">{{ t("vision.openAlerts.all") }}<ArrowRight :size="13" /></RouterLink>
    </header>
    <p v-if="!items.length" class="flex items-center gap-2 px-4 pb-4 pt-1 text-sm text-muted"><CircleCheck :size="16" class="shrink-0 text-success" />{{ t("vision.openAlerts.none") }}</p>
    <ul v-else class="flex flex-col px-2 pb-2">
      <li v-for="{ alert, since } in items" :key="alert.id">
        <RouterLink :to="`${base}?alert=${alert.id}`" class="flex items-center gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-highlight" :data-alert="alert.id">
          <span :class="['grid size-8 shrink-0 place-items-center rounded-full', alert.kind === 'unattended' ? 'bg-danger-soft text-danger' : alert.kind === 'queue' ? 'bg-warning-soft text-warning' : 'bg-surface-2 text-muted']">
            <Hand v-if="alert.kind === 'unattended'" :size="15" />
            <WifiOff v-else-if="alert.kind === 'agent_offline'" :size="15" />
            <UsersRound v-else :size="15" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-semibold text-fg">{{ t(`vision.alert.kind.${alert.kind}`) }}</span>
            <span class="block truncate text-xs text-muted">{{ [alert.camera?.name, alert.branch.name].filter(Boolean).join(" · ") }}<template v-if="alert.acknowledged_by"> · {{ t("vision.banner.going", { name: alert.acknowledged_by.name }) }}</template></span>
          </span>
          <span :class="['shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums', alert.kind === 'unattended' ? 'bg-danger-soft text-danger' : 'bg-warning-soft text-warning']">{{ since }}</span>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
