<script setup lang="ts">
/**
 * Person 360's "Career" tab (plan §13.4): their working life here as one line, newest first.
 * Changes still to come ("From 1 December"), their leaving (asked, agreed, left), the job changes
 * that took effect (position, branch, department, pay: the pay for payroll.view) and the day they
 * joined. A change or a leaving opens in its own panel without leaving the page.
 */
import { CalendarClock, CircleCheck, DoorOpen, LogOut, Plus, Shuffle, Sparkles, UserRoundPlus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useCareer } from "../api";
import { CHANGE_TONES, changeAccess, LEAVING_TONES } from "../lib";
import type { JobChange, LeavingRow } from "../types";
import ChangeDrawer from "./ChangeDrawer.vue";
import ChangeLines from "./ChangeLines.vue";
import CountdownText from "./CountdownText.vue";
import LeavingDrawer from "./LeavingDrawer.vue";
import ProposeChangeDialog from "./ProposeChangeDialog.vue";

const props = defineProps<{ memberId: number }>();

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const access = computed(() => changeAccess((perm) => company.can(perm)));

const career = useCareer(() => props.memberId);
const data = computed(() => career.data.value ?? null);

type Entry =
  | { key: string; day: string; kind: "change"; change: JobChange }
  | { key: string; day: string; kind: "leaving"; leaving: LeavingRow }
  | { key: string; day: string; kind: "hired" };
const entries = computed<Entry[]>(() => {
  const value = data.value;
  if (!value) return [];
  const list: Entry[] = [
    ...value.changes.map((change) => ({ key: `c${change.id}`, day: change.effective_on, kind: "change" as const, change })),
    ...value.leavings.map((leaving) => ({ key: `l${leaving.id}`, day: leaving.left_on ?? leaving.last_day ?? leaving.wished_last_day ?? leaving.requested_at.slice(0, 10), kind: "leaving" as const, leaving })),
  ];
  list.sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
  if (value.hired_on) list.push({ key: "hired", day: value.hired_on, kind: "hired" });
  return list;
});
const hasHistory = computed(() => entries.value.some((entry) => entry.kind !== "hired"));

function openChange(id: number): void {
  void router.push({ query: { ...route.query, change: String(id) } });
}
function openLeaving(id: number): void {
  void router.push({ query: { ...route.query, termination: String(id) } });
}
const proposing = ref(false);
/** The dialog names them from their job today. */
const member = computed(() => ({ id: props.memberId, name: "" }));

function leavingTitle(row: LeavingRow): string {
  if (row.status === "completed") return t("lifecycle.career.left");
  if (row.status === "agreed") return t("lifecycle.career.lastDay");
  return t("lifecycle.career.asked");
}
</script>

