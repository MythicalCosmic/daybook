<script setup lang="ts">
/**
 * The zone editor (docs/KOZ.md §4) on a camera's latest picture. Tools for the queue, the place
 * behind the counter, the entrance line (with its inside arrow and a flip), the floor and hidden
 * areas. Click or tap to add corners; Enter, a double-click or Finish closes a shape (a line closes
 * at its second point); drag a corner or a whole zone; click an edge to add a corner; Delete
 * removes; Ctrl+Z and Ctrl+Shift+Z undo and redo; the arrows nudge. The backend's rules (eight
 * zones, 3–24 corners, a line of two points, everything inside the picture, unique names) are
 * checked as you draw; Save sends the zones with PATCH.
 */
import {
  ArrowRightLeft,
  Check,
  EyeOff,
  FlipHorizontal2,
  LayoutDashboard,
  MousePointer2,
  MoveRight,
  Redo2,
  RefreshCw,
  Trash2,
  TriangleAlert,
  Undo2,
  UserRound,
  UsersRound,
  X,
} from "@lucide/vue";
import { useMediaQuery, useResizeObserver } from "@vueuse/core";
import { computed, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { isApiError } from "@/api/http";
import IconButton from "@/components/IconButton.vue";
import UiButton from "@/components/UiButton.vue";
import { toast } from "@/components/useToast";
import { useHotkey } from "@/core/hotkeys";
import { useCompanyId } from "@/stores/company";

import { requestSnapshot, updateCamera, useRefresh } from "../api";
import { MAX_ZONES, hitEdge, hitVertex, hitZone, insideArrow, labelAnchor, pixelDistance, pointFromClient, type Size } from "../lib/geometry";
import { ZONE_COLOR, missingZones } from "../lib/look";
import { useZoneEditor, type Tool } from "../lib/zoneEditor";
import type { Camera, Point, Zone } from "../types";

const props = defineProps<{ camera: Camera }>();
const emit = defineEmits<{ saved: [] }>();

const { t } = useI18n();
const uid = useId();
const companyId = useCompanyId();
const refresh = useRefresh();
const coarse = useMediaQuery("(pointer: coarse)");

const editor = useZoneEditor(props.camera.zones);
watch(
  () => props.camera.id,
  () => editor.reset(props.camera.zones),
);
defineExpose({ dirty: editor.dirty });

const aspect = computed(() => (props.camera.w && props.camera.h ? props.camera.w / props.camera.h : 16 / 9));
const VW = 1000;
const VH = computed(() => VW / aspect.value);

const svg = ref<SVGSVGElement | null>(null);
const shown = ref<Size>({ w: 800, h: 450 });
useResizeObserver(svg, (entries) => {
  const box = entries[0]?.contentRect;
  if (box) shown.value = { w: box.width, h: box.height };
});
/** One screen pixel in viewBox units. */
const px = computed(() => VW / Math.max(1, shown.value.w));

const TOOLS: Array<{ id: Tool; icon: typeof Check }> = [
  { id: "select", icon: MousePointer2 },
  { id: "queue", icon: UsersRound },
  { id: "staff", icon: UserRound },
  { id: "line", icon: MoveRight },
  { id: "floor", icon: LayoutDashboard },
  { id: "mask", icon: EyeOff },
];

const hint = computed(() => {
  if (editor.drawing.value) return editor.tool.value === "line" ? t("vision.zones.drawingLine") : coarse.value ? t("vision.zones.drawingTouch") : t("vision.zones.drawing");
  return t(`vision.zones.hint.${editor.tool.value}`);
});

// ─── Pointer ────────────────────────────────────────────────────────────────

interface Drag {
  kind: "point" | "zone";
  zone: number;
  point: number;
  start: Point;
  from: Zone[];
  moved: boolean;
}
let drag: Drag | null = null;
const hover = ref<Point | null>(null);

function rect(): DOMRect | null {
  return svg.value?.getBoundingClientRect() ?? null;
}
function toPoint(event: PointerEvent | MouseEvent): Point {
  const box = rect();
  return box ? pointFromClient(event.clientX, event.clientY, box) : [0, 0];
}
function size(): Size {
  const box = rect();
  return box ? { w: box.width, h: box.height } : shown.value;
}
const radiusFor = (event: PointerEvent) => (event.pointerType === "touch" ? 22 : 12);

function onPointerDown(event: PointerEvent): void {
  if (event.button !== 0) return;
  svg.value?.setPointerCapture(event.pointerId);
  const p = toPoint(event);
  const radius = radiusFor(event);
  const zones = editor.zones.value;
  if (editor.tool.value !== "select") {
    const points = editor.drawing.value;
    if (points && points.length >= 3 && pixelDistance(points[0]!, p, size()) <= radius) {
      editor.finish();
      return;
    }
    if (editor.full.value) {
      toast.warning(t("vision.zones.problem.too_many", { max: MAX_ZONES }));
      return;
    }
    editor.addPoint(p);
    return;
  }
  const vertex = hitVertex(zones, p, size(), radius);
  if (vertex) {
    editor.select({ zone: vertex.zone, point: vertex.point });
    drag = { kind: "point", zone: vertex.zone, point: vertex.point, start: p, from: zones, moved: false };
    return;
  }
  const current = editor.selectedZone.value;
  const selection = editor.selected.value;
  if (current && selection && current.kind !== "line") {
    const edge = hitEdge(current, p, size(), radius * 0.7);
    if (edge !== null) {
      const point = editor.addCorner(selection.zone, edge, p);
      if (point !== null) {
        editor.select({ zone: selection.zone, point });
        drag = { kind: "point", zone: selection.zone, point, start: p, from: editor.zones.value, moved: false };
        return;
      }
    }
  }
  const hit = hitZone(zones, p, size(), radius);
  if (hit !== null) {
    editor.select({ zone: hit, point: null });
    drag = { kind: "zone", zone: hit, point: -1, start: p, from: zones, moved: false };
    return;
  }
  editor.select(null);
}

function onPointerMove(event: PointerEvent): void {
  const p = toPoint(event);
  hover.value = p;
  if (!drag) return;
  if (!drag.moved && pixelDistance(p, drag.start, size()) < 2) return;
  drag.moved = true;
  if (drag.kind === "point") editor.dragPoint(drag.zone, drag.point, p, drag.from);
  else editor.dragZone(drag.zone, p[0] - drag.start[0], p[1] - drag.start[1], drag.from);
}

function onPointerUp(): void {
  if (drag?.moved) editor.endDrag();
  drag = null;
}

/** A double-click adds the same corner twice before it closes the shape: drop the copy. */
function onDoubleClick(): void {
  const points = editor.drawing.value;
  if (!points) return;
  const last = points[points.length - 1];
  const before = points[points.length - 2];
  if (last && before && pixelDistance(last, before, size()) < 6) editor.undoPoint();
  editor.finish();
}

// ─── Keys ───────────────────────────────────────────────────────────────────

function onKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
  const step = event.shiftKey ? 0.02 : 0.005;
  switch (event.key) {
    case "Enter":
      if (editor.drawing.value) {
        event.preventDefault();
        editor.finish();
      }
      break;
    case "Escape":
      if (editor.drawing.value) editor.cancelDrawing();
      else editor.select(null);
      break;
    case "Delete":
    case "Backspace":
      event.preventDefault();
      if (editor.drawing.value) editor.undoPoint();
      else editor.removeSelected();
      break;
    case "ArrowLeft":
    case "ArrowRight":
    case "ArrowUp":
    case "ArrowDown":
      if (!editor.selected.value) return;
      event.preventDefault();
      editor.nudge(event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0, event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0);
      break;
  }
}
useHotkey("mod+z", () => editor.undo(), { group: "page", description: "vision.zones.undo" });
useHotkey("mod+shift+z", () => editor.redo(), { group: "page", description: "vision.zones.redo" });
useHotkey("mod+y", () => editor.redo(), { group: "page" });

