<script setup lang="ts">
/**
 * One person's pay in a side panel synced with `?member=`: the setup in force, the one coming
 * next, and every earlier one, newest first (`compensations/?member=`). Rows a finalized payroll
 * used are locked (read-only, with the reason); a change is a new row from a day, made with
 * "Change pay".
 */
import { CalendarClock, Lock, Pencil, UserRoundX, WalletCards } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { todayIn } from "@/lib/dates";
import { useCompanyStore } from "@/stores/company";

import { useCompensations } from "../api";
import { payHistory } from "../lib";
import type { Compensation, Member, PayRow } from "../types";
import ChangePayDialog from "./ChangePayDialog.vue";
import PayHistory from "./PayHistory.vue";

/** `ready`: the list has loaded, so a person missing from it (a stale link, another branch) is gone. */
const props = defineProps<{ rows: PayRow[]; ready?: boolean }>();

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();
const canManage = computed(() => company.can("payroll.manage"));

const memberId = computed(() => {
  const raw = route.query.member;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const query = useCompensations(
  () => ({ member: memberId.value }),
  () => memberId.value !== null,
);
const pay = computed(() => payHistory(query.data.value ?? [], todayIn(company.timezone)));
/** The person from the list (with position and branch), or from their pay rows on a deep link. */
const member = computed<Member | null>(() => props.rows.find((row) => row.member.id === memberId.value)?.member ?? query.data.value?.[0]?.member ?? null);
const where = computed(() => [member.value?.position, member.value?.home_branch].filter(Boolean).join(" · "));

const changing = ref(false);
const editing = ref<Compensation | null>(null);
function change(from?: Compensation): void {
  editing.value = from ?? null;
  changing.value = true;
}
</script>

<template>
  <UiDrawer query-key="member" size="md" :title="t('payroll.pay.drawerTitle')">
    <template #default>
      <div class="p-5">
        <div v-if="query.isPending.value && memberId" class="flex flex-col gap-4">
          <SkeletonBlock height="44px" radius="12px" />
          <SkeletonBlock v-for="n in 3" :key="n" height="120px" radius="12px" />
        </div>
        <ErrorState v-else-if="query.isError.value" :error="query.error.value" :retry="() => query.refetch()" />
        <EmptyState v-else-if="ready && !member" tone="neutral" :icon="UserRoundX" :title="t('payroll.pay.notFound')" :description="t('payroll.pay.notFoundBody')" data-testid="pay-not-found" />
        <div v-else class="flex flex-col gap-5">
          <header v-if="member" class="flex items-center gap-3">
            <UserAvatar :name="member.name" :src="member.photo_url" :size="44" shape="rounded" />
            <div class="min-w-0 flex-1">
              <RouterLink :to="`/c/${company.currentId}/people/${member.id}/pay`" class="block truncate text-base font-semibold text-fg hover:underline">{{ member.name }}</RouterLink>
              <p v-if="where" class="truncate text-sm text-muted">{{ where }}</p>
            </div>
            <StatusPill v-if="!pay.current" tone="warning" size="sm" :label="t('payroll.pay.none')" />
          </header>

          <PayHistory :history="pay.history" :current="pay.current" :editable="canManage" @edit="change" />
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="memberId && canManage && member" class="flex w-full items-center gap-2">
        <p v-if="pay.upcoming" class="inline-flex min-w-0 flex-1 items-center gap-1 truncate text-xs text-muted"><CalendarClock :size="12" />{{ t("payroll.pay.upcomingHint") }}</p>
        <span v-else class="flex-1" />
        <UiButton variant="primary" size="sm" :icon="pay.current ? Pencil : WalletCards" :disabled="!member" data-testid="change-pay" @click="change()">{{ pay.current ? t("payroll.pay.change") : t("payroll.pay.set") }}</UiButton>
      </div>
      <p v-else-if="memberId && member" class="inline-flex items-center gap-1.5 text-xs text-muted"><Lock :size="12" />{{ t("payroll.pay.readOnly") }}</p>
    </template>
  </UiDrawer>
  <ChangePayDialog v-if="member" v-model:open="changing" :member="member" :history="pay.history" :start="editing" />
</template>
