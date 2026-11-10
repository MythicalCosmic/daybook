<script setup lang="ts">
/**
 * Hiring (HR › Hiring): the vacancies, working ones first, each a card with its applicants by
 * stage, what waits to be looked at, and its link and QR code to share; the numbers across them on
 * top. "New vacancy" (also `?new=1` from the palette) opens the form with the question builder.
 * Without any vacancy yet, the page explains the three steps instead.
 */
import { BriefcaseBusiness, CircleCheck, Inbox, MessagesSquare, Plus, QrCode, Send, Trash2, UserCheck, XCircle } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { hiringApi, useHiringMutation, useVacancies } from "../api";
import ShareDialog from "../components/ShareDialog.vue";
import VacancyCard from "../components/VacancyCard.vue";
import VacancyFormDialog from "../components/VacancyFormDialog.vue";
import { inProgress, vacancyState } from "../lib";
import type { Vacancy } from "../types";

type View = "active" | "drafts" | "closed" | "all";

const { t } = useI18n();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();

const query = useVacancies();
const vacancies = computed(() => query.data.value ?? []);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const view = useRouteState<View>("view", rs.enum(["active", "drafts", "closed", "all"] as const, "active"));

function viewOf(vacancy: Vacancy): Exclude<View, "all"> {
  if (vacancy.status === "draft") return "drafts";
  if (vacancy.status === "closed" || vacancyState(vacancy, today.value) === "ended") return "closed";
  return "active";
}
const counts = computed(() => {
  const found = { active: 0, drafts: 0, closed: 0, all: vacancies.value.length };
  for (const vacancy of vacancies.value) found[viewOf(vacancy)] += 1;
  return found;
});
const shown = computed(() => (view.value === "all" ? vacancies.value : vacancies.value.filter((vacancy) => viewOf(vacancy) === view.value)));
const tabs = computed(() => (["active", "drafts", "closed", "all"] as const).map((id) => ({ id, label: t(`hr.hiring.tab.${id}`), count: counts.value[id] })));

const kpis = computed(() => {
  const rows = vacancies.value;
  const sum = (pick: (vacancy: Vacancy) => number) => rows.reduce((total, vacancy) => total + pick(vacancy), 0);
  return [
    { id: "open", label: t("hr.hiring.kpi.open"), value: rows.filter((vacancy) => vacancy.accepting).length, icon: BriefcaseBusiness, hint: t("hr.hiring.kpi.openHint") },
    { id: "new", label: t("hr.hiring.kpi.new"), value: sum((vacancy) => vacancy.counts.new), icon: Inbox, hint: t("hr.hiring.kpi.newHint") },
    { id: "progress", label: t("hr.hiring.kpi.progress"), value: sum((vacancy) => inProgress(vacancy.counts)), icon: MessagesSquare, hint: t("hr.hiring.kpi.progressHint") },
    { id: "hired", label: t("hr.hiring.kpi.hired"), value: sum((vacancy) => vacancy.counts.hired), icon: UserCheck, hint: t("hr.hiring.kpi.hiredHint") },
  ];
});

// The form: new (also from the palette, ?new=1) or an edit.
const formOpen = ref(false);
const editing = ref<Vacancy | null>(null);
function create(): void {
  editing.value = null;
  formOpen.value = true;
}
function edit(vacancy: Vacancy): void {
  editing.value = vacancy;
  formOpen.value = true;
}
const newParam = useRouteState("new", rs.boolean(false));
watch(
  newParam,
  (value) => {
    if (!value) return;
    newParam.value = false;
    if (company.can("hr.hiring")) create();
  },
  { immediate: true },
);
function saved(vacancy: Vacancy, created: boolean): void {
  if (created) {
    view.value = viewOf(vacancy) === "drafts" ? "drafts" : "active";
    if (vacancy.status === "open") share(vacancy);
  }
}

// Sharing.
const shareOpen = ref(false);
const sharing = ref<Vacancy | null>(null);
function share(vacancy: Vacancy): void {
  sharing.value = vacancy;
  shareOpen.value = true;
}

// Opening, pausing, closing, deleting.
const statusChange = useHiringMutation((cid, args: { id: number; verb: "open" | "pause" | "close" }) => hiringApi.setStatus(cid, args.id, args.verb));
const removal = useHiringMutation((cid, id: number) => hiringApi.removeVacancy(cid, id));