<template>
  <section class="ui-card p-5" data-career>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold text-fg">{{ t("lifecycle.career.title") }}</h2>
        <p class="text-sm text-muted">{{ t("lifecycle.career.description") }}</p>
      </div>
      <UiButton v-if="access.propose" size="sm" :icon="Plus" @click="proposing = true">{{ t("lifecycle.person.changeJob") }}</UiButton>
    </div>

    <div v-if="career.isPending.value" class="flex flex-col gap-3">
      <SkeletonBlock v-for="n in 3" :key="n" height="64px" radius="12px" />
    </div>
    <ErrorState v-else-if="career.isError.value" :error="career.error.value" :retry="() => career.refetch()" />
    <template v-else>
      <EmptyState v-if="!hasHistory" :icon="Sparkles" tone="neutral" size="sm" :title="t('lifecycle.career.empty')" :description="t('lifecycle.career.emptyBody')" class="mb-2" />
      <ol class="relative flex flex-col">
        <li v-for="(entry, index) in entries" :key="entry.key" class="relative flex gap-4 pb-5 last:pb-0">
          <!-- The line between the dots -->
          <span v-if="index < entries.length - 1" class="absolute left-[17px] top-9 bottom-0 w-px bg-line" aria-hidden="true" />
          <span
            :class="[
              'relative z-[1] grid size-9 shrink-0 place-items-center rounded-full border',
              entry.kind === 'hired'
                ? 'border-line bg-surface-2 text-muted'
                : entry.kind === 'leaving'
                  ? 'border-transparent bg-warning-soft text-warning'
                  : entry.change.status === 'approved'
                    ? 'border-dashed border-[var(--c-primary)] bg-primary-soft text-primary'
                    : 'border-transparent bg-success-soft text-success',
            ]"
            aria-hidden="true"
          >
            <UserRoundPlus v-if="entry.kind === 'hired'" :size="16" />
            <LogOut v-else-if="entry.kind === 'leaving' && entry.leaving.status === 'completed'" :size="16" />
            <DoorOpen v-else-if="entry.kind === 'leaving'" :size="16" />
            <CalendarClock v-else-if="entry.change.status === 'approved'" :size="16" />
            <Shuffle v-else :size="16" />
          </span>

          <div v-if="entry.kind === 'hired'" class="min-w-0 flex-1 pt-1.5">
            <p class="text-sm font-medium text-fg">{{ t("lifecycle.career.hired") }}</p>
            <p class="text-xs tabular-nums text-muted">{{ fmt.day(entry.day, "long") }}</p>
          </div>

          <button
            v-else-if="entry.kind === 'leaving'"
            type="button"
            class="min-w-0 flex-1 rounded-[12px] border border-line px-3.5 py-3 text-left transition-colors hover:border-line-strong hover:bg-surface-2/50"
            @click="openLeaving(entry.leaving.id)"
          >
            <div class="flex flex-wrap items-center gap-2">
              <p class="text-sm font-semibold text-fg">{{ leavingTitle(entry.leaving) }}: {{ fmt.day(entry.day, "medium") }}</p>
              <StatusPill size="sm" variant="outline" :tone="LEAVING_TONES[entry.leaving.status]" :label="t(`lifecycle.leavingStatus.${entry.leaving.status}`)" />
            </div>
            <p class="mt-0.5 text-xs text-muted">
              {{ t(`lifecycle.leavingKind.${entry.leaving.kind}`) }}
              <template v-if="entry.leaving.status === 'agreed'"> · <CountdownText :day="entry.leaving.last_day" :today="today" /></template>
            </p>
          </button>

          <button
            v-else
            type="button"
            :class="[
              'min-w-0 flex-1 rounded-[12px] border px-3.5 py-3 text-left transition-colors hover:bg-surface-2/50',
              entry.change.status === 'approved' ? 'border-dashed border-[color-mix(in_srgb,var(--c-primary)_45%,transparent)]' : 'border-line hover:border-line-strong',
            ]"
            @click="openChange(entry.change.id)"
          >
            <div class="mb-2 flex flex-wrap items-center gap-2">
              <p class="text-sm font-semibold tabular-nums text-fg">
                {{ entry.change.status === "approved" ? t("lifecycle.changes.from", { date: fmt.day(entry.day, "medium") }) : fmt.day(entry.day, "medium") }}
              </p>
              <StatusPill
                size="sm"
                variant="outline"
                :tone="entry.change.status === 'approved' ? 'info' : CHANGE_TONES[entry.change.status]"
                :label="entry.change.status === 'approved' ? t('lifecycle.career.coming') : t(`lifecycle.changeStatus.${entry.change.status}`)"
              />
              <CountdownText v-if="entry.change.status === 'approved'" :day="entry.day" :today="today" class="text-xs text-muted" />
              <CircleCheck v-else :size="14" class="text-success" aria-hidden="true" />
            </div>
            <ChangeLines :change="entry.change" />
          </button>
        </li>
      </ol>
    </template>

    <ChangeDrawer />
    <LeavingDrawer />
    <ProposeChangeDialog v-model:open="proposing" :member="member" @saved="(change) => openChange(change.id)" />
  </section>
</template>
