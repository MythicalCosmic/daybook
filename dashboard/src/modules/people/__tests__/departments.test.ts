// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import MultiSelect from "@/components/MultiSelect.vue";
import SelectBox from "@/components/SelectBox.vue";
import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { modulesToRefresh } from "@/core/pulse";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { addDepartmentMembers, createDepartment, deleteDepartment, listDepartments, listPeople, updateDepartment, updatePerson } from "../api";
import DepartmentCard from "../components/DepartmentCard.vue";
import {
  allowedParents,
  buildDepartmentTree,
  columnsFor,
  deleteOutcome,
  departmentCounts,
  departmentOptions,
  descendantIds,
  flattenDepartments,
  headAbove,
  headedBy,
  placedCount,
  rowsOf,
  TOP_LEVEL,
} from "../departments";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { Department } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

type Responder = (call: Call) => Response | Promise<Response> | undefined;

function stub(respond: Responder = () => undefined): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      // Unhandled: an empty page for people lists, an empty list for the rest (positions, roles…).
      return (await respond(call)) ?? json(/\/people\/(\?|$)/.test(call.url) ? { count: 0, next: null, previous: null, results: [] } : []);
    }),
  );
  return calls;
}

/** An answer that takes a while, as over a real network. */
const later = (response: () => Response, ms = 60) => new Promise<Response>((resolve) => setTimeout(() => resolve(response()), ms));

const path = (call: Call) => call.url.replace("/api/v1/owner/companies/1/", "");

/** The options a (generic) picker was given. */
const optionsOf = (picker: { props: () => unknown }) => (picker.props() as { options: unknown }).options;

const aziz = { id: 21, name: "Aziz Karimov", photo_url: null };
const dilshod = { id: 22, name: "Dilshod Rahimov", photo_url: null };
const nigora = { id: 23, name: "Nigora Tosheva", photo_url: null };

function dept(id: number, name: string, parentId: number | null, trail: string[], overrides: Partial<Department> = {}): Department {
  return { id, name, parent_id: parentId, head: null, member_count: 0, total_count: 0, path: [...trail, name], can_edit: true, ...overrides };
}

/** In the server's tree order: Kuryerlar and Rahbariyat at the top, siblings by name. */
const DEPARTMENTS: Department[] = [
  dept(7, "Kuryerlar", null, [], { member_count: 0, total_count: 0 }),
  dept(1, "Rahbariyat", null, [], { head: aziz, member_count: 2, total_count: 14 }),
  dept(2, "Dorixonalar", 1, ["Rahbariyat"], { head: dilshod, member_count: 1, total_count: 8 }),
  dept(4, "Chilonzor filiali", 2, ["Rahbariyat", "Dorixonalar"], { head: nigora, member_count: 4, total_count: 4 }),
  dept(5, "Yunusobod filiali", 2, ["Rahbariyat", "Dorixonalar"], { member_count: 3, total_count: 3 }),
  dept(6, "Moliya", 1, ["Rahbariyat"], { head: aziz, member_count: 1, total_count: 1 }),
  dept(3, "Ombor", 1, ["Rahbariyat"], { member_count: 3, total_count: 3 }),
];

function person(id: number, name: string, department: { id: number; name: string } | null, extra: Record<string, unknown> = {}) {
  return {
    id,
    name,
    full_name: name,
    first_name: name.split(" ")[0],
    last_name: name.split(" ")[1] ?? "",
    photo_url: null,
    phone: "",
    username: "",
    position: { id: 1, name: "Farmatsevt" },
    role: { id: 2, name: "Xodim", is_owner: false },
    home_branch: { id: 1, name: "Chilonzor", code: "CHL" },
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    status: "approved",
    suspended_until: null,
    joined_on: "2025-10-06",
    left_on: null,
    onboarded: true,
    bot_blocked: false,
    work: { on_time_30d: null, done_30d: 0, late_now: 0, open_now: 0 },
    fields: {},
    department,
    manager: null,
    ...extra,
  };
}

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