async function setStatus(vacancy: Vacancy, verb: "open" | "pause" | "close"): Promise<Vacancy | null> {
  if (verb === "close") {
    const answer = await confirm({
      title: t("hr.hiring.confirm.closeTitle", { title: vacancy.title }),
      message: t("hr.hiring.confirm.closeBody"),
      confirmLabel: t("hr.hiring.action.close"),
      icon: XCircle,
      onConfirm: () => statusChange.mutateAsync({ id: vacancy.id, verb }),
    });
    if (answer) toast.success(t("hr.hiring.toast.closed", { title: vacancy.title }));
    return null;
  }
  const updated = await statusChange.mutateAsync({ id: vacancy.id, verb });
  if (verb === "pause") {
    toast.info(t("hr.hiring.toast.paused", { title: vacancy.title }), {
      action: { label: t("common.undo"), onClick: () => statusChange.mutateAsync({ id: vacancy.id, verb: "open" }) },
    });
  } else {
    toast.success(t("hr.hiring.toast.opened", { title: vacancy.title }), { action: { label: t("hr.hiring.action.share"), onClick: () => share(updated) } });
  }
  return updated;
}

async function publishFromShare(vacancy: Vacancy): Promise<void> {
  const updated = await setStatus(vacancy, "open");
  if (updated) sharing.value = updated;
}

async function remove(vacancy: Vacancy): Promise<void> {
  const answer = await confirm({
    title: t("hr.hiring.confirm.deleteTitle", { title: vacancy.title }),
    message: t("hr.hiring.confirm.deleteBody"),
    tone: "danger",
    confirmLabel: t("common.delete"),
    icon: Trash2,
    onConfirm: () => removal.mutateAsync(vacancy.id),
  });
  if (answer) toast.success(t("hr.hiring.toast.deleted", { title: vacancy.title }));
}

const steps = computed(() => [
  { icon: BriefcaseBusiness, title: t("hr.hiring.empty.step1"), body: t("hr.hiring.empty.step1Body") },
  { icon: QrCode, title: t("hr.hiring.empty.step2"), body: t("hr.hiring.empty.step2Body") },
  { icon: Send, title: t("hr.hiring.empty.step3"), body: t("hr.hiring.empty.step3Body") },
  { icon: CircleCheck, title: t("hr.hiring.empty.step4"), body: t("hr.hiring.empty.step4Body") },
]);
</script>

<template>
  <div>
    <PageHeader v-model:tab="view" :title="t('hr.nav.hiring')" :description="t('hr.hiring.description')" :tabs="vacancies.length ? tabs : []">
      <template #actions>
        <UiButton variant="primary" :icon="Plus" data-new-vacancy @click="create">{{ t("hr.hiring.newVacancy") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />

    <div v-else-if="skeleton" class="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
      <SkeletonBlock v-for="n in 3" :key="n" height="248px" radius="12px" />
    </div>

    <!-- Nothing yet: how it works, in four steps -->
    <section v-else-if="query.data.value && !vacancies.length" class="ui-card overflow-hidden" data-hiring-empty>
      <div class="flex flex-col items-center px-5 pb-2 pt-10 text-center">
        <EmptyState :icon="BriefcaseBusiness" size="lg" :title="t('hr.hiring.empty.title')" :description="t('hr.hiring.empty.body')">
          <UiButton variant="primary" :icon="Plus" @click="create">{{ t("hr.hiring.newVacancy") }}</UiButton>
        </EmptyState>
      </div>
      <ol class="grid grid-cols-1 gap-px border-t border-line bg-[var(--c-border)] sm:grid-cols-2 xl:grid-cols-4">
        <li v-for="(step, index) in steps" :key="step.title" class="flex gap-3 bg-surface p-5">
          <span class="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-fg"><component :is="step.icon" :size="17" aria-hidden="true" /></span>
          <div class="min-w-0">
            <p class="text-sm font-semibold text-fg"><span class="tabular-nums text-subtle">{{ index + 1 }}. </span>{{ step.title }}</p>
            <p class="mt-0.5 text-sm text-muted">{{ step.body }}</p>
          </div>
        </li>
      </ol>
    </section>

    <div v-else-if="vacancies.length" class="flex flex-col gap-4">
      <KpiStrip :items="kpis" :columns="4" phone="grid" />
      <div v-if="shown.length" class="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3" data-vacancies>
        <VacancyCard v-for="vacancy in shown" :key="vacancy.id" :vacancy="vacancy" @share="share" @edit="edit" @status="setStatus" @remove="remove" />
      </div>
      <div v-else class="ui-card">
        <EmptyState :icon="BriefcaseBusiness" :title="t(`hr.hiring.emptyTab.${view}`)" :description="t('hr.hiring.emptyTabBody')">
          <UiButton v-if="view !== 'all'" variant="ghost" @click="view = 'all'">{{ t("hr.hiring.tab.all") }}</UiButton>
        </EmptyState>
      </div>
    </div>

    <VacancyFormDialog v-model:open="formOpen" :vacancy="editing" @saved="saved" />
    <ShareDialog v-model:open="shareOpen" :vacancy="sharing" @publish="publishFromShare" />
  </div>
</template>
