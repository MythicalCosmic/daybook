/**
 * The zone editor's state: the zones being edited with undo and redo, what is selected, the shape
 * being drawn, and every edit as one function, so the component only turns pointer and key events
 * into these calls. Each finished edit is one step in the history; a drag is one step, not one per
 * pixel.
 */
import { computed, ref, shallowRef } from "vue";

import type { Point, Zone, ZoneKind } from "../types";
import { MAX_POLYGON_POINTS, MAX_ZONES, canClose, cleanZone, flipInside, insertPoint, moveZone, movePoint, nextZoneId, normalizePoint, removePoint, selfIntersects, validateZones } from "./geometry";

export type Tool = "select" | ZoneKind;

export interface Selection {
  zone: number;
  point: number | null;
}

function copy(zones: readonly Zone[]): Zone[] {
  return zones.map((zone) => ({ ...zone, points: zone.points.map((p) => [p[0], p[1]] as Point) }));
}

function same(a: readonly Zone[], b: readonly Zone[]): boolean {
  return JSON.stringify(a.map(cleanZone)) === JSON.stringify(b.map(cleanZone));
}

export function useZoneEditor(initial: readonly Zone[] = []) {
  const saved = shallowRef<Zone[]>(copy(initial));
  const history = shallowRef<Zone[][]>([copy(initial)]);
  const index = ref(0);
  /** The zones as shown, while a drag moves them (not yet in the history). */
  const live = shallowRef<Zone[] | null>(null);
  const zones = computed<Zone[]>(() => live.value ?? history.value[index.value]!);
  const selected = ref<Selection | null>(null);
  const tool = ref<Tool>("select");
  const drawing = shallowRef<Point[] | null>(null);

  const canUndo = computed(() => index.value > 0 && !drawing.value);
  const canRedo = computed(() => index.value < history.value.length - 1 && !drawing.value);
  const dirty = computed(() => !same(zones.value, saved.value));
  const problems = computed(() => validateZones(zones.value));
  const crossing = computed(() => zones.value.filter((zone) => zone.kind !== "line" && selfIntersects(zone.points)).map((zone) => zone.id));
  const full = computed(() => zones.value.length >= MAX_ZONES);
  const selectedZone = computed(() => (selected.value ? (zones.value[selected.value.zone] ?? null) : null));

  /** Starts again from these zones (loaded or saved). */
  function reset(next: readonly Zone[]): void {
    saved.value = copy(next);
    history.value = [copy(next)];
    index.value = 0;
    live.value = null;
    selected.value = null;
    drawing.value = null;
  }

  function commit(next: Zone[]): void {
    live.value = null;
    if (same(next, history.value[index.value]!)) return;
    history.value = [...history.value.slice(0, index.value + 1), copy(next)];
    index.value = history.value.length - 1;
  }

  function undo(): void {
    if (!canUndo.value) return;
    index.value--;
    selected.value = null;
  }

  function redo(): void {
    if (!canRedo.value) return;
    index.value++;
    selected.value = null;
  }

  function setTool(next: Tool): void {
    tool.value = next;
    drawing.value = null;
    if (next !== "select") selected.value = null;
  }

  // ─── Drawing a new zone ──────────────────────────────────────────────────

  /** Adds a corner; a line finishes by itself at its second point, a polygon at 24. */
  function addPoint(point: Point): void {
    if (tool.value === "select" || full.value) return;
    const points = [...(drawing.value ?? []), normalizePoint(point)];
    drawing.value = points;
    if (tool.value === "line" ? points.length === 2 : points.length >= MAX_POLYGON_POINTS) finish();
  }

  function undoPoint(): void {
    if (!drawing.value) return;
    drawing.value = drawing.value.length > 1 ? drawing.value.slice(0, -1) : null;
  }

  /** Closes the shape being drawn into a zone and selects it. False when it can't close yet. */
  function finish(): boolean {
    const points = drawing.value;
    const kind = tool.value;
    if (!points || kind === "select" || !canClose(kind, points)) return false;
    const zone: Zone = { id: nextZoneId(zones.value, kind), kind, points };
    if (kind === "line") zone.in = "left";
    const next = [...copy(zones.value), zone];
    commit(next);
    drawing.value = null;
    tool.value = "select";
    selected.value = { zone: next.length - 1, point: null };
    return true;
  }

  function cancelDrawing(): void {
    drawing.value = null;
  }

  // ─── Editing ─────────────────────────────────────────────────────────────

  function select(next: Selection | null): void {
    selected.value = next;
  }

  /** While dragging: the zones as they look now, committed on `endDrag`. */
  function dragPoint(zoneIndex: number, pointIndex: number, to: Point, from: readonly Zone[]): void {
    const next = copy(from);
    next[zoneIndex] = movePoint(next[zoneIndex]!, pointIndex, to);
    live.value = next;
  }

  function dragZone(zoneIndex: number, dx: number, dy: number, from: readonly Zone[]): void {
    const next = copy(from);
    next[zoneIndex] = moveZone(next[zoneIndex]!, dx, dy);
    live.value = next;
  }

  function endDrag(): void {
    if (live.value) commit(live.value);
  }

  /** A corner on an edge of a polygon, after corner `after`; returns its index. */
  function addCorner(zoneIndex: number, after: number, point: Point): number | null {
    const zone = zones.value[zoneIndex];
    if (!zone || zone.kind === "line" || zone.points.length >= MAX_POLYGON_POINTS) return null;
    const next = copy(zones.value);
    next[zoneIndex] = insertPoint(zone, after, point);
    commit(next);
    return after + 1;
  }

  /** Delete: the selected corner (a polygon keeps at least three), else the selected zone. */
  function removeSelected(): void {
    const selection = selected.value;
    if (!selection) return;
    const zone = zones.value[selection.zone];
    if (!zone) return;
    const next = copy(zones.value);
    if (selection.point !== null && zone.kind !== "line" && zone.points.length > 3) {
      next[selection.zone] = removePoint(zone, selection.point);
      selected.value = { zone: selection.zone, point: null };
    } else {
      next.splice(selection.zone, 1);
      selected.value = null;
    }
    commit(next);
  }

  function flip(zoneIndex: number): void {
    const zone = zones.value[zoneIndex];
    if (!zone || zone.kind !== "line") return;
    const next = copy(zones.value);
    next[zoneIndex] = flipInside(zone);
    commit(next);
  }

  /** Arrow keys: the selected corner or zone moves by `step` of the frame. */
  function nudge(dx: number, dy: number): void {
    const selection = selected.value;
    const zone = selection ? zones.value[selection.zone] : null;
    if (!selection || !zone) return;
    const next = copy(zones.value);
    if (selection.point !== null) {
      const p = zone.points[selection.point]!;
      next[selection.zone] = movePoint(zone, selection.point, [p[0] + dx, p[1] + dy]);
    } else next[selection.zone] = moveZone(zone, dx, dy);
    commit(next);
  }

  /** The zones as the API wants them. */
  const payload = computed(() => zones.value.map(cleanZone));

  return {
    zones,
    selected,
    selectedZone,
    tool,
    drawing,
    canUndo,
    canRedo,
    dirty,
    problems,
    crossing,
    full,
    payload,
    reset,
    undo,
    redo,
    setTool,
    addPoint,
    undoPoint,
    finish,
    cancelDrawing,
    select,
    dragPoint,
    dragZone,
    endDrag,
    addCorner,
    removeSelected,
    flip,
    nudge,
    markSaved: () => (saved.value = copy(zones.value)),
  };
}

export type ZoneEditor = ReturnType<typeof useZoneEditor>;