beforeEach(() => {
  mergeModuleMessages("people", { en, ru, uz });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  confirmQueue.value = [];
  setLanguage("en");
});

describe("the tree", () => {
  it("builds parents and children from the flat list, keeping the server's sibling order", () => {
    const roots = buildDepartmentTree(DEPARTMENTS);
    expect(roots.map((node) => node.department.name)).toEqual(["Kuryerlar", "Rahbariyat"]);
    const top = roots[1]!;
    expect(top.children.map((node) => node.department.name)).toEqual(["Dorixonalar", "Moliya", "Ombor"]);
    expect(top.children[0]!.children.map((node) => [node.department.name, node.depth])).toEqual([
      ["Chilonzor filiali", 2],
      ["Yunusobod filiali", 2],
    ]);
    expect(flattenDepartments(DEPARTMENTS).map((node) => node.department.id)).toEqual([7, 1, 2, 4, 5, 6, 3]);
  });

  it("doesn't depend on parents coming first, and never loses a department", () => {
    const shuffled = [DEPARTMENTS[4]!, DEPARTMENTS[3]!, DEPARTMENTS[6]!, DEPARTMENTS[2]!, DEPARTMENTS[1]!, DEPARTMENTS[5]!, DEPARTMENTS[0]!];
    const flat = flattenDepartments(shuffled);
    expect(flat).toHaveLength(7);
    expect(flat.find((node) => node.department.id === 4)!.depth).toBe(2);
    // A parent that isn't in the list (gone meanwhile): shown at the top.
    expect(buildDepartmentTree([dept(9, "Kassa", 99, ["Sotuv"])]).map((node) => node.department.name)).toEqual(["Kassa"]);
    // A cycle (the server forbids them) still shows every department, once.
    const looped = flattenDepartments([dept(1, "A", 2, ["B"]), dept(2, "B", 1, ["A"])]);
    expect(looped.map((node) => node.department.id).sort()).toEqual([1, 2]);
  });

  it("never offers a department, or one below it, as its own parent", () => {
    expect([...descendantIds(DEPARTMENTS, 1)].sort()).toEqual([2, 3, 4, 5, 6]);
    expect([...descendantIds(DEPARTMENTS, 2)].sort()).toEqual([4, 5]);
    expect(descendantIds(DEPARTMENTS, 4).size).toBe(0);
    expect(allowedParents(DEPARTMENTS, 2).map((node) => node.department.id)).toEqual([7, 1, 6, 3]);
    expect(allowedParents(DEPARTMENTS, 1).map((node) => node.department.id)).toEqual([7]);
    // A new department may go anywhere.
    expect(allowedParents(DEPARTMENTS, null)).toHaveLength(7);
  });

  it("names the departments above each choice", () => {
    const options = departmentOptions(flattenDepartments(DEPARTMENTS), (d) => d.id);
    expect(options.find((o) => o.value === 4)).toMatchObject({ label: "Chilonzor filiali", description: "Rahbariyat › Dorixonalar" });
    expect(options.find((o) => o.value === 1)!.description).toBeUndefined();
  });

  it("counts people directly in a department, and everyone with the ones below when that differs", () => {
    expect(departmentCounts(DEPARTMENTS[1]!, true)).toEqual({ direct: 2, total: 14 });
    expect(departmentCounts(DEPARTMENTS[3]!, false)).toEqual({ direct: 4, total: null });
    // Sub-departments without people add nothing worth repeating.
    expect(departmentCounts(dept(8, "Sotuv", null, [], { member_count: 5, total_count: 5 }), true)).toEqual({ direct: 5, total: null });
    expect(placedCount(DEPARTMENTS)).toBe(14);
  });

  it("says what deleting does, naming only what the department has", () => {
    const say = (id: number, list = DEPARTMENTS) => deleteOutcome(list, list.find((d) => d.id === id)!);
    expect(say(2)).toEqual({ key: "people.dept.deleteBodyParent", parent: "Rahbariyat" });
    expect(say(3)).toEqual({ key: "people.dept.deletePeopleParent", parent: "Rahbariyat" });
    expect(say(7)).toEqual({ key: "people.dept.deleteBodyEmpty", parent: null });
    expect(say(1)).toEqual({ key: "people.dept.deleteBodyTop", parent: null });
    const emptyTop = DEPARTMENTS.map((d) => (d.id === 1 ? { ...d, member_count: 0 } : d));
    expect(say(1, emptyTop)).toEqual({ key: "people.dept.deleteSubsTop", parent: null });
    const emptyMiddle = DEPARTMENTS.map((d) => (d.id === 2 ? { ...d, member_count: 0 } : d));
    expect(say(2, emptyMiddle)).toEqual({ key: "people.dept.deleteSubsParent", parent: "Rahbariyat" });
    expect(say(7, DEPARTMENTS.map((d) => (d.id === 7 ? { ...d, member_count: 2 } : d)))).toEqual({ key: "people.dept.deletePeopleTop", parent: null });
    // Every outcome has its words in all three languages.
    for (const key of ["Body", "People", "Subs"].flatMap((what) => [`people.dept.delete${what}Parent`, `people.dept.delete${what}Top`])) {
      for (const dictionary of [en, uz, ru] as Array<Record<string, string>>) expect(dictionary[key], key).toBeTruthy();
    }
  });

  it("finds the head a head reports to, skipping their own other departments", () => {
    expect(headAbove(DEPARTMENTS, 4)).toMatchObject({ head: { id: 22 }, department: { name: "Dorixonalar" } });
    expect(headAbove(DEPARTMENTS, 2)).toMatchObject({ head: { id: 21 }, department: { name: "Rahbariyat" } });
    // Aziz heads Moliya and the department above it: nobody above him.
    expect(headAbove(DEPARTMENTS, 6)).toBeNull();
    expect(headAbove(DEPARTMENTS, 1)).toBeNull();
    // Yunusobod has no head: its people report to Dilshod (the server says so); the chart asks nothing here.
    expect(headedBy(DEPARTMENTS, 21).map((d) => d.name)).toEqual(["Rahbariyat", "Moliya"]);
  });

  it("lays sub-departments out in as many columns as fit, one on a phone", () => {
    expect(columnsFor(1100, 5, 232, 16)).toBe(4);
    expect(columnsFor(1100, 2, 232, 16)).toBe(2);
    expect(columnsFor(330, 5, 232, 16)).toBe(1);
    expect(columnsFor(0, 5, 232, 16)).toBe(1);
    expect(rowsOf([1, 2, 3, 4, 5], 4)).toEqual([[1, 2, 3, 4], [5]]);
  });
});

