// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SelectBox from "@/components/SelectBox.vue";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import DayRoutineCard from "../components/DayRoutineCard.vue";
import RoutineEditor from "../components/RoutineEditor.vue";
import RunReadings from "../components/RunReadings.vue";
import StoragePresetDialog from "../components/StoragePresetDialog.vue";
import en from "../i18n/en.json";
import module from "../index";
import { backInRangeAt, fromDrafts, presetSpecs, rangeText, readingNumber, stillOut, toDraft, valueText } from "../readings";
import { inRange, readingsOption } from "../readingsChart";
import type { DayRoutine, ReadingTaken, Routine } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const settings = {
  storage_fridge_min: "2.0",
  storage_fridge_max: "8.0",
  storage_room_min: "15.0",
  storage_room_max: "25.0",
  storage_humidity_max: "60.0",
  storage_times: ["09:00", "20:00"],
};
const options = { people: [{ id: 11, name: "Alisher Valiyev", photo_url: null, position: "Pharmacist", branch: "Chilonzor", branch_id: 1, position_id: 3 }], positions: [{ id: 3, name: "Pharmacist" }], routines: [], policies: [] };

const reading = (overrides: Partial<ReadingTaken> = {}): ReadingTaken => ({
  id: 1,
  key: "t",
  label: "Fridge 1",
  unit: "°C",
  value: "5.20",
  min: "2.00",
  max: "8.00",
  in_range: true,
  note: "",
  is_recheck: false,
  recorded_at: "2026-11-06T04:05:00Z",
  recorded_by: { id: 11, name: "Alisher Valiyev" },
  ...overrides,
});

