<script setup lang="ts">
/**
 * Person 360 (plan §6.2): everything about one person. A header with their photo, position,
 * branches, role, status, contacts and tenure, the actions the viewer may take (and the
 * `people.profile.actions` slot other modules fill: warn, suspend, terminate…), their key numbers,
 * then tabs: Overview, the tabs other modules register (`personTabs`), History. The tab is in the
 * path (`people/12/history`).
 */
import {
  ArrowLeft,
  AtSign,
  Ban,
  CalendarPlus,
  Crown,
  Ellipsis,
  LogOut,
  MapPin,
  Pause,
  Pencil,
  Phone,
  Play,
  ShieldCheck,
  Undo2,
  UserRoundX,
} from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExtensionSlot from "@/components/ExtensionSlot.vue";
import IconButton from "@/components/IconButton.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { allowed, isModuleVisible } from "@/core/access";
import { hasExtension } from "@/core/extensions";
import { modules } from "@/core/modules";
import { todayIn } from "@/lib/dates";
import { formatPhone } from "@/lib/format";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";

import { personAction, usePerson, usePersonMutation } from "../api";
import PersonHistory from "../components/PersonHistory.vue";
import PersonOverviewTab from "../components/PersonOverviewTab.vue";
import PersonTabBar from "../components/PersonTabBar.vue";
import { bookedDaysAhead, rateTone, statusChip, tenureParts } from "../status";
import type { PersonDetail } from "../types";

const PersonEditDialog = defineAsyncComponent(() => import("../components/PersonEditDialog.vue"));
const SuspendDialog = defineAsyncComponent(() => import("../components/SuspendDialog.vue"));

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();

const memberId = computed(() => Number(route.params.memberId));
const query = usePerson(memberId);
const person = computed(() => query.data.value ?? null);
// The breadcrumb and the browser tab say whose page this is.
usePageTitle(() => person.value?.name);
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const base = computed(() => `/c/${company.currentId}/people/${memberId.value}`);

// Tabs: Overview, what other modules registered for Person 360, History.
const extraTabs = computed(() =>
  modules
    .filter((module) => isModuleVisible(module, company.current))
    .flatMap((module) => (module.personTabs ?? []).filter((tab) => allowed(company.current, tab)).map((tab) => ({ ...tab, module: module.id })))
    .sort((a, b) => (a.order ?? 50) - (b.order ?? 50)),
);
const tabs = computed(() => [
  { id: "overview", label: t("people.tab.overview"), to: base.value },
  ...extraTabs.value.map((tab) => ({ id: tab.id, label: t(tab.title), to: `${base.value}/${tab.id}` })),
  { id: "history", label: t("people.tab.history"), to: `${base.value}/history` },
]);
const tab = computed(() => {
  const value = String(route.params.tab ?? "");
  return value && tabs.value.some((item) => item.id === value) ? value : "overview";
});
const extraTab = computed(() => extraTabs.value.find((item) => item.id === tab.value) ?? null);

// The same short date as on the Team list; the banner and the time-off card give the full one.
const chip = computed(() => (person.value ? statusChip(person.value, (d) => fmt.day(d, "short")) : null));
const tenure = computed(() => {
  const parts = tenureParts(person.value?.overview.tenure_days);
  if (!parts) return null;
  if (parts.years) return parts.months ? t("people.tenure.yearsMonths", { y: parts.years, m: parts.months }, parts.years) : t("people.tenure.years", { n: parts.years }, parts.years);
  if (parts.months) return t("people.tenure.months", { n: parts.months }, parts.months);
  return t("people.tenure.days", { n: parts.days }, parts.days);
});

/** Approved days still ahead, which "days off taken this year" leaves out (it counts up to today). */
const booked = computed(() => bookedDaysAhead(person.value?.overview.upcoming_time_off ?? [], todayIn(company.timezone)));

const kpis = computed(() => {
  const o = person.value?.overview;
  return [
    {
      id: "on_time",
      label: t("people.kpi.onTime30"),
      value: o?.on_time_percent ?? null,
      format: (value: number) => fmt.percent(value, 1),
      hint: o?.total ? t("people.kpi.onTimeOf", { done: o.on_time, total: o.total }) : undefined,
    },
    { id: "done", label: t("people.kpi.done30"), value: o?.done ?? null },
    { id: "late", label: t("people.kpi.lateNow"), value: o?.late_now ?? null, hint: o?.open_now ? t("people.kpi.openNow", { n: o.open_now }) : undefined },
    { id: "streak", label: t("people.kpi.streak"), value: o?.streak ?? null, format: (value: number) => t("people.days", { n: value }, value) },
    {
      id: "off",
      label: t("people.kpi.daysOff"),
      value: o?.days_off_this_year ?? null,
      format: (value: number) => t("people.days", { n: value }, value),
      hint: booked.value ? t("people.kpi.daysBooked", { n: booked.value }, booked.value) : undefined,
    },
  ];
});

