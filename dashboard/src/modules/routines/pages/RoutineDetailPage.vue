<script setup lang="ts">
/**
 * One routine (plan §6.1 `routines/:id`): how it went over a range (on time, late, missed per day
 * and per person), who gets it on a day, its settings and its audited history.
 */
import { CalendarClock, Clock, ListChecks, Pause, Pencil, Play, Store, UsersRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AuditTrail from "@/components/AuditTrail.vue";
import BarChart from "@/components/BarChart.vue";
import ChartCard from "@/components/ChartCard.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import ErrorState from "@/components/ErrorState.vue";
import KpiCard from "@/components/KpiCard.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import PageHeader from "@/components/PageHeader.vue";
import PageSection from "@/components/PageSection.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import { useChartTheme } from "@/components/useChartTheme";
import { toast } from "@/components/useToast";
import { useBreakpoints } from "@/lib/useBreakpoints";
import { useFormat } from "@/lib/useFormat";
import { useRangeState } from "@/lib/useRangeState";

import { useCompliance, useRoutine, useSaveRoutine } from "../api";
import RoutineEditor from "../components/RoutineEditor.vue";
import RoutinePreview from "../components/RoutinePreview.vue";
import WeekdayDots from "../components/WeekdayDots.vue";

const { t } = useI18n();
const { isPhone } = useBreakpoints();
const chart = useChartTheme();
const fmt = useFormat();
const route = useRoute();
const router = useRouter();

const id = computed(() => Number(route.params.id) || null);
const routine = useRoutine(id);
const period = useRangeState({ preset: "last_30" });
const range = computed(() => ({ from: period.value.range.from, to: period.value.range.to }));
const compliance = useCompliance(id, range);
const save = useSaveRoutine();
const editorOpen = ref(false);

const data = computed(() => routine.data.value ?? null);
const totals = computed(() => compliance.data.value?.totals);
const kpis = computed(() => [
  { id: "made", label: t("routines.detail.made"), value: totals.value?.made ?? null },
  { id: "on_time", label: t("routines.detail.onTime"), value: totals.value?.on_time_percent ?? null, format: "percent" as const, spark: compliance.data.value?.series.map((d) => d.on_time_percent) ?? [] },
  { id: "late", label: t("routines.detail.late"), value: totals.value?.late ?? null },
  { id: "missed", label: t("routines.detail.missed"), value: totals.value?.missed ?? null },
]);

const series = computed(() => compliance.data.value?.series ?? []);
const chartSeries = computed(() => [
  { name: t("routines.detail.onTimeShort"), data: series.value.map((d) => d.on_time), color: chart.value.success, stack: "done" },
  { name: t("routines.detail.late"), data: series.value.map((d) => d.late), color: chart.value.warning, stack: "done" },
  { name: t("routines.detail.missed"), data: series.value.map((d) => d.missed), color: chart.value.danger, stack: "done" },
]);

async function setActive(active: boolean): Promise<void> {
  if (!data.value) return;
  try {
    await save.mutateAsync({ id: data.value.id, input: { is_active: active } });
    toast.success(active ? t("routines.toast.resumed") : t("routines.toast.paused"), { description: data.value.title });
  } catch {
    // shown by the HTTP layer
  }
}

const subtitle = computed(() => {
  const routineValue = data.value;
  if (!routineValue) return undefined;
  return [routineValue.due_time.slice(0, 5), routineValue.branch?.name].filter(Boolean).join(" · ");
});
const tone = (value: number | null) => (value === null ? "neutral" : value >= 90 ? "success" : value >= 70 ? "warning" : "danger");
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <div v-if="routine.isPending.value" class="flex flex-col gap-4"><SkeletonBlock width="30%" height="28px" /><SkeletonBlock height="120px" radius="12px" /></div>
    <ErrorState v-else-if="routine.isError.value" class="ui-card" :error="routine.error.value" :retry="() => routine.refetch()" />
    <template v-else-if="data">
      <PageHeader :title="data.title" :description="data.description || subtitle" :back="{ name: 'routines.list' }" :back-label="t('routines.title')">
        <template #actions>
          <UiButton :icon="data.is_active ? Pause : Play" :loading="save.isPending.value" @click="setActive(!data.is_active)">{{ data.is_active ? t("routines.pause") : t("routines.resume") }}</UiButton>
          <UiButton variant="primary" :icon="Pencil" @click="editorOpen = true">{{ t("common.edit") }}</UiButton>
        </template>
      </PageHeader>

      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
        <span v-if="!data.is_active" class="rounded-full bg-surface-2 px-2 py-px text-xs font-medium text-muted">{{ t("routines.paused") }}</span>
        <WeekdayDots :days="data.weekdays" />
        <span class="inline-flex items-center gap-1 tabular-nums"><Clock :size="14" />{{ data.due_time.slice(0, 5) }}</span>
        <span v-if="data.branch" class="inline-flex items-center gap-1"><Store :size="14" />{{ data.branch.name }}</span>
        <span class="inline-flex items-center gap-1"><UsersRound :size="14" />{{ [...data.positions.map((p) => p.name), ...data.assignees.map((p) => p.name)].join(", ") || t("routines.nobody") }}</span>
        <span v-if="data.checklist.length" class="inline-flex items-center gap-1"><ListChecks :size="14" />{{ t("routines.steps", { n: data.checklist.length }, data.checklist.length) }}</span>
        <span v-if="data.reminder_policy" class="inline-flex items-center gap-1"><CalendarClock :size="14" />{{ data.reminder_policy.name }}</span>
        <span class="flex-1" />
        <DateRangePicker v-model="period" align="end" />
      </div>

      <div v-if="isPhone" class="grid grid-cols-2 gap-2">
        <KpiCard v-for="(item, index) in kpis" :key="index" v-bind="{ ...item, spark: undefined, hint: undefined }" :loading="compliance.isPending.value" />
      </div>
      <KpiStrip v-else :items="kpis" :loading="compliance.isPending.value" :columns="4" />

      <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <ChartCard
          :title="t('routines.detail.chartTitle')"
          :subtitle="fmt.range(range)"
          :loading="compliance.isPending.value"
          :error="compliance.error.value"
          :retry="() => compliance.refetch()"
          :empty="!series.some((d) => d.made > 0)"
          :empty-text="t('routines.detail.chartEmpty')"
          height="260px"
        >
          <BarChart :categories="series.map((d) => d.date)" :series="chartSeries" stacked x-format="day" height="260px" />
        </ChartCard>
        <section class="ui-card flex flex-col gap-3 p-4">
          <h2 class="text-sm font-semibold text-fg">{{ t("routines.preview.title") }}</h2>
          <RoutinePreview :routine-id="data.id" />
        </section>
      </div>

      <PageSection :title="t('routines.detail.people')" variant="card" flush>
        <div v-if="compliance.isPending.value" class="flex flex-col gap-2 p-4"><SkeletonBlock v-for="n in 3" :key="n" height="28px" /></div>
        <p v-else-if="!compliance.data.value?.people.length" class="p-4 text-sm text-muted">{{ t("routines.detail.noPeople") }}</p>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[560px] text-sm">
            <thead class="bg-surface-2 text-left text-xs font-medium text-muted">
              <tr>
                <th class="px-4 py-2.5 font-medium">{{ t("routines.detail.person") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.detail.made") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.detail.onTimeShort") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.detail.late") }}</th>
                <th class="px-3 py-2.5 text-right font-medium">{{ t("routines.detail.missed") }}</th>
                <th class="w-[220px] px-4 py-2.5 font-medium">{{ t("routines.detail.onTime") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in compliance.data.value.people" :key="row.member.id" class="border-t border-line">
                <td class="px-4 py-2.5">
                  <span class="flex items-center gap-2"><UserAvatar :name="row.member.name" :src="row.member.photo_url" :size="24" /><span class="truncate font-medium text-fg">{{ row.member.name }}</span></span>
                </td>
                <td class="px-3 py-2.5 text-right tabular-nums">{{ row.made }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums text-success">{{ row.on_time }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums text-warning">{{ row.late }}</td>
                <td class="px-3 py-2.5 text-right tabular-nums text-danger">{{ row.missed }}</td>
                <td class="px-4 py-2.5">
                  <span class="flex items-center gap-2"><ProgressBar class="flex-1" :value="row.on_time_percent ?? 0" :tone="tone(row.on_time_percent)" /><span class="w-12 text-right tabular-nums text-muted">{{ fmt.percent(row.on_time_percent, 0) }}</span></span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </PageSection>

      <PageSection :title="t('routines.detail.history')" variant="card">
        <AuditTrail target-type="tasktemplate" :target-id="data.id" />
      </PageSection>

      <RoutineEditor v-model:open="editorOpen" :routine="data" @deleted="router.push({ name: 'routines.list' })" />
    </template>
  </div>
</template>