// ─── Drawing ────────────────────────────────────────────────────────────────

const pts = (points: readonly Point[]) => points.map(([x, y]) => `${x * VW},${y * VH.value}`).join(" ");
const invalid = computed(() => new Set(editor.problems.value.map((p) => p.zone).filter(Boolean)));
const shapes = computed(() =>
  editor.zones.value.map((zone, index) => {
    let arrow: { x1: number; y1: number; x2: number; y2: number } | null = null;
    if (zone.kind === "line" && zone.points.length === 2) {
      const { from, to } = insideArrow(zone.points[0]!, zone.points[1]!, zone.in ?? "left", shown.value, 46);
      arrow = { x1: from[0] * VW, y1: from[1] * VH.value, x2: to[0] * VW, y2: to[1] * VH.value };
    }
    return {
      zone,
      index,
      points: pts(zone.points),
      color: ZONE_COLOR[zone.kind],
      selected: editor.selected.value?.zone === index,
      bad: invalid.value.has(zone.id) || editor.crossing.value.includes(zone.id),
      tag: zone.kind === "line" ? midpoint(zone) : labelAnchor(zone.points),
      arrow,
    };
  }),
);
function midpoint(zone: Zone): Point {
  const [a, b] = zone.points;
  return a && b ? [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] : [0.5, 0.5];
}
const drawingColor = computed(() => (editor.tool.value === "select" ? "#ffffff" : ZONE_COLOR[editor.tool.value]));
const rubber = computed(() => {
  const points = editor.drawing.value;
  const last = points?.[points.length - 1];
  if (!points || !last || !hover.value) return null;
  return { x1: last[0] * VW, y1: last[1] * VH.value, x2: hover.value[0] * VW, y2: hover.value[1] * VH.value };
});