// Actions ----------------------------------------------------------------------------------
const editing = ref(false);
const suspending = ref(false);
/** Package S brings its own Suspend (with records); until then this page offers the basic one. */
const lifecycleInstalled = computed(() => modules.some((module) => module.id === "lifecycle"));
const act = usePersonMutation((cid, input: { id: number; action: "block" | "unblock" | "reinstate" }) => personAction(cid, input.id, input.action));

async function block(p: PersonDetail): Promise<void> {
  const answer = await confirm({
    title: t("people.block.title", { name: p.name }),
    message: t("people.block.body"),
    tone: "danger",
    confirmLabel: t("people.block.confirm"),
    icon: Ban,
  });
  if (!answer) return;
  await run(() => act.mutateAsync({ id: p.id, action: "block" }), t("people.block.done", { name: p.name }));
}

async function unblock(p: PersonDetail): Promise<void> {
  const answer = await confirm({ title: t("people.unblock.title", { name: p.name }), message: t("people.unblock.body"), confirmLabel: t("people.unblock.confirm") });
  if (!answer) return;
  await run(() => act.mutateAsync({ id: p.id, action: "unblock" }), t("people.unblock.done", { name: p.name }));
}

async function reinstate(p: PersonDetail): Promise<void> {
  const answer = await confirm({ title: t("people.reinstate.title", { name: p.name }), message: t("people.reinstate.body"), confirmLabel: t("people.reinstate.confirm") });
  if (!answer) return;
  await run(() => act.mutateAsync({ id: p.id, action: "reinstate" }), t("people.reinstate.done", { name: p.name }));
}

async function run(task: () => Promise<unknown>, done: string): Promise<void> {
  try {
    await task();
    toast.success(done);
  } catch {
    // The HTTP layer showed the server's reason.
  }
}

function goneText(p: PersonDetail): string {
  const day = p.left_on ? fmt.day(p.left_on, "long") : null;
  if (p.status === "blocked") return day ? t("people.blockedBannerOn", { date: day }) : t("people.blockedBanner");
  return day ? t("people.leftBannerOn", { date: day }) : t("people.leftBanner");
}

function recordTimeOff(p: PersonDetail): void {
  void router.push({ path: `/c/${company.currentId}/time-off`, query: { record: String(p.id) } });
}

const menu = computed<MenuEntry[]>(() => {
  const p = person.value;
  if (!p) return [];
  const entries: MenuEntry[] = [];
  if (p.can.change_role) entries.push({ label: t("people.action.changeRole"), icon: ShieldCheck, onSelect: () => (editing.value = true) });
  if (p.can.suspend && !lifecycleInstalled.value) entries.push({ label: t("people.action.suspend"), icon: Pause, onSelect: () => (suspending.value = true) });
  // Reinstate and unblock sit in the status banner, where the person's state is explained.
  if (entries.length && (p.can.block || p.can.offboard)) entries.push({ type: "separator" });
  if (p.can.offboard) entries.push({ label: t("people.action.offboard"), icon: LogOut, danger: true, onSelect: () => void router.push(`${base.value}/offboard`) });
  if (p.can.block) entries.push({ label: t("people.action.block"), icon: Ban, danger: true, onSelect: () => void block(p) });
  return entries;
});

const slotContext = computed(() => ({ companyId: company.currentId, memberId: memberId.value, person: person.value }));
const hasProfileActions = computed(() => hasExtension("people.profile.actions", company.current));
</script>