describe("api", () => {
  it("calls the department endpoints with their bodies, and filters people by department", async () => {
    const calls = stub();
    await listDepartments(1);
    await createDepartment(1, { name: "Ombor", parent_id: 1, head_id: 24 });
    await updateDepartment(1, 3, { parent_id: null });
    await deleteDepartment(1, 3);
    await addDepartmentMembers(1, 2, [31, 32]);
    await updatePerson(1, 31, { department_id: null });
    await listPeople(1, { status: "current", department: ["2", "7"] });
    expect(calls.map((c) => `${c.method} ${path(c)}`)).toEqual([
      "GET departments/",
      "POST departments/",
      "PATCH departments/3/",
      "DELETE departments/3/",
      "POST departments/2/members/",
      "PATCH people/31/",
      "GET people/?status=current&department=2&department=7",
    ]);
    expect(calls[1]!.body).toEqual({ name: "Ombor", parent_id: 1, head_id: 24 });
    expect(calls[2]!.body).toEqual({ parent_id: null });
    expect(calls[4]!.body).toEqual({ member_ids: [31, 32] });
    expect(calls[5]!.body).toEqual({ department_id: null });
  });

  it("refreshes People when the departments pulse key moves", () => {
    expect(modulesToRefresh(["members.departments"])).toContain("people");
  });
});

