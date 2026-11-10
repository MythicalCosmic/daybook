<script setup lang="ts">
/**
 * One policy (`hr/policies/:policyId`): what it is and who it applies to, how the signing goes
 * (signed of everyone asked, waiting, late, the deadline), and three tabs: the people (who signed
 * when, who is still to sign; "Remind"), the text in force with its file, and the versions (read
 * any, compare two). hr.manage edits, publishes, reminds, archives; the export is the signatures.
 */
import { Archive, ArchiveRestore, ArrowLeft, BellRing, EllipsisVertical, FileText, History, MapPin, Paperclip, PenLine, Plus, Trash2, Users } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { isApiError } from "@/api/http";
import DropdownMenu, { type MenuEntry } from "@/components/DropdownMenu.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import ExportButton from "@/components/ExportButton.vue";
import IconButton from "@/components/IconButton.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import SegmentedControl from "@/components/SegmentedControl.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { usePageTitle } from "@/lib/usePageTitle";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useHrMutation } from "../api";
import { policyApi, usePolicy, usePolicyVersion } from "../policies/api";
import { audienceParts, CATEGORY_ICONS, CATEGORY_TINTS, daysUntil, signedPercent } from "../policies/lib";
import PolicyPeople from "../policies/PolicyPeople.vue";
import PolicyProse from "../policies/PolicyProse.vue";
import PolicyVersions from "../policies/PolicyVersions.vue";

const { t } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const confirm = useConfirm();

const id = computed(() => (/^\d+$/.test(String(route.params.policyId ?? "")) ? Number(route.params.policyId) : null));
const query = usePolicy(id);
const policy = computed(() => query.data.value ?? null);
usePageTitle(() => policy.value?.title);
const base = computed(() => `/c/${company.currentId}/hr/policies`);
const editTo = computed(() => (policy.value?.can_change ? `${base.value}/${policy.value.id}/edit` : null));
const canManage = computed(() => company.can("hr.manage"));

type Tab = "people" | "text" | "versions";
const tab = useRouteState<Tab>("tab", rs.enum(["people", "text", "versions"] as const, "people"));
const tabs = computed(() => [
  { value: "people" as const, label: t("hr.policy.tab.people"), icon: Users },
  { value: "text" as const, label: t("hr.policy.tab.text"), icon: FileText },
  { value: "versions" as const, label: t("hr.policy.tab.versions"), icon: History, badge: policy.value?.versions.length },
]);

const current = usePolicyVersion(
  () => policy.value?.id ?? null,
  () => (tab.value === "text" ? (policy.value?.version?.number ?? null) : null),
);

const audience = computed(() => (policy.value ? audienceParts(policy.value, { everyPosition: t("hr.policy.everyPosition"), everyBranch: t("hr.policy.everyBranch") }) : null));
const tally = computed(() => policy.value?.tally ?? null);
const asking = computed(() => !!policy.value && policy.value.is_active && policy.value.requires_ack && !!policy.value.version);
const toSign = computed(() => (tally.value ? tally.value.waiting + tally.value.late : 0));

const kpis = computed(() => {
  const row = tally.value;
  if (!row || !policy.value) return [];
  const due = policy.value.due_on;
  const left = due ? daysUntil(due, today.value) : null;
  return [
    { id: "signed", label: t("hr.policy.kpi.signed"), value: row.signed, hint: t("hr.policy.kpi.ofTotal", { total: row.total, percent: signedPercent(row) }) },
    { id: "waiting", label: t("hr.policy.kpi.waiting"), value: row.waiting },
    { id: "late", label: t("hr.policy.kpi.late"), value: row.late },
    {
      id: "deadline",
      label: t("hr.policy.kpi.deadline"),
      value: null,
      format: () => (due ? fmt.day(due, "medium") : "—"),
      hint: left === null ? undefined : left > 0 ? t("hr.days.in.none", { n: left }, left) : left === 0 ? t("hr.policy.dueToday") : t("hr.policy.deadlinePassed", { date: fmt.day(due!, "short") }),
    },
  ];
});

// Actions -------------------------------------------------------------------------------------
const update = useHrMutation((cid, input: { id: number; is_active: boolean }) => policyApi.update(cid, input.id, { is_active: input.is_active }));
const remove = useHrMutation((cid, policyId: number) => policyApi.remove(cid, policyId));
const remindMutation = useHrMutation((cid, input: { id: number; members: number[] | null }) => policyApi.remind(cid, input.id, input.members ?? undefined));