beforeEach(() => {
  mergeModuleMessages("routines", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("reading words", () => {
  it("writes values and ranges as a pharmacist reads them", () => {
    expect(readingNumber("5.20", "en")).toBe("5.2");
    expect(readingNumber("5.20", "uz")).toBe("5,2");
    expect(readingNumber("8.00", "ru")).toBe("8");
    expect(valueText("5.20", "°C", "uz")).toBe("5,2 °C");
    expect(rangeText("2.0", "8.0", "°C", "en")).toBe("2–8 °C");
    expect(rangeText(null, "60.0", "%", "en")).toBe("≤ 60 %");
    expect(rangeText("15.0", null, "°C", "ru")).toBe("≥ 15 °C");
    expect(rangeText(null, null, "°C", "en")).toBe("");
  });

  it("knows a run is back in range only when a recheck brought every value back", () => {
    const out = reading({ value: "8.9", in_range: false, note: "Door left open" });
    const back = reading({ id: 2, value: "5.6", is_recheck: true, recorded_at: "2026-11-06T04:40:00Z" });
    expect(stillOut([out])).toBe(true);
    expect(backInRangeAt([out])).toBeNull();
    expect(stillOut([out, back])).toBe(false);
    expect(backInRangeAt([out, back])).toBe("2026-11-06T04:40:00Z");
    expect(backInRangeAt([reading()])).toBeNull(); // nothing was out
  });

  it("turns the editor's rows into specs, refusing a nameless one or a range upside down", () => {
    expect(fromDrafts([{ label: " Fridge 1 ", unit: "°C", min: 2, max: 8, critical: true }])).toEqual({
      specs: [{ label: "Fridge 1", unit: "°C", min: "2", max: "8", critical: true }],
      problem: null,
    });
    expect(fromDrafts([{ label: "", unit: "°C", min: 2, max: 8, critical: false }]).problem).toBe("label");
    expect(fromDrafts([{ label: "Room", unit: "°C", min: 25, max: 15, critical: false }]).problem).toBe("range");
    expect(toDraft({ key: "h", label: "Humidity", unit: "%", min: null, max: "60.0", critical: false })).toEqual({ key: "h", label: "Humidity", unit: "%", min: null, max: 60, critical: false });
  });

  it("starts the quick-add rows from Settings → Routines", () => {
    const rows = presetSpecs({ ...settings, storage_fridge_min: "2.5" }, { fridge: "Fridge", room: "Room", humidity: "Humidity" });
    expect(rows.fridge).toMatchObject({ unit: "°C", min: 2.5, max: 8, critical: true });
    expect(rows.humidity).toMatchObject({ unit: "%", min: null, max: 60, critical: false });
  });
});

describe("the journal chart", () => {
  const theme = {
    text: "#000",
    muted: "#666",
    subtle: "#999",
    border: "#ddd",
    surface: "#fff",
    surface2: "#eee",
    primary: "#a85a27",
    success: "#5f7a45",
    warning: "#a8701c",
    danger: "#b3412e",
    info: "#4a6a8a",
    series: ["#c67139"],
    compare: "#8c857a",
    fontFamily: "sans-serif",
    dark: false,
  };

  it("draws the allowed band, both bounds and the excursions in the danger colour", () => {
    const option = readingsOption(theme, {
      days: ["2026-11-01", "2026-11-02", "2026-11-03"],
      values: [5.2, 8.9, null],
      min: 2,
      max: 8,
      label: "Fridge 1",
      unit: "°C",
      lang: "en",
      words: { out: "Out of range", allowed: "Allowed" },
    }) as { series: Array<{ name: string; stack?: string; data: unknown[]; markLine?: { data: Array<{ yAxis: number }> } }> };
    const [base, band, line] = option.series;
    expect(base!.stack).toBe("band");
    expect(band!.data).toEqual([6, 6, 6]);
    expect(line!.markLine!.data).toEqual([{ yAxis: 2 }, { yAxis: 8 }]);
    expect(line!.data[0]).toEqual({ value: 5.2 });
    expect(line!.data[1]).toMatchObject({ value: 8.9, itemStyle: { color: theme.danger } });
    expect(line!.data[2]).toBeNull();
    expect(inRange(60, null, 60)).toBe(true);
    expect(inRange(61, null, 60)).toBe(false);
  });

  it("draws no band for a maximum alone (humidity), only its line", () => {
    const option = readingsOption(theme, { days: ["2026-11-01"], values: [45], min: null, max: 60, label: "Humidity", unit: "%", lang: "en", words: { out: "Out", allowed: "Allowed" } }) as { series: unknown[] };
    expect(option.series).toHaveLength(1);
  });
});

describe("RunReadings", () => {
  it("shows the values, out of range in the danger tone, the recheck after it and the note", async () => {
    const app = await testApp("/c/1/routines", "uz");
    const { wrapper } = mountWithProviders(RunReadings, {
      plugins: app.plugins,
      props: {
        readings: [
          reading({ value: "8.9", in_range: false, note: "Door left open" }),
          reading({ id: 2, value: "5.6", is_recheck: true, recorded_at: "2026-11-06T04:40:00Z" }),
          reading({ id: 3, key: "h", label: "Humidity", unit: "%", value: "48", min: null, max: "60" }),
        ],
      },
    });
    const chips = wrapper.findAll("[data-in-range]");
    expect(chips).toHaveLength(2);
    expect(chips[0]!.attributes("data-in-range")).toBe("false");
    expect(chips[0]!.text()).toContain("8,9 °C"); // a decimal comma in Uzbek
    expect(chips[0]!.text()).toContain("→ 5,6 °C");
    expect(chips[1]!.text()).toContain("48 %");
    expect(wrapper.text()).toContain("Door left open");
  });
});

describe("the routine editor", () => {
  it("offers Readings, adds a fridge from the company's ranges and saves them as specs", async () => {
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET tasks/settings/": () => json({ on_finish: "auto", auto_accept_after_hours: null }),
      "GET routines/settings/": () => json(settings),
      "POST routines/": (call) => json({ id: 40, title: "Fridge", ...(call.body as object), assignees: [], positions: [], branch: null, next_run: null, today: null }, 201),
    });
    const app = await testApp("/c/1/routines/all");
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    const title = document.body.querySelector<HTMLInputElement>("input[type=text], input:not([type])")!;
    title.value = "Fridge, morning";
    title.dispatchEvent(new Event("input"));
    // Pick the readings proof.
    const proof = wrapper.findAllComponents(SelectBox).find((select) => (select.props() as { options: Array<{ value: unknown }> }).options.some((option) => option.value === "readings"));
    expect(proof).toBeTruthy();
    proof!.vm.$emit("update:modelValue", "readings");
    await flushPromises();
    expect(document.body.querySelector("[data-testid=specs-editor]")).toBeTruthy();
    // Without a reading it isn't saved.
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Create")!.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Add at least one reading.");
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Fridge")!.click();
    await flushPromises();
    expect(document.body.querySelectorAll("[data-spec]")).toHaveLength(1);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    wrapper.unmount();
  });

  it("never offers Readings for an onboarding template", async () => {
    stub({ "GET tasks/options/": () => json(options), "GET tasks/settings/": () => json({ on_finish: "auto", auto_accept_after_hours: null }) });
    const app = await testApp("/c/1/routines/onboarding");
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true, onboarding: true } });
    await flushPromises();
    const values = wrapper.findAllComponents(SelectBox).flatMap((select) => (select.props() as { options: Array<{ value: unknown }> }).options.map((option) => option.value));
    expect(values).toContain("photo");
    expect(values).not.toContain("readings");
    expect(document.body.querySelector("[data-testid=shared]")).toBeNull();
    wrapper.unmount();
  });

  it("sends the specs and the shared switch of a readings routine", async () => {
    const existing: Routine = {
      id: 41,
      title: "Fridge 1: temperature, 09:00",
      description: "",
      weekdays: [0, 1, 2, 3, 4, 5, 6],
      due_time: "09:00:00",
      starts_on: null,
      is_active: true,
      onboarding: false,
      due_after_days: 1,
      proof: "readings",
      readings: [{ key: "t", label: "Fridge 1 temperature", unit: "°C", min: "2.0", max: "8.0", critical: true }],
      shared: true,
      needs_confirmation: false,
      checklist: [],
      branch: { id: 1, name: "Chilonzor", code: "CHL" },
      assignees: [],
      positions: [{ id: 3, name: "Pharmacist" }],
      reminder_policy: null,
      escalate_to: null,
      stats: null,
      next_run: null,
      today: null,
      created_at: "2026-09-01T08:00:00Z",
    };
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET tasks/settings/": () => json({ on_finish: "auto", auto_accept_after_hours: null }),
      "GET routines/settings/": () => json(settings),
      "GET routines/41/preview/": () => json({ day: "2026-11-07", due: true, holiday: false, reason: null, due_at: "2026-11-07T04:00:00Z", next_run: null, people: [] }),
      "PATCH routines/41/": (call) => json({ ...existing, ...(call.body as object) }),
    });
    const app = await testApp("/c/1/routines/41");
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true, routine: existing } });
    await flushPromises();
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Save")!.click();
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toMatchObject({
      proof: "readings",
      shared: true,
      readings: [{ key: "t", label: "Fridge 1 temperature", unit: "°C", min: "2", max: "8", critical: true }],
    });
    wrapper.unmount();
  });
});

