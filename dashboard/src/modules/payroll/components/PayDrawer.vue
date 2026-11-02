<script setup lang="ts">
/**
 * One person's pay in a side panel synced with `?member=`: the setup in force, the one coming
 * next, and every earlier one, newest first. Rows a finalized payroll used are locked (read-only,
 * with the reason); a change is a new row from a day, made with "Change pay".
 */
import { CalendarClock, Lock, Pencil, WalletCards } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UiDrawer from "@/components/UiDrawer.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useCompanyStore } from "@/stores/company";

import type { Compensation, PayRow } from "../types";
import ChangePayDialog from "./ChangePayDialog.vue";
import PayHistory from "./PayHistory.vue";

const props = defineProps<{ rows: PayRow[] }>();

const { t } = useI18n();
const route = useRoute();
const company = useCompanyStore();
const canManage = computed(() => company.can("payroll.manage"));

const memberId = computed(() => {
  const raw = route.query.member;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && /^\d+$/.test(value) ? Number(value) : null;
});
const row = computed(() => props.rows.find((item) => item.member.id === memberId.value) ?? null);

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
        <EmptyState v-if="!row" size="sm" :icon="WalletCards" :title="t('payroll.pay.notFound')" />
        <div v-else class="flex flex-col gap-5">
          <header class="flex items-center gap-3">
            <UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="44" shape="rounded" />
            <div class="min-w-0 flex-1">
              <RouterLink :to="`/c/${company.currentId}/people/${row.member.id}/pay`" class="block truncate text-base font-semibold text-fg hover:underline">{{ row.member.name }}</RouterLink>
              <p v-if="row.member.position" class="truncate text-sm text-muted">{{ row.member.position }}</p>
            </div>
            <StatusPill v-if="!row.current" tone="warning" size="sm" :label="t('payroll.pay.none')" />
          </header>

          <PayHistory :history="row.history" :current="row.current" :editable="canManage" @edit="change" />
        </div>
      </div>
    </template>
    <template #footer>
      <div v-if="row && canManage" class="flex w-full items-center gap-2">
        <p v-if="row.upcoming" class="inline-flex min-w-0 flex-1 items-center gap-1 truncate text-xs text-muted"><CalendarClock :size="12" />{{ t("payroll.pay.upcomingHint") }}</p>
        <span v-else class="flex-1" />
        <UiButton variant="primary" size="sm" :icon="row.current ? Pencil : WalletCards" data-testid="change-pay" @click="change()">{{ row.current ? t("payroll.pay.change") : t("payroll.pay.set") }}</UiButton>
      </div>
      <p v-else-if="row && !canManage" class="inline-flex items-center gap-1.5 text-xs text-muted"><Lock :size="12" />{{ t("payroll.pay.readOnly") }}</p>
    </template>
  </UiDrawer>
  <ChangePayDialog v-if="row" v-model:open="changing" :member="row.member" :history="row.history" :start="editing" />
</template>
