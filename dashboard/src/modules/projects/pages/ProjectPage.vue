<script setup lang="ts">
/**
 * One project (plan §13.3 "Project page tabs"): the header with health, lead, dates and team, and
 * the tabs Board, List, Timeline, Milestones, People, Time, Money, Updates, Files and links,
 * Settings. The tab is in the path (`projects/12/board`); an open card is `?card=345` on any tab.
 */
import { Archive, ArchiveRestore, CalendarDays, Ellipsis, FileText, Flag, FolderKanban, GanttChart, HeartPulse, Kanban, MessageSquarePlus, Paperclip, Pencil, Rows3, Settings2, Timer, Users, Wallet } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import AvatarStack from "@/components/AvatarStack.vue";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PageHeader, { type PageTab } from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { todayIn } from "@/lib/dates";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";

import { archiveProject, restoreProject, useProject, useRefreshProjects } from "../api";
import CardDrawer from "../components/CardDrawer.vue";
import HealthDot from "../components/HealthDot.vue";
import ProjectBadge from "../components/ProjectBadge.vue";
import ProjectFormDialog from "../components/ProjectFormDialog.vue";
import UpdateDialog from "../components/UpdateDialog.vue";
import { daysBetween, STATUS_TONE } from "../lib";
import { PROJECT_TABS, type ProjectTab } from "../types";

const BoardTab = defineAsyncComponent(() => import("../components/BoardTab.vue"));
const ListTab = defineAsyncComponent(() => import("../components/ListTab.vue"));
const TimelineTab = defineAsyncComponent(() => import("../components/TimelineTab.vue"));
const MilestonesTab = defineAsyncComponent(() => import("../components/MilestonesTab.vue"));
const PeopleTab = defineAsyncComponent(() => import("../components/PeopleTab.vue"));
const TimeTab = defineAsyncComponent(() => import("../components/TimeTab.vue"));
const MoneyTab = defineAsyncComponent(() => import("../components/MoneyTab.vue"));
const UpdatesTab = defineAsyncComponent(() => import("../components/UpdatesTab.vue"));
const FilesTab = defineAsyncComponent(() => import("../components/FilesTab.vue"));
const SettingsTab = defineAsyncComponent(() => import("../components/SettingsTab.vue"));

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefreshProjects();

const projectId = computed(() => Number(route.params.projectId) || 0);
const query = useProject(projectId);
const project = computed(() => query.data.value ?? null);
// The breadcrumb and the browser tab say which project this is.
usePageTitle(() => project.value?.name);
const caps = computed(() => project.value?.capabilities);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const notFound = computed(() => isApiError(query.error.value) && query.error.value.status === 404);

const base = computed(() => `/c/${company.currentId}/projects/${projectId.value}`);
const tab = computed<ProjectTab>(() => {
  const value = String(route.params.tab ?? "board") as ProjectTab;
  return PROJECT_TABS.includes(value) ? value : "board";
});

const tabs = computed<PageTab[]>(() => {
  const list: PageTab[] = [
    { id: "board", label: t("projects.tab.board"), icon: Kanban, to: `${base.value}/board` },
    { id: "list", label: t("projects.tab.list"), icon: Rows3, to: `${base.value}/list` },
    { id: "timeline", label: t("projects.tab.timeline"), icon: GanttChart, to: `${base.value}/timeline` },
    { id: "milestones", label: t("projects.tab.milestones"), icon: Flag, to: `${base.value}/milestones` },
    { id: "people", label: t("projects.tab.people"), icon: Users, to: `${base.value}/people`, count: project.value?.member_count },
    { id: "time", label: t("projects.tab.time"), icon: Timer, to: `${base.value}/time` },
  ];
  if (caps.value?.see_money) list.push({ id: "money", label: t("projects.tab.money"), icon: Wallet, to: `${base.value}/money` });
  list.push({ id: "updates", label: t("projects.tab.updates"), icon: HeartPulse, to: `${base.value}/updates` });
  list.push({ id: "files", label: t("projects.tab.files"), icon: Paperclip, to: `${base.value}/files` });
  if (caps.value?.manage) list.push({ id: "settings", label: t("projects.tab.settings"), icon: Settings2, to: `${base.value}/settings` });
  return list;
});

