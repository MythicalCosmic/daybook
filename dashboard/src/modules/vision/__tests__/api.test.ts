/** The endpoints Ko‘z calls (docs/KOZ.md §6): paths, parameters and bodies, and a 204 frame. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json } from "@/test/fixtures";

import { createAgent, createClip, deleteAgent, getFrame, getLive, getOverview, getReview, listAlerts, listCameras, newPairing, requestSnapshot, saveSettings, updateCamera } from "../api";
import { FIXTURES } from "../mode";

let calls: Array<{ url: string; method: string; body: unknown }>;
let reply: Response | (() => Response);

beforeEach(() => {
  calls = [];
  reply = json({});
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return typeof reply === "function" ? reply() : reply.clone();
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const base = "/api/v1/owner/companies/1/vision/";

describe("the Ko‘z API", () => {
  it("never answers from fixtures outside the dev server's fixture mode", () => {
    expect(FIXTURES).toBe(false);
  });

  it("reads the overview, live numbers, cameras and the review with their filters", async () => {
    await getOverview(1, { branch: 2, day: "2026-11-20" });
    await getOverview(1, { branch: null, day: null });
    await getLive(1, 2);
    await listCameras(1, null);
    await getReview(1, { day: "2026-11-23" });
    expect(calls.map((c) => c.url)).toEqual([
      `${base}overview/?branch=2&day=2026-11-20`,
      `${base}overview/`,
      `${base}live/?branch=2`,
      `${base}cameras/`,
      `${base}review/?day=2026-11-23`,
    ]);
  });

  it("pages alerts and passes the filters as the API names them", async () => {
    reply = json({ count: 0, next: null, previous: null, results: [] });
    await listAlerts(1, { branch: 1, state: "open", kind: "queue", from: "2026-11-01", to: "2026-11-23", page: 2, page_size: 50 });
    expect(calls[0]!.url).toBe(`${base}alerts/?branch=1&state=open&kind=queue&from=2026-11-01&to=2026-11-23&page=2&page_size=50`);
  });

  it("gives null for a camera with no fresh frame yet (204)", async () => {
    reply = () => new Response(null, { status: 204 });
    expect(await getFrame(1, 11)).toBeNull();
    expect(calls[0]!.url).toBe(`${base}cameras/11/frame/`);
  });

  it("writes cameras, zones, snapshots, settings and boxes", async () => {
    await updateCamera(1, 11, { zones: [{ id: "q1", kind: "queue", points: [[0, 0], [1, 0], [1, 1]] }], register_id: 2 });
    await requestSnapshot(1, 11);
    await saveSettings(1, { queue_people: 4 });
    await createAgent(1, { name: "Chilonzor qutisi", branch_id: 1 });
    await newPairing(1, 4);
    reply = () => new Response(null, { status: 204 });
    await deleteAgent(1, 4);
    expect(calls.map((c) => `${c.method} ${c.url.slice(base.length)}`)).toEqual(["PATCH cameras/11/", "POST cameras/11/snapshot/", "PATCH settings/", "POST agents/", "POST agents/4/pairing/", "DELETE agents/4/"]);
    expect(calls[0]!.body).toEqual({ zones: [{ id: "q1", kind: "queue", points: [[0, 0], [1, 0], [1, 1]] }], register_id: 2 });
    expect(calls[3]!.body).toEqual({ name: "Chilonzor qutisi", branch_id: 1 });
  });

  it("asks a sale's or a moment's clip on clips/, an alert's on the alert", async () => {
    await createClip(1, { sale_id: 991 });
    await createClip(1, { camera_id: 11, at: "2026-11-23T16:31:00Z", before_s: 10, after_s: 5 });
    await createClip(1, { alert_id: 123 });
    expect(calls.map((c) => `${c.method} ${c.url.slice(base.length)}`)).toEqual(["POST clips/", "POST clips/", "POST alerts/123/clip/"]);
    expect(calls[0]!.body).toEqual({ sale_id: 991 });
  });
});
