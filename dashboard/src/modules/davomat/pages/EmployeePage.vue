<script setup lang="ts">
/**
 * One employee (`team/:employeeId`): who they are (photo, job, locations, the numbers the
 * terminals know them by, phone, hire date, schedule) and where they are today, this month's
 * attendance as a calendar, the scans of the day picked in it (today first) with the terminal's
 * snapshots, and their Telegram link. Edit opens the same form as the list; "Left the company"
 * and "Returned" change their status.
 */
import { ArrowLeft, MoreHorizontal, Pencil, ScanFace, Send, ShieldCheck, UserCheck, UserMinus, UserX } from "@lucide/vue";
import { computed, defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import UserAvatar from "@/components/UserAvatar.vue";
import { formatPhone } from "@/lib/format";
import { useFormat } from "@/lib/useFormat";
import { usePageTitle } from "@/lib/usePageTitle";
import { useCan } from "@/lib/usePermission";
import { patchQuery, rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useEmployee } from "../api";
import EmployeeCalendar from "../components/team/EmployeeCalendar.vue";
import ScanList from "../components/team/ScanList.vue";
import { branchNames } from "../components/team/team";
import { useReturn } from "../components/team/teamApi";
import TelegramLinkCard from "../components/team/TelegramLinkCard.vue";
import TodayChip from "../components/team/TodayChip.vue";

const EmployeeDrawer = defineAsyncComponent(() => import("../components/team/EmployeeDrawer.vue"));
const LeaveDialog = defineAsyncComponent(() => import("../components/team/LeaveDialog.vue"));

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();
const canManage = useCan("members.manage");

const id = computed(() => Number(Array.isArray(route.params.employeeId) ? route.params.employeeId[0] : route.params.employeeId) || 0);
const query = useEmployee(id);
const employee = computed(() => query.data.value ?? null);
usePageTitle(() => employee.value?.full_name);

const picked = useRouteState("day", rs.day());
const day = computed({ get: () => picked.value ?? today.value, set: (value: string) => (picked.value = value === today.value ? null : value) });

const leaving = ref(false);
const returning = useReturn();
const notFound = computed(() => isApiError(query.error.value) && query.error.value.status === 404);
const back = computed(() => `/c/${company.currentId}/team`);

interface Fact {
  id: string;
  label: string;
  value: string;
  href?: string;
}

const facts = computed<Fact[]>(() => {
  const row = employee.value;
  if (!row) return [];
  const where = branchNames(row.branch_ids, company.current?.branches ?? []);
  return [
    { id: "branches", label: t("davomat.employee.fact.branches"), value: where.join(", ") || "—" },
    { id: "phone", label: t("davomat.employee.fact.phone"), value: formatPhone(row.phone) || "—", href: row.phone ? `tel:${row.phone.replace(/[^\d+]/g, "")}` : undefined },
    { id: "hired", label: t("davomat.employee.fact.hired"), value: row.hire_date ? fmt.day(row.hire_date) : "—" },
    { id: "schedule", label: t("davomat.employee.fact.schedule"), value: row.schedule?.name ?? t("davomat.employee.fact.noSchedule") },
  ];
});

function edit(): void {
  patchQuery(router, { employee: String(id.value) }, true);
}

async function comeBack(): Promise<void> {
  const row = employee.value;
  if (!row) return;
  const answer = await confirm({ title: t("davomat.team.return.title", { name: row.full_name }), message: t("davomat.team.return.body"), confirmLabel: t("davomat.team.return.confirm"), icon: UserCheck });
  if (!answer) return;
  await returning.mutateAsync(row.id);
  toast.success(t("davomat.team.return.done", { name: row.full_name }));
}

const menu = computed<MenuEntry[]>(() => {
  const row = employee.value;
  if (!row || !canManage.value) return [];
  return row.status === "active"
    ? [{ label: t("davomat.team.leave.action"), icon: UserMinus, danger: true, onSelect: () => (leaving.value = true) }]
    : [{ label: t("davomat.team.return.action"), icon: UserCheck, onSelect: () => void comeBack() }];
});
</script>

<template>
  <div class="flex flex-col gap-5">
    <RouterLink :to="back" class="group -ml-1 inline-flex w-fit items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg" data-back>
      <ArrowLeft :size="15" class="transition-transform duration-150 group-hover:-translate-x-0.5" />
      {{ t("davomat.nav.employees") }}
    </RouterLink>

    <div v-if="query.isPending.value" class="ui-card flex items-center gap-5 p-5" aria-hidden="true">
      <SkeletonBlock circle width="88px" height="88px" />
      <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="40%" height="22px" /><SkeletonBlock width="26%" /><SkeletonBlock width="34%" /></div>
    </div>
    <div v-else-if="notFound" class="ui-card">
      <EmptyState :icon="UserX" :title="t('davomat.employee.notFound.title')" :description="t('davomat.employee.notFound.body')">
        <UiButton variant="secondary" :to="back">{{ t("davomat.nav.employees") }}</UiButton>
      </EmptyState>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />

    <template v-else-if="employee">
      <section class="ui-card relative overflow-hidden" data-employee-hero>
        <div class="hero-wash pointer-events-none absolute inset-x-0 top-0 h-28" aria-hidden="true" />
        <div class="relative flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-5">
          <UserAvatar class="hero-photo" :name="employee.full_name" :src="employee.photo_url" :size="88" :status="employee.today?.state === 'in' ? 'in' : undefined" />
          <div class="min-w-0 flex-1">
            <h1 class="truncate text-xl font-semibold tracking-[-0.01em] text-fg">{{ employee.full_name }}</h1>
            <p class="truncate text-base text-muted">{{ [employee.position?.name, employee.department?.name].filter(Boolean).join(" · ") || t("davomat.employee.noJob") }}</p>
            <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
              <TodayChip :today="employee.today" :status="employee.status" size="md" />
              <StatusPill v-if="employee.status === 'left' && employee.left_on" tone="neutral" size="md" :label="t('davomat.employee.leftOn', { date: fmt.day(employee.left_on) })" />
              <StatusPill v-if="employee.telegram_linked" tone="info" size="md" :icon="Send" :dot="false" :label="t('davomat.team.telegram.linked')" />
              <StatusPill v-if="employee.is_user" tone="primary" size="md" :icon="ShieldCheck" :dot="false" :label="t('davomat.team.alsoUser')" />
            </div>
          </div>
          <div v-if="canManage" class="flex items-center gap-2 sm:self-start">
            <UiButton variant="secondary" :icon="Pencil" data-edit @click="edit">{{ t("common.edit") }}</UiButton>
            <DropdownMenu v-if="menu.length" :items="menu" width="230px">
              <template #trigger>
                <IconButton :icon="MoreHorizontal" :label="t('common.more')" variant="secondary" />
              </template>
            </DropdownMenu>
          </div>
        </div>

        <!-- One-pixel separators at every width: the cells sit on the line colour with a gap of 1 px. -->
        <div class="relative grid grid-cols-2 gap-px border-t border-line bg-line lg:grid-cols-[minmax(0,1.3fr)_repeat(4,minmax(0,1fr))]">
          <div class="col-span-2 flex flex-col gap-1.5 bg-surface px-5 py-3.5 lg:col-span-1" data-fact="face">
            <span class="flex items-center gap-1.5 text-xs font-medium text-muted"><ScanFace :size="13" aria-hidden="true" />{{ t("davomat.employee.fact.face") }}</span>
            <span v-if="employee.face_numbers.length" class="flex flex-wrap gap-1">
              <span v-for="number in employee.face_numbers" :key="number" class="ui-chip font-mono tabular-nums">{{ number }}</span>
            </span>
            <span v-else class="text-sm text-warning">{{ t("davomat.team.noFace") }}</span>
          </div>
          <div v-for="fact in facts" :key="fact.id" class="flex min-w-0 flex-col gap-1 bg-surface px-5 py-3.5" :data-fact="fact.id">
            <span class="text-xs font-medium text-muted">{{ fact.label }}</span>
            <a v-if="fact.href" :href="fact.href" class="truncate text-sm font-medium tabular-nums text-fg hover:text-primary">{{ fact.value }}</a>
            <span v-else class="truncate text-sm font-medium text-fg" :title="fact.value">{{ fact.value }}</span>
          </div>
        </div>
      </section>

      <InlineAlert v-if="employee.source === 'terminal' && employee.status === 'active'" tone="info" :icon="ScanFace" :title="t('davomat.employee.fromTerminal.title')" :description="t('davomat.employee.fromTerminal.body')" data-from-terminal>
        <template v-if="canManage" #actions>
          <UiButton size="sm" variant="secondary" :icon="Pencil" @click="edit">{{ t("davomat.employee.fromTerminal.fix") }}</UiButton>
        </template>
      </InlineAlert>

      <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
        <EmployeeCalendar v-model:day="day" :member-id="employee.id" />
        <div class="flex min-w-0 flex-col gap-5">
          <ScanList :member-id="employee.id" :day="day" :name="employee.full_name" :photo="employee.photo_url" />
          <TelegramLinkCard :employee="employee" />
        </div>
      </div>

      <LeaveDialog v-if="canManage" v-model:open="leaving" :employee="employee" />
    </template>

    <EmployeeDrawer v-if="canManage" />
  </div>
</template>

<style scoped>
.hero-wash {
  background: linear-gradient(180deg, color-mix(in srgb, var(--c-accent-soft) 85%, transparent), transparent);
}
.hero-photo {
  --avatar-ring: var(--c-surface);
  box-shadow:
    0 0 0 4px var(--c-surface),
    0 8px 24px -12px color-mix(in srgb, var(--c-text) 40%, transparent);
  border-radius: 999px;
}
</style>