// ─── The side panel ─────────────────────────────────────────────────────────

const serverProblems = ref<string[]>([]);
const messages = computed(() => [
  ...editor.problems.value.map((p) => (p.zone ? `${p.zone}: ` : "") + t(`vision.zones.problem.${p.code}`, { ...(p.params ?? {}) })),
  ...serverProblems.value,
]);
const needs = computed(() => missingZones(props.camera.role, editor.zones.value.map((zone) => zone.kind)));
const needsText = computed(() => (needs.value.length ? t("vision.zones.needs", { list: needs.value.map((kind) => t(`vision.zone.${kind}`)).join(", ") }) : ""));

const saving = ref(false);
async function save(): Promise<void> {
  if (editor.problems.value.length) return;
  saving.value = true;
  serverProblems.value = [];
  try {
    await updateCamera(companyId.value, props.camera.id, { zones: editor.payload.value }, false);
    editor.markSaved();
    toast.success(t("vision.zones.saved"));
    refresh();
    emit("saved");
  } catch (error) {
    if (isApiError(error)) serverProblems.value = error.fieldErrors.zones ?? (error.detail ? [error.detail] : [t("common.error.generic")]);
  } finally {
    saving.value = false;
  }
}

const refreshing = ref(false);
async function newSnapshot(): Promise<void> {
  refreshing.value = true;
  try {
    await requestSnapshot(companyId.value, props.camera.id);
    toast.info(t("vision.cameras.refreshing"));
    setTimeout(() => {
      refresh();
      refreshing.value = false;
    }, 3200);
  } catch {
    refreshing.value = false;
  }
}
</script>

