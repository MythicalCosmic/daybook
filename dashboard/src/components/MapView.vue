<script setup lang="ts">
/**
 * A map of places (plan §6.3): branch check-in circles with their names on the edge, and dots for
 * check-in points coloured by trust (`tone`); clicking a dot emits `select`. With `picker` it
 * chooses one place instead: click the map or drag the pin (`pick` emits decimal strings), the
 * circle shows `radius`, and "My location" asks the browser.
 *
 *   <MapView :branches="fences" :points="checkIns" height="300px" @select="openRecord" />
 *   <MapView picker :latitude="lat" :longitude="lng" :radius="150" @pick="(at) => …" />
 *
 * Leaflet (and its CSS) loads on mount in its own chunk, so importing this component costs little;
 * tiles come from OpenStreetMap (allowed by the dashboard's CSP). Names go in as text, never HTML.
 */
import { Crosshair, LocateFixed } from "@lucide/vue";
import type * as Leaflet from "leaflet";
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "./SkeletonBlock.vue";
import UiButton from "./UiButton.vue";
import { toast } from "./useToast";

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

const props = withDefaults(
  defineProps<{
    branches?: MapBranch[];
    points?: MapPoint[];
    /** CSS height ("300px") or pixels. */
    height?: string | number;
    /** Pan and zoom (off for a small map in a drawer). */
    interactive?: boolean;
    /** Accessible name of the map. */
    label?: string;
    /** Picker mode: one place, chosen by clicking the map or dragging the pin. */
    picker?: boolean;
    latitude?: string | null;
    longitude?: string | null;
    /** Picker: the check-in circle's radius in metres. */
    radius?: number;
    /** Picker: false shows the place without letting anyone move it. */
    editable?: boolean;
    /** Picker: the hint while no place is chosen. */
    placeHint?: string;
  }>(),
  {
    branches: () => [],
    points: () => [],
    height: "280px",
    interactive: true,
    label: undefined,
    picker: false,
    latitude: null,
    longitude: null,
    radius: 0,
    editable: true,
    placeHint: undefined,
  },
);
const emit = defineEmits<{ select: [id: number | string]; pick: [point: { latitude: string; longitude: string }] }>();

const { t } = useI18n();
const el = ref<HTMLDivElement | null>(null);
const ready = ref(false);
const locating = ref(false);
const map = shallowRef<Leaflet.Map | null>(null);
let L: typeof Leaflet | null = null;
let layer: Leaflet.LayerGroup | null = null;
let marker: Leaflet.Marker | null = null;
let circle: Leaflet.Circle | null = null;
let resize: ResizeObserver | null = null;

const boxHeight = computed(() => (typeof props.height === "number" ? `${props.height}px` : props.height));
const canPick = computed(() => props.picker && props.editable);

/** Tashkent: where a map with nothing on it starts. */
const FALLBACK: [number, number] = [41.3111, 69.2797];
// Metres per degree of latitude (close enough to place a label on a circle's edge).
const METRES_PER_DEGREE = 111_320;

/** Leaflet inserts string content as HTML; names come from people and owners, so they go in as text. */
function text(value: string): HTMLElement {
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}

function chosen(): [number, number] | null {
  const lat = props.latitude === null ? NaN : Number(props.latitude);
  const lng = props.longitude === null ? NaN : Number(props.longitude);
  return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null;
}