// A tab the person may not open (money, settings) falls back to the board.
watch(
  () => [tab.value, caps.value] as const,
  ([current, capabilities]) => {
    if (!capabilities) return;
    if ((current === "money" && !capabilities.see_money) || (current === "settings" && !capabilities.manage)) void router.replace(`${base.value}/board`);
  },
);

const editing = ref(false);
const posting = ref(false);

const menu = computed<MenuEntry[]>(() => {
  const p = project.value;
  if (!p || !caps.value?.manage) return [];
  return [
    { label: t("projects.action.edit"), icon: Pencil, onSelect: () => (editing.value = true) },
    { label: t("projects.action.settings"), icon: Settings2, onSelect: () => void router.push(`${base.value}/settings`) },
    { type: "separator" },
    p.archived_at
      ? { label: t("projects.action.restore"), icon: ArchiveRestore, onSelect: () => void restore() }
      : { label: t("projects.action.archive"), icon: Archive, danger: true, onSelect: () => void archive() },
  ];
});

async function archive(): Promise<void> {
  const p = project.value;
  if (!p) return;
  const answer = await confirm({ title: t("projects.archive.title", { key: p.key }), message: t("projects.archive.body"), confirmLabel: t("projects.action.archive"), tone: "danger", icon: Archive });
  if (!answer) return;
  await archiveProject(company.currentId ?? 0, p.id);
  toast.success(t("projects.archive.done", { key: p.key }), { action: { label: t("common.undo"), onClick: () => void restore() } });
  void refresh();
}

async function restore(): Promise<void> {
  const p = project.value;
  if (!p) return;
  await restoreProject(company.currentId ?? 0, p.id);
  toast.success(t("projects.archive.restored", { key: p.key }));
  void refresh();
}

// g + b / l / t … jump between tabs.
const KEYS: Array<[string, ProjectTab]> = [
  ["1", "board"],
  ["2", "list"],
  ["3", "timeline"],
  ["4", "milestones"],
  ["5", "people"],
  ["6", "time"],
  ["7", "money"],
  ["8", "updates"],
  ["9", "files"],
];
for (const [key, id] of KEYS) {
  useHotkey(key, () => void router.push(`${base.value}/${id}`), {
    description: `projects.keys.tab.${id}`,
    group: "page",
    enabled: () => !!project.value && tabs.value.some((item) => item.id === id),
  });
}
useHotkey("u", () => (posting.value = true), { description: "projects.keys.update", group: "page", enabled: () => !!caps.value?.post_update });

const daysLeft = computed(() => {
  const due = project.value?.due_on;
  if (!due || project.value?.status === "completed") return null;
  return daysBetween(todayIn(company.timezone), due);
});
</script>

