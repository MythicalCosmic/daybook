<script setup lang="ts">
/**
 * A person's pay setups as a timeline, newest first: the coming one, the one in force, the
 * earlier ones. Each says the pay, how it is prorated, overtime and task rates, who set it and
 * why; a row a finalized payroll used is locked, with the reason. Unlocked rows can be edited.
 */
import { Clock3, ListChecks, Lock, Pencil } from "@lucide/vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/EmptyState.vue";
import IconButton from "@/components/IconButton.vue";
import StatusPill from "@/components/StatusPill.vue";
import { useFormat } from "@/lib/useFormat";

import type { Compensation } from "../types";
import PayAmount from "./PayAmount.vue";

withDefaults(defineProps<{ history: Compensation[]; current: Compensation | null; editable?: boolean }>(), { editable: false });
const emit = defineEmits<{ edit: [row: Compensation] }>();

const { t } = useI18n();
const fmt = useFormat();
</script>

<template>
  <EmptyState v-if="!history.length" size="sm" :icon="Clock3" :title="t('payroll.pay.noHistory')" :description="t('payroll.pay.noHistoryBody')" tone="neutral" />
  <ol v-else class="relative flex flex-col gap-3 before:absolute before:bottom-3 before:left-[7px] before:top-3 before:w-px before:bg-line" data-testid="pay-history">
    <li v-for="row in history" :key="row.id" class="relative pl-6">
      <span
        :class="[
          'absolute left-0 top-4 size-[15px] rounded-full border-2 bg-surface',
          row.id === current?.id ? 'border-primary bg-primary' : row.effective_from > (current?.effective_from ?? '') && row.id !== current?.id ? 'border-info' : 'border-line-strong',
        ]"
        aria-hidden="true"
      />
      <article :class="['rounded-[12px] border px-3.5 py-3', row.id === current?.id ? 'border-primary/40 bg-accent-soft/40' : 'border-line bg-surface']">
        <div class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <p class="text-xs font-medium text-muted">{{ t("payroll.pay.from", { date: fmt.day(row.effective_from, "long") }) }}</p>
            <p class="mt-0.5 text-lg font-semibold tabular-nums text-fg">
              <PayAmount :value="row.amount" :currency="row.currency" /><span class="ml-1 text-sm font-normal text-muted">{{ t(`payroll.pay.per.${row.pay_type}`) }}</span>
            </p>
          </div>
          <StatusPill v-if="row.id === current?.id" tone="primary" size="sm" :label="t('payroll.pay.current')" />
          <StatusPill v-else-if="!current || row.effective_from > current.effective_from" tone="info" size="sm" :label="t('payroll.pay.upcoming')" />
          <IconButton v-if="editable && !row.locked" :icon="Pencil" size="sm" :label="t('payroll.pay.edit')" class="-mr-1.5 -mt-1" @click="emit('edit', row)" />
        </div>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <span class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted">{{ t(`payroll.payType.${row.pay_type}`) }}</span>
          <span v-if="row.pay_type === 'monthly'" class="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted">{{ t(`payroll.proration.${row.proration}`) }}</span>
          <span v-if="row.overtime_eligible" class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted"><Clock3 :size="11" />{{ t("payroll.pay.overtime") }}</span>
          <span v-if="row.pays_task_rates" class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold text-muted"><ListChecks :size="11" />{{ t("payroll.pay.taskRates") }}</span>
        </div>
        <p v-if="row.note" class="mt-2 text-sm text-fg">{{ row.note }}</p>
        <p class="mt-1.5 text-xs text-subtle">
          {{ row.created_by ? t("payroll.pay.setBy", { name: row.created_by.name, date: fmt.instant(row.created_at, "date") }) : fmt.instant(row.created_at, "date") }}
        </p>
        <p v-if="row.locked" class="mt-2 flex items-start gap-1.5 rounded-[8px] bg-surface-2 px-2.5 py-2 text-xs text-muted" data-testid="pay-locked">
          <Lock :size="12" class="mt-px shrink-0" />{{ row.locked_reason || t("payroll.pay.lockedReason") }}
        </p>
      </article>
    </li>
  </ol>
</template>
