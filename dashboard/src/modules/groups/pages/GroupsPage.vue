<script setup lang="ts">
/**
 * Groups (plan §1.5, §6.2 "Groups (A)"): the company's Telegram groups and what the bot posts in
 * each. Adding the bot to a group as a manager connects it; this page chooses its events and whose
 * news it gets, and disconnects it.
 */
import { Bot, Link2Off, Plus, Send, UsersRound } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useDelayedPending } from "@/lib/useDelayedPending";

import { useGroups } from "../api";
import GroupCard from "../components/GroupCard.vue";

const { t } = useI18n();
const groups = useGroups();
const { isPhone } = useBreakpoints();
const showSkeleton = useDelayedPending(() => groups.isPending.value);

const active = computed(() => (groups.data.value?.results ?? []).filter((g) => g.is_active));
const inactive = computed(() => (groups.data.value?.results ?? []).filter((g) => !g.is_active));
const link = computed(() => groups.data.value?.connect_link ?? "");
</script>

<template>
  <div>
    <PageHeader :title="t('groups.title')" :description="t('groups.description')">
      <template v-if="link && active.length" #actions>
        <UiButton variant="primary" :icon="Plus" :href="link" target="_blank">{{ t("groups.add") }}</UiButton>
      </template>
    </PageHeader>

    <ErrorState v-if="groups.isError.value" :error="groups.error.value" :retry="() => groups.refetch()" :retrying="groups.isFetching.value" />

    <div v-else-if="showSkeleton || !groups.data.value" class="flex flex-col gap-4" aria-busy="true">
      <div v-for="n in 2" :key="n" class="ui-card flex flex-col gap-4 p-5">
        <div class="flex items-center gap-3"><SkeletonBlock width="40px" height="40px" radius="11px" /><div class="flex flex-1 flex-col gap-2"><SkeletonBlock width="30%" /><SkeletonBlock width="45%" /></div></div>
        <SkeletonBlock :lines="3" />
      </div>
    </div>

    <div v-else-if="!active.length" class="flex flex-col gap-6">
      <EmptyState :title="t('groups.emptyTitle')" :description="t('groups.emptyBody')" :icon="UsersRound" size="lg">
        <UiButton v-if="link" variant="primary" size="lg" :icon="Send" :href="link" target="_blank">{{ t("groups.add") }}</UiButton>
      </EmptyState>
      <ol class="mx-auto grid w-full max-w-[860px] gap-3 md:grid-cols-3">
        <li v-for="step in [1, 2, 3]" :key="step" class="ui-card flex gap-3 p-4">
          <span class="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-accent-fg">{{ step }}</span>
          <span>
            <span class="block text-base font-semibold text-fg">{{ t(`groups.step${step}.title`) }}</span>
            <span class="mt-0.5 block text-sm text-muted">{{ t(`groups.step${step}.body`, { bot: groups.data.value.bot_username ? `@${groups.data.value.bot_username}` : t("groups.theBot") }) }}</span>
          </span>
        </li>
      </ol>
    </div>

    <div v-else class="flex flex-col gap-5">
      <GroupCard
        v-for="(group, index) in active"
        :key="group.id"
        :group="group"
        :options="groups.data.value.options"
        :person-events="groups.data.value.person_events"
        :default-open="index === 0 && !isPhone"
      />
      <p class="flex items-center gap-2 text-sm text-muted"><Bot :size="15" class="text-primary" />{{ t("groups.footer") }}</p>
    </div>

    <PageSection v-if="inactive.length && groups.data.value" class="mt-8" :title="t('groups.disconnectedTitle')" :count="inactive.length" collapsible id="groups-disconnected">
      <ul class="flex flex-col gap-2">
        <li v-for="group in inactive" :key="group.id" class="flex items-center gap-3 rounded-[12px] border border-dashed border-line px-4 py-3 text-muted">
          <Link2Off :size="16" />
          <span class="min-w-0 flex-1 truncate text-base">{{ group.title || t("groups.untitled") }}</span>
          <span class="text-sm">{{ t("groups.reconnectHint") }}</span>
        </li>
      </ul>
    </PageSection>
  </div>
</template>
