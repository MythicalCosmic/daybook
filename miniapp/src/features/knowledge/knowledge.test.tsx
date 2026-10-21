/** The knowledge base feature: cleaning bodies, reading a page and confirming it. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Me, Membership, Task } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { NavigationProvider, useNavigation, type Navigation } from "../../state/navigation";
import { SessionProvider } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import { collectFeatures, type Feature } from "../registry";
import { flattenTree, kbKeys, type KbLink, type KbPage } from "./api";
import { HowTo } from "./HowTo";
import { PageReader } from "./PageReader";
import { safeHtml } from "./safeHtml";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", () => ({ api }));

// The registry (imported above) loads every feature folder first; this is the same module.
const { default: feature } = await import("./index");

function membership(): Membership {
  return {
    id: 7,
    company: { id: 1, name: "Demo Shop", timezone: "Asia/Tashkent", features: [], owner_sees_personal_tasks: false, base_currency: "UZS", team_directory_phones: false },
    status: "approved",
    first_name: "Madina",
    last_name: "Saidova",
    position: null,
    role: "Employee",
    permissions: [],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    home_branch: null,
    branch_ids: [],
    suspended_until: null,
  } as unknown as Membership;
}

const page = (overrides: Partial<KbPage> = {}): KbPage => ({
  id: 5,
  title: "Kassani ochish tartibi",
  emoji: "🔓",
  space: { id: 2, name: "Kassa", icon: "💰" },
  parent_id: null,
  require_ack: true,
  version: 3,
  updated_at: "2026-10-20T09:00:00+05:00",
  updated_by: null,
  excerpt: "",
  body: '<h2>Ochish</h2><p>Razmenni sanang</p><script>alert(1)</script><ul data-type="taskList"><li data-type="taskItem" data-checked="false"><label><input type="checkbox"></label><div><p>Terminal</p></div></li></ul>',
  ack_version: 3,
  breadcrumbs: [],
  children: [],
  my_ack: null,
  ...overrides,
});

function renderWith(node: ReactNode, client: QueryClient) {
  const me = { id: 1, telegram_id: 1004, telegram_username: "", first_name: "Madina", last_name: "Saidova", phone: "", memberships: [membership()] } as Me;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={me}>
            <NavigationProvider>{node}</NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  api.mockReset();
});

describe("safeHtml", () => {
  it("keeps the editor's markup, drops anything that could run, makes checklists read-only", () => {
    const clean = safeHtml(
      '<p onclick="steal()">Hi <a href="javascript:x">bad</a> <a href="https://t.me/x">ok</a></p><script>alert(1)</script><img src="x" onerror="alert(1)"><img src="/api/v1/files/t/" data-image-id="3"><div data-callout="warning" style="color:red"><p>Careful</p></div><input type="checkbox" checked>',
    );
    expect(clean).not.toMatch(/script|onclick|onerror|javascript|style=/);
    expect(clean).toContain('<a href="https://t.me/x" target="_blank" rel="noopener noreferrer">ok</a>');
    expect(clean).toContain('<img src="/api/v1/files/t/" data-image-id="3">');
    expect(clean).not.toContain('src="x"');
    expect(clean).toContain('<div data-callout="warning">');
    expect(clean).toMatch(/<input type="checkbox" checked="" disabled="">/);
  });
});

describe("flattenTree", () => {
  it("lists pages top to bottom with their depth", () => {
    const rows = flattenTree([{ id: 1, title: "A", emoji: "", require_ack: false, children: [{ id: 2, title: "B", emoji: "", require_ack: false, children: [] }] }]);
    expect(rows.map(({ node, depth }) => [node.id, depth])).toEqual([
      [1, 0],
      [2, 1],
    ]);
  });
});

describe("PageReader", () => {
  it("shows the page and confirms it with I've read it, at once", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(kbKeys.page(1, 5), page());
    let release!: () => void;
    api.mockImplementation((_path: string, options?: { method?: string }) => {
      if (options?.method === "POST") return new Promise((resolve) => (release = () => resolve({ version: 3, at: "2026-10-21T09:00:00Z" })));
      return Promise.resolve(page({ my_ack: { version: 3, at: "2026-10-21T09:00:00Z", current: true } }));
    });
    const { container } = renderWith(<PageReader params={{ id: 5 }} />, client);

    expect(screen.getByText("Please read it to the end and confirm.")).toBeTruthy();
    expect(container.querySelector(".kbm-article h2")?.textContent).toBe("Ochish");
    expect(container.querySelector(".kbm-article script")).toBeNull();
    expect(container.querySelector(".kbm-article input")?.hasAttribute("disabled")).toBe(true);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /I’ve read it/ }));
    });
    // Optimistic: confirmed before the server answered.
    await waitFor(() => expect(screen.getByText("You’ve read version 3.")).toBeTruthy());
    expect(api).toHaveBeenCalledWith("/companies/1/knowledge/pages/5/ack/", { method: "POST" });
    await act(async () => release());
    await waitFor(() => expect(screen.queryByRole("button", { name: /I’ve read it/ })).toBeNull());
  });

  it("asks again when the server refuses", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    client.setQueryData(kbKeys.page(1, 5), page());
    api.mockImplementation((_path: string, options?: { method?: string }) => (options?.method === "POST" ? Promise.reject(new Error("403")) : Promise.resolve(page())));
    renderWith(<PageReader params={{ id: 5 }} />, client);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /I’ve read it/ }));
    });
    await waitFor(() => expect(screen.getByText("Please read it to the end and confirm.")).toBeTruthy());
  });
});

describe("How to do this, on the task screen", () => {
  const member = { ...membership(), timeZone: "Asia/Tashkent", companyId: 1 };
  const task = { id: 42, title: "Kassani ochish", status: "todo" } as Task;
  const link = (id: number, pageId: number, title: string, target: "task" | "routine" = "task"): KbLink => ({
    id,
    target_type: target,
    target_id: target === "task" ? 42 : 66,
    target_title: "Kassani ochish",
    page: { id: pageId, title, emoji: pageId === 5 ? "🔓" : "", space: { id: 2, name: "Kassa", icon: "💰" } },
    created_at: "2026-10-20T09:00:00Z",
  });
  let nav: Navigation | null = null;
  function Probe() {
    nav = useNavigation();
    return null;
  }

  it("is registered first among the task screen's blocks", () => {
    const { features, problems } = collectFeatures({ "./knowledge/index.ts": { default: feature } });
    expect(problems).toEqual([]);
    expect((features as Feature[])[0]!.taskActions?.map((slot) => [slot.id, slot.order])).toEqual([["howTo", 10]]);
  });

  it("lists the task's pages and its routine's, each once, and opens one in the reader", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    api.mockResolvedValue([link(1, 5, "Kassani ochish tartibi", "routine"), link(2, 9, "Terminal"), link(3, 5, "Kassani ochish tartibi")]);
    const { container } = renderWith(
      <>
        <HowTo member={member} summary={undefined} task={task} />
        <Probe />
      </>,
      client,
    );

    expect(await screen.findByText("How to do this")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/companies/1/knowledge/linked/?target_type=task&target_id=42");
    const rows = [...container.querySelectorAll(".list-item")];
    expect(rows.map((row) => row.querySelector(".list-item-text > span")?.textContent)).toEqual(["Kassani ochish tartibi", "Terminal"]);
    expect(rows[0]!.textContent).toContain("💰 Kassa");
    expect(rows[1]!.querySelector(".kbm-emoji")?.textContent).toBe("📄");
    act(() => fireEvent.click(rows[1]!));
    expect(nav!.stack).toEqual([{ feature: "knowledge", page: "page", params: { id: 9 } }]);
  });

  it("shows nothing when no page is linked", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    api.mockResolvedValue([]);
    const { container } = renderWith(<HowTo member={member} summary={undefined} task={task} />, client);
    await waitFor(() => expect(api).toHaveBeenCalled());
    await act(async () => {});
    expect(container.textContent).toBe("");
  });
});
