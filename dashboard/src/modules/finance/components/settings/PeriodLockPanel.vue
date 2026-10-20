<script setup lang="ts">
/**
 * The period lock (plan §1.6: "edited history destroys trust"): nothing dated on or before the
 * locked day can be added, changed or voided. Closing moves forward freely ("close last month" in
 * one tap); reopening moves the date back and only an owner may do it.
 */
import { Lock, LockOpen, ShieldCheck } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import DatePicker from "@/components/DatePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import FormField from "@/components/FormField.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { useConfirm } from "@/components/useConfirm";
import { toast } from "@/components/useToast";
import { addDays, startOfMonth, todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import { financeApi, useRefresh, useSettings } from "../../api";

const { t } = useI18n();
const fmt = useFormat();
const company = useCompanyStore();
const confirm = useConfirm();
const refresh = useRefresh();
const settings = useSettings();
const data = computed(() => settings.data.value);
const today = computed(() => todayIn(company.timezone));
const endOfLastMonth = computed(() => addDays(startOfMonth(today.value), -1));
const until = ref<string | null>(null);
watch(
  () => data.value?.locked_until,
  (value) => (until.value = value ?? endOfLastMonth.value),
  { immediate: true },
);

const backwards = computed(() => !!data.value?.locked_until && (!until.value || until.value < data.value.locked_until));

async function apply(target: string | null): Promise<void> {
  const reopening = !!data.value?.locked_until && (!target || target < data.value.locked_until);
  const answer = await confirm({
    title: reopening ? t("finance.lock.reopenTitle") : t("finance.lock.closeTitle", { date: target ? fmt.day(target, "long") : "" }),
    message: reopening ? t("finance.lock.reopenBody") : t("finance.lock.closeBody"),
    tone: reopening ? "danger" : "primary",
    confirmLabel: reopening ? t("finance.lock.reopen") : t("finance.lock.close"),
    onConfirm: () => financeApi.lock(company.currentId ?? 0, target),
  });
  if (answer) {
    toast.success(reopening ? t("finance.lock.reopened") : t("finance.lock.closed"));
    refresh();
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <ErrorState v-if="settings.isError.value" :error="settings.error.value" :retry="() => settings.refetch()" />
    <template v-else>
      <section class="ui-card flex flex-wrap items-center gap-5 p-5">
        <span :class="['grid size-12 place-items-center rounded-[14px]', data?.locked_until ? 'bg-success-soft text-success' : 'bg-surface-2 text-muted']" aria-hidden="true">
          <component :is="data?.locked_until ? Lock : LockOpen" :size="22" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-muted">{{ t("finance.lock.current") }}</p>
          <SkeletonBlock v-if="settings.isPending.value" width="240px" height="28px" />
          <p v-else-if="data?.locked_until" class="text-xl font-semibold text-fg">{{ t("finance.lock.closedUntil", { date: fmt.day(data.locked_until, "long") }) }}</p>
          <p v-else class="text-xl font-semibold text-fg">{{ t("finance.lock.open") }}</p>
          <p class="mt-1 max-w-[560px] text-sm text-muted">{{ t("finance.lock.explain") }}</p>
        </div>
      </section>

      <section class="ui-card flex flex-col gap-4 p-5">
        <div class="flex items-start gap-3">
          <ShieldCheck :size="18" class="mt-0.5 shrink-0 text-subtle" />
          <div>
            <h3 class="text-sm font-semibold text-fg">{{ t("finance.lock.chooseTitle") }}</h3>
            <p class="text-sm text-muted">{{ t("finance.lock.chooseHint") }}</p>
          </div>
        </div>
        <div class="flex flex-wrap items-end gap-3">
          <FormField :label="t('finance.lock.until')" class="w-64">
            <DatePicker v-model="until" :max="today" clearable />
          </FormField>
          <UiButton variant="primary" :icon="backwards ? LockOpen : Lock" :disabled="until === (data?.locked_until ?? null) || (backwards && !data?.can_reopen)" @click="apply(until)">
            {{ backwards ? t("finance.lock.reopen") : t("finance.lock.close") }}
          </UiButton>
          <UiButton v-if="data?.locked_until !== endOfLastMonth && (!data?.locked_until || data.locked_until < endOfLastMonth)" variant="secondary" @click="apply(endOfLastMonth)">
            {{ t("finance.lock.closeLastMonth", { month: fmt.day(endOfLastMonth, "monthYear") }) }}
          </UiButton>
        </div>
        <p v-if="backwards && !data?.can_reopen" class="text-sm text-warning">{{ t("finance.lock.ownerOnly") }}</p>
      </section>
    </template>
  </div>
</template>
