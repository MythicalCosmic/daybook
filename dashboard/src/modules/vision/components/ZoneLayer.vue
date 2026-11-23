<script setup lang="ts">
/** A camera's zones drawn over its picture, still (a camera card's snapshot). */
import { computed, useId } from "vue";

import { insideArrow } from "../lib/geometry";
import { ZONE_COLOR } from "../lib/look";
import type { Zone } from "../types";

const props = withDefaults(defineProps<{ zones: Zone[]; aspect?: number }>(), { aspect: 16 / 9 });

const uid = useId();
const VW = 1000;
const VH = computed(() => VW / props.aspect);
const shapes = computed(() =>
  props.zones.map((zone) => {
    const points = zone.points.map(([x, y]) => `${x * VW},${y * VH.value}`).join(" ");
    let arrow: { x1: number; y1: number; x2: number; y2: number } | null = null;
    if (zone.kind === "line" && zone.points.length === 2) {
      const { from, to } = insideArrow(zone.points[0]!, zone.points[1]!, zone.in ?? "left", { w: VW, h: VH.value }, 60);
      arrow = { x1: from[0] * VW, y1: from[1] * VH.value, x2: to[0] * VW, y2: to[1] * VH.value };
    }
    return { zone, points, color: ZONE_COLOR[zone.kind], arrow };
  }),
);
</script>

<template>
  <svg class="pointer-events-none absolute inset-0 size-full" :viewBox="`0 0 ${VW} ${VH}`" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <pattern :id="`zl-hatch-${uid}`" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="12" height="12" fill="#090909" />
        <line x1="0" y1="0" x2="0" y2="12" stroke="rgba(255,255,255,0.14)" stroke-width="4" />
      </pattern>
      <marker :id="`zl-arrow-${uid}`" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#ffffff" />
      </marker>
    </defs>
    <template v-for="shape in shapes" :key="shape.zone.id">
      <polygon v-if="shape.zone.kind === 'mask'" :points="shape.points" :fill="`url(#zl-hatch-${uid})`" stroke="rgba(255,255,255,0.4)" stroke-dasharray="5 4" vector-effect="non-scaling-stroke" />
      <template v-else-if="shape.zone.kind === 'line'">
        <polyline :points="shape.points" fill="none" stroke="#ffffff" stroke-width="2" stroke-dasharray="8 6" vector-effect="non-scaling-stroke" />
        <line v-if="shape.arrow" :x1="shape.arrow.x1" :y1="shape.arrow.y1" :x2="shape.arrow.x2" :y2="shape.arrow.y2" stroke="#ffffff" stroke-width="2" vector-effect="non-scaling-stroke" :marker-end="`url(#zl-arrow-${uid})`" />
      </template>
      <polygon v-else :points="shape.points" :fill="shape.color" fill-opacity="0.14" :stroke="shape.color" stroke-dasharray="6 5" stroke-width="1.5" vector-effect="non-scaling-stroke" />
    </template>
  </svg>
</template>