<template>
  <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]" @keydown="onKeydown">
    <div class="flex min-w-0 flex-col gap-3">
      <div class="ui-card flex flex-wrap items-center gap-1.5 p-1.5">
        <div role="toolbar" :aria-label="t('vision.zones.tools')" class="flex flex-wrap gap-1">
          <button
            v-for="item in TOOLS"
            :key="item.id"
            type="button"
            :class="[
              'pressable inline-flex h-9 items-center gap-1.5 rounded-[9px] px-2.5 text-sm font-semibold transition-colors',
              editor.tool.value === item.id ? 'bg-fg text-canvas' : 'text-muted hover:bg-highlight hover:text-fg',
            ]"
            :aria-pressed="editor.tool.value === item.id"
            :title="t(`vision.zones.hint.${item.id}`)"
            :data-tool="item.id"
            @click="editor.setTool(item.id)"
          >
            <component :is="item.icon" v-if="item.id === 'select' || item.id === 'line'" :size="15" />
            <span v-else class="size-2.5 rounded-full" :style="{ background: item.id === 'mask' ? '#3a3a3a' : ZONE_COLOR[item.id] }" aria-hidden="true" />
            <span>{{ t(`vision.zones.tool.${item.id}`) }}</span>
          </button>
        </div>
        <span class="flex-1" />
        <div class="flex items-center gap-0.5">
          <IconButton :icon="Undo2" :label="t('vision.zones.undo')" shortcut="mod+z" size="sm" :disabled="!editor.canUndo.value" @click="editor.undo()" />
          <IconButton :icon="Redo2" :label="t('vision.zones.redo')" shortcut="mod+shift+z" size="sm" :disabled="!editor.canRedo.value" @click="editor.redo()" />
          <IconButton
            v-if="editor.selectedZone.value?.kind === 'line'"
            :icon="FlipHorizontal2"
            :label="t('vision.zones.flip')"
            size="sm"
            @click="editor.flip(editor.selected.value!.zone)"
          />
          <IconButton
            :icon="Trash2"
            :label="editor.selected.value?.point !== null && editor.selected.value?.point !== undefined ? t('vision.zones.deletePoint') : t('vision.zones.delete')"
            shortcut="delete"
            size="sm"
            :disabled="!editor.selected.value"
            @click="editor.removeSelected()"
          />
          <IconButton :icon="RefreshCw" :label="t('vision.zones.refresh')" size="sm" :loading="refreshing" :disabled="!camera.online" @click="newSnapshot" />
        </div>
      </div>

      <p class="px-1 text-sm text-muted" aria-live="polite">{{ hint }}</p>

      <div class="koz-stage relative overflow-hidden rounded-[14px] bg-[#0f0d0b]" :style="{ aspectRatio: aspect }" tabindex="0" :aria-label="t('vision.zones.title')">
        <img v-if="camera.snapshot_url" :src="camera.snapshot_url" alt="" draggable="false" class="absolute inset-0 size-full select-none object-fill" />
        <div v-else class="absolute inset-0 grid place-items-center p-6 text-center text-sm text-white/60">{{ t("vision.zones.noSnapshot") }}</div>
        <svg
          ref="svg"
          class="absolute inset-0 size-full touch-none"
          :class="editor.tool.value === 'select' ? 'cursor-default' : 'cursor-crosshair'"
          :viewBox="`0 0 ${VW} ${VH}`"
          preserveAspectRatio="none"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
          @pointerleave="hover = null"
          @dblclick.prevent="onDoubleClick"
        >
          <defs>
            <pattern :id="`ze-hatch-${uid}`" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="12" height="12" fill="#090909" />
              <line x1="0" y1="0" x2="0" y2="12" stroke="rgba(255,255,255,0.15)" stroke-width="4" />
            </pattern>
            <marker :id="`ze-arrow-${uid}`" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#ffffff" />
            </marker>
          </defs>
          <g v-for="shape in shapes" :key="`${shape.zone.id}:${shape.index}`" :data-zone="shape.zone.id" :data-selected="shape.selected || undefined">
            <template v-if="shape.zone.kind === 'line'">
              <polyline :points="shape.points" fill="none" stroke="rgba(0,0,0,0.5)" :stroke-width="7 * px" stroke-linecap="round" />
              <polyline :points="shape.points" fill="none" :stroke="shape.bad ? '#ff6b52' : '#ffffff'" :stroke-width="(shape.selected ? 3 : 2.25) * px" :stroke-dasharray="shape.selected ? undefined : `${10 * px} ${7 * px}`" stroke-linecap="round" />
              <line v-if="shape.arrow" :x1="shape.arrow.x1" :y1="shape.arrow.y1" :x2="shape.arrow.x2" :y2="shape.arrow.y2" stroke="#ffffff" :stroke-width="2.5 * px" stroke-linecap="round" :marker-end="`url(#ze-arrow-${uid})`" />
            </template>
            <polygon
              v-else
              :points="shape.points"
              :fill="shape.zone.kind === 'mask' ? `url(#ze-hatch-${uid})` : shape.color"
              :fill-opacity="shape.zone.kind === 'mask' ? 1 : shape.selected ? 0.22 : 0.13"
              :stroke="shape.bad ? '#ff6b52' : shape.zone.kind === 'mask' ? 'rgba(255,255,255,0.55)' : shape.color"
              :stroke-width="(shape.selected ? 2.5 : 1.75) * px"
              :stroke-dasharray="shape.selected ? undefined : `${7 * px} ${6 * px}`"
              stroke-linejoin="round"
            />
          </g>

          <!-- The selected zone's corners. -->
          <template v-if="editor.selectedZone.value && !editor.drawing.value">
            <circle
              v-for="(point, index) in editor.selectedZone.value.points"
              :key="index"
              :cx="point[0] * VW"
              :cy="point[1] * VH"
              :r="(editor.selected.value?.point === index ? 8 : 6.5) * px * (coarse ? 1.5 : 1)"
              :fill="editor.selected.value?.point === index ? ZONE_COLOR[editor.selectedZone.value.kind] : '#ffffff'"
              :stroke="editor.selectedZone.value.kind === 'line' || editor.selectedZone.value.kind === 'mask' ? '#1c1916' : ZONE_COLOR[editor.selectedZone.value.kind]"
              :stroke-width="2.5 * px"
              class="cursor-grab"
            />
          </template>

          <!-- The shape being drawn. -->
          <template v-if="editor.drawing.value">
            <polygon v-if="editor.tool.value !== 'line' && editor.drawing.value.length >= 3" :points="pts(editor.drawing.value)" :fill="drawingColor" fill-opacity="0.12" stroke="none" />
            <polyline :points="pts(editor.drawing.value)" fill="none" :stroke="drawingColor" :stroke-width="2.5 * px" stroke-linejoin="round" />
            <line v-if="rubber" v-bind="rubber" :stroke="drawingColor" :stroke-width="1.75 * px" :stroke-dasharray="`${6 * px} ${5 * px}`" />
            <circle
              v-for="(point, index) in editor.drawing.value"
              :key="index"
              :cx="point[0] * VW"
              :cy="point[1] * VH"
              :r="(index === 0 && editor.drawing.value.length >= 3 ? 9 : 5.5) * px * (coarse ? 1.4 : 1)"
              :fill="index === 0 ? drawingColor : '#ffffff'"
              :stroke="index === 0 ? '#ffffff' : drawingColor"
              :stroke-width="2.25 * px"
              :class="index === 0 && editor.drawing.value.length >= 3 && 'koz-close'"
            />
          </template>
        </svg>

        <div class="pointer-events-none absolute inset-0" aria-hidden="true">
          <template v-for="shape in shapes" :key="`tag-${shape.zone.id}:${shape.index}`">
            <span
              class="koz-tag absolute inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold"
              :style="{ left: `${shape.tag[0] * 100}%`, top: `${shape.tag[1] * 100}%`, '--tag': shape.zone.kind === 'mask' ? '#cfcfcf' : shape.color }"
              :data-line="shape.zone.kind === 'line' || undefined"
            >
              <span class="size-1.5 rounded-full" :style="{ background: shape.zone.kind === 'mask' ? '#9a9a9a' : shape.color }" />{{ t(`vision.zone.${shape.zone.kind}`) }} · {{ shape.zone.id }}
            </span>
          </template>
        </div>

        <div v-if="editor.drawing.value" class="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center gap-2 p-3">
          <button type="button" class="koz-glass pointer-events-auto inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" :disabled="editor.tool.value === 'line' || editor.drawing.value.length < 3" @click="editor.finish()">
            <Check :size="15" />{{ t("vision.zones.finish") }}
          </button>
          <button type="button" class="koz-glass pointer-events-auto inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-semibold text-white" @click="editor.cancelDrawing()"><X :size="15" />{{ t("common.cancel") }}</button>
        </div>
      </div>
    </div>

    <aside class="flex min-w-0 flex-col gap-3">
      <section class="ui-card flex flex-col" :aria-label="t('vision.zones.list')">
        <header class="flex items-center gap-2 px-4 pb-2 pt-3.5">
          <h2 class="flex-1 text-sm font-semibold text-fg">{{ t("vision.zones.list") }}</h2>
          <span :class="['rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums', editor.full.value ? 'bg-warning-soft text-warning' : 'bg-surface-2 text-muted dark:bg-surface-3']">{{ t("vision.zones.count", { n: editor.zones.value.length, max: MAX_ZONES }) }}</span>
        </header>
        <p v-if="!editor.zones.value.length" class="px-4 pb-4 text-sm text-muted">{{ t("vision.zones.empty") }}</p>
        <ul v-else class="flex flex-col px-2 pb-2">
          <li v-for="shape in shapes" :key="`row-${shape.zone.id}:${shape.index}`">
            <div
              :class="['flex cursor-pointer items-center gap-2.5 rounded-[9px] px-2 py-2 transition-colors', shape.selected ? 'bg-accent-soft' : 'hover:bg-highlight']"
              role="button"
              tabindex="0"
              :aria-pressed="shape.selected"
              @click="(editor.setTool('select'), editor.select({ zone: shape.index, point: null }))"
              @keydown.enter.prevent="(editor.setTool('select'), editor.select({ zone: shape.index, point: null }))"
            >
              <MoveRight v-if="shape.zone.kind === 'line'" :size="14" class="shrink-0 text-fg" />
              <span v-else class="size-3 shrink-0 rounded-[4px]" :style="{ background: shape.zone.kind === 'mask' ? '#3a3a3a' : shape.color }" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-fg">{{ t(`vision.zone.${shape.zone.kind}`) }} <span class="font-mono text-xs font-normal text-muted">{{ shape.zone.id }}</span></span>
                <span class="block truncate text-xs text-muted">
                  <template v-if="shape.zone.kind === 'line'"><ArrowRightLeft :size="11" class="mr-0.5 inline" />{{ t("vision.zones.inside") }}</template>
                  <template v-else>{{ t("vision.zones.points", { n: shape.zone.points.length }, shape.zone.points.length) }}</template>
                </span>
              </span>
              <TriangleAlert v-if="shape.bad" :size="15" class="shrink-0 text-danger" />
              <IconButton v-if="shape.zone.kind === 'line'" :icon="FlipHorizontal2" :label="t('vision.zones.flip')" size="sm" @click.stop="editor.flip(shape.index)" />
            </div>
          </li>
        </ul>
      </section>

      <section v-if="messages.length || editor.crossing.value.length || needsText" class="ui-card flex flex-col gap-2 p-4" aria-live="polite">
        <p v-for="message in messages" :key="message" class="flex items-start gap-2 text-sm text-danger" data-problem><TriangleAlert :size="15" class="mt-0.5 shrink-0" />{{ message }}</p>
        <p v-for="id in editor.crossing.value" :key="`x-${id}`" class="flex items-start gap-2 text-sm text-warning"><TriangleAlert :size="15" class="mt-0.5 shrink-0" />{{ id }}: {{ t("vision.zones.selfIntersect") }}</p>
        <p v-if="needsText" class="flex items-start gap-2 text-sm text-warning"><TriangleAlert :size="15" class="mt-0.5 shrink-0" />{{ needsText }}</p>
      </section>

      <p class="px-1 text-xs leading-5 text-muted">{{ t("vision.zones.maskNote") }}</p>
      <UiButton variant="primary" block :loading="saving" :disabled="!editor.dirty.value || editor.problems.value.length > 0" @click="save">{{ t("vision.zones.save") }}</UiButton>
    </aside>
  </div>
</template>

<style scoped>
.koz-stage:focus-visible {
  outline: 2px solid var(--c-ring);
  outline-offset: 2px;
}
.koz-tag {
  background: rgb(16 13 10 / 0.6);
  color: color-mix(in srgb, var(--tag) 70%, #ffffff);
  transform: translate(6px, 6px);
  -webkit-backdrop-filter: blur(6px);
  backdrop-filter: blur(6px);
}
.koz-tag[data-line] {
  transform: translate(-50%, 10px);
  color: #ffffff;
}
.koz-glass {
  background: rgb(14 11 9 / 0.66);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}
.koz-close {
  animation: koz-close 1.2s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}
@keyframes koz-close {
  50% {
    transform: scale(1.25);
  }
}
:root[data-motion="reduced"] .koz-close {
  animation: none;
}
</style>
