<script setup lang="ts">
/**
 * Person 360 › Record (registered by this module): their warnings and reprimands, newest first,
 * with what still counts from the last six months and the suggested next step (plan §13.4), and
 * their suspensions. A record opens in its drawer here (`?record=`).
 */
import { Banknote, CircleCheck, Gavel, Lightbulb, MessageSquareQuote, Pause, Plus } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import InlineAlert from "@/components/InlineAlert.vue";
import MoneyText from "@/components/MoneyText.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import StatusPill from "@/components/StatusPill.vue";
import UiButton from "@/components/UiButton.vue";
import { useDelayedPending } from "@/lib/useDelayedPending";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore, useCompanyToday } from "@/stores/company";

import { useRecords, useSuspensions } from "../api";
import { isActiveRecord, KIND_TONES, lifecycleAccess, nextStep, STATUS_TONES, SUSPENSION_TONES } from "../lib";
import RecordDrawer from "./RecordDrawer.vue";
import RecordFormDrawer from "./RecordFormDrawer.vue";

const props = defineProps<{ memberId: number }>();

const { t, te } = useI18n();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();
const company = useCompanyStore();
const today = useCompanyToday();
const access = computed(() => lifecycleAccess((perm) => company.can(perm)));

const records = useRecords(() => ({ member: props.memberId, page_size: 100, ordering: "-incident_on" }));
const suspensions = useSuspensions(() => ({ member: props.memberId, page_size: 50 }), computed(() => access.value.suspend || company.can("hr.view")));
const skeleton = useDelayedPending(computed(() => records.isPending.value));
const rows = computed(() => records.data.value?.results ?? []);
const suggestion = computed(() => nextStep(rows.value, today.value));
const category = (value: string) => (te(`lifecycle.category.${value}`) ? t(`lifecycle.category.${value}`) : value);

const creating = ref(false);
function open(id: number): void {
  void router.push({ query: { ...route.query, record: String(id) } });
}
</script>

<template>
  <div class="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
    <section class="ui-card overflow-hidden" data-record-list>
      <header class="flex items-center gap-2 border-b border-line px-5 py-3">
        <Gavel :size="16" class="text-subtle" aria-hidden="true" />
        <h2 class="flex-1 text-md font-semibold text-fg">{{ t("lifecycle.person.records") }}</h2>
        <UiButton v-if="access.discipline" size="sm" :icon="Plus" @click="creating = true">{{ t("lifecycle.person.warn") }}</UiButton>
      </header>
      <div v-if="skeleton" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 3" :key="n" height="52px" /></div>
      <ErrorState v-else-if="records.isError.value" compact class="m-4" :error="records.error.value" :retry="() => records.refetch()" />
      <EmptyState v-else-if="records.data.value && !rows.length" size="sm" tone="success" :icon="CircleCheck" :title="t('lifecycle.person.clean')" :description="t('lifecycle.person.cleanBody')" />
      <template v-else>
        <div v-if="suggestion" class="border-b border-line p-4">
          <InlineAlert
            :tone="suggestion.step === 'consider_termination' ? 'danger' : 'warning'"
            size="sm"
            :icon="Lightbulb"
            :title="t('lifecycle.person.counting', { n: suggestion.count }, suggestion.count)"
            :description="t(`lifecycle.nextStep.${suggestion.step}`)"
          />
        </div>
        <ul class="divide-y divide-[var(--c-border)]">
          <li v-for="row in rows" :key="row.id">
            <button type="button" :class="['flex min-h-14 w-full items-start gap-3 px-5 py-3 text-left transition-colors hover:bg-highlight', !isActiveRecord(row, today) && 'opacity-60']" @click="open(row.id)">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-1.5">
                  <StatusPill :tone="KIND_TONES[row.kind]" size="sm" :label="t(`lifecycle.kind.${row.kind}`)" />
                  <span class="text-sm font-medium text-fg">{{ category(row.category) }}</span>
                </div>
                <p class="mt-1 line-clamp-2 text-sm text-muted">{{ row.description }}</p>
                <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <span class="tabular-nums">{{ fmt.day(row.incident_on, "medium") }}</span>
                  <span v-if="row.fine" class="inline-flex items-center gap-1 font-semibold text-warning"><Banknote :size="12" aria-hidden="true" /><MoneyText :value="row.fine.amount" :currency="row.fine.currency" /></span>
                  <span v-if="row.employee_response" class="inline-flex items-center gap-1 text-info"><MessageSquareQuote :size="12" aria-hidden="true" />{{ t("lifecycle.record.explained") }}</span>
                  <span v-else-if="row.acknowledged_at" class="inline-flex items-center gap-1 text-success"><CircleCheck :size="12" aria-hidden="true" />{{ t("lifecycle.record.read") }}</span>
                </div>
              </div>
              <StatusPill :tone="STATUS_TONES[row.status]" size="sm" variant="outline" :label="t(`lifecycle.status.${row.status}`)" />
            </button>
          </li>
        </ul>
      </template>
    </section>

    <section class="ui-card overflow-hidden" data-record-suspensions>
      <header class="flex items-center gap-2 border-b border-line px-5 py-3">
        <Pause :size="16" class="text-subtle" aria-hidden="true" />
        <h2 class="flex-1 text-md font-semibold text-fg">{{ t("lifecycle.nav.suspensions") }}</h2>
      </header>
      <div v-if="suspensions.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 2" :key="n" height="40px" /></div>
      <ErrorState v-else-if="suspensions.isError.value" compact class="m-4" :error="suspensions.error.value" :retry="() => suspensions.refetch()" />
      <EmptyState v-else-if="!suspensions.data.value?.results.length" size="sm" tone="neutral" :icon="Pause" :title="t('lifecycle.person.noSuspensions')" :description="t('lifecycle.person.noSuspensionsBody')" />
      <ul v-else class="divide-y divide-[var(--c-border)]">
        <li v-for="row in suspensions.data.value!.results" :key="row.id" class="flex flex-col gap-1 px-5 py-3">
          <div class="flex items-center gap-2">
            <p class="min-w-0 flex-1 truncate text-sm font-medium tabular-nums text-fg">
              {{ row.ends_on ? fmt.range({ from: row.starts_on, to: row.ends_on }) : t("lifecycle.suspensions.since", { date: fmt.day(row.starts_on, "medium") }) }}
            </p>
            <StatusPill :tone="SUSPENSION_TONES[row.status]" size="sm" :label="t(`lifecycle.suspensionStatus.${row.status}`)" />
          </div>
          <p class="line-clamp-2 text-xs text-muted">{{ row.reason }}</p>
        </li>
      </ul>
    </section>

    <RecordDrawer />
    <RecordFormDrawer v-if="access.discipline" v-model:open="creating" :member="{ id: memberId, name: rows[0]?.member.name ?? '' }" />
  </div>
</template>
