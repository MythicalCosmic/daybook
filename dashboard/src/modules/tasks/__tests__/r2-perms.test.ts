// Round 2: what people without the matching permission no longer see (bulk actions, answers,
// links to pages that would only say "no access").
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import DataTable from "@/components/DataTable.vue";
import { useDataTable } from "@/components/useDataTable";
import { toasts } from "@/components/useToast";
import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import TasksTable from "../components/TasksTable.vue";
import en from "../i18n/en.json";
import type { TaskRow } from "../types";
import OnTimeWidget from "../widgets/OnTimeWidget.vue";

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
      const query = input.split("?")[1] ?? "";
      return (routes[`${call.method} ${path}?${query}`] ?? routes[`${call.method} ${path}`])?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const person = (id: number, name: string) => ({ id, name, photo_url: null, position: "Farmatsevt" });

const row = (overrides: Partial<TaskRow> = {}): TaskRow =>
  ({
    id: 7,
    kind: "assigned",
    title: "Update the flu-season shelf",
    status: "todo",
    priority: "normal",
    due_at: "2026-10-26T13:00:00Z",
    for_date: null,
    is_overdue: false,
    assignee: person(12, "Alisher Valiyev"),
    created_by: person(99, "Bekzod Mirzayev"),
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    routine: null,
    project: null,
    proof: "none",
    needs_confirmation: false,
    has_proof: false,
    proof_thumb: null,
    proof_photo: null,
    checklist: { done: 0, total: 0 },
    reward: null,
    started_at: null,
    completed_at: null,
    confirmed_at: null,
    created_at: "2026-10-24T13:30:00Z",
    moves: [],
    seen_at: null,
    blocker: null,
    extension: null,
    ...overrides,
  }) as TaskRow;

const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });

function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions })]);
}

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("TasksTable bulk actions", () => {
  async function mountTable(permissions: Perm[]) {
    stub({ "GET tasks/": () => json(page([row()])) });
    const app = await testApp("/c/1/tasks");
    as(permissions);
    const Host = defineComponent({
      setup: () => {
        const state = useDataTable({ id: "tasks.r2" });
        return () => h(TasksTable, { state, params: {}, filtered: false, activeId: null });
      },
    });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return wrapper;
  }

  it("lets nobody select rows who can neither assign nor confirm (tasks/bulk/ refuses them)", async () => {
    const wrapper = await mountTable(["tasks.view_all"]);
    expect((wrapper.findComponent(DataTable).props() as { selectable?: boolean }).selectable).toBe(false);
    wrapper.unmount();
  });

  it("keeps selection for people who confirm", async () => {
    const wrapper = await mountTable(["tasks.view_all", "tasks.confirm"]);
    expect((wrapper.findComponent(DataTable).props() as { selectable?: boolean }).selectable).toBe(true);
    wrapper.unmount();
  });
});

describe("ReviewsPage more-time answers", () => {
  it("shows Approve/Decline only to people who may decide, Open to the others", async () => {
    stub({
      "GET tasks/reviews/": () => json(page([])),
      "GET tasks/?extension=true&page_size=50": () => json(page([row({ id: 8, extension: { until: "2026-10-25T13:00:00Z", note: "", at: "2026-10-25T02:00:00Z" } })])),
      "GET tasks/?blocked=true&page_size=50": () => json(page([])),
    });
    const app = await testApp("/c/1/tasks/reviews");
    as(["tasks.view_all"]);
    const { default: ReviewsPage } = await import("../pages/ReviewsPage.vue");
    const { wrapper } = mountWithProviders(ReviewsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const answers = document.body.querySelector("[data-testid=answers]")!;
    expect(answers.querySelector("[data-testid=answer-approve]")).toBeNull();
    expect(answers.textContent).toContain(en["tasks.answers.open"]);
    wrapper.unmount();
  });
});

describe("links to pages the viewer may not open", () => {
  it("the on-time tile links to the team report only for people with reports.view", async () => {
    stub({ "GET tasks/summary/": () => json({ on_time_percent: 90, on_time_previous: 80, series: [] }) });
    const app = await testApp("/c/1");
    as(["tasks.view_all"]);
    const { wrapper } = mountWithProviders(OnTimeWidget, { props: { companyId: 1 }, plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("a[href*='reports/team']").exists()).toBe(false);
    wrapper.unmount();
  });
});