describe("DepartmentsPage", () => {
  async function mountPage(start: Department[], path = "/c/1/people/departments") {
    // The server's list: a delete takes the department out and moves its sub-departments up; after
    // a create the list comes back slowly (the new department's panel mustn't wait for it).
    let list = start;
    let created = false;
    const calls = stub((call) => {
      if (call.method === "GET" && call.url.includes("/departments/")) return created ? later(() => json(list)) : json(list);
      if (call.url.includes("/people/stats/")) return json({ current: 20, active: 19, suspended: 1, on_leave_today: 0, joined_30d: 0, left_30d: 0, pending_requests: 0, bot_blocked: 0 });
      if (call.method === "DELETE") {
        const id = Number(/departments\/(\d+)\//.exec(call.url)![1]);
        const gone = list.find((d) => d.id === id)!;
        list = list.filter((d) => d.id !== id).map((d) => (d.parent_id === id ? { ...d, parent_id: gone.parent_id } : d));
        return json(null, 204);
      }
      if (call.method === "POST" && call.url.endsWith("/departments/")) {
        const body = call.body as { name: string; parent_id: number | null };
        const made = dept(90, body.name, body.parent_id, []);
        list = [...list, made];
        created = true;
        return json(made, 201);
      }
      return undefined;
    });
    const DepartmentsPage = (await import("../pages/DepartmentsPage.vue")).default;
    const app = await testApp(path);
    const mounted = mountWithProviders(DepartmentsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { ...mounted, calls, app };
  }

  it("draws the structure as cards: name, head or none yet, people directly in it and in all", async () => {
    const { wrapper } = await mountPage(DEPARTMENTS);
    const cards = wrapper.findAll("[data-department]");
    expect(cards.map((card) => card.attributes("data-department"))).toEqual(["7", "1", "2", "4", "5", "6", "3"]);
    const top = wrapper.find('[data-department="1"]');
    expect(top.find("[data-head]").text()).toContain("Aziz Karimov");
    expect(top.find("[data-counts]").text()).toBe("2 people·14 in all");
    const yunusobod = wrapper.find('[data-department="5"]');
    expect(yunusobod.find("[data-no-head]").text()).toContain("No head yet");
    expect(yunusobod.find("[data-counts]").text()).toBe("3 people");
    expect(wrapper.find('[data-department="7"] [data-counts]').text()).toBe("No one yet");
    // Sub-departments hang from their parent.
    expect(wrapper.find('[data-branch="2"] [data-branch="4"]').exists()).toBe(true);
    expect(wrapper.find("[data-departments-summary]").text()).toBe("7 departments·14 people in departments·6 without a department");
    expect(wrapper.find("[data-new-department]").exists()).toBe(true);
  });

  it("opens a new department's panel at once, before the list is fetched again", async () => {
    // The dialog is its own chunk: loaded first, so a busy test run doesn't wait on it.
    await import("../components/DepartmentDialog.vue");
    const { wrapper, app, calls } = await mountPage(DEPARTMENTS);
    await wrapper.find("[data-new-department]").trigger("click");
    const name = await vi.waitFor(() => document.body.querySelector<HTMLInputElement>("[data-department-form] input") ?? Promise.reject(new Error("no dialog yet")), {
      timeout: 10_000,
    });
    name.value = "Sifat nazorati";
    name.dispatchEvent(new Event("input"));
    await flushPromises();
    document.body.querySelector<HTMLFormElement>("[data-department-form]")!.requestSubmit();
    await vi.waitFor(() => expect(app.router.currentRoute.value.query.department).toBe("90"), { timeout: 10_000 });
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ name: "Sifat nazorati", parent_id: null });
    await flushPromises();
    expect(wrapper.find('[data-department="90"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("explains departments when there are none, with the button only for those who may edit", async () => {
    const { wrapper } = await mountPage([]);
    const empty = wrapper.find("[data-departments-empty]");
    expect(empty.text()).toContain("No departments yet");
    expect(empty.find("[data-new-department]").exists()).toBe(true);
  });

  it("hides editing from someone the server says may not change the structure", async () => {
    const { wrapper } = await mountPage(DEPARTMENTS.map((d) => ({ ...d, can_edit: false })));
    expect(wrapper.find("[data-new-department]").exists()).toBe(false);
    expect(wrapper.find("[data-department-menu]").exists()).toBe(false);
    expect(wrapper.find("[data-set-head]").exists()).toBe(false);
  });

  it("asks before deleting, naming where the people go, then deletes", async () => {
    const { wrapper, calls } = await mountPage(DEPARTMENTS);
    const card = wrapper.findAllComponents(DepartmentCard).find((c) => c.props("department").id === 2)!;
    card.vm.$emit("action", "delete");
    await flushPromises();
    const request = confirmQueue.value.at(-1)!;
    expect(request.request.title).toBe("Delete «Dorixonalar»?");
    expect(request.request.message).toBe("Its people and sub-departments move up to «Rahbariyat».");
    settleConfirm(request.id, { reason: "" });
    await flushPromises();
    expect(calls.some((c) => c.method === "DELETE" && path(c) === "departments/2/")).toBe(true);
    // Gone from the chart at once, its sub-departments under Rahbariyat.
    expect(wrapper.find('[data-department="2"]').exists()).toBe(false);
    expect(wrapper.find('[data-branch="1"] [data-branch="4"]').exists()).toBe(true);

    const top = wrapper.findAllComponents(DepartmentCard).find((c) => c.props("department").id === 7)!;
    top.vm.$emit("action", "delete");
    await flushPromises();
    expect(confirmQueue.value.at(-1)!.request.message).toBe("There is no one in it and nothing below it.");
  });
});

describe("DepartmentDialog", () => {
  it("moves a department only to where it may go, and sends only the new parent", async () => {
    const calls = stub((call) => (call.method === "PATCH" ? json({ ...DEPARTMENTS[2]!, parent_id: null, path: ["Dorixonalar"] }) : undefined));
    const DepartmentDialog = (await import("../components/DepartmentDialog.vue")).default;
    const app = await testApp("/c/1/people/departments");
    const { wrapper } = mountWithProviders(DepartmentDialog, { plugins: app.plugins, props: { open: true, mode: "move", department: DEPARTMENTS[2], departments: DEPARTMENTS } });
    await flushPromises();
    const picker = wrapper.findComponent(SelectBox);
    const values = (optionsOf(picker) as Array<{ value: number }>).map((o) => o.value);
    // The top level, then everything but Dorixonalar and its two branches.
    expect(values).toEqual([TOP_LEVEL, 7, 1, 6, 3]);
    picker.vm.$emit("update:modelValue", TOP_LEVEL);
    await flushPromises();
    document.body.querySelector<HTMLFormElement>("[data-department-form]")!.requestSubmit();
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(path(patch)).toBe("departments/2/");
    expect(patch.body).toEqual({ parent_id: null });
  });

  it("creates a sub-department under the one it was asked from", async () => {
    const calls = stub((call) => (call.method === "POST" ? json(dept(9, "Kassa", 2, ["Rahbariyat", "Dorixonalar"]), 201) : undefined));
    const DepartmentDialog = (await import("../components/DepartmentDialog.vue")).default;
    const app = await testApp("/c/1/people/departments");
    const { wrapper, inner } = mountWithProviders(DepartmentDialog, { plugins: app.plugins, props: { open: true, mode: "create", parentId: 2, departments: DEPARTMENTS } });
    await flushPromises();
    const name = document.body.querySelector<HTMLInputElement>("[data-department-form] input")!;
    name.value = "Kassa";
    name.dispatchEvent(new Event("input"));
    await flushPromises();
    document.body.querySelector<HTMLFormElement>("[data-department-form]")!.requestSubmit();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ name: "Kassa", parent_id: 2 });
    expect((inner.emitted("saved")![0]![0] as Department).id).toBe(9);
    wrapper.unmount();
  });
});

