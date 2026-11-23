/**
 * Pieces of the live view and the sales Video button: the counters turn amber past the queue rule
 * and red with customers and nobody at the counter, the banner puts "nobody at the counter" first
 * and says who is going, and Sales › Receipts gets Video only with the module on and `vision.video`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "@/core/modules";
import { extensionsFor } from "@/core/extensions";
import { mergeModuleMessages } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, manager, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import AlertBanner from "../components/AlertBanner.vue";
import LiveCounters from "../components/LiveCounters.vue";
import SaleVideoButton from "../components/SaleVideoButton.vue";
import en from "../i18n/en.json";
import type { Alert, Live, LiveCamera } from "../types";

const camera = (extra: Partial<LiveCamera> = {}): LiveCamera => ({ id: 11, name: "Kassa 1", role: "counter", branch_id: 1, online: true, stale: false, people: 3, queue: 2, staff: 1, wait_s: 45, fps: 2, ...extra });
const live = (cameras: LiveCamera[]): Live => ({ at: "2026-11-23T16:31:05Z", today: { visitors: 47, receipts: 31 }, cameras, open_alerts: [] });
const alert = (extra: Partial<Alert> = {}): Alert => ({
  id: 1,
  kind: "queue",
  state: "open",
  branch: { id: 1, name: "Chilonzor" },
  camera: { id: 11, name: "Kassa 1" },
  started_at: new Date(Date.now() - 95_000).toISOString(),
  resolved_at: null,
  duration_s: 95,
  peak_queue: 4,
  peak_wait_s: 150,
  acknowledged_by: null,
  acknowledged_at: null,
  photo_url: null,
  clip: null,
  ...extra,
});

beforeEach(() => mergeModuleMessages("vision", { en }));
afterEach(() => vi.unstubAllGlobals());

describe("the live counters", () => {
  it("count today's visitors with how many bought, and sum the counter cameras", async () => {
    const app = await testApp("/c/1/vision/live");
    const { wrapper } = mountWithProviders(LiveCounters, {
      props: { live: live([camera({ queue: 2, staff: 1, wait_s: 45 }), camera({ id: 12, queue: 1, staff: 0, wait_s: 20 }), camera({ id: 13, role: "entrance", queue: null, staff: null, wait_s: null })]), liveAt: Date.now(), queuePeople: 3, queueWaitS: 120 },
      plugins: app.plugins,
    });
    const tile = (id: string) => wrapper.find(`[data-counter="${id}"]`);
    expect(tile("visitors").text()).toContain("47");
    expect(tile("visitors").text()).toContain("31 bought");
    expect(tile("queue").text()).toContain("3");
    expect(tile("queue").attributes("data-tone")).toBe("warning");
    expect(tile("staff").text()).toContain("1");
    expect(tile("wait").text()).toContain("0:45");
    expect(tile("wait").attributes("data-tone")).toBe("neutral");
    wrapper.unmount();
  });

  it("turn red when customers wait and nobody stands at the counter", async () => {
    const app = await testApp("/c/1/vision/live");
    const { wrapper } = mountWithProviders(LiveCounters, {
      props: { live: live([camera({ queue: 2, staff: 0, wait_s: 130 })]), liveAt: Date.now(), queuePeople: 3, queueWaitS: 120 },
      plugins: app.plugins,
    });
    expect(wrapper.find('[data-counter="staff"]').attributes("data-tone")).toBe("danger");
    expect(wrapper.find('[data-counter="staff"]').text()).toContain("Customers wait, nobody serves");
    expect(wrapper.find('[data-counter="wait"]').attributes("data-tone")).toBe("danger");
    wrapper.unmount();
  });

  it("say what is missing without a counter camera or an entrance", async () => {
    const app = await testApp("/c/1/vision/live");
    const { wrapper } = mountWithProviders(LiveCounters, {
      props: { live: { ...live([camera({ role: "floor" })]), today: { visitors: null, receipts: 12 } }, liveAt: Date.now(), queuePeople: 3, queueWaitS: 120 },
      plugins: app.plugins,
    });
    expect(wrapper.find('[data-counter="visitors"]').text()).toContain("No entrance camera");
    expect(wrapper.find('[data-counter="queue"]').text()).toContain("—");
    expect(wrapper.find('[data-counter="queue"]').text()).toContain("No counter camera");
    wrapper.unmount();
  });
});

describe("the alert banner", () => {
  it("puts nobody at the counter first, with the live wait and who is going", async () => {
    const app = await testApp("/c/1/vision/live");
    const { wrapper } = mountWithProviders(AlertBanner, {
      props: {
        alerts: [alert({ id: 1 }), alert({ id: 2, kind: "unattended", acknowledged_by: { id: 9, name: "Madina Yusupova" } }), alert({ id: 3, state: "resolved" })],
        cameras: [camera({ queue: 3, wait_s: 75 })],
        liveAt: Date.now(),
        canVideo: true,
      },
      plugins: app.plugins,
    });
    const banners = wrapper.findAll("[data-alert]");
    expect(banners.map((b) => b.attributes("data-alert"))).toEqual(["2", "1"]);
    expect(banners[0]!.text()).toContain("Nobody at the counter · Kassa 1 (Chilonzor)");
    expect(banners[0]!.text()).toContain("Madina Yusupova is going");
    expect(banners[1]!.text()).toContain("3 waiting, the longest for 1:15");
    expect(banners[1]!.text()).toMatch(/1:3\d/);
    wrapper.unmount();
  });
});

describe("the sales Video button", () => {
  async function asMember(features: string[], perms: string[] | "owner") {
    const app = await testApp("/c/1/sales/entries");
    const session = useSessionStore();
    session.me = me([perms === "owner" ? company({ features: features as never }) : manager(perms as never, { id: 1, features: features as never })]);
    useCompanyStore().setCurrent(1);
    return app;
  }

  it("fills the receipts slot only with the Ko‘z switch on", async () => {
    await asMember(["sales"], "owner");
    expect(extensionsFor("sales.entry.actions", useCompanyStore().current).map((e) => e.moduleId)).toEqual([]);
    await asMember(["sales", "vision"], "owner");
    expect(extensionsFor("sales.entry.actions", useCompanyStore().current).map((e) => e.moduleId)).toEqual(["vision"]);
  });

  it("shows Video only to someone who may watch the cameras", async () => {
    const viewer = await asMember(["sales", "vision"], ["vision.view", "sales.view"]);
    const hidden = mountWithProviders(SaleVideoButton, { props: { context: { entry: { id: 5, number: "BUY-1097" } } }, plugins: viewer.plugins });
    expect(hidden.wrapper.find("[data-sale-video]").exists()).toBe(false);
    hidden.wrapper.unmount();
    const watcher = await asMember(["sales", "vision"], ["vision.view", "vision.video", "sales.view"]);
    const shown = mountWithProviders(SaleVideoButton, { props: { context: { entry: { id: 5, number: "BUY-1097" } } }, plugins: watcher.plugins });
    expect(shown.wrapper.find("[data-sale-video]").attributes("aria-label")).toBe("Video of receipt BUY-1097");
    shown.wrapper.unmount();
  });
});