describe("the storage preset", () => {
  it("starts from the branch's defaults and sets it up in one call", async () => {
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET routines/storage-preset/": () =>
        json({ branch: { id: 1, name: "Chilonzor", code: "CHL" }, fridges: 1, times: ["09:00", "20:00"], positions: [{ id: 3, name: "Pharmacist" }], fridge: { min: "2.0", max: "8.0" }, room: { min: "15.0", max: "25.0" }, humidity_max: "60.0", existing: 0 }),
      "POST routines/storage-preset/": () => json({ created: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }, { id: 6 }, { id: 7 }], existing: [] }, 201),
    });
    const app = await testApp("/c/1/routines/all");
    const { wrapper } = mountWithProviders(StoragePresetDialog, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    const plan = document.body.querySelector("[data-testid=preset-plan]")!.textContent!;
    expect(plan).toContain("09:00");
    expect(plan).toContain("Fridge 1");
    expect(document.body.textContent).toContain("2–8 °C");
    expect(document.body.textContent).toContain("≤ 60 %");
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Set up")!.click();
    await flushPromises();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ branch: 1, fridges: 1, positions: [3], times: ["09:00", "20:00"] });
    expect(toasts.at(-1)?.title).toBe("7 routines made");
    wrapper.unmount();
  });

  it("is reached from All routines, the palette and the Get started step", () => {
    const command = module.commands?.({ t: (key: string) => key, go: vi.fn() } as never).find((entry) => entry.id === "routines.storage");
    expect(command?.perm).toBe("tasks.templates");
    expect(module.settings?.map((panel) => panel.id)).toEqual(["routines"]);
  });
});

describe("a day's routine card", () => {
  it("counts the day's values out of range", async () => {
    const row: DayRoutine = {
      routine: { id: 41, title: "Fridge 1: temperature, 09:00", due_time: "09:00", branch: null, proof: "readings", needs_confirmation: false, is_active: true, shared: true },
      due_at: "2026-11-06T04:00:00Z",
      reason: null,
      next_run: null,
      give: null,
      progress: { finished: 1, total: 1, percent: 100 },
      counts: { done: 1, review: 0, late: 0, missed: 0, returned: 0, open: 0, cancelled: 1, skipped: 0, excursions: 1 },
      runs: [],
      skipped: [],
    };
    const app = await testApp("/c/1/routines");
    // The card links to the routine's page by name, inside the company.
    app.router.addRoute({ name: "routines.today", path: "/c/:companyId/routines", component: { render: () => null } });
    app.router.addRoute({ name: "routines.detail", path: "/c/:companyId/routines/:id", component: { render: () => null } });
    await app.router.replace("/c/1/routines");
    const { wrapper } = mountWithProviders(DayRoutineCard, { plugins: app.plugins, props: { row, day: "2026-11-06" } });
    await flushPromises();
    expect(wrapper.text()).toContain("1 out of range");
    expect(wrapper.text()).toContain("One of us does it");
    expect(wrapper.text()).toContain("Readings");
    wrapper.unmount();
  });
});
