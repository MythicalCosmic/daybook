<script setup lang="ts">
/**
 * One person on the Equipment page: who they are, what they hold (a chip each, with its menu), what
 * it is worth (for register readers), and what needs doing: things not confirmed in the app, a
 * last day coming with things still held, or things still out after they left.
 */
import { HandHelping } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import MoneyText from "@/components/MoneyText.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import ItemChip from "./ItemChip.vue";
import type { EquipmentCan, HeldItem, Holder } from "./types";

const props = defineProps<{ row: Holder; can: EquipmentCan; today: string }>();
const emit = defineEmits<{ give: [row: Holder]; action: [kind: "returned" | "lost" | "deduct", row: Holder, item: HeldItem] }>();

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();

const gone = computed(() => props.row.person.status === "left" || props.row.person.status === "blocked");
const subtitle = computed(() => [props.row.person.position, props.row.person.home_branch?.name].filter(Boolean).join(" · "));
</script>

<template>
  <article
    :class="['ui-card flex flex-col gap-3 p-3.5 sm:flex-row sm:items-start sm:gap-4', row.overdue ? 'ring-1 ring-[color-mix(in_srgb,var(--c-danger)_35%,transparent)]' : '']"
    :data-holder="row.person.id"
  >
    <div class="flex min-w-0 items-start gap-3 sm:w-64 sm:shrink-0">
      <UserAvatar :name="row.person.name" :src="row.person.photo_url" :size="40" />
      <div class="min-w-0 flex-1">
        <RouterLink :to="`/c/${company.currentId}/people/${row.person.id}/equipment`" class="block truncate text-base font-semibold text-fg hover:underline">{{ row.person.name }}</RouterLink>
        <p v-if="subtitle" class="truncate text-sm text-muted">{{ subtitle }}</p>
        <div class="mt-1.5 flex flex-wrap gap-1">
          <StatusPill v-if="gone" size="sm" tone="danger" :label="row.left_on ? t('lifecycle.equipment.flag.leftOn', { date: fmt.day(row.left_on, 'short') }) : t('lifecycle.equipment.flag.left')" />
          <StatusPill
            v-else-if="row.leaving"
            size="sm"
            :tone="row.leaving_soon ? 'warning' : 'neutral'"
            :label="row.leaving.day ? t('lifecycle.equipment.flag.leaving', { date: fmt.day(row.leaving.day, 'short') }) : t('lifecycle.equipment.flag.leavingOpen')"
          />
          <StatusPill v-if="row.unconfirmed" size="sm" variant="outline" tone="warning" :label="t('lifecycle.equipment.flag.unconfirmed', { n: row.unconfirmed }, row.unconfirmed)" />
        </div>
      </div>
    </div>

    <div class="min-w-0 flex-1">
      <div v-if="row.items.length" class="flex flex-wrap gap-1.5" data-items>
        <ItemChip v-for="item in row.items" :key="item.assignment_id" :holder="row" :item="item" :can="can" :today="today" @action="(kind, held) => emit('action', kind, row, held)" />
      </div>
      <p v-else class="pt-1.5 text-sm text-subtle">{{ t("lifecycle.equipment.holdsNothing") }}</p>
      <p v-if="row.overdue" class="mt-2 text-xs font-medium text-danger">{{ t("lifecycle.equipment.overdue", { n: row.overdue }, row.overdue) }}</p>
      <p v-else-if="row.leaving_soon" class="mt-2 text-xs font-medium text-warning">{{ t("lifecycle.equipment.toReturn", { n: row.items.length }, row.items.length) }}</p>
    </div>

    <div class="flex shrink-0 items-center justify-between gap-3 sm:flex-col sm:items-end sm:justify-start">
      <span v-if="can.values && row.items.length" class="text-sm font-semibold tabular-nums text-fg"><MoneyText :value="row.value" :currency="company.currency" /></span>
      <UiButton v-if="!gone" size="sm" variant="secondary" :icon="HandHelping" data-give @click="emit('give', row)">{{ t("lifecycle.equipment.give") }}</UiButton>
    </div>
  </article>
</template>
