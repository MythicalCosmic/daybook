// Equipment: the filters and flags, the stock by category, what the return dialog offers, the
// forms' payloads, and the page, the dialogs and Person 360's tab against a stubbed API.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import EquipmentPage from "../equipment/EquipmentPage.vue";
import EquipmentTab from "../equipment/EquipmentTab.vue";
import {
  addErrors,
  addPayload,
  confirmation,
  filterPeople,
  flagsOf,
  issueErrors,
  issuePayload,
  naturalOrder,
  previewNames,
  returnErrors,
  returnOptions,
  returnPayload,
  stockByCategory,
  type AddForm,
  type ReturnForm,
} from "../equipment/lib";
import type { EquipmentCan, EquipmentCategories, EquipmentPeople, EquipmentPersonPage, HeldItem, Holder, StockItem } from "../equipment/types";
import en from "../i18n/en.json";

vi.setConfig({ testTimeout: 20_000 });

beforeEach(() => {
  mergeModuleMessages("lifecycle", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

const coats = { id: 1, name: "Lab coats", icon: "shirt", kind: "low_value" as const };
const phones = { id: 2, name: "Phones", icon: "smartphone", kind: "fixed" as const };

function held(id: number, name: string, overrides: Partial<HeldItem> = {}): HeldItem {
  return {
    assignment_id: id,
    asset_id: 100 + id,
    number: `AV-${String(id).padStart(4, "0")}`,
    name,
    model: "",
    serial: "",
    notes: "",
    category: coats,
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    issued_on: "2026-11-01",
    condition_out: "good",
    note_out: "",
    acknowledged_at: "2026-11-01T10:00:00+05:00",
    photo_url: null,
    value: "190000.00",
    deduction: null,
    may_write_off: true,
    ...overrides,
  };
}

function holder(id: number, name: string, items: HeldItem[], overrides: Partial<Holder> = {}): Holder {
  return {
    person: { id, name, photo_url: null, position: "Farmatsevt", home_branch: { id: 1, name: "Chilonzor", code: "CHL" }, status: "approved" },
    leaving: null,
    left_on: null,
    items,
    value: "190000.00",
    unconfirmed: items.filter((item) => !item.acknowledged_at).length,
    overdue: 0,
    leaving_soon: false,
    ...overrides,
  };
}

const can: EquipmentCan = { values: true, devices: true, deduct: true, pay: true, register: true };

const people = (): EquipmentPeople => ({
  today: "2026-11-11",
  people: [
    holder(3, "Alisher Valiyev", [held(1, "Xalat №1"), held(2, "Beyj", { acknowledged_at: null, issued_on: "2026-11-02" })]),
    holder(5, "Jasur Tursunov", [held(3, "Kuryer skuteri", { category: phones, may_write_off: true })], { leaving: { id: 4, status: "agreed", day: "2026-11-20" }, leaving_soon: true }),
    holder(8, "Nodira Xolmatova", [held(4, "Xalat №2")], { person: { id: 8, name: "Nodira Xolmatova", photo_url: null, position: null, home_branch: null, status: "left" }, left_on: "2026-10-23", overdue: 1 }),
    holder(9, "Kamola Ergasheva", []),
  ],
  totals: { people: 3, items: 4, unconfirmed: 1, to_return: 2, value: "760000.00", in_stock: 3 },
  can,
});

function stock(id: number, name: string, overrides: Partial<StockItem> = {}): StockItem {
  return {
    id,
    number: `AV-${String(id).padStart(4, "0")}`,
    name,
    model: "",
    serial: "",
    notes: "48",
    category: coats,
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    status: "in_storage",
    condition: "new",
    value: "190000.00",
    holder: null,
    issued_on: null,
    acknowledged_at: null,
    photo_url: null,
    ...overrides,
  };
}

const categories: EquipmentCategories = {
  categories: [
    { ...coats, stock: 2, out: 2, may_add: true },
    { ...phones, stock: 1, out: 1, may_add: true },
  ],
  suggestions: [{ key: "badge", name: "Badges", kind: "low_value", icon: "id-card" }],
};

describe("equipment lists", () => {
  it("flags what needs doing and keeps those people first", () => {
    const rows = people().people;
    expect(rows.map(flagsOf)).toEqual([["unconfirmed"], ["leaving"], ["left"], ["empty"]]);
    const all = filterPeople(rows, { q: "", category: null, flags: [] });
    expect(all.map((row) => row.person.name)).toEqual(["Nodira Xolmatova", "Jasur Tursunov", "Alisher Valiyev", "Kamola Ergasheva"]);
    expect(filterPeople(rows, { q: "", category: null, flags: ["unconfirmed"] }).map((row) => row.person.id)).toEqual([3]);
    expect(filterPeople(rows, { q: "skuter", category: null, flags: [] }).map((row) => row.person.id)).toEqual([5]);
    expect(filterPeople(rows, { q: "AV-0004", category: null, flags: [] }).map((row) => row.person.id)).toEqual([8]);
    expect(filterPeople(rows, { q: "", category: 2, flags: [] }).map((row) => row.person.id)).toEqual([5]);
  });

  it("groups the stock by category in natural order (№2 before №10)", () => {
    const items = [stock(12, "Xalat №10"), stock(11, "Xalat №2"), stock(13, "Redmi", { category: phones, notes: "" })].sort(naturalOrder);
    expect(items.map((item) => item.name)).toEqual(["Redmi", "Xalat №2", "Xalat №10"]);
    const groups = stockByCategory(items, categories.categories);
    expect(groups.map((group) => [group.category.name, group.items.map((item) => item.name)])).toEqual([
      ["Lab coats", ["Xalat №2", "Xalat №10"]],
      ["Phones", ["Redmi"]],
    ]);
  });

  it("reads confirmation, and what the return dialog may offer", () => {
    expect(confirmation({ acknowledged_at: "2026-11-02T09:00:00+05:00", issued_on: "2026-11-01" }, "2026-11-11").state).toBe("confirmed");
    expect(confirmation({ acknowledged_at: null, issued_on: "2026-11-10" }, "2026-11-11").state).toBe("waiting");
    expect(confirmation({ acknowledged_at: null, issued_on: "2026-11-01" }, "2026-11-11")).toEqual({ state: "late", tone: "warning" });
    const [alisher, , nodira] = people().people;
    expect(returnOptions(alisher!, alisher!.items[0]!, can)).toEqual({ writeOff: true, deduct: true, deductWhy: null });
    expect(returnOptions(nodira!, nodira!.items[0]!, can)).toMatchObject({ deduct: false, deductWhy: "left" });
    expect(returnOptions(alisher!, held(9, "Beyj", { deduction: { id: 1, amount: null, currency: "UZS", status: "proposed" } }), can)).toMatchObject({ deduct: false, deductWhy: "open" });
    expect(returnOptions(alisher!, held(9, "Beyj", { deduction: { id: 1, amount: null, currency: "UZS", status: "rejected" } }), can).deduct).toBe(true);
    expect(returnOptions(alisher!, alisher!.items[0]!, { ...can, deduct: false })).toMatchObject({ deduct: false, deductWhy: "payroll" });
  });

  it("checks the forms and builds their bodies", () => {
    expect(issueErrors({ person: null, items: [], on: "2026-11-12", condition: "good", note: "", photo: null }, "2026-11-11")).toEqual({ person: "required", items: "required", on: "future" });
    const photo = new File(["x"], "coat.jpg", { type: "image/jpeg" });
    expect(issuePayload({ person: 3, items: [7, 8], on: "2026-11-11", condition: "new", note: "  48  ", photo })).toEqual({ person_id: 3, asset_ids: [7, 8], on: "2026-11-11", condition: "new", note: "48", photo });

    const back: ReturnForm = { outcome: "returned", on: "2026-11-11", condition: "damaged", note: " Yengi yirtilgan ", photo: null, writeOff: true, deduct: true, amount: "95000", reason: "" };
    expect(returnErrors(back, "2026-11-11")).toEqual({});
    expect(returnErrors({ ...back, amount: null }, "2026-11-11")).toEqual({ amount: "amount" });
    expect(returnPayload(back)).toEqual({ outcome: "returned", on: "2026-11-11", note: "Yengi yirtilgan", condition: "damaged", write_off: true, deduction: "95000" });
    // Lost: no condition, no photo, no write-off flag (it is the write-off).
    expect(returnPayload({ ...back, outcome: "lost", deduct: false })).toEqual({ outcome: "lost", on: "2026-11-11", note: "Yengi yirtilgan" });
    // A good one is never written off.
    expect(returnPayload({ ...back, condition: "good", deduct: false })).not.toHaveProperty("write_off");

    const add: AddForm = { category: 1, name: " Xalat ", quantity: 10, branch: 1, note: " 48–50 ", cost: null, serial: "", model: "" };
    expect(addErrors(add, false, true)).toEqual({});
    expect(addErrors({ ...add, quantity: 101, branch: null }, false, true)).toEqual({ quantity: "range", branch: "required" });
    expect(addErrors({ ...add, cost: null }, true, false)).toEqual({ cost: "amount" });
    expect(addPayload(add, false)).toEqual({ category_id: 1, name: "Xalat", quantity: 10, branch_id: 1, note: "48–50" });
    expect(addPayload({ ...add, quantity: 5, cost: "2400000", serial: " RM-1 ", model: "Redmi" }, true)).toEqual({ category_id: 1, name: "Xalat", quantity: 1, branch_id: 1, note: "48–50", cost: "2400000", serial: "RM-1", model: "Redmi" });
    expect(previewNames("Xalat", 3, 13)).toEqual(["Xalat №13", "Xalat №14", "Xalat №15"]);
    expect(previewNames("Telefon", 1)).toEqual(["Telefon"]);
  });
});

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(overrides: { people?: EquipmentPeople; person?: EquipmentPersonPage } = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = input.replace("/api/v1/owner/companies/1/", "");
      const raw = init?.body;
      const body = raw instanceof FormData ? Object.fromEntries([...raw.entries()].map(([k, v]) => [k, typeof v === "string" ? v : `file:${(v as File).name}`])) : raw ? JSON.parse(String(raw)) : undefined;
      calls.push({ method: init?.method ?? "GET", url, body });
      if (url.startsWith("lifecycle/equipment/items/")) return json([stock(21, "Xalat №3"), stock(22, "Xalat №4"), stock(23, "Redmi Note 13", { category: phones, serial: "RM-1188", notes: "" })]);
      if (url.startsWith("lifecycle/equipment/categories/")) return json(categories);
      if (url.startsWith("lifecycle/equipment/issue/") || url.includes("/return/") || url.includes("/deduction/")) return json(people().people[0]);
      if (url.startsWith("lifecycle/people/")) return json(overrides.person ?? personPage());
      if (url.startsWith("lifecycle/equipment/")) return json(overrides.people ?? people());
      return json({});
    }),
  );
  return calls;
}

