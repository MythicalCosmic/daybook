<script setup lang="ts">
/**
 * A vacancy on the Hiring page: its title, where and for which job, its state (open, paused, a
 * draft, closed, or open but past its last day), the pay, how many applied and how many wait to
 * be looked at, the stage bar, and its actions: share the link or QR code, open the board, and the
 * menu (edit, pause or open, close, delete one nobody applied for).
 */
import { ArrowRight, CalendarClock, EllipsisVertical, FileImage, ListChecks, MapPin, Pause, Pencil, Play, QrCode, Share2, Trash2, XCircle } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import IconButton from "@/components/IconButton.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { STATE_TONES, inProgress, vacancyState } from "../lib";
import type { Vacancy } from "../types";
import StageBar from "./StageBar.vue";

const props = defineProps<{ vacancy: Vacancy }>();
const emit = defineEmits<{ share: [vacancy: Vacancy]; edit: [vacancy: Vacancy]; status: [vacancy: Vacancy, verb: "open" | "pause" | "close"]; remove: [vacancy: Vacancy] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const today = useCompanyToday();

const state = computed(() => vacancyState(props.vacancy, today.value));
const to = computed(() => `/c/${company.currentId}/hr/hiring/${props.vacancy.id}`);
const working = computed(() => inProgress(props.vacancy.counts));
const salary = computed(() => {
  const { salary_from: low, salary_to: high, currency } = props.vacancy;
  if (low && high) return low === high ? fmt.money(low, currency) : `${fmt.money(low, currency, { currencyDisplay: "none" })} – ${fmt.money(high, currency)}`;
  if (low) return t("hr.hiring.salaryFrom", { amount: fmt.money(low, currency) });
  if (high) return t("hr.hiring.salaryUpTo", { amount: fmt.money(high, currency) });
  return null;
});
const dates = computed(() => {
  const v = props.vacancy;
  if (state.value === "scheduled" && v.opens_on) return t("hr.hiring.opensOn", { date: fmt.day(v.opens_on, "short") });
  if (v.closes_on && (state.value === "open" || state.value === "paused")) return t("hr.hiring.until", { date: fmt.day(v.closes_on, "short") });
  if (state.value === "ended" && v.closes_on) return t("hr.hiring.endedOn", { date: fmt.day(v.closes_on, "short") });
  return null;
});

const menu = computed<MenuEntry[]>(() => {
  const v = props.vacancy;
  const entries: MenuEntry[] = [{ label: t("common.edit"), icon: Pencil, onSelect: () => emit("edit", v) }];
  if (v.status === "open") entries.push({ label: t("hr.hiring.action.pause"), icon: Pause, onSelect: () => emit("status", v, "pause") });
  if (v.status !== "open") entries.push({ label: t(v.status === "draft" ? "hr.hiring.action.publish" : "hr.hiring.action.open"), icon: Play, onSelect: () => emit("status", v, "open") });
  if (v.status !== "closed") entries.push({ label: t("hr.hiring.action.close"), icon: XCircle, onSelect: () => emit("status", v, "close") });
  if (!v.counts.total) {
    entries.push({ type: "separator" });
    entries.push({ label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => emit("remove", v) });
  }
  return entries;
});
</script>

<template>
  <article
    :class="['ui-card group relative flex flex-col gap-4 p-4 transition-[border-color,box-shadow] duration-150 hover:border-line-strong', (vacancy.status === 'closed' || state === 'ended') && 'opacity-80']"
    data-vacancy-card
    :data-vacancy="vacancy.id"
  >
    <header class="flex items-start gap-3">
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <RouterLink :to="to" class="min-w-0 truncate text-md font-semibold text-fg after:absolute after:inset-0 after:rounded-[inherit] hover:text-primary">{{ vacancy.title }}</RouterLink>
          <StatusPill :tone="STATE_TONES[state]" size="sm" :live="state === 'open'" :label="t(`hr.hiring.state.${state}`)" />
        </div>
        <p class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-muted">
          <span class="inline-flex items-center gap-1"><MapPin :size="13" aria-hidden="true" />{{ vacancy.branch?.name ?? t("hr.hiring.anyBranch") }}</span>
          <span v-if="vacancy.position && vacancy.position.name !== vacancy.title">{{ vacancy.position.name }}</span>
          <span v-if="dates" class="inline-flex items-center gap-1"><CalendarClock :size="13" aria-hidden="true" />{{ dates }}</span>
        </p>
      </div>
      <DropdownMenu :items="menu" align="end">
        <template #trigger><IconButton class="relative z-[1]" :icon="EllipsisVertical" :label="t('common.more')" /></template>
      </DropdownMenu>
    </header>

    <div class="flex items-end justify-between gap-3">
      <div class="min-w-0">
        <p class="flex items-baseline gap-2">
          <span class="text-[28px] font-semibold leading-none tabular-nums text-fg">{{ vacancy.counts.total }}</span>
          <span class="text-sm text-muted">{{ t("hr.hiring.applicantsCount", { n: vacancy.counts.total }, vacancy.counts.total) }}</span>
        </p>
        <p class="mt-1.5 text-xs text-muted">
          <template v-if="working">{{ t("hr.hiring.inProgress", { n: working }, working) }} · </template>{{ t("hr.hiring.opened", { n: vacancy.link_opens }, vacancy.link_opens) }}
        </p>
      </div>
      <span v-if="vacancy.counts.new" class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent-fg" data-new-count>
        <span class="size-1.5 rounded-full bg-primary" aria-hidden="true" />{{ t("hr.hiring.newCount", { n: vacancy.counts.new }, vacancy.counts.new) }}
      </span>
    </div>

    <StageBar :counts="vacancy.counts" />

    <p v-if="salary || vacancy.asks_document || vacancy.questions.length" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
      <span v-if="salary" class="font-semibold tabular-nums text-fg">{{ salary }}</span>
      <span v-if="vacancy.questions.length" class="inline-flex items-center gap-1"><ListChecks :size="13" aria-hidden="true" />{{ t("hr.hiring.questionsCount", { n: vacancy.questions.length }, vacancy.questions.length) }}</span>
      <span v-if="vacancy.asks_document" class="inline-flex items-center gap-1"><FileImage :size="13" aria-hidden="true" />{{ t("hr.hiring.asksDocument") }}</span>
    </p>

    <footer class="relative z-[1] mt-auto flex items-center gap-2 border-t border-line pt-3">
      <UiButton size="sm" :icon="vacancy.link ? QrCode : Share2" data-share-open @click="emit('share', vacancy)">{{ t("hr.hiring.action.share") }}</UiButton>
      <span class="flex-1" />
      <UiButton size="sm" variant="ghost" :icon-right="ArrowRight" :to="to">{{ t("hr.hiring.action.board") }}</UiButton>
    </footer>
  </article>
</template>