<template>
  <div>
    <div v-if="skeleton" class="flex flex-col gap-4">
      <SkeletonBlock width="120px" height="14px" />
      <div class="flex items-center gap-3"><SkeletonBlock width="44px" height="44px" radius="12px" /><div class="flex flex-col gap-2"><SkeletonBlock width="240px" height="22px" /><SkeletonBlock width="320px" height="13px" /></div></div>
      <SkeletonBlock height="38px" />
      <div class="grid grid-cols-4 gap-3"><SkeletonBlock v-for="n in 4" :key="n" height="420px" radius="12px" /></div>
    </div>

    <EmptyState
      v-else-if="notFound"
      :icon="FolderKanban"
      tone="neutral"
      :title="t('projects.project.notFound')"
      :description="t('projects.project.notFoundBody')"
    >
      <UiButton :to="`/c/${company.currentId}/projects`">{{ t("projects.project.back") }}</UiButton>
    </EmptyState>

    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />

    <template v-else-if="project">
      <PageHeader :title="project.name" :back="`/c/${company.currentId}/projects`" :back-label="t('projects.title')" :tabs="tabs">
        <template #actions>
          <UiButton v-if="caps?.post_update" variant="secondary" :icon="MessageSquarePlus" kbd="U" @click="posting = true">{{ t("projects.action.postUpdate") }}</UiButton>
          <UiButton v-if="caps?.manage" variant="ghost" :icon="Pencil" class="max-sm:hidden" @click="editing = true">{{ t("projects.action.edit") }}</UiButton>
          <DropdownMenu v-if="menu.length" :items="menu">
            <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" variant="secondary" /></template>
          </DropdownMenu>
        </template>
        <template #meta>
          <ProjectBadge :color="project.color" :icon="project.icon" :size="26" />
          <span class="rounded-[6px] border border-line bg-surface px-1.5 py-0.5 font-mono text-xs font-semibold text-muted">{{ project.key }}</span>
          <StatusPill size="sm" :tone="STATUS_TONE[project.status]" :label="t(`projects.status.${project.status}`)" />
          <HealthDot :health="project.health" :reported="project.reported?.health ?? null" label />
          <span v-if="project.archived_at" class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted">{{ t("projects.archived") }}</span>
          <span class="mx-1 hidden h-4 w-px bg-line sm:block" aria-hidden="true" />
          <span v-if="project.lead" class="inline-flex items-center gap-1.5 text-sm text-muted">
            <UserAvatar :name="project.lead.name" :src="project.lead.photo_url" :size="20" />
            <span class="text-fg">{{ project.lead.name }}</span>
            <span class="text-subtle">· {{ t("projects.role.lead") }}</span>
          </span>
          <span v-if="project.due_on" class="inline-flex items-center gap-1 text-sm tabular-nums" :class="daysLeft !== null && daysLeft < 0 ? 'text-danger' : daysLeft !== null && daysLeft <= 7 ? 'text-warning' : 'text-muted'">
            <CalendarDays :size="14" />
            <template v-if="project.start_on">{{ fmt.day(project.start_on, "short") }} – </template>{{ fmt.day(project.due_on, "short") }}
            <span v-if="daysLeft !== null" class="font-semibold">· {{ daysLeft < 0 ? t("projects.header.overdueDays", { n: -daysLeft }) : t("projects.header.daysLeft", { n: daysLeft }) }}</span>
          </span>
          <AvatarStack v-if="project.members.length" :people="project.members" :max="5" :size="22" class="ml-1" />
          <span v-if="project.client" class="inline-flex items-center gap-1 text-sm text-muted"><FileText :size="14" />{{ project.client.name }}</span>
        </template>
      </PageHeader>

      <BoardTab v-if="tab === 'board'" :project="project" />
      <ListTab v-else-if="tab === 'list'" :project="project" />
      <TimelineTab v-else-if="tab === 'timeline'" :project="project" />
      <MilestonesTab v-else-if="tab === 'milestones'" :project="project" />
      <PeopleTab v-else-if="tab === 'people'" :project="project" />
      <TimeTab v-else-if="tab === 'time'" :project="project" />
      <MoneyTab v-else-if="tab === 'money' && caps?.see_money" :project="project" />
      <UpdatesTab v-else-if="tab === 'updates'" :project="project" @post="posting = true" />
      <FilesTab v-else-if="tab === 'files'" :project="project" />
      <SettingsTab v-else-if="tab === 'settings' && caps?.manage" :project="project" @edit="editing = true" />

      <CardDrawer :project="project" />
      <ProjectFormDialog v-model:open="editing" :project="project" @saved="() => query.refetch()" />
      <UpdateDialog v-model:open="posting" :project="project" />
    </template>
  </div>
</template>
