<script setup lang="ts">
/**
 * Settings › Notifications (plan §1.10 "Notification preferences per kind"): for every kind of
 * alert the modules registered, whether it shows in the dashboard and whether Telegram gets it.
 * Kinds are grouped by the module they come from; approvals that live in "Needs you" always show
 * there. Each switch saves at once (and moves back if the server refuses).
 */
import { BellOff, BellRing, MessageCircle, MonitorSmartphone } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { usePreferences, useSavePreference } from "../api";
import PanelHeader from "../components/PanelHeader.vue";
import type { NotificationPreference } from "../types";

const { t, te } = useI18n();
const preferences = usePreferences();
const save = useSavePreference();
const showSkeleton = useDelayedPending(() => preferences.isPending.value);

const audience = ref<"owner" | "employee">("owner");
const counts = computed(() => {
  const rows = preferences.data.value ?? [];
  return { owner: rows.filter((r) => r.audience === "owner").length, employee: rows.filter((r) => r.audience === "employee").length };
});
const audiences = computed(() => [
  { value: "owner" as const, label: t("settings.notifications.asOwner"), count: counts.value.owner },
  { value: "employee" as const, label: t("settings.notifications.asEmployee"), count: counts.value.employee },
]);

const groups = computed(() => {
  const byApp = new Map<string, NotificationPreference[]>();
  for (const row of preferences.data.value ?? []) {
    if (row.audience !== audience.value) continue;
    const app = row.kind.split(".")[0]!;
    byApp.set(app, [...(byApp.get(app) ?? []), row]);
  }
  return [...byApp.entries()].map(([app, rows]) => ({ app, title: te(`settings.notifications.app.${app}`) ? t(`settings.notifications.app.${app}`) : app, rows }));
});

const severityTone = { info: "info", warning: "warning", critical: "danger" } as const;

function set(row: NotificationPreference, field: "in_app" | "telegram", value: boolean): void {
  save.mutate({ kind: row.kind, in_app: field === "in_app" ? value : row.in_app, telegram: field === "telegram" ? value : row.telegram });
}
</script>

<template>
  <div>
    <PanelHeader :title="t('settings.panel.notifications')" :description="t('settings.notifications.description')">
      <template v-if="counts.employee" #actions>
        <SegmentedControl v-model="audience" :options="audiences" size="sm" :aria-label="t('settings.notifications.audience')" />
      </template>
    </PanelHeader>

    <ErrorState v-if="preferences.isError.value" :error="preferences.error.value" :retry="() => preferences.refetch()" :retrying="preferences.isFetching.value" />

    <div v-else-if="showSkeleton || !preferences.data.value" class="ui-card flex flex-col gap-4 p-5" aria-busy="true">
      <div v-for="n in 4" :key="n" class="flex items-center gap-4"><SkeletonBlock width="45%" /><span class="flex-1" /><SkeletonBlock width="38px" height="22px" radius="11px" /><SkeletonBlock width="38px" height="22px" radius="11px" /></div>
    </div>

    <EmptyState v-else-if="!groups.length" :title="t('settings.notifications.emptyTitle')" :description="t('settings.notifications.emptyBody')" :icon="BellOff" tone="neutral" />

    <div v-else class="flex flex-col gap-5">
      <section v-for="group in groups" :key="group.app" class="ui-card overflow-hidden">
        <header class="flex items-center gap-3 border-b border-line bg-surface-2 px-4 py-2.5">
          <span class="min-w-0 flex-1 text-sm font-semibold text-fg">{{ group.title }}</span>
          <span class="hidden w-[92px] items-center justify-center gap-1.5 text-xs font-medium text-muted sm:flex"><MonitorSmartphone :size="13" />{{ t("settings.notifications.inApp") }}</span>
          <span class="hidden w-[92px] items-center justify-center gap-1.5 text-xs font-medium text-muted sm:flex"><MessageCircle :size="13" />Telegram</span>
        </header>
        <ul class="divide-y divide-line">
          <li v-for="row in group.rows" :key="row.kind" class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
            <span class="flex min-w-0 flex-1 basis-[220px] items-center gap-2">
              <span class="min-w-0 text-base text-fg sm:truncate">{{ row.label }}</span>
              <StatusPill v-if="row.severity !== 'info'" :tone="severityTone[row.severity]" size="sm" :label="t(`settings.notifications.severity.${row.severity}`)" />
            </span>
            <span class="flex w-full items-center justify-end gap-6 sm:w-auto sm:gap-0">
              <span class="flex items-center gap-2 sm:w-[92px] sm:justify-center">
                <span class="text-xs text-muted sm:hidden">{{ t("settings.notifications.inApp") }}</span>
                <UiTooltip :content="t('settings.notifications.inQueue')" :disabled="row.in_app_available">
                  <ToggleSwitch :model-value="row.in_app" size="sm" :disabled="!row.in_app_available" :aria-label="`${row.label}: ${t('settings.notifications.inApp')}`" @update:model-value="(v: boolean) => set(row, 'in_app', v)" />
                </UiTooltip>
              </span>
              <span class="flex items-center gap-2 sm:w-[92px] sm:justify-center">
                <span class="text-xs text-muted sm:hidden">Telegram</span>
                <ToggleSwitch :model-value="row.telegram" size="sm" :aria-label="`${row.label}: Telegram`" @update:model-value="(v: boolean) => set(row, 'telegram', v)" />
              </span>
            </span>
          </li>
        </ul>
      </section>
      <p class="flex items-center gap-2 text-sm text-muted"><BellRing :size="15" class="shrink-0 text-primary" />{{ t("settings.notifications.footer") }}</p>
    </div>
  </div>
</template>