const personPage = (): EquipmentPersonPage => ({
  today: "2026-11-11",
  holder: people().people[0]!,
  history: [
    { ...held(1, "Xalat №1"), returned_on: null, condition_in: "", note_in: "", photo_in_url: null, outcome: "held" },
    { ...held(7, "Xalat №7"), returned_on: "2026-10-01", condition_in: "worn", note_in: "Yengida dog‘", photo_in_url: null, outcome: "returned" },
    { ...held(6, "Beyj"), returned_on: "2026-09-12", condition_in: "", note_in: "", photo_in_url: null, outcome: "lost", deduction: { id: 3, amount: "50000.00", currency: "UZS", status: "approved" } },
  ],
  can,
});

async function mount(component: object, path: string, props: Record<string, unknown> = {}, features = ["hr", "assets", "payroll"]) {
  const app = await testApp(path);
  useSessionStore().me = me([company({ features })]);
  const { wrapper } = mountWithProviders(component, { plugins: app.plugins, props });
  await flushPromises();
  await flushPromises();
  return wrapper;
}

const body = () => document.body;
const buttonWith = (text: string) => [...body().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim().includes(text));

describe("the Equipment page", () => {
  it("lists who holds what with their flags, the numbers on top", async () => {
    stubApi();
    const wrapper = await mount(EquipmentPage, "/c/1/lifecycle/equipment");
    const rows = wrapper.findAll("[data-holder]");
    expect(rows.map((row) => row.attributes("data-holder"))).toEqual(["8", "5", "3", "9"]);
    expect(wrapper.find('[data-holder="8"]').text()).toContain("Left without handing 1 thing back");
    expect(wrapper.find('[data-holder="5"]').text()).toContain("1 thing to return before the last day");
    expect(wrapper.find('[data-holder="3"]').text()).toContain("1 not confirmed");
    expect(wrapper.find('[data-holder="3"] [data-items]').findAll("[data-item]")).toHaveLength(2);
    expect(wrapper.find('[data-holder="3"] [data-confirmed="false"]').exists()).toBe(true);
    expect(wrapper.find('[data-holder="9"]').text()).toContain(en["lifecycle.equipment.holdsNothing"]);
    // People who left can't be given anything.
    expect(wrapper.find('[data-holder="8"] [data-give]').exists()).toBe(false);
    expect(wrapper.find("[data-equipment-kpis]").text()).toContain(en["lifecycle.equipment.kpi.toReturn"]);
  });

  it("says the assets module is needed while it is off, and asks nothing of the server", async () => {
    const calls = stubApi();
    const wrapper = await mount(EquipmentPage, "/c/1/lifecycle/equipment", {}, ["hr"]);
    expect(wrapper.find("[data-assets-off]").text()).toContain(en["lifecycle.equipment.off.title"]);
    expect(calls.filter((call) => call.url.startsWith("lifecycle/equipment"))).toEqual([]);
  });

  it("gives a person two lab coats from the stock by count", async () => {
    const calls = stubApi();
    const wrapper = await mount(EquipmentPage, "/c/1/lifecycle/equipment");
    await wrapper.find('[data-holder="3"] [data-give]').trigger("click");
    await flushPromises();
    await flushPromises();
    expect(body().querySelector('[role="dialog"]')?.textContent).toContain("Give to Alisher Valiyev");
    const plus = body().querySelector<HTMLButtonElement>('[data-issue-group="1"] [data-more]')!;
    plus.click();
    await flushPromises();
    plus.click();
    await flushPromises();
    expect(body().querySelector('[data-issue-group="1"] [data-count]')?.textContent).toBe("2");
    expect(body().querySelector("[data-issue-chosen]")?.textContent).toContain("Xalat №3");
    body().querySelector<HTMLButtonElement>("[data-issue-submit]")!.click();
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.url).toBe("lifecycle/equipment/issue/");
    expect(post?.body).toMatchObject({ person_id: 3, asset_ids: [21, 22], condition: "good" });
  });

  it("takes back a damaged coat, writes it off and proposes a deduction", async () => {
    const calls = stubApi();
    const wrapper = await mount(EquipmentPage, "/c/1/lifecycle/equipment");
    await wrapper.find('[data-holder="3"] [data-item="1"]').trigger("click");
    await flushPromises();
    const item = [...body().querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) => el.textContent?.includes(en["lifecycle.equipment.action.returned"]));
    item!.click();
    await flushPromises();
    await flushPromises();
    expect(body().querySelector("[data-return-item]")?.textContent).toContain("Xalat №1");
    buttonWith(en["lifecycle.equipment.condition.damaged"])!.click();
    await flushPromises();
    body().querySelector<HTMLElement>("[data-write-off][role='switch'], [data-write-off] [role='switch']")!.click();
    await flushPromises();
    const deduction = body().querySelector("[data-deduction] [role='switch']") as HTMLElement;
    deduction.click();
    await flushPromises();
    body().querySelector<HTMLButtonElement>("[data-return-submit]")!.click();
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.url).toBe("lifecycle/equipment/handouts/1/return/");
    expect(post?.body).toMatchObject({ outcome: "returned", condition: "damaged", write_off: true, deduction: "190000.00" });
  });

  it("shows the stock by category with the suggestions on first use", async () => {
    stubApi();
    const wrapper = await mount(EquipmentPage, "/c/1/lifecycle/equipment?tab=items");
    await flushPromises();
    expect(wrapper.findAll("[data-stock-group]").map((group) => group.attributes("data-stock-group"))).toEqual(["1", "2"]);
    expect(wrapper.find('[data-stock-group="1"]').text()).toContain("Xalat №3");
    expect(wrapper.find('[data-stock-group="2"]').text()).toContain("S/N RM-1188");
  });
});

describe("Person 360's Equipment tab", () => {
  it("shows what they hold, confirmed or not, and what they were given before", async () => {
    stubApi();
    const wrapper = await mount(EquipmentTab, "/c/1/people/3/equipment", { memberId: 3 });
    expect(wrapper.findAll("[data-tab-item]")).toHaveLength(2);
    expect(wrapper.find('[data-tab-item="2"]').text()).toContain(en["lifecycle.equipment.notConfirmed"]);
    const history = wrapper.findAll("[data-history]");
    expect(history.map((row) => row.attributes("data-history"))).toEqual(["7", "6"]);
    expect(history[0]!.text()).toContain("came back Worn");
    expect(history[1]!.text()).toContain(en["lifecycle.equipment.deduction.status.approved"]);
    expect(wrapper.find("[data-tab-give]").exists()).toBe(true);
  });
});
