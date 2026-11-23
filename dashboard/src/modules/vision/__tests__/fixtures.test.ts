/**
 * The fixture pharmacy (fixture mode only) tells the story the live view is built to show: a queue
 * that builds into an alert and clears when a second pharmacist comes, then a customer waiting at an
 * empty counter until the "nobody at the counter" alert opens and ends. The frames it reports
 * follow the contract (normalized boxes, queue waits only inside the queue zone, roles).
 */
import { describe, expect, it } from "vitest";

import { pointInPolygon } from "../lib/geometry";
import { footPoint } from "../lib/tracks";
import { CYCLE, COUNTER_ZONES, bodiesAt, framePeople, incidents, simulateCounter, simulateEntrance, statsAt } from "../fixtures/sim";

const scene = simulateCounter(7);

describe("the fixture pharmacy", () => {
  it("raises a queue alert in the evening rush and clears it once a second pharmacist helps", () => {
    const queue = scene.incidents.find((incident) => incident.kind === "queue");
    expect(queue).toBeDefined();
    expect(queue!.start).toBeGreaterThan(120);
    expect(queue!.end).toBeLessThan(260);
    expect(queue!.peakQueue).toBeGreaterThanOrEqual(3);
    expect(queue!.peakWait).toBeGreaterThanOrEqual(120);
    // Two pharmacists at the counter by the time it clears.
    expect(statsAt(scene, queue!.end).staff).toBe(2);
    expect(queue!.ackAt).toBeGreaterThan(queue!.start);
  });

  it("then leaves the counter empty with a customer waiting, and that alert ends when someone comes back", () => {
    const empty = scene.incidents.find((incident) => incident.kind === "unattended");
    expect(empty).toBeDefined();
    expect(empty!.start).toBeGreaterThan(300);
    expect(empty!.end).toBeLessThan(CYCLE);
    expect(statsAt(scene, empty!.start).staff).toBe(0);
    expect(statsAt(scene, empty!.start).queue).toBeGreaterThan(0);
  });

  it("reports frames in the contract's shape", () => {
    const people = framePeople(scene, bodiesAt(scene, 200), 3);
    expect(people.length).toBeGreaterThan(2);
    const queueZone = COUNTER_ZONES.find((zone) => zone.kind === "queue")!;
    for (const person of people) {
      for (const value of person.box) expect(value).toBeGreaterThanOrEqual(0);
      expect(person.box[0] + person.box[2]).toBeLessThanOrEqual(1.0001);
      expect(person.box[1] + person.box[3]).toBeLessThanOrEqual(1.0001);
      expect(["customer", "staff"]).toContain(person.role);
      const foot = footPoint(person.box);
      if (person.wait_s !== null && person.wait_s !== undefined) expect(pointInPolygon([foot[0], Math.min(foot[1], 0.999)], queueZone.points)).toBe(true);
    }
    expect(people.some((person) => person.role === "staff")).toBe(true);
    // Track ids are stable within a cycle and change with the next one.
    const later = framePeople(scene, bodiesAt(scene, 200.5), 3);
    expect(later.some((person) => people.some((before) => before.track === person.track))).toBe(true);
    expect(framePeople(scene, bodiesAt(scene, 200), 4).every((person) => !people.some((before) => before.track === person.track))).toBe(true);
  });

  it("walks the counter's customers through the entrance before and after", () => {
    const entrance = simulateEntrance(scene, 9);
    expect(Math.max(...entrance.stats.map((s) => s.people))).toBeGreaterThan(0);
  });

  it("applies the rules with their hold and clear times", () => {
    const calm = { people: 1, queue: 1, staff: 1, wait: 10 };
    const busy = { people: 5, queue: 4, staff: 1, wait: 150 };
    // 4 s of a long queue is not enough (5 s are needed); 8 s are.
    expect(incidents([...Array(16).fill(busy), ...Array(200).fill(calm)])).toEqual([]);
    const found = incidents([...Array(32).fill(busy), ...Array(200).fill(calm)]);
    expect(found).toHaveLength(1);
    expect(found[0]!.kind).toBe("queue");
    // It ends 15 s after the queue calmed down.
    expect(found[0]!.end).toBeCloseTo(8 + 15 - 0.25, 1);
  });
});
