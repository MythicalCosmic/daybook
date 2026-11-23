/** The zone editor's state: drawing, closing, dragging as one step, delete, flip, undo and redo. */
import { describe, expect, it } from "vitest";

import { useZoneEditor } from "../lib/zoneEditor";
import type { Zone } from "../types";

const queue: Zone = { id: "q1", kind: "queue", points: [[0.1, 0.5], [0.6, 0.5], [0.7, 0.9], [0.05, 0.9]] };

describe("the zone editor", () => {
  it("draws a polygon corner by corner and closes it into a named zone", () => {
    const editor = useZoneEditor([]);
    editor.setTool("staff");
    editor.addPoint([0.1, 0.2]);
    editor.addPoint([0.8, 0.2]);
    expect(editor.finish()).toBe(false); // two corners don't make a zone
    editor.addPoint([0.8, 0.45]);
    expect(editor.finish()).toBe(true);
    expect(editor.zones.value).toEqual([{ id: "s1", kind: "staff", points: [[0.1, 0.2], [0.8, 0.2], [0.8, 0.45]] }]);
    expect(editor.tool.value).toBe("select");
    expect(editor.selected.value).toEqual({ zone: 0, point: null });
    expect(editor.dirty.value).toBe(true);
  });

  it("finishes a line at its second point, inside on the left until flipped", () => {
    const editor = useZoneEditor([]);
    editor.setTool("line");
    editor.addPoint([0.1, 0.6]);
    editor.addPoint([0.9, 0.62]);
    expect(editor.zones.value[0]).toEqual({ id: "l1", kind: "line", points: [[0.1, 0.6], [0.9, 0.62]], in: "left" });
    editor.flip(0);
    expect(editor.zones.value[0]!.in).toBe("right");
  });

  it("makes one undo step of a whole drag", () => {
    const editor = useZoneEditor([queue]);
    const from = editor.zones.value;
    editor.dragZone(0, 0.01, 0, from);
    editor.dragZone(0, 0.05, 0, from);
    editor.endDrag();
    expect(editor.zones.value[0]!.points[0]).toEqual([0.15, 0.5]);
    editor.undo();
    expect(editor.zones.value[0]!.points[0]).toEqual([0.1, 0.5]);
    expect(editor.dirty.value).toBe(false);
    editor.redo();
    expect(editor.zones.value[0]!.points[0]).toEqual([0.15, 0.5]);
  });

  it("deletes a corner while the polygon keeps three, then the zone", () => {
    const editor = useZoneEditor([queue]);
    editor.select({ zone: 0, point: 1 });
    editor.removeSelected();
    expect(editor.zones.value[0]!.points).toHaveLength(3);
    editor.select({ zone: 0, point: 0 });
    editor.removeSelected();
    expect(editor.zones.value).toEqual([]);
  });

  it("says the backend's problems as you draw, and stops at eight zones", () => {
    const editor = useZoneEditor(Array.from({ length: 8 }, (_, i) => ({ ...queue, id: `q${i + 1}` })));
    expect(editor.full.value).toBe(true);
    editor.setTool("queue");
    editor.addPoint([0.2, 0.2]);
    expect(editor.drawing.value).toBeNull();
    const crossing = useZoneEditor([{ id: "f1", kind: "floor", points: [[0, 0], [1, 1], [1, 0], [0, 1]] }]);
    expect(crossing.crossing.value).toEqual(["f1"]);
  });

  it("knows its saved state again after a save", () => {
    const editor = useZoneEditor([queue]);
    editor.nudge(0, 0);
    editor.select({ zone: 0, point: null });
    editor.nudge(0.01, 0);
    expect(editor.dirty.value).toBe(true);
    editor.markSaved();
    expect(editor.dirty.value).toBe(false);
    expect(editor.payload.value[0]!.points[0]).toEqual([0.11, 0.5]);
  });
});