describe("DepartmentPanel", () => {
  const people = [
    person(31, "Madina Saidova", { id: 2, name: "Dorixonalar" }),
    person(22, "Dilshod Rahimov", { id: 2, name: "Dorixonalar" }),
    // In Chilonzor, below Dorixonalar: the list has them, the panel doesn't.
    person(33, "Jasur Aliyev", { id: 4, name: "Chilonzor filiali" }),
  ];

  async function mountPanel() {
    const calls = stub((call) => {
      if (call.method === "GET" && call.url.includes("department=2")) return json(page(people));
      if (call.method === "GET" && call.url.includes("/people/")) return json(page([...people, person(40, "Olim Yusupov", { id: 3, name: "Ombor" }), person(41, "Kamola Ergasheva", null)]));
      if (call.method === "PATCH") return json({ ...people[0], department: null });
      if (call.method === "POST") return json(DEPARTMENTS[2]);
      return undefined;
    });
    const DepartmentPanel = (await import("../components/DepartmentPanel.vue")).default;
    const app = await testApp("/c/1/people/departments?department=2");
    const mounted = mountWithProviders(DepartmentPanel, { plugins: app.plugins, props: { department: DEPARTMENTS[2], departments: DEPARTMENTS, canEdit: true, canPlace: true } });
    await flushPromises();
    await flushPromises();
    return { ...mounted, calls };
  }

  it("lists the people directly in it, marks the head and says whom the head reports to", async () => {
    const { wrapper, calls } = await mountPanel();
    expect(path(calls.find((c) => c.url.includes("/people/"))!)).toBe("people/?department=2&status=current&ordering=name&page_size=500");
    expect(wrapper.findAll("[data-person]").map((row) => row.attributes("data-person"))).toEqual(["31", "22"]);
    expect(wrapper.find('[data-person="22"]').text()).toContain("Head");
    const above = wrapper.find("[data-head-above]");
    expect(above.findAll("span").map((part) => part.text())).toEqual(["Reports to:", "· Rahbariyat"]);
    expect(above.find("a").text()).toBe("Aziz Karimov");
    expect(above.find("a").attributes("href")).toBe("/c/1/people/21");
    expect(wrapper.findAll("[data-sub]").map((row) => row.attributes("data-sub"))).toEqual(["4", "5"]);
    expect(wrapper.find("[data-team-link]").attributes("href")).toBe("/c/1/people?department=2");
  });

  it("takes someone out at once with PATCH department_id null, and Undo puts them back", async () => {
    const { wrapper, calls } = await mountPanel();
    await wrapper.find('[data-person="31"] [data-take-out]').trigger("click");
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(path(patch)).toBe("people/31/");
    expect(patch.body).toEqual({ department_id: null });
    // Said in the panel (a toast would sit under the drawer), with Undo.
    expect(wrapper.find("[data-panel-notice]").text()).toContain("Madina Saidova is no longer in «Dorixonalar»");
    await wrapper.find("[data-panel-undo]").trigger("click");
    await flushPromises();
    const back = calls.find((c) => c.method === "POST")!;
    expect(path(back)).toBe("departments/2/members/");
    expect(back.body).toEqual({ member_ids: [31] });
    expect(wrapper.find("[data-panel-notice]").exists()).toBe(false);
  });

  it("adds people from other departments or none, and leaves out those already in it", async () => {
    const { wrapper, calls } = await mountPanel();
    await wrapper.find("[data-add-people]").trigger("click");
    await flushPromises();
    await flushPromises();
    const picker = wrapper.findComponent(MultiSelect);
    const options = optionsOf(picker) as Array<{ value: number; description?: string }>;
    // Those in no department first, then by name; those already in it are left out.
    expect(options.map((o) => o.value)).toEqual([41, 33, 40]);
    expect(options.find((o) => o.value === 40)!.description).toBe("Farmatsevt · Now in: Ombor");
    picker.vm.$emit("update:modelValue", [40, 41]);
    await flushPromises();
    await wrapper.find("[data-add-confirm]").trigger("click");
    await flushPromises();
    const post = calls.find((c) => c.method === "POST")!;
    expect(path(post)).toBe("departments/2/members/");
    expect(post.body).toEqual({ member_ids: [40, 41] });
  });
});

