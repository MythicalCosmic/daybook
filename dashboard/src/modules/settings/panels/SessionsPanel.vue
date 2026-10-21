<script setup lang="ts">
/**
 * Settings › Sessions and devices (plan §4.3, §7.3, Should): every browser signed in as you, this
 * one first. Sign one out, every other one, or everywhere (which signs this browser out too and
 * ends every outstanding token). A revoked browser stops refreshing at once; its 15-minute access
 * token runs out by itself. Inside Telegram there is no session: you are signed in by the bot.
 */
import { Globe, LogOut, Monitor, ShieldCheck, ShieldX, Smartphone, Tablet } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiBadge from "@/components/UiBadge.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useSessionStore } from "@/stores/session";

import { useSessionMutations, useSessions } from "../api";
import PanelHeader from "../components/PanelHeader.vue";
import type { DeviceSession } from "../types";

const { t } = useI18n();
const router = useRouter();
const fmt = useFormat();
const sessions = useSessions();
const mutations = useSessionMutations();
const session = useSessionStore();
const confirm = useConfirm();
const showSkeleton = useDelayedPending(() => sessions.isPending.value);

const others = computed(() => (sessions.data.value ?? []).filter((s) => !s.current));
const hasCurrent = computed(() => (sessions.data.value ?? []).some((s) => s.current));
const icons = { desktop: Monitor, phone: Smartphone, tablet: Tablet } as const;

async function signOut(row: DeviceSession): Promise<void> {
  const answer = await confirm({
    title: t("settings.sessions.signOutTitle", { device: row.device.label }),
    message: t("settings.sessions.signOutBody"),
    confirmLabel: t("settings.sessions.signOut"),
    tone: "danger",
  });
  if (!answer) return;
  await mutations.revoke.mutateAsync(row.id);
  toast.success(t("settings.sessions.signedOut", { device: row.device.label }));
}

async function signOutOthers(): Promise<void> {
  const answer = await confirm({
    title: t("settings.sessions.othersTitle"),
    message: t("settings.sessions.othersBody", { n: others.value.length }, others.value.length),
    confirmLabel: t("settings.sessions.others"),
    tone: "danger",
  });
  if (!answer) return;
  const result = await mutations.revokeAll.mutateAsync(true);
  toast.success(t("settings.sessions.othersDone", { n: result.revoked }, result.revoked));
}

async function signOutEverywhere(): Promise<void> {
  const answer = await confirm({
    title: t("settings.sessions.everywhereTitle"),
    message: t("settings.sessions.everywhereBody"),
    confirmLabel: t("settings.sessions.everywhere"),
    tone: "danger",
    icon: ShieldX,
  });
  if (!answer) return;
  await mutations.revokeAll.mutateAsync(false);
  session.endSession();
  await router.replace("/login");
}
</script>

<template>
  <div>
    <PanelHeader :title="t('settings.panel.sessions')" :description="t('settings.sessions.description')">
      <template v-if="sessions.data.value?.length" #actions>
        <UiButton v-if="others.length && hasCurrent" :icon="LogOut" :loading="mutations.revokeAll.isPending.value" @click="signOutOthers">{{ t("settings.sessions.others") }}</UiButton>
        <UiButton variant="danger" :icon="ShieldX" @click="signOutEverywhere">{{ t("settings.sessions.everywhere") }}</UiButton>
      </template>
    </PanelHeader>

    <InlineAlert v-if="sessions.data.value && !hasCurrent" class="mb-4" tone="info" :icon="ShieldCheck" :description="t('settings.sessions.telegramNote')" />

    <ErrorState v-if="sessions.isError.value" :error="sessions.error.value" :retry="() => sessions.refetch()" :retrying="sessions.isFetching.value" />

    <div v-else-if="showSkeleton || !sessions.data.value" class="ui-card divide-y divide-line" aria-busy="true">
      <div v-for="n in 3" :key="n" class="flex items-center gap-4 p-4">
        <SkeletonBlock width="40px" height="40px" radius="10px" />
        <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="30%" /><SkeletonBlock width="55%" /></div>
      </div>
    </div>

    <EmptyState v-else-if="!sessions.data.value.length" :title="t('settings.sessions.emptyTitle')" :description="t('settings.sessions.emptyBody')" :icon="ShieldCheck" tone="success" />

    <TransitionGroup v-else tag="ul" name="list" class="ui-card divide-y divide-line overflow-hidden">
      <li v-for="row in sessions.data.value" :key="row.id" class="flex items-center gap-3 p-4 sm:gap-4">
        <span :class="['grid size-10 shrink-0 place-items-center self-start rounded-[10px] sm:self-center', row.current ? 'bg-success-soft text-success' : 'bg-surface-2 text-muted']">
          <component :is="icons[row.device.kind]" :size="20" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="flex flex-wrap items-center gap-2 text-base font-semibold text-fg">
            {{ row.device.label }}
            <UiBadge v-if="row.current" tone="success">{{ t("settings.sessions.thisDevice") }}</UiBadge>
          </p>
          <p class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-muted">
            <span v-if="row.ip" class="inline-flex items-center gap-1"><Globe :size="13" />{{ row.ip }}</span>
            <span>{{ t("settings.sessions.since", { date: fmt.instant(row.created_at, "date") }) }}</span>
            <span v-if="row.current" class="text-success">{{ t("settings.sessions.activeNow") }}</span>
            <span v-else>{{ t("settings.sessions.lastSeen") }} <RelativeTime :value="row.last_seen_at" /></span>
          </p>
        </div>
        <UiButton v-if="!row.current" variant="ghost" size="sm" :icon="LogOut" class="shrink-0" @click="signOut(row)">{{ t("settings.sessions.signOut") }}</UiButton>
      </li>
    </TransitionGroup>

    <p class="mt-4 flex items-start gap-2 text-sm text-muted"><ShieldCheck :size="15" class="mt-0.5 shrink-0 text-success" />{{ t("settings.sessions.footer") }}</p>
  </div>
</template>

<style scoped>
.list-leave-active {
  transition:
    opacity var(--dur-fade) var(--ease-out),
    transform var(--dur-fade) var(--ease-out);
}
.list-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>
