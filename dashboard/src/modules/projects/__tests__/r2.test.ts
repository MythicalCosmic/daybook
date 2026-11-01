// Round 2 fixes: partial uploads, the card drawer's edits and links, ?new=1 and refetches.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FileDrop from "@/components/FileDrop.vue";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import CardDrawer from "../components/CardDrawer.vue";
import FilesTab from "../components/FilesTab.vue";
import ProjectFormDialog from "../components/ProjectFormDialog.vue";
import en from "../i18n/en.json";
import ProjectsPage from "../pages/ProjectsPage.vue";
import type { CardDetail, ProjectDetail } from "../types";

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
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const person = (id: number, name: string) => ({ id, name, photo_url: null });

function project(): ProjectDetail {
  return {
    id: 1,
    key: "OPEN",
    name: "Chilonzor branch opening",
    color: "chart-1",
    icon: "store",
    status: "active",
    priority: "high",
    visibility: "members",
    lead: person(12, "Bekzod Mirzayev"),
    branch: { id: 1, name: "Chilonzor" },
    client: null,
    start_on: "2026-09-11",
    due_on: "2026-10-27",
    completed_at: null,
    archived_at: null,
    progress: { done: 16, total: 30, overdue: 1, percent: 53 },
    health: "at_risk",
    reported: null,
    members: [person(12, "Bekzod Mirzayev")],
    member_count: 1,
    next_milestone: null,
    my_role: "member",
    currency: "UZS",
    budget: null,
    budget_currency: "UZS",
    spent: null,
    burn: null,
    description: "",
    created_at: "2026-09-06T09:00:00Z",
    created_by: null,
    lists: [{ id: 10, name: "To do", position: 1024, is_done: false, wip_limit: null }],
    labels: [],
    milestones: [],
    capabilities: { manage: true, edit_cards: true, assign_others: true, post_update: true, see_money: true, add_expense: true, see_labour: true, see_all_time: true },
  } as ProjectDetail;
}

function cardDetail(overrides: Partial<CardDetail> = {}): CardDetail {
  return {
    id: 100,
    number: 1,
    key: "OPEN-1",
    title: "Paint the walls",
    list_id: 10,
    position: 1024,
    status: "todo",
    priority: "normal",
    due_at: null,
    start_on: null,
    assignee: null,
    label_ids: [],
    milestone_id: null,
    checklist_done: 0,
    checklist_total: 0,
    comments: 0,
    proof: "none",
    proof_thumb: null,
    needs_confirmation: false,
    overdue: false,
    completed_at: null,
    minutes: 0,
    can_move: true,
    description: "Two coats.",
    created_at: "2026-10-20T09:00:00Z",
    created_by: null,
    checklist: [],
    recent_comments: [],
    time: [],
    actions: [],
    can_edit_task: true,
    proof_text: "",
    proof_photo: null,
    ...overrides,
  } as CardDetail;
}