describe("TeamPage", () => {
  it("filters by department (with the ones below) and shows a department column", async () => {
    const calls = stub((call) => {
      if (call.method === "GET" && call.url.includes("/departments/")) return json(DEPARTMENTS);
      if (call.method === "GET" && /\/people\/\?/.test(call.url)) {
        return json(page([person(22, "Dilshod Rahimov", { id: 2, name: "Dorixonalar" }), person(31, "Madina Saidova", { id: 4, name: "Chilonzor filiali" })]));
      }
      return undefined;
    });
    const TeamPage = (await import("../pages/TeamPage.vue")).default;
    const app = await testApp("/c/1/people?department=2");
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/c/:companyId/people", component: TeamPage },
        { path: "/:any(.*)*", component: { render: () => null } },
      ],
    });
    await router.push("/c/1/people?department=2");
    const { wrapper } = mountWithProviders(TeamPage, { plugins: [app.pinia, router, i18n, [VueQueryPlugin, { queryClient: app.client }]] });
    await flushPromises();
    await flushPromises();
    const list = calls.filter((c) => /\/people\/\?/.test(c.url)).map(path);
    // Filtered from the first request, before the departments themselves have loaded.
    expect(list.length).toBeGreaterThan(0);
    expect(list.every((url) => url.includes("department=2"))).toBe(true);
    expect(wrapper.text()).toContain("Department");
    expect(wrapper.text()).toContain("Chilonzor filiali");
    // Dilshod heads Dorixonalar: his row says so.
    expect(wrapper.findAll("[data-head-tag]").length).toBeGreaterThan(0);
  });
});