async function remind(members: number[] | null, count: number): Promise<void> {
  const row = policy.value;
  if (!row) return;
  const answer = await confirm({
    title: t("hr.policy.remindTitle", { n: count }, count),
    message: t("hr.policy.remindBody"),
    confirmLabel: t("hr.policy.remind"),
    icon: BellRing,
    onConfirm: async () => {
      const result = await remindMutation.mutateAsync({ id: row.id, members });
      toast.success(t("hr.policy.reminded", { n: result.reminded }, result.reminded));
    },
  });
  void answer;
}

async function archive(active: boolean): Promise<void> {
  const row = policy.value;
  if (!row) return;
  if (!active) {
    const answer = await confirm({ title: t("hr.policy.archiveTitle"), message: t("hr.policy.archiveBody"), confirmLabel: t("hr.policy.archive"), icon: Archive, onConfirm: () => update.mutateAsync({ id: row.id, is_active: false }) });
    if (answer) toast.success(t("hr.policy.archivedToast"));
    return;
  }
  await update.mutateAsync({ id: row.id, is_active: true });
  toast.success(t("hr.policy.restoredToast"));
}

async function destroy(): Promise<void> {
  const row = policy.value;
  if (!row) return;
  const answer = await confirm({ title: t("hr.policy.deleteTitle"), message: t("hr.policy.deleteBody"), tone: "danger", confirmLabel: t("common.delete"), icon: Trash2, onConfirm: () => remove.mutateAsync(row.id) });
  if (answer) {
    toast.success(t("hr.policy.deletedToast"));
    void router.push(base.value);
  }
}

const menu = computed<MenuEntry[]>(() => {
  const row = policy.value;
  if (!row?.can_change) return [];
  const entries: MenuEntry[] = [];
  if (row.version) entries.push(row.is_active ? { label: t("hr.policy.archive"), icon: Archive, onSelect: () => void archive(false) } : { label: t("hr.policy.restore"), icon: ArchiveRestore, onSelect: () => void archive(true) });
  else entries.push({ label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => void destroy() });
  return entries;
});

const statusPill = computed(() => {
  const row = policy.value;
  if (!row) return null;
  if (!row.is_active) return { tone: "neutral" as const, label: t("hr.policy.status.archived") };
  if (!row.version) return { tone: "warning" as const, label: t("hr.policy.status.draft") };
  return { tone: "success" as const, label: `${t("hr.policy.status.active")} · ${t("hr.policy.versionShort", { n: row.version.number })}` };
});
</script>