<template>
  <div class="flex flex-col gap-5">
    <RouterLink
      :to="`/c/${company.currentId}/people`"
      class="group -mb-2 -ml-1 inline-flex w-fit items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg"
    >
      <ArrowLeft :size="15" class="transition-transform duration-150 group-hover:-translate-x-0.5" />{{ t("people.title") }}
    </RouterLink>

    <!-- Loading -->
    <div v-if="skeleton && !person" class="ui-card flex flex-col gap-5 p-5">
      <div class="flex items-center gap-4">
        <SkeletonBlock circle height="64px" />
        <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="240px" height="20px" /><SkeletonBlock width="320px" /><SkeletonBlock width="200px" height="12px" /></div>
      </div>
      <SkeletonBlock height="72px" radius="12px" />
    </div>
    <!-- Trying again can't bring back someone who isn't there (404): no retry then. -->
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="isApiError(query.error.value) && query.error.value.status === 404 ? undefined : () => query.refetch()" />

    <template v-else-if="person">
      <!-- Header -->
      <section class="ui-card overflow-hidden">
        <div class="flex flex-col gap-4 p-5 md:flex-row md:items-start">
          <UserAvatar :name="person.name" :src="person.photo_url" :size="72" :status="chip?.avatar" class="shrink-0" />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h1 class="text-xl font-semibold tracking-[-0.01em] text-fg">{{ person.name }}</h1>
              <StatusPill v-if="chip" :tone="chip.tone" :live="chip.live" :label="t(chip.key, chip.params ?? {})" />
              <UiBadge v-if="person.role?.is_owner" tone="primary" size="md"><Crown :size="12" class="mr-1 inline" aria-hidden="true" />{{ person.role.name }}</UiBadge>
            </div>
            <p class="mt-1 text-base text-muted">
              {{ person.position?.name ?? t("people.noPosition") }}
              <template v-if="person.role && !person.role.is_owner && person.role.name !== person.position?.name"> · {{ person.role.name }}</template>
            </p>
            <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted">
              <span v-if="person.home_branch" class="inline-flex items-center gap-1.5">
                <MapPin :size="14" aria-hidden="true" />{{ person.home_branch.name }}
                <span v-for="branch in person.branches.filter((b) => b.id !== person!.home_branch!.id)" :key="branch.id" class="text-subtle">· {{ branch.name }}</span>
              </span>
              <a v-if="person.phone" :href="`tel:${person.phone}`" class="inline-flex items-center gap-1.5 tabular-nums hover:text-fg"><Phone :size="14" aria-hidden="true" />{{ formatPhone(person.phone) }}</a>
              <a v-if="person.username" :href="`https://t.me/${person.username}`" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 hover:text-fg"><AtSign :size="14" aria-hidden="true" />{{ person.username }}</a>
              <span v-if="person.overview.joined_on"
                >{{ t("people.joinedOn", { date: fmt.day(person.overview.joined_on, "medium") }) }}<template v-if="person.overview.left_on">
                  · {{ t("people.lastDay", { date: fmt.day(person.overview.left_on, "medium") }) }}</template
                ><template v-if="tenure"> · {{ tenure }}</template></span
              >
              <span v-if="person.bot_blocked" class="inline-flex items-center gap-1.5 text-danger"><UserRoundX :size="14" aria-hidden="true" />{{ t("people.botBlocked") }}</span>
            </div>
          </div>
          <div class="flex shrink-0 flex-wrap items-center gap-2 md:justify-end">
            <ExtensionSlot v-if="hasProfileActions" name="people.profile.actions" :context="slotContext" as="none" />
            <UiButton v-if="person.can.record_time_off" :icon="CalendarPlus" @click="recordTimeOff(person)">{{ t("people.action.recordTimeOff") }}</UiButton>
            <UiButton v-if="person.can.edit" variant="primary" :icon="Pencil" @click="editing = true">{{ t("people.action.edit") }}</UiButton>
            <DropdownMenu v-if="menu.length" :items="menu" align="end">
              <template #trigger><IconButton :icon="Ellipsis" :label="t('people.action.more')" variant="secondary" /></template>
            </DropdownMenu>
          </div>
        </div>
        <div v-if="person.status === 'suspended'" class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-warning-soft/60 px-5 py-2.5">
          <p class="min-w-0 flex-1 text-sm text-warning">
            {{ person.suspended_until ? t("people.suspendedBanner", { date: fmt.day(person.suspended_until, "long") }) : t("people.suspendedBannerOpen") }}
          </p>
          <UiButton v-if="person.can.reinstate" size="sm" :icon="Play" :loading="act.isPending.value" @click="reinstate(person)">{{ t("people.action.reinstate") }}</UiButton>
        </div>
        <div v-else-if="person.status === 'left' || person.status === 'blocked'" class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-surface-2/60 px-5 py-2.5">
          <p class="min-w-0 flex-1 text-sm text-muted">{{ goneText(person) }}</p>
          <UiButton v-if="person.can.unblock" size="sm" :icon="Undo2" :loading="act.isPending.value" @click="unblock(person)">{{ t("people.action.unblock") }}</UiButton>
        </div>
        <div class="border-t border-line">
          <KpiStrip :items="kpis" :columns="5" phone="compact" class="!rounded-none !border-0 !shadow-none" />
        </div>
      </section>

      <!-- Tabs -->
      <PersonTabBar :tabs="tabs" :active="tab" :aria-label="t('people.tab.label')" />
      <PersonOverviewTab v-if="tab === 'overview'" :person="person" :rate-tone="rateTone(person.overview.on_time_percent)" :time-off-to="tabs.find((item) => item.id === 'time-off')?.to" />
      <section v-else-if="tab === 'history'" class="ui-card p-5">
        <PersonHistory :member-id="person.id" />
      </section>
      <component :is="extraTab.component" v-else-if="extraTab" :member-id="person.id" />

      <PersonEditDialog v-if="editing" v-model:open="editing" :person="person" />
      <SuspendDialog v-if="suspending" v-model:open="suspending" :person="person" />
    </template>
  </div>
</template>