describe("PersonEditDialog", () => {
  it("moves someone to another department with department_id", async () => {
    const calls = stub((call) => {
      if (call.method === "GET" && call.url.includes("/departments/")) return json(DEPARTMENTS);
      if (call.method === "PATCH") return json({ ...person(31, "Madina Saidova", { id: 3, name: "Ombor" }), language: "uz", overview: {}, can: {} });
      return undefined;
    });
    const PersonEditDialog = (await import("../components/PersonEditDialog.vue")).default;
    const app = await testApp("/c/1/people/31");
    const detail = { ...person(31, "Madina Saidova", { id: 2, name: "Dorixonalar" }), language: "uz", overview: {}, can: { change_role: false } };
    const { wrapper } = mountWithProviders(PersonEditDialog, { plugins: app.plugins, props: { open: true, person: detail } });
    await flushPromises();
    await flushPromises();
    const select = wrapper.findAllComponents(SelectBox).find((c) => c.attributes("data-department-select") !== undefined)!;
    expect((optionsOf(select) as Array<{ value: number }>).map((o) => o.value)).toEqual([7, 1, 2, 4, 5, 6, 3]);
    select.vm.$emit("update:modelValue", 3);
    await flushPromises();
    document.body.querySelector<HTMLFormElement>("#person-edit")!.requestSubmit();
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(path(patch)).toBe("people/31/");
    expect(patch.body).toEqual({ department_id: 3 });
  });
});

