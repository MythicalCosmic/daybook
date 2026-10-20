<script setup lang="ts">
/**
 * Package F's own map (plan §6.3: "F builds its own map; the lead merges them at integration"):
 * branch geofences as circles and check-in points as dots, coloured by trust (inside, imprecise,
 * outside). Leaflet with OpenStreetMap tiles (allowed by the dashboard CSP); loaded only on pages
 * that show it. Points are where people tapped "check in"; nothing here tracks anyone.
 */
import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";

export interface MapBranch {
  id: number;
  name: string;
  latitude: string | null;
  longitude: string | null;
  geofence_m: number;
}

export interface MapPoint {
  id: number | string;
  lat: string | number;
  lng: string | number;
  tone: "ok" | "warn" | "bad";
  label: string;
}

const props = withDefaults(defineProps<{ branches: MapBranch[]; points?: MapPoint[]; height?: string; interactive?: boolean }>(), {
  points: () => [],
  height: "280px",
  interactive: true,
});
const emit = defineEmits<{ select: [id: number | string] }>();

const el = ref<HTMLElement | null>(null);
const map = shallowRef<L.Map | null>(null);
let layer: L.LayerGroup | null = null;

function draw(): void {
  const current = map.value;
  if (!current) return;
  layer?.remove();
  layer = L.layerGroup().addTo(current);
  const bounds: L.LatLngExpression[] = [];
  for (const branch of props.branches) {
    if (branch.latitude === null || branch.longitude === null) continue;
    const center: L.LatLngExpression = [Number(branch.latitude), Number(branch.longitude)];
    bounds.push(center);
    L.circle(center, { radius: branch.geofence_m, className: "att-geo-fence", weight: 1.5 })
      .bindTooltip(branch.name, { permanent: true, direction: "top", className: "att-geo-label", offset: [0, -6] })
      .addTo(layer);
    L.circleMarker(center, { radius: 4, className: "att-geo-center", weight: 2 }).addTo(layer);
  }
  for (const point of props.points) {
    const at: L.LatLngExpression = [Number(point.lat), Number(point.lng)];
    bounds.push(at);
    L.circleMarker(at, { radius: 6, className: `att-geo-point att-geo-${point.tone}`, weight: 2 })
      .bindTooltip(point.label, { direction: "top", offset: [0, -4] })
      .on("click", () => emit("select", point.id))
      .addTo(layer);
  }
  if (bounds.length === 1) current.setView(bounds[0]!, 16);
  else if (bounds.length > 1) current.fitBounds(L.latLngBounds(bounds), { padding: [36, 36], maxZoom: 16 });
}

onMounted(() => {
  if (!el.value) return;
  map.value = L.map(el.value, {
    zoomControl: props.interactive,
    attributionControl: true,
    scrollWheelZoom: false,
    dragging: props.interactive,
    doubleClickZoom: props.interactive,
  }).setView([41.3, 69.25], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
  }).addTo(map.value);
  draw();
});

watch(() => [props.branches, props.points], draw, { deep: true });

onBeforeUnmount(() => {
  map.value?.remove();
  map.value = null;
});
</script>

<template>
  <div ref="el" class="att-geo-map relative z-0 w-full overflow-hidden rounded-[10px] border border-line bg-surface-2" :style="{ height }" />
</template>

<style>
.att-geo-map .leaflet-container {
  font-family: var(--font-sans);
  background: var(--c-surface-2);
}
[data-theme="dark"] .att-geo-map .leaflet-tile-pane {
  filter: invert(1) hue-rotate(180deg) brightness(0.92) contrast(0.88) saturate(0.6);
}
.att-geo-map .att-geo-fence {
  stroke: var(--c-primary);
  fill: var(--c-primary);
  fill-opacity: 0.1;
}
.att-geo-map .att-geo-center {
  stroke: var(--c-primary);
  fill: var(--c-surface);
  fill-opacity: 1;
}
.att-geo-map .att-geo-point {
  stroke: var(--c-surface);
  fill-opacity: 0.95;
}
.att-geo-map .att-geo-ok {
  fill: var(--c-success);
}
.att-geo-map .att-geo-warn {
  fill: var(--c-warning);
}
.att-geo-map .att-geo-bad {
  fill: var(--c-danger);
}
.att-geo-map .att-geo-label {
  background: var(--c-surface);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: 6px;
  box-shadow: var(--sh-xs);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
}
.att-geo-map .att-geo-label::before {
  display: none;
}
.att-geo-map .leaflet-control-attribution {
  font-size: 9px;
  background: color-mix(in srgb, var(--c-surface) 80%, transparent);
  color: var(--c-muted);
}
.att-geo-map .leaflet-control-attribution a {
  color: var(--c-muted);
}
.att-geo-map .leaflet-bar a {
  background: var(--c-surface);
  color: var(--c-text);
  border-color: var(--c-border);
}
</style>
