<script setup lang="ts">
/** People who blocked the employee bot (plan §1.3): reminders can't reach them until they unblock it. */
import { BellOff, MessageCircleWarning, ShieldCheck } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import RelativeTime from "@/components/RelativeTime.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useCompanyStore } from "@/stores/company";

import { useBlocked } from "../api";

const { t } = useI18n();
const company = useCompanyStore();
const query = useBlocked();
const skeleton = useDelayedPending(computed(() => query.isPending.value));
</script>

<template>
  <div class="flex flex-col gap-3">
    <p class="flex items-start gap-2 rounded-[10px] bg-surface-2 px-3 py-2.5 text-sm text-muted">
      <MessageCircleWarning :size="16" class="mt-0.5 shrink-0 text-warning" />{{ t("reminders.blocked.hint") }}
    </p>
    <div v-if="skeleton" class="grid gap-3 md:grid-cols-2"><SkeletonBlock v-for="n in 2" :key="n" height="88px" radius="12px" /></div>
    <ErrorState v-else-if="query.isError.value" class="ui-card" :error="query.error.value" :retry="() => query.refetch()" />
    <div v-else-if="query.data.value && !query.data.value.length" class="ui-card">
      <EmptyState tone="success" :icon="ShieldCheck" :title="t('reminders.blocked.emptyTitle')" :description="t('reminders.blocked.emptyBody')" />
    </div>
    <ul v-else class="grid gap-3 md:grid-cols-2">
      <li v-for="row in query.data.value" :key="row.member.id" class="ui-card flex min-w-0 items-center gap-3 p-4">
        <span class="relative">
          <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="40" />
          <span class="absolute -bottom-0.5 -right-0.5 grid size-5 place-items-center rounded-full border-2 border-surface bg-danger text-on-primary"><BellOff :size="10" /></span>
        </span>
        <div class="min-w-0 flex-1">
          <RouterLink :to="`/c/${company.currentId}/people/${row.member.id}`" class="block truncate text-base font-semibold text-fg hover:underline">{{ row.member.name }}</RouterLink>
          <p class="truncate text-sm text-muted">{{ [row.member.position, row.branch].filter(Boolean).join(" · ") }}</p>
          <p class="mt-0.5 text-xs text-subtle">{{ t("reminders.blocked.since") }} <RelativeTime :value="row.blocked_at" /></p>
        </div>
        <div class="shrink-0 text-right">
          <RouterLink :to="`/c/${company.currentId}/tasks?assignee=${row.member.id}&sv=open`" class="block text-md font-semibold tabular-nums text-fg hover:underline">{{ row.open_tasks }}</RouterLink>
          <p class="text-xs text-muted">{{ t("reminders.blocked.open") }}</p>
          <p v-if="row.late_tasks" class="text-xs font-semibold text-danger">{{ t("reminders.blocked.late", { n: row.late_tasks }) }}</p>
        </div>
      </li>
    </ul>
  </div>
</template>
