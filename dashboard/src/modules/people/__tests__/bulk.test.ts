// Join requests in bulk: selection, what the bulk approve dialog starts with, the body it sends,
// the answer's handling on the page, and the single approval starting from the team link.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import type { BranchRef } from "@/api/types";
import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { toasts } from "@/components/useToast";
import { i18n, mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import { decideRequests } from "../api";
import { AS_LINK, bulkApproveBody, bulkOutcome, bulkStart, namesLine, useSelection } from "../bulk";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { JoinRequest, Role } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const t = (key: string, params?: Record<string, unknown>) => i18n.global.t(key, params ?? {});

const CHILONZOR: BranchRef = { id: 1, name: "Chilonzor", code: "CHL" };
const YUNUSOBOD: BranchRef = { id: 2, name: "Yunusobod", code: "YNS" };
const MEETING = { id: 5, name: "Xodimlar yig‘ilishi", auto_approve: false, branch: { id: 2, name: "Yunusobod" }, role: { id: 4, name: "Farmatsevt" } };

function request(id: number, overrides: Partial<JoinRequest> = {}): JoinRequest {
  return {
    id,
    name: `Person ${id}`,
    first_name: `Person`,
    last_name: `${id}`,
    photo_url: null,
    phone: "",
    username: "",
    position: { id: 9, name: "Farmatsevt" },
    onboarded: true,
    requested_at: "2026-10-26T04:00:00Z",
    former: null,
    join_link: null,
    fields: {},
    ...overrides,
  };
}

function role(overrides: Partial<Role>): Role {
  return { id: 3, name: "Xodim", permissions: [], is_owner: false, is_default: false, members_count: 4, can_edit: true, can_assign: true, ...overrides };
}
const ROLES = [role({ id: 1, name: "Egasi", is_owner: true }), role({ id: 3, name: "Xodim", is_default: true }), role({ id: 4, name: "Farmatsevt" })];

beforeEach(() => {
  mergeModuleMessages("people", { en, ru, uz });
});

afterEach(() => {
  vi.unstubAllGlobals();
  confirmQueue.value = [];
  toasts.splice(0, toasts.length);
  document.body.innerHTML = "";
});

describe("useSelection", () => {
  it("toggles one or all, knows all from some, and lets go of ids that leave the list", async () => {
    const ids = ref([1, 2, 3]);
    const selection = useSelection(() => ids.value);
    selection.toggle(2, true);
    selection.toggle(2, true);
    expect(selection.selected.value).toEqual([2]);
    expect([selection.all.value, selection.some.value]).toEqual([false, true]);
    selection.toggleAll(true);
    expect(selection.all.value).toBe(true);
    ids.value = [1, 3, 4];
    await nextTick();
    expect(selection.selected.value).toEqual([1, 3]);
    expect(selection.all.value).toBe(false);
    selection.toggle(1, false);
    expect(selection.selected.value).toEqual([3]);
    selection.clear();
    expect(selection.some.value).toBe(false);
  });
});

describe("bulkStart", () => {
  it("starts from 'as their link says' and their shared branch when everyone's link names them", () => {
    const rows = [request(1, { join_link: MEETING }), request(2, { join_link: MEETING })];
    expect(bulkStart(rows, ROLES, [CHILONZOR, YUNUSOBOD])).toEqual({
      role: AS_LINK,
      linkRoles: "all",
      branchIds: [2],
      homeId: 2,
      everyoneHasBranch: true,
      branchRequired: false,
    });
  });

  it("starts from the default role when someone's link names none, and asks for branches when someone came without one", () => {
    const rows = [request(1, { join_link: MEETING }), request(2)];
    expect(bulkStart(rows, ROLES, [CHILONZOR, YUNUSOBOD])).toMatchObject({ role: 3, linkRoles: "some", branchIds: [], homeId: null, everyoneHasBranch: false, branchRequired: true });
    expect(bulkStart([request(3)], ROLES, [CHILONZOR, YUNUSOBOD])).toMatchObject({ role: 3, linkRoles: "none", branchRequired: true });
    // One branch: nothing to choose.
    expect(bulkStart(rows, ROLES, [CHILONZOR]).branchRequired).toBe(false);
  });

  it("leaves the branches empty (each to their own link's) when their links name different ones, or one the approver can't give", () => {
    const elsewhere = { ...MEETING, id: 6, branch: { id: 1, name: "Chilonzor" } };
    expect(bulkStart([request(1, { join_link: MEETING }), request(2, { join_link: elsewhere })], ROLES, [CHILONZOR, YUNUSOBOD])).toMatchObject({
      branchIds: [],
      everyoneHasBranch: true,
      branchRequired: false,
    });
    expect(bulkStart([request(1, { join_link: MEETING })], ROLES, [CHILONZOR]).branchIds).toEqual([]);
  });
});

describe("bulkApproveBody and bulkOutcome", () => {
  it("sends only what was chosen for everyone", () => {
    expect(bulkApproveBody([1, 2], { role: AS_LINK, positionId: null, branchIds: [], homeId: null }, true)).toEqual({ ids: [1, 2], action: "approve" });
    expect(bulkApproveBody([1, 2], { role: 4, positionId: 9, branchIds: [1, 2], homeId: 2 }, true)).toEqual({
      ids: [1, 2],
      action: "approve",
      role_id: 4,
      position_id: 9,
      branch_ids: [1, 2],
      home_branch_id: 2,
    });
    // With one branch the backend picks it.
    expect(bulkApproveBody([1], { role: 3, positionId: null, branchIds: [1], homeId: 1 }, false)).toEqual({ ids: [1], action: "approve", role_id: 3 });
  });

  it("counts who went through and names who didn't, with the reason", () => {
    const rows = [request(1), request(2, { name: "Zarina Abdullayeva" })];
    const outcome = bulkOutcome(
      { results: [{ id: 1, ok: true, detail: "" }, { id: 2, ok: false, detail: "They haven't filled in their details yet." }, { id: 9, ok: false, detail: "This request no longer exists." }], done: 1, failed: 2 },
      rows,
    );
    expect(outcome.done).toBe(1);
    expect(outcome.failed).toEqual([
      { id: 2, name: "Zarina Abdullayeva", detail: "They haven't filled in their details yet." },
      { id: 9, name: "#9", detail: "This request no longer exists." },
    ]);
  });

  it("lists a few names and counts the rest", () => {
    expect(namesLine(["A", "B", "C", "D"], t)).toBe("A, B, C, D");
    expect(namesLine(["A", "B", "C", "D", "E", "F"], t)).toBe("A, B, C and 3 more");
  });

  it("posts to join-requests/bulk/", async () => {
    const calls = stub({ "POST join-requests/bulk/": () => json({ results: [], done: 0, failed: 0 }) });
    await decideRequests(1, { ids: [3, 4], action: "reject", reason: "Not hiring" });
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/v1/owner/companies/1/join-requests/bulk/", body: { ids: [3, 4], action: "reject", reason: "Not hiring" } });
  });
});

describe("RequestsPage", () => {
  const rows = () => [
    request(1, { name: "Aziza Karimova", join_link: MEETING }),
    request(2, { name: "Zarina Abdullayeva", join_link: MEETING }),
    request(3, { name: "Laylo Hamidova" }),
    request(4, { name: "Bahodir Ergashev", onboarded: false }),
  ];

  it("selects all ready requests, approves them in one go, and keeps the refused one selected with the reason", async () => {
    let list = rows();
    const calls = stub({
      "GET join-requests/": () => json(list),
      "GET roles/": () => json(ROLES),
      "GET positions/": () => json([]),
      "POST join-requests/bulk/": (call) => {
        const ids = (call.body as { ids: number[] }).ids;
        list = list.filter((row) => row.id === 3 || !ids.includes(row.id));
        return json({ results: ids.map((id) => ({ id, ok: id !== 3, detail: id === 3 ? "You can't give this role." : "" })), done: ids.length - 1, failed: 1 });
      },
    });
    const app = await testApp("/c/1/people/requests");
    const { default: RequestsPage } = await import("../pages/RequestsPage.vue");
    const { wrapper } = mountWithProviders(RequestsPage, { plugins: app.plugins });
    await flushPromises();

    // The ones who came through a team link say so; someone still filling in can't be picked.
    expect(wrapper.findAll("[data-via]").map((chip) => chip.text())).toEqual(["Via “Xodimlar yig‘ilishi”", "Via “Xodimlar yig‘ilishi”"]);
    expect(wrapper.find("[data-select-all]").text()).toContain("Select all (3)");
    await wrapper.find("[data-select-all] button[role=checkbox]").trigger("click");
    await flushPromises();
    expect(document.body.textContent).toContain("3 selected");

    document.querySelector<HTMLButtonElement>("[data-bulk-approve]")!.click();
    // The dialog loads on first use.
    await vi.waitFor(() => expect(document.querySelector("[data-bulk-confirm]")).not.toBeNull());
    await flushPromises();
    expect(document.querySelector("[data-bulk-who]")!.textContent).toContain("Aziza Karimova, Zarina Abdullayeva, Laylo Hamidova");
    // Not everyone's link names a role: the default role for all, unless changed.
    document.querySelector<HTMLButtonElement>("[data-bulk-confirm]")!.click();
    await flushPromises();
    await flushPromises();

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ ids: [1, 2, 3], action: "approve", role_id: 3 });
    expect(toasts.map((toast) => toast.title)).toContain("2 people are on the team");
    const failures = wrapper.find("[data-bulk-failures]");
    expect(failures.text()).toContain("1 person couldn’t be approved");
    expect(failures.text()).toContain("Laylo Hamidova · You can't give this role.");
    expect(document.body.textContent).toContain("1 selected");
    expect(wrapper.findAll("[data-request]")).toHaveLength(1);
  });

  it("rejects the selected ones after asking, with an optional reason", async () => {
    const calls = stub({
      "GET join-requests/": () => json(rows()),
      "GET roles/": () => json(ROLES),
      "GET positions/": () => json([]),
      "POST join-requests/bulk/": () => json({ results: [{ id: 1, ok: true, detail: "" }, { id: 2, ok: true, detail: "" }], done: 2, failed: 0 }),
    });
    const app = await testApp("/c/1/people/requests");
    const { default: RequestsPage } = await import("../pages/RequestsPage.vue");
    const { wrapper } = mountWithProviders(RequestsPage, { plugins: app.plugins });
    await flushPromises();
    for (const id of [1, 2]) await wrapper.find(`[data-request="${id}"] button[role=checkbox]`).trigger("click");
    document.querySelector<HTMLButtonElement>("[data-bulk-reject]")!.click();
    await flushPromises();
    expect(confirmQueue.value[0]?.request.title).toBe("Reject 2 requests?");
    settleConfirm(confirmQueue.value[0]!.id, { reason: "Not hiring now" }, 0);
    await flushPromises();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ ids: [1, 2], action: "reject", reason: "Not hiring now" });
    expect(toasts.map((toast) => toast.title)).toContain("2 requests rejected");
    expect(wrapper.find("[data-bulk-failures]").exists()).toBe(false);
  });

  it("links to the team links from the header", async () => {
    stub({ "GET join-requests/": () => json([]) });
    const app = await testApp("/c/1/people/requests");
    const { default: RequestsPage } = await import("../pages/RequestsPage.vue");
    const { wrapper } = mountWithProviders(RequestsPage, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("[data-team-links]").attributes("href")).toBe("/c/1/settings/invite#team-links");
  });
});

describe("ApproveDialog", () => {
  it("starts from the team link's role and branch when the approver may give them", async () => {
    stub({ "GET roles/": () => json(ROLES), "GET positions/": () => json([]) });
    const app = await testApp("/c/1/people/requests");
    useSessionStore().me = me([company({ branches: [CHILONZOR, YUNUSOBOD] })]);
    const { default: ApproveDialog } = await import("../components/ApproveDialog.vue");
    const { inner } = mountWithProviders(ApproveDialog, { plugins: app.plugins, props: { open: true, request: request(1, { join_link: MEETING }) } });
    await flushPromises();
    expect(document.querySelector("[data-from-link]")?.textContent).toContain("Filled in from the team link “Xodimlar yig‘ilishi”.");
    const confirmButton = [...document.querySelectorAll("button")].find((button) => button.textContent?.trim() === "Approve")!;
    confirmButton.click();
    await flushPromises();
    expect(inner.emitted("approve")?.[0]?.[0]).toEqual({ role_id: 4, position_id: 9, branch_ids: [2], home_branch_id: 2 });
  });
});