describe("PersonPage", () => {
  it("shows the department, whom they report to and the departments they head", async () => {
    const detail = {
      ...person(22, "Dilshod Rahimov", { id: 2, name: "Dorixonalar" }, { manager: aziz, heads: [{ id: 2, name: "Dorixonalar" }, { id: 6, name: "Moliya" }] }),
      language: "uz",
      overview: { trend: [], on_time: 0, late: 0, missed: 0, total: 0, on_time_percent: null, streak: 0, joined_on: "2025-10-06", left_on: null, tenure_days: 10, days_off_this_year: 0, range: { from: "2026-09-27", to: "2026-10-26" }, upcoming_time_off: [], open_now: 0, late_now: 0, done: 0 },
      can: {},
    };
    stub((call) => (call.url.endsWith("/people/22/") ? json(detail) : undefined));
    const PersonPage = (await import("../pages/PersonPage.vue")).default;
    const app = await testApp("/c/1/people/22");
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/c/:companyId/people/:memberId(\\d+)/:tab?", component: PersonPage },
        { path: "/:any(.*)*", component: { render: () => null } },
      ],
    });
    await router.push("/c/1/people/22");
    const { wrapper } = mountWithProviders(PersonPage, { plugins: [app.pinia, router, i18n, [VueQueryPlugin, { queryClient: app.client }]] });
    await flushPromises();
    await flushPromises();
    expect(wrapper.find("[data-person-department]").attributes("href")).toBe("/c/1/people/departments?department=2");
    const manager = wrapper.find("[data-person-manager]");
    expect(manager.find("span").text()).toBe("Reports to:");
    expect(manager.find("a").text()).toContain("Aziz Karimov");
    expect(manager.find("a").attributes("href")).toBe("/c/1/people/21");
    // Heading their own department is a badge on it; the others they head are listed.
    expect(wrapper.find("[data-person-heads-own]").text()).toBe("Head");
    expect(wrapper.find("[data-person-heads]").text()).toBe("Heads:Moliya");
    expect(wrapper.find("[data-person-heads] a").attributes("href")).toBe("/c/1/people/departments?department=6");
    expect(wrapper.find("[data-detail-department]").text()).toBe("Dorixonalar");
  });

  it("says nothing about departments for someone they don't touch", async () => {
    const detail = {
      ...person(41, "Kamola Ergasheva", null),
      language: "uz",
      overview: { trend: [], on_time: 0, late: 0, missed: 0, total: 0, on_time_percent: null, streak: 0, joined_on: null, left_on: null, tenure_days: null, days_off_this_year: 0, range: { from: "2026-09-27", to: "2026-10-26" }, upcoming_time_off: [], open_now: 0, late_now: 0, done: 0 },
      can: {},
    };
    stub((call) => (call.url.endsWith("/people/41/") ? json(detail) : undefined));
    const PersonPage = (await import("../pages/PersonPage.vue")).default;
    const app = await testApp("/c/1/people/41");
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/c/:companyId/people/:memberId(\\d+)/:tab?", component: PersonPage },
        { path: "/:any(.*)*", component: { render: () => null } },
      ],
    });
    await router.push("/c/1/people/41");
    const { wrapper } = mountWithProviders(PersonPage, { plugins: [app.pinia, router, i18n, [VueQueryPlugin, { queryClient: app.client }]] });
    await flushPromises();
    await flushPromises();
    expect(wrapper.find("[data-person-org]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Department");
  });
});

describe("texts", () => {
  it("speak Russian plurals with three forms and Uzbek with one", () => {
    setLanguage("ru");
    expect([1, 3, 5, 21].map((n) => i18n.global.t("people.dept.count", { n }, n))).toEqual(["1 отдел", "3 отдела", "5 отделов", "21 отдел"]);
    expect(i18n.global.t("people.dept.people", { n: 2 }, 2)).toBe("2 человека");
    setLanguage("uz");
    expect(i18n.global.t("people.dept.count", { n: 5 }, 5)).toBe("5 ta bo‘lim");
    setLanguage("en");
    expect([1, 2].map((n) => i18n.global.t("people.dept.people", { n }, n))).toEqual(["1 person", "2 people"]);
  });
});