beforeEach(() => {
  mergeModuleMessages("projects", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("FilesTab", () => {
  it("shows the files that went up when a later one in the same drop fails", async () => {
    let posts = 0;
    const calls = stubApi({
      "GET projects/1/files/": () => json([]),
      "GET projects/1/links/": () => json([]),
      "POST projects/1/files/": () => {
        posts += 1;
        return posts === 1 ? json({ id: 1, name: "plan.pdf" }, 201) : json({ file: ["Too big."] }, 400);
      },
    });
    const app = await testApp("/c/1/projects/1/files");
    const { wrapper } = mountWithProviders(FilesTab, { props: { project: project() }, plugins: app.plugins });
    await flushPromises();
    const files = [new File(["a"], "plan.pdf"), new File(["b"], "big.pdf")];
    wrapper.findComponent(FileDrop).vm.$emit("update:modelValue", files);
    await flushPromises();
    await flushPromises();
    expect(calls.filter((c) => c.method === "GET" && c.url.includes("/files/"))).toHaveLength(2);
    wrapper.unmount();
  });

  it("writes sizes with the language's decimal comma", async () => {
    stubApi({
      "GET projects/1/files/": () =>
        json([{ id: 1, name: "plan.pdf", kind: "pdf", size: 1.5 * 1024 * 1024, url: "/f/1", uploaded_by: null, created_at: "2026-10-20T09:00:00Z", can_delete: false }]),
      "GET projects/1/links/": () => json([]),
    });
    const app = await testApp("/c/1/projects/1/files", "ru");
    mergeModuleMessages("projects", { en, ru: en, uz: en });
    const { wrapper } = mountWithProviders(FilesTab, { props: { project: project() }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("1,5 MB");
    wrapper.unmount();
  });
});

describe("CardDrawer", () => {
  async function openCard(routes: Record<string, (call: Call) => Response | Promise<Response>>, overrides?: () => void) {
    const calls = stubApi(routes);
    const app = await testApp("/c/1/projects/1/board?card=100");
    overrides?.();
    const { wrapper } = mountWithProviders(CardDrawer, { props: { project: project() }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { calls, app, wrapper };
  }

  it("keeps the title being typed when the card refetches, and saves it once on Enter then blur", async () => {
    let gets = 0;
    const { calls, app, wrapper } = await openCard({
      "GET projects/1/cards/100/": () => {
        gets += 1;
        return json(cardDetail(gets > 1 ? { title: "Paint the walls (edited elsewhere)", comments: 1 } : {}));
      },
      "PATCH projects/1/cards/100/": () => new Promise<Response>(() => undefined),
    });
    const edit = document.body.querySelector<HTMLButtonElement>(`[aria-label="${en["projects.drawer.editTitle"]}"]`)!;
    edit.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>("header input")!;
    input.value = "Paint the walls white";
    input.dispatchEvent(new Event("input"));
    await app.client.invalidateQueries();
    await flushPromises();
    expect(document.body.querySelector<HTMLInputElement>("header input")!.value).toBe("Paint the walls white");
    const box = document.body.querySelector<HTMLInputElement>("header input")!;
    box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    box.dispatchEvent(new FocusEvent("blur"));
    await flushPromises();
    const patches = calls.filter((c) => c.method === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0]!.body).toEqual({ title: "Paint the walls white" });
    wrapper.unmount();
  });

  it("asks for the card once after a save (not a refetch plus an invalidation)", async () => {
    const { calls, wrapper } = await openCard({
      "GET projects/1/cards/100/": () => json(cardDetail()),
      "PATCH projects/1/cards/100/": () => json(cardDetail({ title: "New" })),
    });
    const edit = document.body.querySelector<HTMLButtonElement>(`[aria-label="${en["projects.drawer.editTitle"]}"]`)!;
    edit.click();
    await flushPromises();
    const input = document.body.querySelector<HTMLInputElement>("header input")!;
    input.value = "New";
    input.dispatchEvent(new Event("input"));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await flushPromises();
    await flushPromises();
    expect(calls.filter((c) => c.method === "GET" && c.url.includes("/cards/100/"))).toHaveLength(2);
    wrapper.unmount();
  });

  it("offers Open in Tasks only to people who may open Tasks", async () => {
    const { wrapper } = await openCard({ "GET projects/1/cards/100/": () => json(cardDetail()) }, () => {
      useSessionStore().me = me([company({ is_owner: false, permissions: ["projects.manage"] })]);
    });
    expect(document.body.textContent).not.toContain(en["projects.drawer.openTask"]);
    wrapper.unmount();
  });
});

describe("ProjectsPage KPI strip", () => {
  it("says the summary failed and offers Try again", async () => {
    stubApi({
      "GET projects/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "GET projects/summary/": () => json({ detail: "Server error." }, 500),
      "GET projects/people/": () => json([]),
      "GET projects/options/": () => json({ branches: [], clients: [], currency: "UZS", can_create: true }),
    });
    const app = await testApp("/c/1/projects");
    const { wrapper } = mountWithProviders(ProjectsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect([...document.body.querySelectorAll("button")].some((b) => b.textContent?.trim() === "Try again")).toBe(true);
    wrapper.unmount();
  });
});

describe("ProjectsPage ?new=1", () => {
  it("doesn't open the new project form for someone who can't create one", async () => {
    stubApi({
      "GET projects/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "GET projects/summary/": () => json({ active: 0, planning: 0, at_risk: 0, off_track: 0, overdue_cards: 0, due_this_week: 0, hours_this_week: 0, budget: null, spent: null, currency: "UZS" }),
      "GET projects/people/": () => json([]),
      "GET projects/options/": () => json({ branches: [], clients: [], currency: "UZS", can_create: false }),
    });
    const app = await testApp("/c/1/projects?new=1");
    useSessionStore().me = me([company({ is_owner: false, permissions: [] })]);
    const { wrapper } = mountWithProviders(ProjectsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.findComponent(ProjectFormDialog).props("open")).toBe(false);
    expect(app.router.currentRoute.value.query.new).toBeUndefined();
    wrapper.unmount();
  });
});