/** Branch circles and check-in dots. */
function draw(): void {
  const current = map.value;
  if (!L || !current) return;
  layer?.remove();
  layer = L.layerGroup().addTo(current);
  const bounds: Leaflet.LatLngExpression[] = [];
  for (const branch of props.branches) {
    if (branch.latitude === null || branch.longitude === null) continue;
    const lat = Number(branch.latitude);
    const lng = Number(branch.longitude);
    const center: Leaflet.LatLngExpression = [lat, lng];
    // The name sits on the circle's top edge, so it never hides a check-in inside it.
    const edge: Leaflet.LatLngExpression = [lat + branch.geofence_m / METRES_PER_DEGREE, lng];
    bounds.push(center, edge, [lat - branch.geofence_m / METRES_PER_DEGREE, lng]);
    L.circle(center, { radius: branch.geofence_m, className: "ui-map-fence", weight: 1.5, interactive: false }).addTo(layer);
    L.circleMarker(center, { radius: 4, className: "ui-map-center", weight: 2, interactive: false }).addTo(layer);
    L.tooltip({ permanent: true, direction: "top", className: "ui-map-label", offset: [0, -2] })
      .setLatLng(edge)
      .setContent(text(branch.name))
      .addTo(layer);
  }
  for (const point of props.points) {
    const at: Leaflet.LatLngExpression = [Number(point.lat), Number(point.lng)];
    bounds.push(at);
    L.circleMarker(at, { radius: 6, className: `ui-map-point ui-map-${point.tone}`, weight: 2 })
      .bindTooltip(text(point.label), { direction: "top", offset: [0, -4] })
      .on("click", () => emit("select", point.id))
      .addTo(layer);
  }
  if (props.picker) return;
  if (bounds.length === 1) current.setView(bounds[0]!, 16);
  else if (bounds.length > 1) current.fitBounds(L.latLngBounds(bounds), { padding: [36, 36], maxZoom: 16 });
}

/** Picker: the pin and its circle. */
function place(latlng: [number, number], fit: boolean): void {
  if (!L || !map.value) return;
  if (!marker) {
    marker = L.marker(latlng, {
      draggable: canPick.value,
      keyboard: canPick.value,
      icon: L.divIcon({ className: "ui-map-pin", html: '<span class="ui-map-pin__dot"></span>', iconSize: [30, 30], iconAnchor: [15, 28] }),
    }).addTo(map.value);
    marker.on("dragend", () => {
      const at = marker!.getLatLng();
      choose([at.lat, at.lng]);
    });
  } else marker.setLatLng(latlng);
  if (!circle) circle = L.circle(latlng, { radius: props.radius, className: "ui-map-fence", weight: 2, interactive: false }).addTo(map.value);
  else circle.setLatLng(latlng);
  if (fit) map.value.fitBounds(circle.getBounds(), { padding: [28, 28], maxZoom: 17 });
}

function choose(latlng: [number, number]): void {
  emit("pick", { latitude: latlng[0].toFixed(6), longitude: latlng[1].toFixed(6) });
}

