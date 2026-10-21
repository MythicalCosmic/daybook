<script lang="ts">
/**
 * Whether this page can draw on a canvas at all, asked once. Without one (jsdom in the tests, a
 * browser with canvas blocked) a chart keeps its box and label and draws nothing, rather than
 * ECharts failing a tick later ("clearRect" of null) and taking whatever renders next down with it.
 */
let canvas: boolean | undefined;
function canDraw(): boolean {
  if (canvas === undefined) {
    try {
      canvas = typeof document !== "undefined" && !!document.createElement("canvas").getContext("2d");
    } catch {
      canvas = false;
    }
  }
  return canvas;
}
</script>

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

const drawable = canDraw();

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
    <VChart v-if="drawable" ref="chart" :option="(option as Option)" autoresize :update-options="{ notMerge: true }" class="size-full" />
  </div>
</template>
