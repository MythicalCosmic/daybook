<script setup lang="ts">
/**
 * The branch's place and check-in circle on a map (plan §6.3: A's own MapView; F builds one for
 * attendance and the lead merges them at integration). Click the map or drag the pin to move the
 * branch; the circle shows the geofence radius. Leaflet and its tiles load only when the map is
 * shown (OpenStreetMap tiles are allowed by the dashboard's CSP).
 */
import { Crosshair, LocateFixed } from "@lucide/vue";
import type * as Leaflet from "leaflet";
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { useI18n } from "vue-i18n";

import SkeletonBlock from "@/components/SkeletonBlock.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";

const props = withDefaults(
  defineProps<{
    latitude: string | null;
    longitude: string | null;
    radius: number;
    editable?: boolean;
    height?: number;
  }>(),
  { editable: true, height: 260 },
);
const emit = defineEmits<{ pick: [point: { latitude: string; longitude: string }] }>();

const { t } = useI18n();
const el = ref<HTMLDivElement | null>(null);
const ready = ref(false);
const locating = ref(false);
const map = shallowRef<Leaflet.Map | null>(null);
let L: typeof Leaflet | null = null;
let marker: Leaflet.Marker | null = null;
let circle: Leaflet.Circle | null = null;
let resize: ResizeObserver | null = null;

/** Tashkent: where a branch without a place starts. */
const FALLBACK: [number, number] = [41.3111, 69.2797];

function point(): [number, number] | null {
  const lat = props.latitude === null ? NaN : Number(props.latitude);
  const lng = props.longitude === null ? NaN : Number(props.longitude);
  return Number.isFinite(lat) && Number.isFinite(lng) ? [lat, lng] : null;
}

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function place(latlng: [number, number], fit: boolean): void {
  if (!L || !map.value) return;
  const color = token("--c-primary");
  if (!marker) {
    marker = L.marker(latlng, {
      draggable: props.editable,
      keyboard: props.editable,
      icon: L.divIcon({ className: "branch-pin", html: '<span class="branch-pin__dot"></span>', iconSize: [30, 30], iconAnchor: [15, 28] }),
    }).addTo(map.value);
    marker.on("dragend", () => {
      const at = marker!.getLatLng();
      choose([at.lat, at.lng]);
    });
  } else {
    marker.setLatLng(latlng);
  }
  if (!circle) {
    circle = L.circle(latlng, { radius: props.radius, color, weight: 2, fillColor: color, fillOpacity: 0.12, interactive: false }).addTo(map.value);
  } else {
    circle.setLatLng(latlng);
  }
  if (fit) map.value.fitBounds(circle.getBounds(), { padding: [28, 28], maxZoom: 17 });
}

function choose(latlng: [number, number]): void {
  emit("pick", { latitude: latlng[0].toFixed(6), longitude: latlng[1].toFixed(6) });
}

onMounted(async () => {
  const [leaflet] = await Promise.all([import("leaflet"), import("leaflet/dist/leaflet.css")]);
  L = leaflet;
  if (!el.value) return;
  const start = point();
  const instance = L.map(el.value, { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView(start ?? FALLBACK, start ? 16 : 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
    className: "branch-map-tiles",
  }).addTo(instance);
  map.value = instance;
  if (start) place(start, true);
  if (props.editable) instance.on("click", (event: Leaflet.LeafletMouseEvent) => choose([event.latlng.lat, event.latlng.lng]));
  resize = new ResizeObserver(() => instance.invalidateSize());
  resize.observe(el.value);
  ready.value = true;
});

watch(
  () => [props.latitude, props.longitude] as const,
  () => {
    const at = point();
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
      toast.error(t("settings.map.locateFailed"));
    },
    { enableHighAccuracy: true, timeout: 10_000 },
  );
}

onBeforeUnmount(() => {
  resize?.disconnect();
  map.value?.remove();
});
</script>

<template>
  <div class="relative overflow-hidden rounded-[12px] border border-line bg-surface-2" :style="{ height: `${height}px` }">
    <div ref="el" class="branch-map size-full" :aria-label="t('settings.map.label')" role="application" />
    <div v-if="!ready" class="absolute inset-0 grid place-items-center"><SkeletonBlock width="100%" height="100%" radius="0" /></div>
    <div v-if="ready && editable" class="pointer-events-none absolute inset-x-2 bottom-2 z-[500] flex items-end justify-between gap-2">
      <span v-if="!point()" class="pointer-events-auto inline-flex items-center gap-1.5 rounded-full bg-surface/95 px-3 py-1.5 text-xs font-medium text-fg shadow-pop">
        <Crosshair :size="13" class="text-primary" />
        {{ t("settings.map.clickToPlace") }}
      </span>
      <span v-else />
      <UiButton class="pointer-events-auto shadow-pop" size="sm" :icon="LocateFixed" :loading="locating" @click="locate">{{ t("settings.map.myLocation") }}</UiButton>
    </div>
  </div>
</template>

<style scoped>
.branch-map {
  background-color: var(--c-surface-2);
  background-image:
    linear-gradient(var(--c-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--c-border) 1px, transparent 1px);
  background-size: 32px 32px;
  font: inherit;
}
.branch-map :deep(.branch-pin) {
  background: transparent;
  border: 0;
}
.branch-map :deep(.branch-pin__dot) {
  position: absolute;
  inset: 0;
  border-radius: 50% 50% 50% 0;
  transform: rotate(-45deg);
  background: var(--c-primary);
  box-shadow:
    0 0 0 3px var(--c-surface),
    0 6px 14px -4px rgb(0 0 0 / 0.45);
}
.branch-map :deep(.branch-pin__dot)::after {
  content: "";
  position: absolute;
  inset: 9px;
  border-radius: 50%;
  background: var(--c-surface);
}
.branch-map :deep(.leaflet-control-attribution) {
  font-size: 10px;
  background: color-mix(in srgb, var(--c-surface) 85%, transparent);
  color: var(--c-muted);
}
.branch-map :deep(.leaflet-control-attribution a) {
  color: var(--c-muted);
}
.branch-map :deep(.leaflet-bar a) {
  background: var(--c-surface);
  color: var(--c-text);
  border-color: var(--c-border);
}
:global([data-theme="dark"] .branch-map-tiles) {
  filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.6);
}
</style>
