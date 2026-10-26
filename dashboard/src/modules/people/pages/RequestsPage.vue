<script setup lang="ts">
/**
 * Join requests (plan §6.2 "Requests"): people who opened an invite link or a team link that asks
 * first. Approve one with role, position, branches and home branch, or reject with an optional
 * reason; a request leaves the list at once and comes back if the server refuses. `?request=12`
 * opens the approval for that request (links from Needs you and the bot).
 *
 * Several at once: tick the ready ones (or "Select all"), then Approve or Reject in the bar. The
 * ones that went through leave; the ones that didn't stay selected, listed with the reason.
 * Someone who came through a team link carries a "Via «…»" chip, and their approval starts with
 * that link's role and branch.
 */
import { AtSign, Check, History, Link2, Phone, QrCode, UserPlus, UsersRound, X } from "@lucide/vue";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import BulkActionBar from "@/components/BulkActionBar.vue";
import CheckBox from "@/components/CheckBox.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiTooltip from "@/components/UiTooltip.vue";
import { useConfirm } from "@/components/useConfirm";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { formatPhone } from "@/lib/format";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useBulkDecide, useDecideRequest, useJoinRequests } from "../api";
import { bulkOutcome, useSelection, type BulkOutcome } from "../bulk";
import ApproveDialog from "../components/ApproveDialog.vue";
import type { ApproveInput, BulkDecisionInput, JoinRequest } from "../types";

const BulkApproveDialog = defineAsyncComponent(() => import("../components/BulkApproveDialog.vue"));

const { t } = useI18n();
const fmt = useFormat();
const router = useRouter();
const company = useCompanyStore();
const confirm = useConfirm();

const query = useJoinRequests();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
const ready = computed(() => (query.data.value ?? []).filter((row) => row.onboarded));
const waitingForDetails = computed(() => (query.data.value ?? []).filter((row) => !row.onboarded));
const decide = useDecideRequest();
const bulk = useBulkDecide();

const requestParam = useRouteState("request", rs.optionalNumber());
const approving = computed(() => (requestParam.value === null ? null : (query.data.value ?? []).find((row) => row.id === requestParam.value) ?? null));
const dialogOpen = ref(false);
watch(approving, (row) => (dialogOpen.value = row !== null && row.onboarded), { immediate: true });
watch(dialogOpen, (value) => {
  if (!value) requestParam.value = null;
});

/** Settings pages belong to another module; link to them only once they exist. */
function settingsPath(hash = ""): string | null {
  const path = `/c/${company.currentId}/settings/invite`;
  return router.resolve(path).name !== "company-not-found" ? `${path}${hash}` : null;
}
const invite = computed(() => settingsPath());
const teamLinks = computed(() => settingsPath("#team-links"));

// ─── One at a time ─────────────────────────────────────────────────────────

async function approve(row: JoinRequest, body: ApproveInput): Promise<void> {
  dialogOpen.value = false;
  try {
    const person = await decide.mutateAsync({ id: row.id, approve: true, body });
    toast.success(t("people.requests.approved", { name: row.name }), {
      action: { label: t("people.requests.openProfile"), onClick: () => void router.push(`/c/${company.currentId}/people/${person?.id ?? row.id}`) },
    });
  } catch {
    // Back in the list; the HTTP layer showed why.
  }
}

async function reject(row: JoinRequest): Promise<void> {
  const answer = await confirm({
    title: t("people.requests.rejectTitle", { name: row.name }),
    message: t("people.requests.rejectBody"),
    tone: "danger",
    reason: "optional",
    reasonLabel: t("people.requests.rejectReason"),
    confirmLabel: t("common.reject"),
  });
  if (!answer) return;
  try {
    await decide.mutateAsync({ id: row.id, approve: false, reason: answer.reason });
    toast.info(t("people.requests.rejected", { name: row.name }));
  } catch {
    // Back in the list.
  }
}

// ─── Several at once ───────────────────────────────────────────────────────

const selection = useSelection(() => ready.value.map((row) => row.id));
const chosen = computed(() => ready.value.filter((row) => selection.has(row.id)));
const bulkOpen = ref(false);
/** The last bulk answer's refusals, shown until dismissed or the next bulk action. */
const failures = ref<(BulkOutcome & { action: "approve" | "reject" }) | null>(null);
const running = ref<"approve" | "reject" | null>(null);