onMounted(async () => {
  const [leaflet] = await Promise.all([import("leaflet"), import("leaflet/dist/leaflet.css")]);
  L = leaflet;
  if (!el.value) return;
  const start = props.picker ? chosen() : null;
  const instance = L.map(el.value, {
    zoomControl: props.interactive,
    attributionControl: true,
    scrollWheelZoom: false,
    dragging: props.interactive,
    doubleClickZoom: props.interactive,
  }).setView(start ?? FALLBACK, start ? 16 : 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap", className: "ui-map-tiles" }).addTo(instance);
  map.value = instance;
  draw();
  if (start) place(start, true);
  if (canPick.value) instance.on("click", (event: Leaflet.LeafletMouseEvent) => choose([event.latlng.lat, event.latlng.lng]));
  if (typeof ResizeObserver !== "undefined") {
    resize = new ResizeObserver(() => instance.invalidateSize());
    resize.observe(el.value);
  }
  ready.value = true;
});

watch(() => [props.branches, props.points], draw, { deep: true });
watch(
  () => [props.latitude, props.longitude] as const,
  () => {
    const at = props.picker ? chosen() : null;
    if (at) place(at, !marker);
  },
);
watch(
  () => props.radius,
  (radius) => {
    circle?.setRadius(radius);
    if (circle && map.value) map.value.fitBounds(circle.getBounds(), { padding: [28, 28], maxZoom: 17 });
  },
);

function locate(): void {
  if (!navigator.geolocation) return;
  locating.value = true;
  navigator.geolocation.getCurrentPosition(
    (position) => {
      locating.value = false;
      choose([position.coords.latitude, position.coords.longitude]);
    },
    () => {
      locating.value = false;
      toast.error(t("common.map.locateFailed"));
    },
    { enableHighAccuracy: true, timeout: 10_000 },
  );
}

onBeforeUnmount(() => {
  resize?.disconnect();
  map.value?.remove();
  map.value = null;
});
</script>

<template>
  <div class="ui-map relative z-0 w-full overflow-hidden rounded-[12px] border border-line bg-surface-2" :style="{ height: boxHeight }">
    <div ref="el" class="ui-map-canvas size-full" :aria-label="label ?? t('common.map.label')" role="application" />
    <div v-if="!ready" class="absolute inset-0 grid place-items-center"><SkeletonBlock width="100%" height="100%" radius="0" /></div>
    <div v-if="ready && canPick" class="pointer-events-none absolute inset-x-2 bottom-2 z-[500] flex items-end justify-between gap-2">
      <span v-if="!chosen()" class="pointer-events-auto inline-flex items-center gap-1.5 rounded-full bg-surface/95 px-3 py-1.5 text-xs font-medium text-fg shadow-pop">
        <Crosshair :size="13" class="text-primary" />
        {{ placeHint ?? t("common.map.clickToPlace") }}
      </span>
      <span v-else />
      <UiButton class="pointer-events-auto shadow-pop" size="sm" :icon="LocateFixed" :loading="locating" @click="locate">{{ t("common.map.myLocation") }}</UiButton>
    </div>
  </div>
</template>

<style>
/* Leaflet builds its own DOM, so these rules are global, under the component's class. */
.ui-map-canvas {
  background-color: var(--c-surface-2);
  background-image:
    linear-gradient(var(--c-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--c-border) 1px, transparent 1px);
  background-size: 32px 32px;
  font: inherit;
}
.ui-map .leaflet-container {
  font-family: var(--font-sans);
}
[data-theme="dark"] .ui-map .ui-map-tiles {
  filter: invert(1) hue-rotate(180deg) brightness(0.88) contrast(0.9) saturate(0.6);
}
.ui-map .ui-map-fence {
  stroke: var(--c-primary);
  fill: var(--c-primary);
  fill-opacity: 0.12;
}
.ui-map .ui-map-center {
  stroke: var(--c-primary);
  fill: var(--c-surface);
  fill-opacity: 1;
}
.ui-map .ui-map-point {
  stroke: var(--c-surface);
  fill-opacity: 0.95;
}
.ui-map .ui-map-ok {
  fill: var(--c-success);
}
.ui-map .ui-map-warn {
  fill: var(--c-warning);
}
.ui-map .ui-map-bad {
  fill: var(--c-danger);
}
.ui-map .ui-map-label {
  background: var(--c-surface);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: 6px;
  box-shadow: var(--sh-xs);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
}
.ui-map .ui-map-label::before {
  display: none;
}
.ui-map .ui-map-pin {
  background: transparent;
  border: 0;
}
.ui-map .ui-map-pin__dot {
  position: absolute;
  inset: 0;
  border-radius: 50% 50% 50% 0;
  transform: rotate(-45deg);
  background: var(--c-primary);
  box-shadow:
    0 0 0 3px var(--c-surface),
    0 6px 14px -4px rgb(0 0 0 / 0.45);
}
.ui-map .ui-map-pin__dot::after {
  content: "";
  position: absolute;
  inset: 9px;
  border-radius: 50%;
  background: var(--c-surface);
}
.ui-map .leaflet-control-attribution {
  font-size: 10px;
  background: color-mix(in srgb, var(--c-surface) 85%, transparent);
  color: var(--c-muted);
}
.ui-map .leaflet-control-attribution a {
  color: var(--c-muted);
}
.ui-map .leaflet-bar a {
  background: var(--c-surface);
  color: var(--c-text);
  border-color: var(--c-border);
}
</style>
