// Ask AI: deleting a conversation from the list or from its own header, after a confirm; the open
// one gives way to a new chat.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import AskPage from "../pages/AskPage.vue";
import type { Conversation } from "../types";
import { status } from "./fixtures";

interface Call {
  method: string;
  url: string;
}

const CONVERSATIONS: Conversation[] = [
  { id: 3, title: "Kim kechikdi?", created_at: "2026-11-09T09:00:00+05:00", last_activity_at: "2026-11-09T09:05:00+05:00" },
  { id: 2, title: "Muzlatgich", created_at: "2026-11-08T09:00:00+05:00", last_activity_at: "2026-11-08T09:05:00+05:00" },
];

function stubApi(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: String(input) };
      calls.push(call);
      if (call.method === "DELETE") return new Response(null, { status: 204 });
      if (call.url.includes("/ai/status/")) return json(status());
      if (call.url.includes("/messages/")) return json([{ id: 1, role: "user", text: "Kim kechikdi?", created_at: "2026-11-09T09:00:00+05:00", steps: [] }]);
      if (call.url.includes("/ai/conversations/")) return json(CONVERSATIONS);
      return json({});
    }),
  );
  return calls;
}

async function page(path: string) {
  const calls = stubApi();
  const made = await testApp("/c/1/ai");
  for (const [name, at] of [
    ["ai.agents", "/c/:companyId/ai"],
    ["ai.agent", "/c/:companyId/ai/agents/:key"],
    ["ai.activity", "/c/:companyId/ai/activity"],
    ["ai.voice", "/c/:companyId/ai/voice"],
    ["ai.ask", "/c/:companyId/ai/ask"],
  ] as const) {
    made.router.addRoute({ path: at, name, component: { render: () => null } });
  }
  await made.router.replace(path);
  const { wrapper } = mountWithProviders(AskPage, { plugins: made.plugins });
  await flushPromises();
  await flushPromises();
  return { wrapper, calls, app: made };
}

async function answer(yes: boolean): Promise<void> {
  await flushPromises();
  const [request] = confirmQueue.value;
  settleConfirm(request!.id, yes ? { reason: "" } : null, 0);
  await flushPromises();
  await flushPromises();
}

beforeEach(() => {
  mergeModuleMessages("ai", { en, ru, uz });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  confirmQueue.value = [];
});

describe("deleting an Ask AI conversation", () => {
  it("deletes one from the list after a confirm and leaves the open one alone", async () => {
    const { wrapper, calls, app } = await page("/c/1/ai/ask?c=3");

    await wrapper.find("[data-conversation='2'] [data-testid=ai-delete-conversation]").trigger("click");
    expect(confirmQueue.value[0]!.request.message).toContain("Muzlatgich");
    await answer(true);

    expect(calls.find((call) => call.method === "DELETE")!.url).toContain("/ai/conversations/2/");
    expect(wrapper.find("[data-conversation='2']").exists()).toBe(false);
    expect(app.router.currentRoute.value.query.c).toBe("3");
  });

  it("deletes the open one from its header and starts a new chat", async () => {
    const { wrapper, calls, app } = await page("/c/1/ai/ask?c=3");

    expect(wrapper.find("[data-testid=ai-thread-header]").text()).toContain("Kim kechikdi?");
    await wrapper.find("[data-testid=ai-delete-open]").trigger("click");
    await answer(true);

    expect(calls.find((call) => call.method === "DELETE")!.url).toContain("/ai/conversations/3/");
    expect(app.router.currentRoute.value.query.c).toBeUndefined();
    expect(wrapper.find("[data-testid=ai-thread-header]").exists()).toBe(false);
    expect(wrapper.find("[data-suggestion=late]").exists()).toBe(true);
  });

  it("deletes nothing when the confirm is cancelled", async () => {
    const { wrapper, calls } = await page("/c/1/ai/ask?c=3");

    await wrapper.find("[data-testid=ai-delete-open]").trigger("click");
    await answer(false);

    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    expect(wrapper.find("[data-conversation='3']").exists()).toBe(true);
  });

  it("has the texts in every language", () => {
    for (const messages of [en, uz, ru] as Record<string, string>[]) {
      for (const key of ["ai.chat.delete", "ai.chat.deleteAria", "ai.chat.deleteTitle", "ai.chat.deleteBody", "ai.chat.deleted"]) {
        expect(messages[key]).toBeTruthy();
      }
    }
  });
});