async function runBulk(body: BulkDecisionInput, rows: JoinRequest[]): Promise<void> {
  failures.value = null;
  running.value = body.action;
  try {
    const outcome = bulkOutcome(await bulk.mutateAsync(body), rows);
    if (outcome.done) {
      if (body.action === "approve") toast.success(t("people.bulk.approved", { n: outcome.done }, outcome.done));
      else toast.info(t("people.bulk.rejected", { n: outcome.done }, outcome.done));
    }
    // Who didn't go through stays selected, with the reason.
    selection.set(outcome.failed.map((row) => row.id));
    failures.value = outcome.failed.length ? { ...outcome, action: body.action } : null;
  } catch {
    // Nothing changed; the HTTP layer said why. The selection stays for another try.
  } finally {
    running.value = null;
  }
}

async function approveChosen(body: BulkDecisionInput): Promise<void> {
  bulkOpen.value = false;
  await runBulk(body, chosen.value);
}

async function rejectChosen(): Promise<void> {
  const rows = chosen.value;
  const answer = await confirm({
    title: t("people.bulk.rejectTitle", { n: rows.length }, rows.length),
    message: t("people.bulk.rejectBody"),
    tone: "danger",
    reason: "optional",
    reasonLabel: t("people.requests.rejectReason"),
    confirmLabel: t("common.reject"),
  });
  if (!answer) return;
  await runBulk({ ids: rows.map((row) => row.id), action: "reject", reason: answer.reason }, rows);
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader class="!mb-0" :title="t('people.requests.title')" :description="t('people.requests.description')" :back="`/c/${company.currentId}/people`" :back-label="t('people.title')">
      <template v-if="invite" #actions>
        <UiButton v-if="teamLinks" :to="teamLinks" variant="ghost" :icon="UsersRound" data-team-links>{{ t("people.requests.teamLinks") }}</UiButton>
        <UiButton :to="invite" :icon="QrCode">{{ t("people.requests.invite") }}</UiButton>
      </template>
    </PageHeader>

    <div v-if="skeleton" class="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <div v-for="n in 4" :key="n" class="ui-card flex gap-3 p-4">
        <SkeletonBlock circle height="44px" />
        <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="50%" /><SkeletonBlock width="70%" height="12px" /><SkeletonBlock width="180px" height="28px" radius="8px" /></div>
      </div>
    </div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !ready.length && !waitingForDetails.length" class="ui-card">
      <EmptyState :icon="UserPlus" tone="success" :title="t('people.requests.emptyTitle')" :description="t('people.requests.emptyBody')">
        <div class="flex flex-wrap justify-center gap-2">
          <UiButton v-if="invite" :to="invite" variant="primary" :icon="QrCode">{{ t("people.requests.invite") }}</UiButton>
          <UiButton v-if="teamLinks" :to="teamLinks" :icon="UsersRound">{{ t("people.requests.teamLinks") }}</UiButton>
        </div>
      </EmptyState>
    </div>
    <template v-else>
      <InlineAlert
        v-if="failures"
        tone="warning"
        dismissible
        :title="t(failures.action === 'approve' ? 'people.bulk.failedApprove' : 'people.bulk.failedReject', { n: failures.failed.length }, failures.failed.length)"
        data-bulk-failures
        @dismiss="failures = null"
      >
        <p class="text-sm">{{ t("people.bulk.failedHint") }}</p>
        <ul class="mt-1.5 flex flex-col gap-0.5 text-sm">
          <li v-for="row in failures.failed" :key="row.id"><span class="font-semibold">{{ row.name }}</span> · {{ row.detail }}</li>
        </ul>
      </InlineAlert>

      <div v-if="ready.length > 1" class="-mb-2 flex items-center gap-3 px-1" data-select-all>
        <CheckBox :model-value="selection.all.value" :indeterminate="selection.some.value" :label="t('people.requests.selectAll', { n: ready.length })" size="sm" @update:model-value="(value: boolean) => selection.toggleAll(value)" />
      </div>

      <TransitionGroup name="list" tag="div" class="relative grid grid-cols-1 gap-3 lg:grid-cols-2">
        <article
          v-for="row in ready"
          :key="row.id"
          :class="['ui-card flex flex-col gap-3 p-4 transition-shadow', selection.has(row.id) && 'shadow-[0_0_0_2px_var(--c-primary)]']"
          :data-request="row.id"
        >
          <div class="flex items-start gap-3">
            <div class="flex shrink-0 items-center gap-3">
              <CheckBox :model-value="selection.has(row.id)" :aria-label="t('people.requests.select', { name: row.name })" @update:model-value="(value: boolean) => selection.toggle(row.id, value)" />
              <UserAvatar :name="row.name" :src="row.photo_url" :size="44" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-start gap-2">
                <h2 class="min-w-0 flex-1 truncate text-md font-semibold text-fg">{{ row.name }}</h2>
                <RelativeTime :value="row.requested_at" class="shrink-0 pt-0.5 text-xs text-subtle" />
              </div>
              <p class="truncate text-sm text-muted">{{ row.position?.name ?? t("people.noPosition") }}</p>
              <div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                <a v-if="row.phone" :href="`tel:${row.phone}`" class="inline-flex items-center gap-1 tabular-nums hover:text-fg"><Phone :size="13" aria-hidden="true" />{{ formatPhone(row.phone) }}</a>
                <a v-if="row.username" :href="`https://t.me/${row.username}`" target="_blank" rel="noopener" class="inline-flex items-center gap-1 hover:text-fg"><AtSign :size="13" aria-hidden="true" />{{ row.username }}</a>
              </div>
            </div>
          </div>
          <div v-if="row.join_link || row.former" class="flex flex-wrap items-center gap-1.5">
            <UiTooltip v-if="row.join_link" :content="t('people.requests.viaHint')">
              <StatusPill :icon="Link2" tone="primary" class="max-w-full" :label="t('people.requests.via', { name: row.join_link.name })" tabindex="0" data-via />
            </UiTooltip>
            <StatusPill
              v-if="row.former"
              :icon="History"
              :tone="row.former.how === 'blocked' ? 'danger' : 'info'"
              :label="row.former.how === 'blocked' ? t('people.requests.formerBlocked', { date: fmt.day(row.former.left_on, 'medium') }) : t('people.requests.former', { date: fmt.day(row.former.left_on, 'medium') })"
            />
          </div>
          <div class="mt-auto flex items-center gap-2 border-t border-line pt-3">
            <UiButton variant="primary" size="sm" :icon="Check" @click="requestParam = row.id">{{ t("common.approve") }}</UiButton>
            <UiButton size="sm" :icon="X" class="hover:!text-danger" @click="reject(row)">{{ t("common.reject") }}</UiButton>
          </div>
        </article>
      </TransitionGroup>

      <section v-if="waitingForDetails.length" class="flex flex-col gap-2">
        <h2 class="text-sm font-semibold text-muted">{{ t("people.requests.noDetails", { n: waitingForDetails.length }, waitingForDetails.length) }}</h2>
        <ul class="ui-card divide-y divide-[var(--c-border)]">
          <li v-for="row in waitingForDetails" :key="row.id" class="flex items-center gap-3 px-4 py-2.5">
            <UserAvatar :name="row.name" :src="row.photo_url" :size="28" />
            <span class="min-w-0 flex-1 truncate text-base text-fg">{{ row.name }}</span>
            <span class="text-xs text-subtle">{{ t("people.requests.noDetailsHint") }}</span>
            <UiButton size="sm" variant="ghost" class="hover:!text-danger" @click="reject(row)">{{ t("common.reject") }}</UiButton>
          </li>
        </ul>
      </section>
    </template>

    <BulkActionBar :count="selection.selected.value.length" @clear="selection.clear()">
      <UiButton size="sm" variant="ghost" :icon="Check" :loading="running === 'approve'" :disabled="running === 'reject'" data-bulk-approve @click="bulkOpen = true">{{ t("common.approve") }}</UiButton>
      <UiButton size="sm" variant="ghost" :icon="X" :loading="running === 'reject'" :disabled="running === 'approve'" data-bulk-reject @click="rejectChosen">{{ t("common.reject") }}</UiButton>
    </BulkActionBar>

    <ApproveDialog v-if="approving && dialogOpen" v-model:open="dialogOpen" :request="approving" :busy="decide.isPending.value" @approve="(body) => approve(approving!, body)" />
    <BulkApproveDialog v-if="bulkOpen && chosen.length" v-model:open="bulkOpen" :requests="chosen" :busy="bulk.isPending.value" @approve="approveChosen" />
  </div>
</template>
