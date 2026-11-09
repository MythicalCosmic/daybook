// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import FileDrop from "@/components/FileDrop.vue";
import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { toasts } from "@/components/useToast";
import { i18n, mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import EmployeeDrawer from "../components/team/EmployeeDrawer.vue";
import FaceNumbersInput from "../components/team/FaceNumbersInput.vue";
import ImportDialog from "../components/team/ImportDialog.vue";
import TodayChip from "../components/team/TodayChip.vue";
import base from "../i18n/en.json";
import team from "../i18n/parts/team.en.json";
import BranchesPage from "../pages/BranchesPage.vue";
import DepartmentsPage from "../pages/DepartmentsPage.vue";
import EmployeePage from "../pages/EmployeePage.vue";
import EmployeesPage from "../pages/EmployeesPage.vue";
import type { Employee, ImportResult } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** Answers `/owner/companies/1/<path>` by "METHOD path"; JSON bodies are recorded, files as they are. */
function stubApi(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const raw = init?.body;
      const call = { method: init?.method ?? "GET", url: input, body: typeof raw === "string" ? JSON.parse(raw) : raw };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const path = (call: Call) => call.url.replace("/api/v1/owner/companies/1/", "");

/** testApp with a router that knows the page's own pattern (for `route.params`). */
async function appAt(url: string, pattern?: string) {
  const app = await testApp(url);
  const routes = [...(pattern ? [{ path: pattern, component: { render: () => null } }] : []), { path: "/:any(.*)*", component: { render: () => null } }];
  const router = createRouter({ history: createMemoryHistory(), routes });
  await router.push(url);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { router, plugins: [app.pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] as typeof app.plugins };
}

const employee = (extra: Partial<Employee> = {}): Employee => ({
  id: 7,
  first_name: "Aziza",
  last_name: "Karimova",
  full_name: "Aziza Karimova",
  photo_url: null,
  phone: "+998901234567",
  position: { id: 2, name: "Manager" },
  department: { id: 3, name: "Sales" },
  branch_ids: [1],
  face_numbers: ["00000002"],
  status: "active",
  hire_date: "2025-03-01",
  left_on: null,
  schedule: { id: 4, name: "Five days" },
  telegram_linked: true,
  is_user: false,
  // 08:02 in Tashkent.
  today: { state: "in", since: "2026-11-10T03:02:00Z" },
  ...extra,
});

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

beforeEach(() => {
  mergeModuleMessages("davomat", { en: { ...base, ...team }, ru: { ...base, ...team }, uz: { ...base, ...team } });
  toasts.splice(0, toasts.length);
  confirmQueue.value = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("TodayChip", () => {
  it("says where someone is today, in the company's time", async () => {
    const app = await testApp("/c/1/team");
    const chip = (props: Record<string, unknown>) => mountWithProviders(TodayChip, { props, plugins: app.plugins }).wrapper.text();
    expect(chip({ today: { state: "in", since: "2026-11-10T03:02:00Z" } })).toBe("In since 08:02");
    expect(chip({ today: { state: "out", since: "2026-11-10T13:10:00Z" } })).toBe("Left at 18:10");
    expect(chip({ today: { state: "not_in", since: null } })).toBe("Not in yet");
    expect(chip({ today: { state: "leave", since: null } })).toBe("On leave");
    expect(chip({ today: null, status: "left" })).toBe("Left the company");
    expect(chip({ today: null })).toBe("");
  });
});

describe("FaceNumbersInput", () => {
  it("adds numbers on Enter and from a pasted list, refuses odd ones, Backspace takes the last back", async () => {
    const app = await testApp("/c/1/team");
    let value: string[] = [];
    const wrapper = mount(FaceNumbersInput, {
      props: { modelValue: value, "onUpdate:modelValue": (next: string[]) => void wrapper.setProps({ modelValue: (value = next) }) },
      global: { plugins: app.plugins },
    });
    const input = wrapper.find("input");
    await input.setValue("00000002");
    await input.trigger("keydown", { key: "Enter" });
    expect(value).toEqual(["00000002"]);

    const paste = new Event("paste", { bubbles: true, cancelable: true }) as ClipboardEvent;
    Object.defineProperty(paste, "clipboardData", { value: { getData: () => "15, 31 15" } });
    input.element.dispatchEvent(paste);
    await nextTick();
    expect(value).toEqual(["00000002", "15", "31"]);

    await input.setValue("12/4");
    await input.trigger("keydown", { key: "Enter" });
    expect(wrapper.text()).toContain("Only letters, digits, - and _");
    expect(value).toHaveLength(3);

    await input.setValue("");
    await input.trigger("keydown", { key: "Backspace" });
    expect(value).toEqual(["00000002", "15"]);
    wrapper.unmount();
  });
});

describe("EmployeesPage", () => {
  it("lists employees with their job, location, today, Face ID number and Telegram", async () => {
    const calls = stubApi({
      "GET employees/": () => json(page([employee(), employee({ id: 8, full_name: "Bekzod Aliyev", face_numbers: [], telegram_linked: false, today: { state: "not_in", since: null } })])),
      "GET positions/": () => json([{ id: 2, name: "Manager", order: 1, is_active: true, members_count: 1 }]),
      "GET departments/": () => json([{ id: 3, name: "Sales", parent_id: null, head: null, member_count: 1, total_count: 1, path: ["Sales"], can_edit: true }]),
    });
    const app = await appAt("/c/1/team");
    const { wrapper } = mountWithProviders(EmployeesPage, { plugins: app.plugins });
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("Aziza Karimova");
    expect(text).toContain("Manager");
    expect(text).toContain("Sales");
    expect(text).toContain("Chilonzor");
    expect(text).toContain("In since 08:02");
    expect(text).toContain("00000002");
    expect(text).toContain("Bekzod Aliyev");
    expect(text).toContain("Not in yet");
    expect(text).toContain("No Face ID number");
    expect(text).toContain("2 employees");
    const list = calls.find((call) => call.method === "GET" && path(call).startsWith("employees/"))!;
    expect(path(list)).toBe("employees/?status=active&page=1&page_size=100");

    await app.router.replace({ query: { q: "aziz", status: "left", telegram: "0", face: "0", branch: "1" } });
    await flushPromises();
    const filtered = calls.filter((call) => path(call).startsWith("employees/")).at(-1)!;
    expect(path(filtered)).toBe("employees/?search=aziz&status=left&branch=1&linked=0&face=0&page=1&page_size=100");

    await app.router.replace({ query: { status: "all" } });
    await flushPromises();
    expect(path(calls.filter((call) => path(call).startsWith("employees/")).at(-1)!)).toBe("employees/?page=1&page_size=100");
  });

  it("marks the employees a terminal added from an unknown face", async () => {
    stubApi({ "GET employees/": () => json(page([employee({ source: "terminal", full_name: "Гулирано", phone: "" })])), "GET positions/": () => json([]), "GET departments/": () => json([]) });
    const app = await appAt("/c/1/team");
    const { wrapper } = mountWithProviders(EmployeesPage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("[data-from-terminal]").text()).toBe("Added by a terminal");
  });

  it("invites to add, import or simply scan when nobody is here yet", async () => {
    stubApi({ "GET employees/": () => json(page([])), "GET positions/": () => json([]), "GET departments/": () => json([]) });
    const app = await appAt("/c/1/team");
    const { wrapper } = mountWithProviders(EmployeesPage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("[data-team-empty]").exists()).toBe(true);
    expect(wrapper.text()).toContain("No employees yet");
    expect(wrapper.text()).toContain("Import");
  });

  it("downloads the list as a file", async () => {
    const calls = stubApi({
      "GET employees/": () => json(page([employee()])),
      "GET positions/": () => json([]),
      "GET departments/": () => json([]),
      "GET employees/export/": () => new Response("x", { status: 200, headers: { "Content-Disposition": 'attachment; filename="employees-2026-11-10.xlsx"' } }),
    });
    const created: string[] = [];
    const { createObjectURL, revokeObjectURL } = URL;
    URL.createObjectURL = () => "blob:1";
    URL.revokeObjectURL = () => undefined;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      created.push(this.download);
    });
    const app = await appAt("/c/1/team");
    const { wrapper } = mountWithProviders(EmployeesPage, { plugins: app.plugins });
    await flushPromises();
    await wrapper.find("[data-export]").trigger("click");
    await flushPromises();
    expect(calls.some((call) => path(call) === "employees/export/?status=active&format=xlsx")).toBe(true);
    // Reading the file's body takes a few turns of the event loop.
    await vi.waitFor(() => expect(created).toEqual(["employees-2026-11-10.xlsx"]));
    click.mockRestore();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
  });
});

describe("EmployeeDrawer", () => {
  const lists = {
    "GET positions/": () => json([{ id: 2, name: "Manager", order: 1, is_active: true, members_count: 1 }]),
    "GET departments/": () => json([]),
    "GET attendance/schedules/": () => json([{ id: 4, name: "Five days", kind: "fixed", is_active: true }]),
  };

  it("adds an employee with their Face ID number, at the only location", async () => {
    const calls = stubApi({ ...lists, "POST employees/": () => json(employee({ telegram_linked: false }), 201) });
    const app = await appAt("/c/1/team?employee=new");
    mountWithProviders(EmployeeDrawer, { plugins: app.plugins });
    await flushPromises();
    expect(document.body.textContent).toContain("New employee");
    const first = document.querySelector<HTMLInputElement>('[data-field="first_name"] input, input[data-field="first_name"]')!;
    first.value = "Aziza";
    first.dispatchEvent(new Event("input"));
    const number = document.querySelector<HTMLInputElement>("#employee-face-numbers")!;
    number.value = "00000002";
    number.dispatchEvent(new Event("input"));
    number.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await nextTick();
    document.querySelector<HTMLFormElement>("#employee-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    const post = calls.find((call) => call.method === "POST")!;
    expect(path(post)).toBe("employees/");
    expect(post.body).toEqual({
      first_name: "Aziza",
      last_name: "",
      phone: "",
      position_id: null,
      department_id: null,
      branch_ids: [1],
      face_numbers: ["00000002"],
      schedule_id: null,
      hire_date: null,
    });
    expect(toasts.at(-1)?.title).toBe("Aziza Karimova added");
  });

  it("shows the server's refusal next to its field", async () => {
    stubApi({ ...lists, "POST employees/": () => json({ face_numbers: ["Number 00000002 belongs to Bekzod Aliyev."] }, 400) });
    const app = await appAt("/c/1/team?employee=new");
    mountWithProviders(EmployeeDrawer, { plugins: app.plugins });
    await flushPromises();
    const first = document.querySelector<HTMLInputElement>('[data-field="first_name"] input, input[data-field="first_name"]')!;
    first.value = "Aziza";
    first.dispatchEvent(new Event("input"));
    await nextTick();
    document.querySelector<HTMLFormElement>("#employee-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(document.body.textContent).toContain("Number 00000002 belongs to Bekzod Aliyev.");
  });

  it("fills in an employee to edit and saves only to their id", async () => {
    const calls = stubApi({ ...lists, "GET employees/7/": () => json(employee()), "PATCH employees/7/": () => json(employee({ phone: "+998907654321" })) });
    const app = await appAt("/c/1/team?employee=7");
    mountWithProviders(EmployeeDrawer, { plugins: app.plugins });
    await flushPromises();
    expect(document.body.textContent).toContain("Edit employee");
    const first = document.querySelector<HTMLInputElement>('[data-field="first_name"] input, input[data-field="first_name"]')!;
    expect(first.value).toBe("Aziza");
    document.querySelector<HTMLFormElement>("#employee-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    const patch = calls.find((call) => call.method === "PATCH")!;
    expect(path(patch)).toBe("employees/7/");
    expect(patch.body).toMatchObject({ first_name: "Aziza", face_numbers: ["00000002"], position_id: 2, department_id: 3, schedule_id: 4, hire_date: "2025-03-01" });
  });
});

describe("ImportDialog", () => {
  const preview: ImportResult = {
    dry_run: true,
    columns: ["Ism", "Familiya", "Filial", "Izoh"],
    mapping: { Ism: "first_name", Familiya: "last_name", Filial: "branch" },
    created: 1,
    updated: 1,
    skipped: 1,
    rows: [
      { row: 2, action: "create", name: "Aziza Karimova", employee_id: null, errors: [] },
      { row: 3, action: "update", name: "Bekzod Aliyev", employee_id: 8, errors: [] },
      { row: 4, action: "skip", name: "Sardor", employee_id: null, errors: ["No location named Moon."] },
    ],
  };

  it("checks the file first, shows each row's result, then imports", async () => {
    const calls = stubApi({ "POST employees/import/": (call) => json(call.url.includes("dry_run=1") ? preview : { ...preview, dry_run: false }) });
    const app = await appAt("/c/1/team?import=1");
    const { wrapper } = mountWithProviders(ImportDialog, { props: { open: true }, plugins: app.plugins });
    await flushPromises();
    const file = new File(["first_name\nAziza"], "team.csv", { type: "text/csv" });
    wrapper.findComponent(FileDrop).vm.$emit("update:modelValue", [file]);
    await flushPromises();
    const dry = calls.find((call) => call.method === "POST")!;
    expect(path(dry)).toBe("employees/import/?dry_run=1");
    expect(((dry.body as FormData).get("file") as File).name).toBe("team.csv");
    const text = document.body.textContent ?? "";
    expect(text).toContain("1 new");
    expect(text).toContain("1 to update");
    expect(text).toContain("1 skipped");
    expect(text).toContain("1 with an error");
    expect(text).toContain("Bekzod Aliyev");
    expect(text).toContain("No location named Moon.");
    expect(text).toContain("Import 2 employees");
    // How the header was read: known columns by their field, the rest left out.
    const mapping = document.querySelector("[data-import-mapping]")!.textContent ?? "";
    expect(mapping).toContain("Ism");
    expect(mapping).toContain("First name");
    expect(mapping).toContain("Izoh");
    expect(mapping).toContain("not used");

    document.querySelector<HTMLButtonElement>("[data-import-confirm]")!.click();
    await flushPromises();
    const real = calls.filter((call) => call.method === "POST").at(-1)!;
    expect(path(real)).toBe("employees/import/");
    expect(document.body.textContent).toContain("Imported");
    expect(document.body.textContent).toContain("New: 1. Updated: 1.");
  });

  it("says why a file can't be read", async () => {
    stubApi({ "POST employees/import/": () => json({ detail: "The first row must name the columns." }, 400) });
    const app = await appAt("/c/1/team?import=1");
    const { wrapper } = mountWithProviders(ImportDialog, { props: { open: true }, plugins: app.plugins });
    await flushPromises();
    wrapper.findComponent(FileDrop).vm.$emit("update:modelValue", [new File(["x"], "team.csv", { type: "text/csv" })]);
    await flushPromises();
    expect(document.body.textContent).toContain("The first row must name the columns.");
    expect(document.querySelector<HTMLButtonElement>("[data-import-confirm]")!.disabled).toBe(true);
  });
});

describe("DepartmentsPage", () => {
  it("adds, renames and deletes departments", async () => {
    const departments = [{ id: 5, name: "Sales", parent_id: null, head: null, member_count: 4, total_count: 4, path: ["Sales"], can_edit: true }];
    const calls = stubApi({
      "GET departments/": () => json(departments),
      "POST departments/": () => json({ ...departments[0], id: 6, name: "Warehouse" }, 201),
      "PATCH departments/5/": () => json({ ...departments[0], name: "Retail" }),
      "DELETE departments/5/": () => new Response(null, { status: 204 }),
    });
    const app = await appAt("/c/1/team/departments");
    const { wrapper } = mountWithProviders(DepartmentsPage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).toContain("Sales");
    expect(wrapper.text()).toContain("4 people");

    await wrapper.find("[data-new-name] input, input[data-new-name]").setValue("Warehouse");
    await wrapper.find("[data-name-list] form").trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({ name: "Warehouse" });

    await wrapper.find('[aria-label="Rename Sales"]').trigger("click");
    await nextTick();
    await wrapper.find('[data-rename="5"] input').setValue("Retail");
    await wrapper.find('[data-rename="5"]').trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ name: "Retail" });

    await wrapper.find('[aria-label="Delete Sales"]').trigger("click");
    await flushPromises();
    expect(confirmQueue.value[0]?.request.title).toBe("Delete the Sales department?");
    settleConfirm(confirmQueue.value[0]!.id, { reason: "" }, 0);
    await flushPromises();
    expect(calls.some((call) => call.method === "DELETE" && path(call) === "departments/5/")).toBe(true);
  });
});

describe("EmployeePage", () => {
  it("shows the person, their month, the day's scans and makes a Telegram link", async () => {
    const calls = stubApi({
      "GET employees/7/": () => json(employee({ telegram_linked: false })),
      "GET attendance/members/7/": () =>
        json({
          schedule: { id: 4, name: "Five days" },
          month: "2026-11",
          days: ["2026-11-02", "2026-11-03"],
          today: "2026-11-03",
          holidays: {},
          cells: { "2026-11-02": { code: "present", minutes: 540, late: 0, record_id: 1, shift_id: 1 }, "2026-11-03": { code: "late", minutes: 500, late: 14, record_id: 2, shift_id: 2 } },
          totals: { scheduled_days: 20, attended_days: 2, leave_days: 0, absent_days: 0, worked_minutes: 1040, approved_overtime_minutes: 0, late_arrivals: 1, late_minutes: 14, has_schedule: true },
        }),
      "GET faceid/events/": () =>
        json(
          page([
            {
              id: 31,
              event_at: "2026-11-10T08:02:10+05:00",
              received_at: "2026-11-10T08:02:11+05:00",
              device: { id: 1, name: "Entrance" },
              branch: { id: 1, name: "Chilonzor", code: "CHL" },
              kind: "person",
              action: "checked_in",
              employee_no: "00000002",
              name_on_device: "Aziza",
              member: null,
              record: { id: 2, status: "open", check_in_at: "2026-11-10T08:02:10+05:00", check_out_at: null, is_late: true, late_minutes: 14, worked_minutes: 0 },
              photo_url: "/api/v1/files/snap/",
            },
          ]),
        ),
      "POST employees/7/telegram-link/": () => json({ url: "https://t.me/namuna_bot?start=link_abc", code: "abc", expires_at: "2026-11-11T08:00:00Z" }, 201),
    });
    const app = await appAt("/c/1/team/7", "/c/:companyId/team/:employeeId");
    const { wrapper } = mountWithProviders(EmployeePage, { plugins: app.plugins });
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("Aziza Karimova");
    expect(text).toContain("Manager · Sales");
    expect(text).toContain("00000002");
    expect(text).toContain("Five days");
    expect(text).toContain("In since 08:02");
    expect(text).toContain("Days at work");
    expect(text).toContain("of 20 expected");
    expect(text).toContain("Late 14m");
    expect(calls.some((call) => path(call).startsWith("faceid/events/?member=7&date="))).toBe(true);
    expect(calls.some((call) => path(call).startsWith("attendance/members/7/?month="))).toBe(true);

    await wrapper.find("[data-create-link]").trigger("click");
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && path(call) === "employees/7/telegram-link/")).toBe(true);
    expect(wrapper.find("[data-telegram-qr]").exists()).toBe(true);
    expect(wrapper.text()).toContain("Works once, until");
  });

  it("says so when the employee isn't there", async () => {
    stubApi({});
    const app = await appAt("/c/1/team/99", "/c/:companyId/team/:employeeId");
    const { wrapper } = mountWithProviders(EmployeePage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).toContain("This employee isn’t here");
  });
});

describe("BranchesPage", () => {
  it("shows each location with its people, who is in now and its terminals", async () => {
    stubApi({
      "GET branches/": () =>
        json([
          { id: 1, name: "Main office", code: "HQ", address: "Amir Temur 1", phone: "", opens_at: "08:00:00", closes_at: "18:00:00", open_24h: false, is_active: true, order: 1, people: 12 },
          { id: 2, name: "Old site", code: "", address: "", phone: "", opens_at: null, closes_at: null, open_24h: false, is_active: false, order: 2, people: 0 },
        ]),
      "GET attendance/board/": () => json({ date: "2026-11-10", is_today: true, now: "", holiday: null, totals: {}, people: [], branches: [{ id: 1, name: "Main office", rostered: 10, checked_in: 7, first_check_in: null }] }),
      "GET faceid/status/": () => json({ total: 1, online: 1, quiet: 0, never: 0, unlinked: 0, devices: [{ id: 3, name: "Front door", branch: { id: 1, name: "Main office", code: "HQ" }, status: "online", last_event_at: null, scans_today: 9 }] }),
    });
    const app = await appAt("/c/1/team/branches");
    const { wrapper } = mountWithProviders(BranchesPage, { plugins: app.plugins });
    await flushPromises();
    const card = wrapper.find('[data-branch="1"]');
    expect(card.text()).toContain("Main office");
    expect(card.text()).toContain("Amir Temur 1");
    expect(card.text()).toContain("08:00–18:00");
    expect(card.text()).toContain("12");
    expect(card.text()).toContain("7");
    expect(card.text()).toContain("/ 10");
    expect(card.text()).toContain("Front door");
    expect(card.text()).toContain("Online");
    expect(wrapper.find("[data-closed-branches]").text()).toContain("Old site");
  });
});
