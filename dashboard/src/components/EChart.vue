<script setup lang="ts">
/**
 * The one place ECharts is loaded (plan §6.5: vue-echarts over a tree-shaken `echarts/core`, only
 * on pages with charts). Chart components import this file lazily, so the ECharts chunk downloads
 * the first time a chart renders. Registers its PNG export with the surrounding ChartCard.
 */
import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { use, type ComposeOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import VChart from "vue-echarts";
import { inject, onBeforeUnmount, onMounted, ref } from "vue";

import { CHART_CARD_KEY } from "./chartCard";

use([LineChart, BarChart, PieChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, MarkLineComponent, CanvasRenderer]);

type Option = ComposeOption<never>;

defineProps<{ option: Record<string, unknown>; height: string; label?: string }>();

const chart = ref<InstanceType<typeof VChart> | null>(null);
const card = inject(CHART_CARD_KEY, null);

function toPng(background: string): string | null {
  return chart.value?.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: background }) ?? null;
}

onMounted(() => card?.register(toPng));
onBeforeUnmount(() => card?.register(null));
</script>

<template>
  <div role="img" :aria-label="label" :style="{ height }">
    <VChart ref="chart" :option="(option as Option)" autoresize :update-options="{ notMerge: true }" class="size-full" />
  </div>
</template>
