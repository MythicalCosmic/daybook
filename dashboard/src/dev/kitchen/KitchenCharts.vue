<script setup lang="ts">
/** Kitchen: KPI cards and strip, every chart in its ChartCard, sparklines and bullet bars. */
import { Banknote, Receipt, ShoppingBag, Users } from "@lucide/vue";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import AreaChart from "@/components/AreaChart.vue";
import BarChart from "@/components/BarChart.vue";
import BulletBar from "@/components/BulletBar.vue";
import ChartCard from "@/components/ChartCard.vue";
import DonutChart from "@/components/DonutChart.vue";
import HeatmapChart from "@/components/HeatmapChart.vue";
import KpiCard from "@/components/KpiCard.vue";
import KpiStrip from "@/components/KpiStrip.vue";
import LineChart from "@/components/LineChart.vue";
import SparkLine from "@/components/SparkLine.vue";
import UiButton from "@/components/UiButton.vue";
import DateRangePicker from "@/components/DateRangePicker.vue";
import { rangeValue } from "@/lib/dateRange";
import { todayIn } from "@/lib/dates";
import { useFormat } from "@/lib/useFormat";
import { useCompanyStore } from "@/stores/company";

import KitchenSection from "./KitchenSection.vue";
import KitchenSpecimen from "./KitchenSpecimen.vue";
import { dailySeries, seeded } from "./kitchenData";

const { t } = useI18n();
const k = (key: string, params?: Record<string, unknown>) => t(`dev.kitchen.${key}`, params ?? {});
const fmt = useFormat();
const company = useCompanyStore();
const today = todayIn(company.timezone);

const net = dailySeries(today, 30, 4_800_000, 2_400_000, 11);
const previous = dailySeries(today, 30, 4_300_000, 2_200_000, 12);
const cash = dailySeries(today, 30, 86_000_000, 9_000_000, 13);
const card = dailySeries(today, 30, 2_100_000, 900_000, 14);
const period = ref(rangeValue("last_30", company.timezone, "prev"));

// KPIs that change on demand, to show the tween.
const bump = ref(0);
const kpi = computed(() => {
  const random = seeded(100 + bump.value);
  return {
    net: `${Math.round((44_000_000 + random() * 9_000_000) / 1000) * 1000}.00`,
    receipts: Math.round(1180 + random() * 240),
    avg: `${Math.round(36_000 + random() * 6000)}.00`,
    onTime: Math.round((88 + random() * 10) * 10) / 10,
  };
});

const branches = ["Chilonzor", "Yunusobod", "Sergeli", "Mirobod"];
const csv = computed(() => ({
  filename: "net-by-day",
  columns: [
    { key: "day", label: k("date") },
    { key: "net", label: k("md.net") },
    { key: "previous", label: t("common.chart.compare") },
  ],
  rows: net.days.map((day, i) => ({ day, net: net.values[i], previous: previous.values[i] })) as never[],
}));

const heat = (() => {
  const random = seeded(21);
  const out: Array<[number, number, number]> = [];
  for (let d = 0; d < 7; d++)
    for (let h = 0; h < 14; h++) {
      const peak = Math.exp(-((h - 9) ** 2) / 8) + Math.exp(-((h - 3) ** 2) / 6) * 0.6;
      out.push([h, d, Math.round((peak * (d >= 5 ? 1.4 : 1) * 1_400_000 + random() * 300_000) / 1000) * 1000]);
    }
  return out;
})();
const hours = Array.from({ length: 14 }, (_, i) => `${String(i + 8).padStart(2, "0")}`);
const weekdays = computed(() => Array.from({ length: 7 }, (_, i) => t(`common.weekday.short.${i}`)));
</script>

