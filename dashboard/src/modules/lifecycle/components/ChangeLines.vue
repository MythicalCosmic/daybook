<script setup lang="ts">
/**
 * What a job change does, a line a part: "Position  Farmatsevt → Provizor", the branch they move
 * to, the department, and the pay (its amounts only for payroll.view; otherwise a lock and "The
 * pay changes"). `dense` for table cells and cards.
 */
import { ArrowRight, Banknote, Briefcase, LockKeyhole, MapPin, Network, type LucideIcon } from "@lucide/vue";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import MoneyText from "@/components/MoneyText.vue";

import { partSides } from "../lib";
import type { ChangePart, JobChange } from "../types";

const props = withDefaults(defineProps<{ change: Pick<JobChange, "parts" | "before" | "after" | "has_pay">; dense?: boolean }>(), { dense: false });

const { t } = useI18n();
const ICONS: Record<ChangePart, LucideIcon> = { position: Briefcase, branch: MapPin, department: Network, pay: Banknote };

const lines = computed(() =>
  props.change.parts
    .filter((part): part is Exclude<ChangePart, "pay"> => part !== "pay")
    .map((part) => {
      const { was, now } = partSides(props.change, part);
      const none = part === "department" ? t("lifecycle.changes.noDepartment") : part === "position" ? t("lifecycle.changes.noPosition") : "—";
      return { part, was: was ?? none, now: now ?? none };
    }),
);
const pay = computed(() => (props.change.parts.includes("pay") ? { before: props.change.before.pay, after: props.change.after.pay } : null));
</script>

<template>
  <ul :class="['flex min-w-0 flex-col', dense ? 'gap-1' : 'gap-2']" data-change-lines>
    <li v-for="line in lines" :key="line.part" class="flex min-w-0 items-center gap-2" :data-part="line.part">
      <component :is="ICONS[line.part]" :size="dense ? 13 : 15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span v-if="!dense" class="w-24 shrink-0 text-sm text-muted">{{ t(`lifecycle.changePart.${line.part}`) }}</span>
      <span :class="['min-w-0 truncate text-muted', dense ? 'text-xs' : 'text-sm']" :title="line.was">{{ line.was }}</span>
      <ArrowRight :size="dense ? 12 : 14" class="shrink-0 text-subtle" aria-hidden="true" />
      <span :class="['min-w-0 truncate font-medium text-fg', dense ? 'text-sm' : 'text-sm']" :title="line.now">{{ line.now }}</span>
    </li>
    <li v-if="pay" class="flex min-w-0 items-center gap-2" data-part="pay">
      <component :is="ICONS.pay" :size="dense ? 13 : 15" class="shrink-0 text-subtle" aria-hidden="true" />
      <span v-if="!dense" class="w-24 shrink-0 text-sm text-muted">{{ t("lifecycle.changePart.pay") }}</span>
      <template v-if="pay.after">
        <span :class="['min-w-0 truncate tabular-nums text-muted', dense ? 'text-xs' : 'text-sm']">
          <MoneyText v-if="pay.before" :value="pay.before.amount" :currency="pay.before.currency" />
          <template v-else>—</template>
        </span>
        <ArrowRight :size="dense ? 12 : 14" class="shrink-0 text-subtle" aria-hidden="true" />
        <span class="min-w-0 truncate text-sm font-semibold tabular-nums text-fg">
          <MoneyText :value="pay.after.amount" :currency="pay.after.currency" />
          <span class="ml-1 text-xs font-normal text-muted">{{ t(`lifecycle.payType.${pay.after.pay_type}`) }}</span>
        </span>
      </template>
      <span v-else class="inline-flex min-w-0 items-center gap-1 truncate text-sm text-muted" :title="t('lifecycle.changes.payHidden')">
        <LockKeyhole :size="12" aria-hidden="true" />{{ t("lifecycle.changes.payChanges") }}
      </span>
    </li>
  </ul>
</template>
