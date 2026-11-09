<script setup lang="ts">
/**
 * The badge catalogue (PLAN-LEARNING §7.3, §11): every badge with its tier, how to earn it and who
 * has it (approved people in the viewer's branches, or one branch), the newest first.
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import AvatarStack from "@/components/AvatarStack.vue";
import BranchPicker from "@/components/BranchPicker.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useFormat } from "@/lib/useFormat";
import { rs, useRouteState } from "@/lib/useRouteState";

import { useBadges } from "../api";
import Medal from "../components/Medal.vue";
import { personRef } from "../lib";

const { t } = useI18n();
const fmt = useFormat();
const branch = useRouteState("branch", rs.optionalNumber());
const badges = useBadges(() => (branch.value ? { branch: branch.value } : {}));
const earned = computed(() => (badges.data.value ?? []).reduce((sum, entry) => sum + entry.count, 0));
const expanded = ref<string | null>(null);
</script>

<template>
  <div class="flex flex-col gap-4">
    <PageHeader :title="t('recognition.nav.badges')" :description="t('recognition.badges.description', { n: earned }, earned)" />
    <div class="w-56"><BranchPicker v-model="branch" clearable :placeholder="t('recognition.board.allBranches')" /></div>

    <div v-if="badges.isPending.value" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><SkeletonBlock v-for="n in 6" :key="n" height="120px" radius="12px" /></div>
    <ul v-else class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="badge-catalogue">
      <li v-for="entry in badges.data.value" :key="entry.key" class="ui-card flex flex-col gap-3 p-4">
        <div class="flex items-start gap-3">
          <Medal :icon="entry.icon" :tier="entry.tier" :size="48" :locked="entry.count === 0" />
          <div class="min-w-0 flex-1">
            <p class="font-semibold text-fg">{{ entry.name }}</p>
            <p class="text-xs font-medium uppercase tracking-wide text-muted">{{ t(`recognition.tier.${entry.tier}`) }}</p>
            <p class="mt-1 text-sm text-muted">{{ entry.description }}</p>
          </div>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="text-sm text-muted">{{ t("recognition.badges.holders", { n: entry.count }, entry.count) }}</span>
          <AvatarStack v-if="entry.count" :people="entry.holders.map((holder) => personRef(holder.member))" :max="5" />
        </div>
        <template v-if="entry.count">
          <UiButton size="sm" variant="ghost" class="self-start" @click="expanded = expanded === entry.key ? null : entry.key">
            {{ expanded === entry.key ? t("recognition.badges.hide") : t("recognition.badges.who") }}
          </UiButton>
          <ul v-if="expanded === entry.key" class="divide-y divide-line">
            <li v-for="holder in entry.holders" :key="`${holder.member.id}:${holder.ref}`" class="flex items-center justify-between gap-3 py-1.5 text-sm">
              <span class="min-w-0 truncate text-fg">{{ holder.member.name }}<span v-if="holder.ref" class="text-muted"> · {{ holder.name }}</span></span>
              <span class="shrink-0 text-xs text-muted">{{ fmt.instant(holder.awarded_at, "date") }}</span>
            </li>
          </ul>
        </template>
      </li>
    </ul>
  </div>
</template>
