<script setup lang="ts">
/**
 * Thanks between colleagues (PLAN-LEARNING §7.5, §11), newest first, for every branch the viewer
 * sees or one: who thanked whom, for what, the note. Owners hide an inappropriate one (it
 * disappears everywhere and its points go); anyone here can say thanks.
 */
import { EyeOff, HeartHandshake, Send } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import BranchPicker from "@/components/BranchPicker.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";
import { useCompanyStore } from "@/stores/company";

import { recognitionApi, useKudosFeed, useRefresh } from "../api";
import KudosDialog from "../components/KudosDialog.vue";
import { kudosIcon, MANAGE } from "../lib";
import type { Kudos } from "../types";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const branch = useRouteState("branch", rs.optionalNumber());
const feed = useKudosFeed(() => (branch.value ? { branch: branch.value } : {}));
const canHide = computed(() => company.can(MANAGE));
const sending = ref(false);

async function hide(row: Kudos): Promise<void> {
  const answer = await confirm({
    title: t("recognition.kudosFeed.hideTitle"),
    message: t("recognition.kudosFeed.hideBody", { from: row.from.name, to: row.to.name }),
    confirmLabel: t("recognition.kudosFeed.hide"),
    tone: "danger",
    onConfirm: () => recognitionApi.hideKudos(company.currentId ?? 0, row.id),
  });
  if (answer) {
    toast.success(t("recognition.kudosFeed.hidden"));
    refresh();
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('recognition.nav.kudos')" :description="t('recognition.kudosFeed.description')">
      <template #actions>
        <UiButton variant="primary" :icon="Send" @click="sending = true">{{ t("recognition.kudos.button") }}</UiButton>
      </template>
    </PageHeader>
    <div class="flex items-center gap-3">
      <div class="w-56"><BranchPicker v-model="branch" clearable :placeholder="t('recognition.board.allBranches')" /></div>
    </div>

    <div v-if="feed.isPending.value" class="grid gap-3"><SkeletonBlock v-for="n in 3" :key="n" height="88px" radius="12px" /></div>
    <ErrorState v-else-if="feed.isError.value" :error="feed.error.value" :retry="() => feed.refetch()" />
    <div v-else-if="!feed.data.value?.length" class="ui-card">
      <EmptyState :icon="HeartHandshake" :title="t('recognition.kudosFeed.emptyTitle')" :description="t('recognition.kudosFeed.emptyBody')" />
    </div>
    <ul v-else class="flex flex-col gap-3" data-testid="kudos-feed">
      <li v-for="row in feed.data.value" :key="row.id" class="ui-card flex items-start gap-3 p-4">
        <UserAvatar :name="row.from.name" :src="row.from.avatar_url" :size="40" />
        <div class="min-w-0 flex-1">
          <p class="text-sm text-fg">
            <span class="font-semibold">{{ row.from.name }}</span>
            <span class="text-muted"> → </span>
            <span class="font-semibold">{{ row.to.name }}</span>
          </p>
          <p class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span class="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent-fg">
              <component :is="kudosIcon(row.badge)" :size="13" aria-hidden="true" />{{ t(`recognition.kudosBadge.${row.badge}`) }}
            </span>
            <span>{{ fmt.instant(row.at, "datetime") }}</span>
            <span v-if="row.task">· {{ row.task.title }}</span>
          </p>
          <p v-if="row.message" class="mt-2 text-sm text-fg">«{{ row.message }}»</p>
        </div>
        <UiButton v-if="canHide" size="sm" variant="ghost" :icon="EyeOff" :aria-label="t('recognition.kudosFeed.hide')" @click="hide(row)" />
      </li>
    </ul>

    <KudosDialog v-model:open="sending" />
  </div>
</template>