<template>
  <div class="flex flex-col gap-4 pb-10">
    <RouterLink :to="base" class="group -mb-1 -ml-1 inline-flex w-fit items-center gap-1.5 rounded-[6px] px-1 py-0.5 text-sm font-medium text-muted hover:text-fg">
      <ArrowLeft :size="15" class="transition-transform duration-150 group-hover:-translate-x-0.5" />{{ t("hr.nav.policies") }}
    </RouterLink>

    <div v-if="query.isPending.value" class="flex flex-col gap-4" aria-hidden="true">
      <div class="ui-card flex gap-4 p-5"><SkeletonBlock width="48px" height="48px" radius="12px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="45%" height="22px" /><SkeletonBlock width="70%" /></div></div>
      <SkeletonBlock height="96px" radius="12px" />
      <SkeletonBlock height="320px" radius="12px" />
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="isApiError(query.error.value) && query.error.value.status === 404 ? undefined : () => query.refetch()" />

    <template v-else-if="policy && audience">
      <section class="ui-card flex flex-col gap-4 p-4 md:p-5" data-policy-header>
        <div class="flex flex-wrap items-start gap-4">
          <span :class="['grid size-12 shrink-0 place-items-center rounded-[12px]', CATEGORY_TINTS[policy.category]]" aria-hidden="true">
            <component :is="CATEGORY_ICONS[policy.category]" :size="22" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h1 class="min-w-0 text-xl font-semibold tracking-tight text-fg">{{ policy.title }}</h1>
              <StatusPill v-if="statusPill" :tone="statusPill.tone" size="sm" :label="statusPill.label" />
              <StatusPill v-if="!policy.requires_ack" tone="neutral" variant="outline" size="sm" :dot="false" :label="t('hr.policy.toRead')" />
            </div>
            <p class="mt-1 text-sm text-muted">{{ t(`hr.policy.category.${policy.category}`) }}<template v-if="policy.requires_ack"> · {{ t("hr.policy.signWithin", { n: policy.ack_within_days }, policy.ack_within_days) }}</template></p>
            <div class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-fg">
              <span class="inline-flex min-w-0 items-center gap-1.5"><Users :size="14" class="shrink-0 text-subtle" aria-hidden="true" />{{ audience.positions }}</span>
              <span class="inline-flex min-w-0 items-center gap-1.5"><MapPin :size="14" class="shrink-0 text-subtle" aria-hidden="true" />{{ audience.branches }}</span>
            </div>
          </div>
          <div class="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <UiButton v-if="asking && canManage && toSign > 0" :icon="BellRing" data-remind-all @click="remind(null, toSign)">{{ t("hr.policy.remind") }}</UiButton>
            <ExportButton v-if="asking" kind="hr.policy_signatures" :params="{ policy: policy.id }" />
            <UiButton v-if="editTo && policy.is_active" variant="primary" :icon="policy.draft ? PenLine : Plus" :to="editTo">{{ policy.draft ? t("hr.policy.continueDraft") : policy.version ? t("hr.policy.newVersion") : t("common.edit") }}</UiButton>
            <DropdownMenu v-if="menu.length" :items="menu" align="end">
              <template #trigger><IconButton :icon="EllipsisVertical" :label="t('common.more')" variant="secondary" /></template>
            </DropdownMenu>
          </div>
        </div>
        <InlineAlert v-if="policy.draft && policy.version" tone="info" size="sm" :icon="PenLine" :description="t('hr.policy.draftBanner', { n: policy.draft.number, current: policy.version.number })" />
        <InlineAlert v-else-if="!policy.version" tone="warning" size="sm" :icon="PenLine" :description="t('hr.policy.draftBannerNew', { n: policy.audience_count }, policy.audience_count)" />
        <InlineAlert v-if="!policy.is_active" tone="neutral" size="sm" :icon="Archive" :description="t('hr.policy.archivedBanner')" />
      </section>

      <KpiStrip v-if="asking && tally" :items="kpis" :columns="4" phone="grid" />

      <SegmentedControl v-model="tab" :options="tabs" :aria-label="t('hr.policy.tab.people')" />

      <template v-if="tab === 'people'">
        <div v-if="!policy.version" class="ui-card">
          <EmptyState :icon="Users" :title="t('hr.policy.notPublishedPeople')" :description="t('hr.policy.notPublishedPeopleBody', { n: policy.audience_count }, policy.audience_count)">
            <UiButton v-if="editTo" variant="primary" :icon="PenLine" :to="editTo">{{ t("hr.policy.continueDraft") }}</UiButton>
          </EmptyState>
        </div>
        <div v-else-if="!policy.requires_ack" class="ui-card">
          <EmptyState :icon="FileText" :title="t('hr.policy.noSignature')" :description="t('hr.policy.noSignatureBody')" />
        </div>
        <PolicyPeople v-else :policy="policy" :can-remind="canManage && policy.is_active" @remind="remind" />
      </template>

      <template v-else-if="tab === 'text'">
        <section class="ui-card flex flex-col gap-4 p-5 md:p-7" data-policy-text-view>
          <EmptyState v-if="!policy.version" size="sm" tone="neutral" :icon="FileText" :title="t('hr.policy.neverPublished')" :description="t('hr.policy.textNotPublished')" />
          <template v-else>
            <div class="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span class="font-medium text-fg">{{ t("hr.policy.version", { n: policy.version.number }) }}</span>
              <span v-if="policy.version.published_at">· {{ fmt.instant(policy.version.published_at, "datetime") }}</span>
              <span v-if="policy.versions.find((row) => row.id === policy!.version!.id)?.published_by">· {{ policy.versions.find((row) => row.id === policy!.version!.id)?.published_by }}</span>
            </div>
            <div v-if="current.isPending.value" class="flex flex-col gap-2" aria-hidden="true"><SkeletonBlock v-for="n in 8" :key="n" :width="n % 3 ? '100%' : '70%'" /></div>
            <ErrorState v-else-if="current.isError.value" compact :error="current.error.value" :retry="() => current.refetch()" />
            <template v-else-if="current.data.value">
              <p v-if="current.data.value.change_note" class="rounded-[10px] bg-surface-2 px-3.5 py-2.5 text-sm text-fg dark:bg-surface-3">
                <span class="font-semibold">{{ t("hr.policy.field.changeNote") }}:</span> {{ current.data.value.change_note }}
              </p>
              <PolicyProse v-if="current.data.value.body" :html="current.data.value.body" class="max-w-[72ch]" />
              <EmptyState v-else size="sm" tone="neutral" :icon="Paperclip" :title="t('hr.policy.text.empty')" />
              <a v-if="current.data.value.file_url" :href="current.data.value.file_url" target="_blank" rel="noopener" class="inline-flex w-fit items-center gap-2 rounded-[10px] border border-line px-3.5 py-2.5 text-sm font-medium text-fg hover:bg-highlight" data-policy-file>
                <Paperclip :size="15" class="text-subtle" aria-hidden="true" />{{ t("hr.policy.text.openFile") }}
              </a>
            </template>
          </template>
        </section>
      </template>

      <PolicyVersions v-else :policy="policy" :edit-to="editTo" />
    </template>
  </div>
</template>
