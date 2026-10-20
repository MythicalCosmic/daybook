<script setup lang="ts">
/**
 * Join requests (plan §6.2 "Requests"): people who opened the invite link, newest decisions first
 * waiting. Approve with role, position, branches and home branch; reject with an optional reason.
 * A request leaves the list at once and comes back if the server refuses. `?request=12` opens the
 * approval for that request (links from Needs you and the bot).
 */
import { AtSign, Check, History, Phone, QrCode, UserPlus, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import UserAvatar from "@/components/UserAvatar.vue";
import { toast } from "@/components/useToast";
import { formatPhone } from "@/lib/format";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { useDecideRequest, useJoinRequests } from "../api";
import ApproveDialog from "../components/ApproveDialog.vue";
import type { ApproveInput, JoinRequest } from "../types";

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

const requestParam = useRouteState("request", rs.optionalNumber());
const approving = computed(() => (requestParam.value === null ? null : (query.data.value ?? []).find((row) => row.id === requestParam.value) ?? null));
const dialogOpen = ref(false);
watch(approving, (row) => (dialogOpen.value = row !== null && row.onboarded), { immediate: true });
watch(dialogOpen, (value) => {
  if (!value) requestParam.value = null;
});

/** The invite page belongs to package A; link to it only once it exists. */
const invite = computed(() => {
  const path = `/c/${company.currentId}/settings/invite`;
  return router.resolve(path).name !== "company-not-found" ? path : null;
});

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
</script>

<template>
  <div class="flex flex-col gap-5">
    <PageHeader :title="t('people.requests.title')" :description="t('people.requests.description')" :back="`/c/${company.currentId}/people`" :back-label="t('people.nav.team')">
      <template v-if="invite" #actions>
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
        <UiButton v-if="invite" :to="invite" variant="primary" :icon="QrCode">{{ t("people.requests.invite") }}</UiButton>
      </EmptyState>
    </div>
    <template v-else>
      <TransitionGroup name="list" tag="div" class="relative grid grid-cols-1 gap-3 lg:grid-cols-2">
        <article v-for="row in ready" :key="row.id" class="ui-card flex flex-col gap-3 p-4">
          <div class="flex items-start gap-3">
            <UserAvatar :name="row.name" :src="row.photo_url" :size="44" />
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
          <StatusPill
            v-if="row.former"
            :icon="History"
            :tone="row.former.how === 'blocked' ? 'danger' : 'info'"
            class="w-fit"
            :label="row.former.how === 'blocked' ? t('people.requests.formerBlocked', { date: fmt.day(row.former.left_on, 'medium') }) : t('people.requests.former', { date: fmt.day(row.former.left_on, 'medium') })"
          />
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

    <ApproveDialog v-if="approving && dialogOpen" v-model:open="dialogOpen" :request="approving" :busy="decide.isPending.value" @approve="(body) => approve(approving!, body)" />
  </div>
</template>
