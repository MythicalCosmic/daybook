<script setup lang="ts">
/** Learning's overview (`learning.overview.cards`): this week's top learners by learning points. */
import { GraduationCap } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { useLeaderboard } from "../api";

defineProps<{ context?: { companyId?: number | null } }>();
const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const board = useLeaderboard(() => ({ period: "week", kind: "learning" }));
const rows = computed(() => (board.data.value?.rows ?? []).slice(0, 5));
</script>

<template>
  <section class="ui-card flex flex-col gap-3 p-4" data-testid="recognition-top-learners">
    <div class="flex items-center justify-between gap-3">
      <h3 class="flex items-center gap-2 text-sm font-semibold text-fg"><GraduationCap :size="16" aria-hidden="true" />{{ t("recognition.topLearners.title") }}</h3>
      <RouterLink :to="`/c/${company.currentId}/recognition?kind=learning`" class="text-sm font-medium text-primary hover:underline">{{ t("recognition.topLearners.all") }}</RouterLink>
    </div>
    <SkeletonBlock v-if="board.isPending.value" height="120px" radius="10px" />
    <EmptyState v-else-if="!rows.length" size="sm" :title="t('recognition.topLearners.empty')" />
    <ol v-else class="flex flex-col gap-2">
      <li v-for="row in rows" :key="row.member.id" class="flex items-center gap-3">
        <span class="w-5 text-center text-sm font-semibold tabular-nums text-muted">{{ row.place }}</span>
        <UserAvatar :name="row.member.name" :src="row.member.avatar_url" :size="28" />
        <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ row.member.name }}</span>
        <span class="text-sm font-semibold tabular-nums">{{ fmt.number(row.points) }}</span>
      </li>
    </ol>
  </section>
</template>
