<script setup lang="ts">
/**
 * Person 360 › Record (registered by this module): their warnings and reprimands, newest first,
 * with what still counts from the last six months and the suggested next step (plan §13.4), and
 * whether they are suspended now (until when and why). A record opens in its drawer here
 * (`?record=`); hr.discipline issues a new one from here.
 */
import { Banknote, CircleCheck, Gavel, Lightbulb, MessageSquareQuote, Pause, Play, Plus } from "@lucide/vue";
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
import { KIND_TONES, lifecycleAccess, nextStep, recordState, STATE_TONES } from "../lib";
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

const records = useRecords(() => ({ member: props.memberId, page_size: 100 }));
const suspensions = useSuspensions(computed(() => access.value.suspend || company.can("hr.view")));
const skeleton = useDelayedPending(computed(() => records.isPending.value));
const rows = computed(() => records.data.value?.results ?? []);
const suggestion = computed(() => nextStep(rows.value, today.value));
const suspension = computed(() => suspensions.data.value?.find((row) => row.member.id === props.memberId) ?? null);
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
            <button type="button" :class="['flex min-h-14 w-full items-start gap-3 px-5 py-3 text-left transition-colors hover:bg-highlight', !row.active && 'opacity-60']" @click="open(row.id)">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-1.5">
                  <StatusPill :tone="KIND_TONES[row.kind]" size="sm" :label="t(`lifecycle.kind.${row.kind}`)" />
                  <span class="text-sm font-medium text-fg">{{ category(row.category) }}</span>
                </div>
                <p class="mt-1 line-clamp-2 text-sm text-muted">{{ row.description }}</p>
                <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  <span class="tabular-nums">{{ fmt.day(row.incident_on, "medium") }}</span>
                  <span v-if="row.fine" class="inline-flex items-center gap-1 font-semibold text-warning"><Banknote :size="12" aria-hidden="true" /><MoneyText :value="row.fine.amount" :currency="row.fine.currency" /></span>
                  <span v-else-if="row.fine_id" class="inline-flex items-center gap-1 text-warning"><Banknote :size="12" aria-hidden="true" />{{ t("lifecycle.record.fine") }}</span>
                  <span v-if="row.employee_response" class="inline-flex items-center gap-1 text-info"><MessageSquareQuote :size="12" aria-hidden="true" />{{ t("lifecycle.record.explained") }}</span>
                  <span v-else-if="row.acknowledged_at" class="inline-flex items-center gap-1 text-success"><CircleCheck :size="12" aria-hidden="true" />{{ t("lifecycle.record.read") }}</span>
                </div>
              </div>
              <StatusPill :tone="STATE_TONES[recordState(row)]" size="sm" variant="outline" :label="t(`lifecycle.status.${recordState(row)}`)" />
            </button>
          </li>
        </ul>
      </template>
    </section>

    <section class="ui-card overflow-hidden" data-record-suspension>
      <header class="flex items-center gap-2 border-b border-line px-5 py-3">
        <Pause :size="16" class="text-subtle" aria-hidden="true" />
        <h2 class="flex-1 text-md font-semibold text-fg">{{ t("lifecycle.person.suspension") }}</h2>
      </header>
      <div v-if="suspensions.isPending.value" class="p-4"><SkeletonBlock height="44px" /></div>
      <ErrorState v-else-if="suspensions.isError.value" compact class="m-4" :error="suspensions.error.value" :retry="() => suspensions.refetch()" />
      <div v-else-if="suspension" class="flex flex-col gap-2 p-5">
        <StatusPill tone="warning" class="w-fit" :label="suspension.until ? t('lifecycle.suspensions.until', { date: fmt.day(suspension.until, 'long') }) : t('lifecycle.suspensions.untilReinstated')" />
        <p class="whitespace-pre-line text-sm text-fg">{{ suspension.reason }}</p>
        <p class="text-xs text-muted">
          <template v-if="suspension.since">{{ t("lifecycle.suspensions.since", { date: fmt.day(suspension.since.slice(0, 10), "medium") }) }}</template>
          <template v-if="suspension.by"> · {{ suspension.by }}</template>
        </p>
      </div>
      <div v-else class="flex items-center gap-3 p-5">
        <span class="grid size-9 shrink-0 place-items-center rounded-full bg-success-soft text-success" aria-hidden="true"><Play :size="16" /></span>
        <p class="text-sm text-muted">{{ t("lifecycle.person.notSuspended") }}</p>
      </div>
    </section>

    <RecordDrawer />
    <RecordFormDrawer v-if="access.discipline" v-model:open="creating" :member="{ id: memberId, name: rows[0]?.member.name ?? '' }" />
  </div>
</template>
