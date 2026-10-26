<script setup lang="ts">
/**
 * Team links (Settings › Invite staff, under the main invite link): one QR code or link that adds
 * many people at once, with the branch and role chosen here. The live links first (active, then
 * full), the stopped and expired ones in a quiet "Ended" group (folded when it holds more than 3).
 * A new link opens its live screen as soon as it is saved. `#team-links` in the URL scrolls here
 * (People's "Add people" and Join requests' "Team links" land on it).
 */
import { ChevronDown, Plus, Trash2, UsersRound } from "@lucide/vue";
import { useQueryClient } from "@tanstack/vue-query";
import { computed, defineAsyncComponent, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { settingsKeys, useCompanyId, useJoinLinkMutations, useJoinLinks } from "../api";
import { ENDED_OPEN_MAX, botOf, groupLinks, telegramShare } from "../teamLinks";
import type { JoinLink, PosterTarget } from "../types";
import TeamLinkRow from "./TeamLinkRow.vue";

const TeamLinkDialog = defineAsyncComponent(() => import("./TeamLinkDialog.vue"));
const TeamLinkLive = defineAsyncComponent(() => import("./TeamLinkLive.vue"));

const emit = defineEmits<{ poster: [target: PosterTarget] }>();

const { t } = useI18n();
const route = useRoute();
const client = useQueryClient();
const cid = useCompanyId();
const company = useCompanyStore();
const confirm = useConfirm();
const query = useJoinLinks();
const { update, remove } = useJoinLinkMutations();
const showSkeleton = useDelayedPending(() => query.isPending.value);

const groups = computed(() => groupLinks(query.data.value ?? []));
const endedOpen = ref<boolean | null>(null);
/** Short "Ended" lists start open, long ones folded, until someone opens or folds it. */
const showEnded = computed(() => endedOpen.value ?? groups.value.ended.length <= ENDED_OPEN_MAX);

const dialogOpen = ref(false);
const editing = ref<JoinLink | null>(null);
const live = ref<JoinLink | null>(null);
const copiedId = ref<number | null>(null);

const shareText = computed(() => t("settings.invite.shareText", { company: company.current?.name ?? "" }));
const shareUrl = (link: JoinLink) => telegramShare(link.link, shareText.value);

function openNew(): void {
  editing.value = null;
  dialogOpen.value = true;
}

function edit(link: JoinLink): void {
  editing.value = link;
  dialogOpen.value = true;
}

function onSaved(link: JoinLink, created: boolean): void {
  if (created) live.value = link;
  else toast.success(t("settings.teamLinks.toast.saved"));
}

function closeLive(): void {
  live.value = null;
  void client.invalidateQueries({ queryKey: settingsKeys.joinLinks(cid.value) });
}

async function copy(link: JoinLink): Promise<void> {
  try {
    await navigator.clipboard.writeText(link.link);
    copiedId.value = link.id;
    toast.success(t("settings.invite.copied"));
    setTimeout(() => {
      if (copiedId.value === link.id) copiedId.value = null;
    }, 1800);
  } catch {
    toast.error(t("settings.invite.copyFailed"));
  }
}

function poster(link: JoinLink): void {
  emit("poster", {
    link: link.link,
    company: { name: company.current?.name ?? "", logo: company.current?.logo ?? null },
    bot: botOf(link.link),
    branch: link.branch?.name ?? null,
    autoApprove: link.auto_approve,
  });
}

async function stop(link: JoinLink): Promise<void> {
  try {
    await update.mutateAsync({ id: link.id, patch: { is_active: false } });
    toast.info(t("settings.teamLinks.toast.stopped"), { action: { label: t("settings.teamLinks.resume"), onClick: () => void resume(link) } });
  } catch {
    // Flipped back; the HTTP layer said why.
  }
}

async function resume(link: JoinLink): Promise<void> {
  try {
    const saved = await update.mutateAsync({ id: link.id, patch: { is_active: true } });
    // Resumed but still closed (its end has passed, or every place is taken): say what to change.
    if (saved.status === "expired") toast.warning(t("settings.teamLinks.toast.resumedExpired"));
    else if (saved.status === "full") toast.warning(t("settings.teamLinks.toast.resumedFull"));
    else toast.success(t("settings.teamLinks.toast.resumed"));
  } catch {
    // Flipped back.
  }
}

async function removeLink(link: JoinLink): Promise<void> {
  const answer = await confirm({
    title: t("settings.teamLinks.deleteTitle", { name: link.name }),
    message: t("settings.teamLinks.deleteBody"),
    confirmLabel: t("common.delete"),
    tone: "danger",
    icon: Trash2,
  });
  if (!answer) return;
  try {
    await remove.mutateAsync(link.id);
    toast.success(t("settings.teamLinks.toast.deleted"));
  } catch {
    // Back in the list.
  }
}

// Arriving at "settings/invite#team-links": bring the section into view once it has something to show.
const section = ref<HTMLElement | null>(null);
watch(
  [() => route.hash, () => query.isPending.value],
  async ([hash, pending]) => {
    if (hash !== "#team-links" || pending) return;
    await nextTick();
    section.value?.scrollIntoView({ block: "start", behavior: "smooth" });
  },
  { immediate: true },
);
</script>

<template>
  <section id="team-links" ref="section" class="scroll-mt-[calc(var(--topbar-h)+20px)]" data-team-links>
    <header class="mb-3 flex flex-wrap items-end gap-x-4 gap-y-3">
      <div class="min-w-[min(100%,260px)] flex-1">
        <h3 class="text-md font-semibold text-fg">{{ t("settings.teamLinks.title") }}</h3>
        <p class="mt-0.5 max-w-[620px] text-sm text-muted">{{ t("settings.teamLinks.why") }}</p>
      </div>
      <UiButton v-if="query.data.value?.length" variant="primary" :icon="Plus" data-new-link @click="openNew">{{ t("settings.teamLinks.new") }}</UiButton>
    </header>

    <ErrorState v-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" :retrying="query.isFetching.value" />
    <div v-else-if="showSkeleton || !query.data.value" class="flex flex-col gap-2.5" aria-busy="true">
      <div v-for="n in 2" :key="n" class="ui-card flex items-center gap-4 p-4">
        <div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="40%" /><SkeletonBlock width="65%" height="12px" /><SkeletonBlock width="30%" height="12px" /></div>
        <SkeletonBlock width="110px" height="28px" radius="8px" />
      </div>
    </div>
    <div v-else-if="!query.data.value.length" class="ui-card">
      <EmptyState :icon="UsersRound" :title="t('settings.teamLinks.emptyTitle')" :description="t('settings.teamLinks.emptyBody')">
        <UiButton variant="primary" :icon="Plus" data-new-link @click="openNew">{{ t("settings.teamLinks.new") }}</UiButton>
      </EmptyState>
    </div>
    <template v-else>
      <TransitionGroup name="list" tag="div" class="relative flex flex-col gap-2.5">
        <TeamLinkRow
          v-for="link in groups.live"
          :key="link.id"
          :link="link"
          :copied="copiedId === link.id"
          :share-url="shareUrl(link)"
          @show="live = link"
          @copy="copy(link)"
          @poster="poster(link)"
          @edit="edit(link)"
          @stop="stop(link)"
          @resume="resume(link)"
          @remove="removeLink(link)"
        />
      </TransitionGroup>
      <p v-if="!groups.live.length" class="rounded-[12px] border border-dashed border-line-strong px-4 py-3 text-sm text-muted">{{ t("settings.teamLinks.noneLive") }}</p>

      <div v-if="groups.ended.length" class="mt-5" data-ended>
        <button
          type="button"
          class="pressable -ml-1 inline-flex items-center gap-1.5 rounded-[7px] px-1 py-0.5 text-sm font-semibold text-muted hover:text-fg"
          :aria-expanded="showEnded"
          @click="endedOpen = !showEnded"
        >
          <ChevronDown :size="15" :class="['transition-transform duration-200', !showEnded && '-rotate-90']" aria-hidden="true" />
          {{ t("settings.teamLinks.ended", { n: groups.ended.length }) }}
        </button>
        <div v-if="showEnded" class="mt-2 flex flex-col gap-2.5">
          <TeamLinkRow
            v-for="link in groups.ended"
            :key="link.id"
            :link="link"
            :copied="copiedId === link.id"
            :share-url="shareUrl(link)"
            @show="live = link"
            @copy="copy(link)"
            @poster="poster(link)"
            @edit="edit(link)"
            @stop="stop(link)"
            @resume="resume(link)"
            @remove="removeLink(link)"
          />
        </div>
      </div>
    </template>

    <TeamLinkDialog v-if="dialogOpen" v-model:open="dialogOpen" :link="editing" @saved="onSaved" />
    <TeamLinkLive v-if="live" :link="live" @close="closeLive" />
  </section>
</template>
