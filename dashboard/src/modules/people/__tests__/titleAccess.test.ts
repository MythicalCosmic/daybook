// A job title gives its access: shown and changed in People › Positions (for those who hold it
// too), suggested when approving one person or several, and said when editing someone.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SelectBox from "@/components/SelectBox.vue";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { AS_LINK, bulkStart } from "../bulk";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { JoinRequest, PersonDetail, PositionRow, Role } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json([]);
    }),
  );
  return calls;
}

function role(overrides: Partial<Role>): Role {
  return { id: 3, name: "Xodim", permissions: [], is_owner: false, is_default: false, members_count: 4, can_edit: true, can_assign: true, ...overrides };
}
const ROLES = [
  role({ id: 1, name: "Egasi", is_owner: true }),
  role({ id: 3, name: "Xodim", is_default: true }),
  role({ id: 5, name: "Kassir" }),
  role({ id: 6, name: "Menejer", can_assign: false }),
];

function title(id: number, name: string, given: { id: number; name: string } | null, members = 0): PositionRow {
  return { id, name, order: id, is_active: true, members_count: members, role: given && { ...given, is_owner: false } };
}
const POSITIONS = [title(9, "Kassir", { id: 5, name: "Kassir" }, 3), title(10, "Farrosh", null, 1), title(11, "Bosh menejer", { id: 6, name: "Menejer" })];

function request(id: number, positionId: number | null, overrides: Partial<JoinRequest> = {}): JoinRequest {
  const position = POSITIONS.find((p) => p.id === positionId);
  return {
    id,
    name: `Person ${id}`,
    first_name: "Person",
    last_name: `${id}`,
    photo_url: null,
    phone: "",
    username: "",
    position: position ? { id: position.id, name: position.name } : null,
    onboarded: true,
    requested_at: "2026-10-30T04:00:00Z",
    former: null,
    join_link: null,
    fields: {},
    ...overrides,
  };
}

function person(overrides: Partial<PersonDetail>): PersonDetail {
  return {
    id: 21,
    name: "Aziza Karimova",
    full_name: "Aziza Karimova",
    first_name: "Aziza",
    last_name: "Karimova",
    photo_url: null,
    phone: "",
    username: "",
    position: { id: 9, name: "Kassir" },
    role: { id: 5, name: "Kassir", is_owner: false },
    home_branch: null,
    branches: [],
    status: "approved",
    suspended_until: null,
    joined_on: "2026-10-01",
    left_on: null,
    onboarded: true,
    bot_blocked: false,
    work: { on_time_30d: null, done_30d: 0, late_now: 0, open_now: 0 },
    fields: {},
    language: "uz",
    overview: {} as PersonDetail["overview"],
    can: { edit: true, change_role: true } as PersonDetail["can"],
    role_follows_title: true,
    ...overrides,
  };
}

beforeEach(() => {
  mergeModuleMessages("people", { en, ru, uz });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  toasts.splice(0);
});

describe("People › Positions", () => {
  it("says the access each title gives, and gives a new one to those who hold it", async () => {
    const calls = stub({
      "GET positions/": () => json(POSITIONS),
      "GET roles/": () => json(ROLES),
      "PATCH positions/10/": () => json({ ...title(10, "Farrosh", { id: 5, name: "Kassir" }, 1), applied: 1 }),
    });
    const app = await testApp("/c/1/people/positions");
    const { default: PositionsPage } = await import("../pages/PositionsPage.vue");
    const { wrapper } = mountWithProviders(PositionsPage, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("Access: Kassir");
    expect(wrapper.text()).toContain("Access: Xodim"); // Farrosh: the default role
    const page = wrapper.element as HTMLElement;
    const row = [...page.querySelectorAll<HTMLElement>("*")].find((el) => el.children.length === 0 && el.textContent === "Farrosh")!;
    row.click();
    await flushPromises();
    wrapper.findComponent(SelectBox).vm.$emit("update:modelValue", 5);
    await flushPromises();
    expect(document.querySelector("[data-apply-holders]")?.textContent).toContain("Also give it to those who hold it now (1)");
    [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === "Save")!.click();
    await flushPromises();

    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Farrosh", is_active: true, role_id: 5, apply_to_holders: true });
    expect(toasts.map((toast) => toast.title)).toContain("Saved “Farrosh”: 1 person got the new access");
  });
});

describe("approving", () => {
  async function approveWith(positionId: number | null) {
    stub({ "GET roles/": () => json(ROLES), "GET positions/": () => json(POSITIONS) });
    const app = await testApp("/c/1/people/requests");
    useSessionStore().me = me([company()]);
    const { default: ApproveDialog } = await import("../components/ApproveDialog.vue");
    const { inner } = mountWithProviders(ApproveDialog, { plugins: app.plugins, props: { open: true, request: request(1, positionId) } });
    await flushPromises();
    [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === "Approve")!.click();
    await flushPromises();
    return (inner.emitted("approve")?.[0]?.[0] as { role_id: number }).role_id;
  }

  it("starts from the role the job title gives, when the approver may give it", async () => {
    expect(await approveWith(9)).toBe(5); // Kassir gives Kassir
    document.body.innerHTML = "";
    expect(await approveWith(11)).toBe(3); // Menejer isn't theirs to give: the default role
    document.body.innerHTML = "";
    expect(await approveWith(10)).toBe(3); // a title without access of its own
  });

  it("starts a group from each one's own role when anyone has one through their job title", () => {
    const branches = [{ id: 1, name: "Chilonzor", code: "CHL" }];
    expect(bulkStart([request(1, 9), request(2, 10)], ROLES, branches, POSITIONS)).toMatchObject({ role: AS_LINK, linkRoles: "some" });
    expect(bulkStart([request(1, 9)], ROLES, branches, POSITIONS)).toMatchObject({ role: AS_LINK, linkRoles: "all" });
    expect(bulkStart([request(1, 10)], ROLES, branches, POSITIONS)).toMatchObject({ role: 3, linkRoles: "none" });
  });
});

describe("editing someone", () => {
  async function edit(detail: PersonDetail) {
    stub({ "GET roles/": () => json(ROLES), "GET positions/": () => json(POSITIONS), "GET departments/": () => json([]) });
    const app = await testApp("/c/1/people/21");
    useSessionStore().me = me([company()]);
    const { default: PersonEditDialog } = await import("../components/PersonEditDialog.vue");
    const mounted = mountWithProviders(PersonEditDialog, { plugins: app.plugins, props: { open: true, person: detail } });
    await flushPromises();
    return mounted;
  }
  const note = () => document.querySelector("[data-access-note]")?.textContent?.trim();

  it("says the access comes with the job title, and follows a new one", async () => {
    const { wrapper } = await edit(person({}));
    expect(note()).toBe("Access: Kassir, from the job title");

    wrapper.findAllComponents(SelectBox)[0]!.vm.$emit("update:modelValue", 10);
    await flushPromises();
    expect(note()).toBe("Access: Xodim, from the job title");
    // The role by hand is the advanced part, out of the way.
    expect(document.querySelector("[data-access-advanced]")?.textContent).toContain("Change access by hand");
  });

  it("says when the access was set by hand or is the Owner role, so a new title won't move it", async () => {
    await edit(person({ role: { id: 6, name: "Menejer", is_owner: false }, role_follows_title: false }));
    expect(note()).toBe("Access: Menejer, set by hand: a new job title doesn't change it");
    document.body.innerHTML = "";
    await edit(person({ role: { id: 1, name: "Egasi", is_owner: true }, role_follows_title: false }));
    expect(note()).toBe("Access: Owner. A new job title doesn't change it.");
  });
});
