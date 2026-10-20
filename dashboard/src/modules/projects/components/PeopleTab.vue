<script setup lang="ts">
/**
 * The People tab: who works on the project and their load here (open, waiting for a check, done,
 * overdue cards, hours this week), with a load bar so overloaded people stand out. Managers add
 * people, switch members and viewers, and remove them.
 */
import { Ellipsis, Eye, UserMinus, UserPlus, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import PersonCell from "@/components/PersonCell.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { addMember, removeMember, setMemberRole, useCompanyId, useMembers, usePeople, useRefreshProjects } from "../api";
import { hhmm } from "../lib";
import type { Member, ProjectDetail } from "../types";

const props = defineProps<{ project: ProjectDetail }>();

const { t } = useI18n();
const confirm = useConfirm();
const companyId = useCompanyId();
const refresh = useRefreshProjects();
const query = useMembers(() => props.project.id);
const people = usePeople();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const manage = computed(() => props.project.capabilities.manage);

const picked = ref<number | null>(null);
const role = ref<"member" | "viewer">("member");
const adding = ref(false);

const members = computed(() => query.data.value ?? []);
const maxLoad = computed(() => Math.max(4, ...members.value.map((m) => m.open + m.review)));
const candidates = computed(() =>
  (people.data.value ?? []).filter((p) => !members.value.some((m) => m.person.id === p.id)).map((p) => ({ id: p.id, name: p.name, photo_url: p.photo_url, subtitle: p.position || undefined })),
);
const totals = computed(() => ({
  open: members.value.reduce((sum, m) => sum + m.open, 0),
  overdue: members.value.reduce((sum, m) => sum + m.overdue, 0),
  minutes: members.value.reduce((sum, m) => sum + m.week_minutes, 0),
}));
const roleOptions = computed(() => [
  { value: "member" as const, label: t("projects.role.member") },
  { value: "viewer" as const, label: t("projects.role.viewer") },
]);

async function add(): Promise<void> {
  if (!picked.value) return;
  adding.value = true;
  try {
    await addMember(companyId.value, props.project.id, picked.value, role.value);
    toast.success(t("projects.people.added"), { description: t("projects.people.addedHint") });
    picked.value = null;
    void refresh();
  } catch {
    // The HTTP layer showed why.
  } finally {
    adding.value = false;
  }
}

function menu(member: Member): MenuEntry[] {
  if (!manage.value || member.role === "lead" || member.id === null) return [];
  const id = member.id;
  return [
    member.role === "viewer"
      ? { label: t("projects.people.makeMember"), icon: Users, onSelect: () => void changeRole(id, "member") }
      : { label: t("projects.people.makeViewer"), icon: Eye, onSelect: () => void changeRole(id, "viewer") },
    { type: "separator" },
    { label: t("projects.people.remove"), icon: UserMinus, danger: true, onSelect: () => void remove(member) },
  ];
}

async function changeRole(rowId: number, next: "member" | "viewer"): Promise<void> {
  await setMemberRole(companyId.value, props.project.id, rowId, next);
  void refresh();
}

async function remove(member: Member): Promise<void> {
  if (member.id === null) return;
  const answer = await confirm({
    title: t("projects.people.removeTitle", { name: member.person.name }),
    message: member.open ? t("projects.people.removeOpen", { n: member.open }) : t("projects.people.removeBody"),
    tone: "danger",
    confirmLabel: t("projects.people.remove"),
    icon: UserMinus,
  });
  if (!answer) return;
  await removeMember(companyId.value, props.project.id, member.id);
  void refresh();
}

function loadTone(member: Member): "success" | "warning" | "danger" {
  if (member.overdue) return "danger";
  return member.open + member.review >= 6 ? "warning" : "success";
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div v-if="manage" class="ui-card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <span class="grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent-fg"><UserPlus :size="17" /></span>
        <PersonPicker v-model="picked" :people="candidates" :placeholder="t('projects.people.pick')" class="min-w-0 flex-1" />
      </div>
      <SegmentedControl v-model="role" :options="roleOptions" size="sm" :aria-label="t('projects.people.role')" />
      <UiButton variant="primary" :icon="UserPlus" :disabled="!picked" :loading="adding" @click="add">{{ t("projects.people.add") }}</UiButton>
    </div>

    <div v-if="skeleton" class="ui-card flex flex-col gap-4 p-4">
      <div v-for="n in 5" :key="n" class="flex items-center gap-3"><SkeletonBlock circle height="32px" /><SkeletonBlock width="30%" /><SkeletonBlock width="40%" height="8px" class="ml-auto" /></div>
    </div>
    <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
    <EmptyState v-else-if="query.data.value && !members.length" :icon="Users" :title="t('projects.people.emptyTitle')" :description="t('projects.people.emptyBody')" />
    <section v-else class="ui-card overflow-hidden">
      <header class="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-line bg-surface-2/50 px-4 py-2.5 text-xs font-semibold text-muted">
        <span>{{ t("projects.people.count", { n: members.length }) }}</span>
        <span>{{ t("projects.people.openTotal", { n: totals.open }) }}</span>
        <span :class="totals.overdue ? 'text-danger' : ''">{{ t("projects.people.overdueTotal", { n: totals.overdue }) }}</span>
        <span>{{ t("projects.people.hoursTotal", { time: hhmm(totals.minutes) }) }}</span>
      </header>
      <ul class="divide-y divide-line">
        <li v-for="member in members" :key="member.person.id" class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1.4fr)_110px_minmax(0,1.6fr)_90px_36px]">
          <PersonCell :person="member.person" :subtitle="member.position || null" />
          <StatusPill size="sm" :tone="member.role === 'lead' ? 'primary' : member.role === 'viewer' ? 'neutral' : 'info'" :label="t(`projects.role.${member.role}`)" :dot="false" class="justify-self-end md:justify-self-start" />
          <div class="col-span-2 flex min-w-0 flex-col gap-1 md:col-span-1">
            <ProgressBar :value="member.open + member.review" :max="maxLoad" size="xs" :tone="loadTone(member)" />
            <p class="flex flex-wrap gap-x-3 text-xs text-muted">
              <span>{{ t("projects.people.open", { n: member.open }) }}</span>
              <span v-if="member.review">{{ t("projects.people.review", { n: member.review }) }}</span>
              <span v-if="member.overdue" class="font-semibold text-danger">{{ t("projects.people.overdue", { n: member.overdue }) }}</span>
              <span class="text-subtle">{{ t("projects.people.done", { n: member.done }) }}</span>
            </p>
          </div>
          <p class="text-sm font-semibold tabular-nums text-fg max-md:justify-self-start">{{ hhmm(member.week_minutes) }}<span class="ml-1 text-xs font-normal text-muted md:hidden">{{ t("projects.people.thisWeek") }}</span></p>
          <DropdownMenu v-if="menu(member).length" :items="menu(member)">
            <template #trigger><IconButton :icon="Ellipsis" :label="t('common.more')" size="sm" /></template>
          </DropdownMenu>
          <span v-else class="hidden md:block" />
        </li>
      </ul>
      <p class="border-t border-line px-4 py-2 text-xs text-subtle">{{ t("projects.people.hoursHint") }}</p>
    </section>
  </div>
</template>
