// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { json, manager, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { createDevice, createLink, faceKeys, ignoreNumber, listPeople, listScans, regenerate, saveSettings, simulate } from "../api";
import CatchupHint from "../components/CatchupHint.vue";
import HistoryNote from "../components/HistoryNote.vue";
import ScanItem from "../components/ScanItem.vue";
import SetupWizard from "../components/SetupWizard.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import { actionChip, catchupCommand, clockOf, freshIds, initials, peak, scanName } from "../lib";
import PeoplePage from "../pages/PeoplePage.vue";
import type { Device, DeviceHistory, KnownPerson, Scan, Setup } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("faceid", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const scan = (extra: Partial<Scan> = {}): Scan => ({
  id: 1,
  event_at: "2026-11-09T08:00:12+05:00",
  received_at: "2026-11-09T08:00:13+05:00",
  device: { id: 3, name: "Kirish" },
  branch: { id: 1, name: "Chilonzor", code: "CHL" },
  kind: "person",
  action: "checked_in",
  method: "face",
  verify_mode: "cardOrFaceOrFp",
  employee_no: "00000002",
  name_on_device: "Mushtariy",
  member: { id: 7, name: "Mushtariy Karimova", photo_url: null, position: { id: 1, name: "Farmatsevt" }, home_branch: null, status: "approved" },
  record: { id: 9, status: "open", check_in_at: "2026-11-09T08:00:12+05:00", check_out_at: null, is_late: false, late_minutes: 0, worked_minutes: 0 },
  flags: [],
  photo_url: "/api/v1/files/abc/",
  ...extra,
});

describe("module", () => {
  it("is its own switch, in People next to attendance, with attendance's permission", () => {
    expect(module.id).toBe("faceid");
    expect(module.feature).toBe("face_id");
    expect(module.group).toBe("people");
    expect(module.perm).toBe("attendance.view");
    expect(module.routes.map((route) => route.path)).toEqual(["faceid", "faceid/people", "faceid/terminals", "faceid/settings"]);
  });

  it("has every word in all three languages, plurals in the house shape", () => {
    const keys = Object.keys(en).sort();
    expect(Object.keys(uz).sort()).toEqual(keys);
    expect(Object.keys(ru).sort()).toEqual(keys);
    for (const dictionary of [en, uz, ru] as Record<string, string>[]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(value.trim(), key).not.toBe("");
        const forms = value.split(" | ");
        if (forms.length > 1) {
          expect(forms.length, key).toBe(3);
          const placeholders = forms.map((form) => [...form.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort().join(","));
          expect(new Set(placeholders).size, key).toBe(1);
        }
      }
    }
    // Uzbek uses ‘ and ’, never a straight apostrophe or a backtick.
    for (const value of Object.values(uz as Record<string, string>)) expect(value).not.toMatch(/[a-z]['`][a-z]/i);
  });
});

describe("api", () => {
  it("calls the Face ID endpoints with the right params and bodies", async () => {
    const calls = stubApi({
      "GET faceid/events/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "GET faceid/people/": () => json([]),
      "POST faceid/devices/": () => json({}, 201),
      "POST faceid/devices/3/regenerate/": () => json({}),
      "POST faceid/devices/3/simulate/": () => json({}, 201),
      "POST faceid/links/": () => json({}, 201),
      "POST faceid/people/ignore/": () => json({}, 201),
      "PATCH faceid/settings/": () => json({}),
    });
    await listScans(1, { date: "2026-11-09", action: ["not_linked"], branch: [], page_size: 100 });
    await listPeople(1, "0");
    await createDevice(1, { name: "Kirish", branch_id: 1, direction: "toggle" });
    await regenerate(1, 3);
    await simulate(1, 3);
    await createLink(1, "00000002", 7);
    await ignoreNumber(1, "00000044");
    await saveSettings(1, { telegram: "every_scan" });
    expect(calls.map((call) => `${call.method} ${call.url.replace("/api/v1/owner/companies/1/", "")}`)).toEqual([
      "GET faceid/events/?date=2026-11-09&action=not_linked&page_size=100",
      "GET faceid/people/?linked=0",
      "POST faceid/devices/",
      "POST faceid/devices/3/regenerate/",
      "POST faceid/devices/3/simulate/",
      "POST faceid/links/",
      "POST faceid/people/ignore/",
      "PATCH faceid/settings/",
    ]);
    expect(calls[2]!.body).toEqual({ name: "Kirish", branch_id: 1, direction: "toggle" });
    expect(calls[5]!.body).toEqual({ employee_no: "00000002", member_id: 7 });
    expect(faceKeys.scans(1, { date: "x" })[0]).toBe(1);
  });
});

describe("lib", () => {
  it("names, initials, chips and fresh rows", () => {
    expect(scanName(scan())).toBe("Mushtariy Karimova");
    expect(scanName(scan({ member: null }))).toBe("Mushtariy");
    expect(scanName(scan({ member: null, name_on_device: "" }))).toBe("00000002");
    expect(initials("Шахзодбек")).toBe("ША");
    expect(initials("Mushtariy Karimova")).toBe("MK");
    expect(actionChip(scan({ record: { ...scan().record!, is_late: true, late_minutes: 14 } }))).toEqual({ key: "faceid.action.late", minutes: 14 });
    expect(actionChip(scan({ action: "checked_out", record: { ...scan().record!, worked_minutes: 547 } }))).toEqual({ key: "faceid.action.left", minutes: 547 });
    expect(actionChip(scan({ flags: ["simulated"] })).key).toBe("faceid.action.test");
    expect(actionChip(scan({ action: "stranger" })).key).toBe("faceid.action.stranger");
    expect(clockOf("2026-11-09T08:00:12+05:00")).toBe("08:00");
    expect(peak([0, 0, 0])).toBe(1);
    expect(freshIds([1, 2], [{ id: 3 }, { id: 1 }])).toEqual([3]);
  });
});

describe("ScanItem", () => {
  it("shows who, where, when and what the scan did", async () => {
    const app = await testApp("/c/1/faceid");
    const { wrapper } = mountWithProviders(ScanItem, { props: { scan: scan({ record: { ...scan().record!, is_late: true, late_minutes: 14 } }) }, plugins: app.plugins });
    const text = wrapper.text();
    expect(text).toContain("Mushtariy Karimova");
    expect(text).toContain("Farmatsevt");
    expect(text).toContain("Kirish");
    expect(text).toContain("08:00");
    expect(text).toContain("Late 14m");
    expect(wrapper.find("img").attributes("src")).toBe("/api/v1/files/abc/");
  });

  it("an unknown face says so", async () => {
    const app = await testApp("/c/1/faceid");
    const { wrapper } = mountWithProviders(ScanItem, { props: { scan: scan({ kind: "stranger", action: "stranger", member: null, name_on_device: "", employee_no: "", record: null }) }, plugins: app.plugins });
    expect(wrapper.text()).toContain("Unknown face");
  });
});

describe("HistoryNote", () => {
  const history = { skipped: 40600, until: "2026-11-07T15:02:11+05:00", active: true, clock_hides: false };

  it("says the terminal sends its old history first, with the count so far", async () => {
    const app = await testApp("/c/1/faceid");
    const { wrapper } = mountWithProviders(HistoryNote, { props: { history }, plugins: app.plugins });
    expect(wrapper.text()).toContain("sending its old history first; live scans start when it's done");
    expect(wrapper.text()).toMatch(/Old scans skipped so far: 40.600 \(newest: 7 Nov 2026\)/);
  });

  it("is a quiet line once it stopped, a clock warning when the clock hides live scans, nothing before", async () => {
    const app = await testApp("/c/1/faceid");
    const done = mountWithProviders(HistoryNote, { props: { history: { ...history, active: false } }, plugins: app.plugins });
    expect(done.wrapper.text()).toContain("Only live scans are kept.");
    const clock = mountWithProviders(HistoryNote, { props: { history: { ...history, clock_hides: true } }, plugins: app.plugins });
    expect(clock.wrapper.text()).toContain("Set its date and time");
    expect(clock.wrapper.text()).not.toContain("sending its old history");
    const none = mountWithProviders(HistoryNote, { props: { history: { skipped: 0, until: null, active: false, clock_hides: false } }, plugins: app.plugins });
    expect(none.wrapper.text()).toBe("");
  });
});

describe("PeoplePage", () => {
  it("links a number to the closest name in one tap", async () => {
    const person: KnownPerson = {
      employee_no: "00000008",
      name_on_device: "Гулирано",
      first_at: "2026-11-09T08:01:00+05:00",
      last_at: "2026-11-09T08:01:00+05:00",
      scans: 1,
      device: { id: 3, name: "Kirish" },
      photo_url: null,
      member: null,
      link: null,
      suggestions: [
        { member: { id: 5, name: "Gulirano Saidova", photo_url: null, position: null, home_branch: null, status: "approved" }, score: 100, has_number: false },
      ],
    };
    const calls = stubApi({
      "GET faceid/people/": () => json([person]),
      "POST faceid/links/": () => json({ id: 1, employee_no: "00000008", member: person.suggestions[0]!.member, auto: false, ignored: false, created_at: "" }, 201),
    });
    const app = await testApp("/c/1/faceid/people");
    const { wrapper } = mountWithProviders(PeoplePage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).toContain("Гулирано");
    expect(wrapper.text()).toContain("Not in Daybook");
    const chip = wrapper.findAll("button").find((button) => button.text().includes("Gulirano Saidova"));
    await chip!.trigger("click");
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toEqual({ employee_no: "00000008", member_id: 5 });
    expect(toasts.at(-1)?.title).toContain("Gulirano Saidova");
  });
});

describe("Get today's scans now", () => {
  const history: DeviceHistory = { skipped: 40600, until: "2026-11-07T15:02:11+05:00", active: true, clock_hides: false };
  const terminal = { id: 3, ip: "192.168.1.250" };
  const COMMAND = "HIK_PASS=… python3 catchup.py --terminal 192.168.1.250";

  const device = (extra: Partial<Device> = {}): Device => ({
    id: 3,
    name: "Kirish",
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    direction: "toggle",
    enabled: true,
    vendor: "hikvision",
    model: "DS-K1T341AMF",
    ip: "192.168.1.250",
    mac: "e8:a0:ed:12:34:56",
    status: "online",
    last_seen_at: "2026-11-10T09:00:00+05:00",
    last_event_at: null,
    heartbeats: true,
    clock_offset_s: 0,
    clock_off: false,
    scans_today: 0,
    hourly: Array(24).fill(0),
    last_scan: null,
    history,
    created_at: "2026-11-10T08:00:00+05:00",
    ...extra,
  });

  const setup = (extra: Partial<Setup> = {}): Setup => ({
    host: "davomat.example.uz",
    addressing: "hostname",
    path: "/api/v1/devices/hik/abcdefghijklmnopqrstuvwx/",
    recommended: "https",
    heartbeat_minutes: 5,
    http: { port: 80, url: "http://davomat.example.uz/api/v1/devices/hik/abcdefghijklmnopqrstuvwx/" },
    https: { port: 443, url: "https://davomat.example.uz/api/v1/devices/hik/abcdefghijklmnopqrstuvwx/" },
    ip: "192.168.1.250",
    last_event_at: null,
    last_seen_at: "2026-11-10T09:00:00+05:00",
    last_test_at: null,
    history,
    ...extra,
  });

  /** Opens the wizard on a terminal and goes to its last step ("First scan"). */
  async function lastStep(values: Setup) {
    stubApi({ "GET faceid/devices/3/setup/": () => json(values) });
    const app = await testApp("/c/1/faceid/terminals");
    return app;
  }

  async function openWizard(app: Awaited<ReturnType<typeof testApp>>) {
    const mounted = mountWithProviders(SetupWizard, { props: { open: true, device: device() }, plugins: app.plugins });
    await flushPromises();
    [...document.querySelectorAll("button")].find((button) => button.textContent?.includes("I typed them in"))!.click();
    await flushPromises();
    return mounted;
  }

  it("runs the helper next to the file, with the terminal's address, Windows' way too", () => {
    expect(catchupCommand("192.168.1.250")).toBe(COMMAND);
    expect(catchupCommand(" 10.0.0.7 ", "windows")).toBe("py catchup.py --terminal 10.0.0.7");
  });

  it("folds under the terminal's history note while the old scans come", async () => {
    const app = await testApp("/c/1/faceid/terminals");
    const { wrapper } = mountWithProviders(HistoryNote, { props: { history, catchup: terminal }, plugins: app.plugins });
    const toggle = wrapper.find("button[aria-expanded]");
    expect(toggle.text()).toBe("Get today's scans now");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find('[data-testid="catchup-command"]').isVisible()).toBe(false);
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="catchup-command"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="catchup-command"]').text()).toBe(COMMAND);
    expect(wrapper.text()).toContain("a small helper on a computer in the terminal's network sends them straight away");
    expect(wrapper.text()).toContain("On Windows: py catchup.py --terminal 192.168.1.250, then type the terminal's password.");
    expect(wrapper.text()).toContain("It stops by itself when the terminal catches up.");
    // The history note itself still says what it said.
    expect(wrapper.text()).toContain("sending its old history first");
  });

  it("isn't offered without a terminal to manage, once the old scans stopped, or when the clock hides scans", async () => {
    const app = await testApp("/c/1/faceid/terminals");
    for (const props of [{ history }, { history: { ...history, active: false }, catchup: terminal }, { history: { ...history, clock_hides: true }, catchup: terminal }]) {
      const { wrapper } = mountWithProviders(HistoryNote, { props, plugins: app.plugins });
      expect(wrapper.text()).not.toContain("Get today's scans now");
    }
  });

  it("says where the address goes when the terminal hasn't said its own yet", async () => {
    const app = await testApp("/c/1/faceid/terminals");
    const { wrapper } = mountWithProviders(CatchupHint, { props: { deviceId: 3, ip: "" }, plugins: app.plugins });
    expect(wrapper.find('[data-testid="catchup-command"]').text()).toBe("HIK_PASS=… python3 catchup.py --terminal TERMINAL-ADDRESS");
  });

  it("downloads catchup.py filled in for the terminal and copies the command", async () => {
    const calls = stubApi({ "GET faceid/devices/3/catchup/": () => new Response('DEVICE_URL = "https://x"\n', { status: 200, headers: { "Content-Type": "text/x-python" } }) });
    const saved: string[] = [];
    const { createObjectURL, revokeObjectURL } = URL;
    URL.createObjectURL = () => "blob:catchup";
    URL.revokeObjectURL = () => undefined;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    try {
      const app = await testApp("/c/1/faceid/terminals");
      const { wrapper } = mountWithProviders(CatchupHint, { props: { deviceId: 3, ip: "192.168.1.250" }, plugins: app.plugins });
      expect(wrapper.text()).toContain("Get today's scans now");
      await wrapper.find('[data-testid="catchup-download"]').trigger("click");
      await vi.waitFor(() => expect(saved).toEqual(["catchup.py"]));
      expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual(["GET /api/v1/owner/companies/1/faceid/devices/3/catchup/"]);
      await wrapper.find('[data-testid="catchup-copy"]').trigger("click");
      await flushPromises();
      expect(writeText).toHaveBeenCalledWith(COMMAND);
      expect(wrapper.find('[data-testid="catchup-copy"]').attributes("aria-label")).toBe("Copied");
    } finally {
      click.mockRestore();
      URL.createObjectURL = createObjectURL;
      URL.revokeObjectURL = revokeObjectURL;
    }
  });

  it("opens in the wizard's last step while the terminal sends its old history", async () => {
    const app = await lastStep(setup());
    const { wrapper } = await openWizard(app);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Connected: old history first");
    expect(text).toContain("Get today's scans now");
    expect(text).toContain("It stops by itself when the terminal catches up.");
    expect(document.querySelector('[data-testid="catchup-command"]')?.textContent).toBe(COMMAND);
    expect(document.querySelector("button[aria-expanded]")).toBeNull(); // open, not folded
    wrapper.unmount();
  });

  it("isn't in the wizard once the first live scan came, nor for someone who only sees attendance", async () => {
    const live = await lastStep(setup({ last_event_at: "2026-11-10T09:01:00+05:00" }));
    const first = await openWizard(live);
    expect(document.body.textContent).toContain("Connected");
    expect(document.body.textContent).not.toContain("Get today's scans now");
    first.wrapper.unmount();
    document.body.innerHTML = "";

    const app = await lastStep(setup());
    useSessionStore().me = me([manager(["dashboard.access", "attendance.view"], { id: 1 })]);
    useCompanyStore().setCurrent(1);
    const second = await openWizard(app);
    expect(document.body.textContent).toContain("Connected: old history first");
    expect(document.body.textContent).not.toContain("Get today's scans now");
    second.wrapper.unmount();
  });
});