<template>
  <KitchenSection id="kpi" :title="k('section.kpi')" :description="k('section.kpiHint')">
    <KitchenSpecimen name="KpiStrip.vue" wide flush>
      <div class="flex flex-col gap-3 p-4">
        <div class="flex items-center gap-2">
          <UiButton size="sm" variant="secondary" @click="bump++">{{ k("shuffle") }}</UiButton>
          <span class="text-xs text-muted">{{ k("shuffleHint") }}</span>
        </div>
        <KpiStrip
          :items="[
            { label: k('kpi.net'), value: kpi.net, previous: '41200000.00', format: 'money', compact: true, spark: net.values, deltaLabel: k('vsLastMonth'), icon: Banknote, to: '/dev/login' },
            { label: k('kpi.receipts'), value: kpi.receipts, previous: 1204, spark: card.values, sparkColor: 'var(--c-chart-3)', icon: Receipt },
            { label: k('kpi.avg'), value: kpi.avg, previous: '39800.00', format: 'money', icon: ShoppingBag, sparkColor: 'var(--c-chart-4)', spark: previous.values },
            { label: k('kpi.onTime'), value: kpi.onTime, previous: 93.4, format: 'percent', points: true, icon: Users, hint: k('kpi.onTimeHint') },
          ]"
        />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="KpiCard.vue">
      <div class="grid gap-3 sm:grid-cols-2">
        <KpiCard :label="k('kpi.expenses')" value="18450000.00" previous="16200000.00" format="money" compact inverse :delta-label="k('vsLastMonth')" />
        <KpiCard :label="k('kpi.cash')" :value="cash.values.at(-1)" format="money" compact :spark="cash.values" spark-color="var(--c-chart-3)" :hint="fmt.approx('6780', 'USD')" />
        <KpiCard :label="k('kpi.late')" :value="3" :previous="5" inverse :delta-label="k('vsYesterday')" />
        <KpiCard :label="k('kpi.loading')" :value="null" loading />
      </div>
    </KitchenSpecimen>
    <KitchenSpecimen name="BulletBar.vue · SparkLine.vue">
      <div class="flex flex-col gap-4">
        <BulletBar :label="k('target.sales')" value="48120000" target="60000000" :expected="0.65" value-format="compact" />
        <BulletBar :label="k('target.budget')" value="9800000" target="9000000" :expected="0.65" inverse value-format="compact" />
        <BulletBar :label="k('target.project')" value="21500000" target="40000000" :expected="0.4" inverse value-format="compact" size="sm" />
        <div class="flex items-center gap-6 pt-1">
          <SparkLine :data="net.values" />
          <SparkLine :data="cash.values" color="var(--c-chart-3)" :area="false" />
          <SparkLine :data="[3, 5, 4, null, 6, 8, 7]" color="var(--c-chart-6)" :width="80" />
        </div>
      </div>
    </KitchenSpecimen>
  </KitchenSection>

  <KitchenSection id="charts" :title="k('section.charts')" :description="k('section.chartsHint')">
    <ChartCard :title="k('chart.net')" :value="fmt.money('148200000', undefined, { compact: true })" :subtitle="k('chart.netSub')" :csv="csv" class="@5xl:col-span-2">
      <template #actions><DateRangePicker v-model="period" size="sm" variant="ghost" align="end" /></template>
      <LineChart
        :categories="net.days"
        :series="[{ name: k('md.net'), data: net.values }]"
        :compare="{ name: t('common.chart.compare'), data: previous.values }"
        :target="{ value: 5000000, label: t('common.chart.target') }"
        value-format="money"
        x-format="day"
        height="260px"
      />
    </ChartCard>
    <ChartCard :title="k('chart.cashFlow')" :subtitle="k('chart.cashFlowSub')">
      <AreaChart
        :categories="net.days"
        :series="[
          { name: k('income'), data: net.values },
          { name: k('expenses'), data: previous.values.map((v) => String(Math.round(Number(v) * 0.6))) },
        ]"
        value-format="money"
        x-format="day"
        stacked
      />
    </ChartCard>
    <ChartCard :title="k('chart.branches')" :subtitle="k('chart.branchesSub')">
      <BarChart
        :categories="branches"
        :series="[
          { name: k('chart.thisMonth'), data: ['61400000', '22800000', '48800000', '15100000'] },
          { name: k('chart.lastMonth'), data: ['58200000', '27300000', '44100000', '12900000'] },
        ]"
        value-format="money"
      />
    </ChartCard>
    <ChartCard :title="k('chart.mix')" :subtitle="k('chart.mixSub')">
      <BarChart
        :categories="branches"
        :series="[
          { name: k('chart.cash'), data: [62, 48, 70, 35] },
          { name: k('chart.card'), data: [31, 44, 25, 51] },
          { name: k('chart.transfer'), data: [7, 8, 5, 14] },
        ]"
        horizontal
        normalize
        height="200px"
      />
    </ChartCard>
    <ChartCard :title="k('chart.expenses')" :subtitle="k('chart.expensesSub')">
      <DonutChart
        :slices="[
          { name: 'Rent', value: '12000000' },
          { name: 'Salaries', value: '61200000' },
          { name: 'Supplies', value: '4800000' },
          { name: 'Utilities', value: '3100000' },
          { name: 'Delivery', value: '2200000' },
          { name: 'Marketing', value: '1900000' },
          { name: 'Repairs', value: '700000' },
        ]"
        value-format="money"
        :center-label="k('total')"
      />
    </ChartCard>
    <ChartCard :title="k('chart.hours')" :subtitle="k('chart.hoursSub')">
      <HeatmapChart :x="hours" :y="weekdays" :values="heat" value-format="money" :label="k('md.net')" height="240px" />
    </ChartCard>
    <ChartCard :title="k('chart.loading')" loading />
    <ChartCard :title="k('chart.emptyTitle')" empty />
    <ChartCard :title="k('chart.errorTitle')" :error="new Error('boom')" :retry="() => undefined" />
  </KitchenSection>
</template>
