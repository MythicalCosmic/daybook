// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { Editor } from "@tiptap/core";
import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { company, me } from "@/test/fixtures";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import { kbKeys, knowledgeApi } from "../api";
import ArchiveDrawer from "../components/ArchiveDrawer.vue";
import PageBody from "../components/PageBody.vue";
import { buildExtensions } from "../components/editor/extensions";
import en from "../i18n/en.json";
import module from "../index";
import RichEditor from "../components/editor/RichEditor.vue";
import { moveData, normalizeBody, pathTo, readTone, safeBody, toTreeNodes } from "../lib";
import PageView from "../pages/PageView.vue";
import type { PageDetail, TreeNodeData } from "../types";

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
      const body = init?.body;
      const call = { method: init?.method ?? "GET", url: input, body: typeof body === "string" ? JSON.parse(body) : body };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const node = (id: number, title: string, children: TreeNodeData[] = [], published = true): TreeNodeData => ({
  id,
  title,
  emoji: "📄",
  published,
  require_ack: false,
  position: 0,
  children,
});

function detail(overrides: Partial<PageDetail> = {}): PageDetail {
  return {
    id: 5,
    title: "Kassani ochish tartibi",
    emoji: "🔓",
    space: { id: 2, name: "Kassa", icon: "💰" },
    parent_id: null,
    published: true,
    published_at: "2026-10-10T09:00:00+05:00",
    require_ack: true,
    version: 3,
    archived: false,
    updated_at: "2026-10-20T09:00:00+05:00",
    updated_by: { id: 1, name: "Dilnoza Karimova", photo_url: null },
    excerpt: "Count the float",
    read: { read: 1, total: 4 },
    body: "<h2>Steps</h2><p>Count the float</p>",
    ack_version: 3,
    breadcrumbs: [],
    children: [],
    links: [],
    my_ack: null,
    created_at: "2026-10-01T09:00:00+05:00",
    created_by: { id: 1, name: "Dilnoza Karimova", photo_url: null },
    can_edit: true,
    ...overrides,
  };
}

beforeEach(() => {
  mergeModuleMessages("knowledge", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("calls the knowledge endpoints with the right params and bodies", async () => {
    const calls = stubApi({
      "GET knowledge/pages/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "PATCH knowledge/pages/5/": () => json(detail()),
      "POST knowledge/pages/5/move/": () => json(detail()),
      "POST knowledge/pages/5/links/": () => json({}),
      "GET knowledge/pages/linked/": () => json([]),
      "POST knowledge/images/": () => json({ id: 9, url: "/api/v1/files/x/", width: 10, height: 10 }, 201),
    });
    await knowledgeApi.pages(1, { q: "kassa", status: "draft", require_ack: true, page: 2 });
    await knowledgeApi.savePage(1, 5, { body: "<p>x</p>", base_version: 3, reread: true });
    await knowledgeApi.move(1, 5, { parent: 7, index: 0 });
    await knowledgeApi.link(1, 5, "routine", 12);
    await knowledgeApi.linked(1, "task", 77);
    await knowledgeApi.upload(1, new File(["x"], "a.png", { type: "image/png" }), 5);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/knowledge/pages/?q=kassa&status=draft&require_ack=true&page=2",
      "PATCH /api/v1/owner/companies/1/knowledge/pages/5/",
      "POST /api/v1/owner/companies/1/knowledge/pages/5/move/",
      "POST /api/v1/owner/companies/1/knowledge/pages/5/links/",
      "GET /api/v1/owner/companies/1/knowledge/pages/linked/?target_type=task&target_id=77",
      "POST /api/v1/owner/companies/1/knowledge/images/",
    ]);
    expect(calls[1]!.body).toEqual({ body: "<p>x</p>", base_version: 3, reread: true });
    expect(calls[2]!.body).toEqual({ parent: 7, index: 0 });
    expect(calls[3]!.body).toEqual({ target_type: "routine", target_id: 12 });
    const form = calls[5]!.body as FormData;
    expect(form.get("page")).toBe("5");
    expect((form.get("file") as File).name).toBe("a.png");
  });

  it("keys every query under the company and the module", () => {
    expect(kbKeys.page(4, 5)).toEqual([4, "knowledge", "page", { id: 5 }]);
    expect(kbKeys.all(4)).toEqual([4, "knowledge"]);
  });

  it("registers as the catalog says, with a widget, commands, settings and the tasks slot", () => {
    expect(module).toMatchObject({ id: "knowledge", group: "comms", order: 40, hotkey: "k", invalidates: ["knowledge"] });
    expect(module.widgets?.map((w) => w.id)).toEqual(["knowledge.reading"]);
    expect(module.settings?.map((s) => s.id)).toEqual(["knowledge"]);
    expect(Object.keys(module.extensions ?? {})).toEqual(["tasks.drawer.actions"]);
    expect(module.deepLinks?.kb?.("12")).toBe("knowledge/p/12");
  });
});

describe("tree helpers", () => {
  const tree = [node(1, "A", [node(2, "B", [node(3, "C")])]), node(4, "D", [], false)];

  it("draws drafts with a badge and finds the way down to a page", () => {
    const nodes = toTreeNodes(tree, "Draft");
    expect(nodes[1]).toMatchObject({ id: 4, label: "📄 D", badge: "Draft" });
    expect(nodes[0]!.children![0]!.children![0]).toMatchObject({ id: 3, label: "📄 C" });
    expect(pathTo(tree, 3)).toEqual([1, 2]);
    expect(pathTo(tree, 99)).toBeNull();
  });

  it("moves a page with its children, like the server does", () => {
    const moved = moveData(tree, { id: 2, parentId: 4, index: 0 });
    expect(moved[0]!.children).toEqual([]);
    expect(moved[1]!.children.map((child) => child.id)).toEqual([2]);
    expect(moved[1]!.children[0]!.children.map((child) => child.id)).toEqual([3]);
  });

  it("colours read progress", () => {
    expect(readTone({ read: 4, total: 4 })).toBe("success");
    expect(readTone({ read: 2, total: 4 })).toBe("warning");
    expect(readTone({ read: 1, total: 4 })).toBe("danger");
    expect(readTone(null)).toBe("neutral");
  });
});

describe("editor", () => {
  it("writes exactly the markup the server's allow-list keeps", () => {
    const editor = new Editor({
      extensions: buildExtensions("Write"),
      content:
        '<h2>Ochish</h2><div data-callout="warning"><p>Ehtiyot</p></div>' +
        '<ul data-type="taskList"><li data-type="taskItem" data-checked="true"><label><input type="checkbox" checked><span></span></label><div><p>Razmen</p></div></li></ul>' +
        '<img data-image-id="12" src="/api/v1/files/t/" alt="Kassa">' +
        "<table><tbody><tr><th><p>A</p></th></tr><tr><td><p>1</p></td></tr></tbody></table>",
    });
    const html = editor.getHTML();
    expect(html).toContain('<div data-callout="warning"><p>Ehtiyot</p></div>');
    expect(html).toContain('<ul data-type="taskList">');
    expect(html).toMatch(/<li (data-checked="true" data-type="taskItem"|data-type="taskItem" data-checked="true")>/);
    expect(html).toContain('data-image-id="12"');
    expect(html).toContain("<table><tbody><tr><th><p>A</p></th></tr><tr><td><p>1</p></td></tr></tbody></table>");
    editor.commands.insertTable(2, 2);
    expect(editor.getHTML().match(/<table>/g)).toHaveLength(2);
    editor.destroy();
  });

  it("settles a loaded page quietly, so opening it is not an unsaved change", async () => {
    const app = await testApp("/c/1/knowledge/p/5/edit");
    // Hand-written HTML (newlines between blocks) ending in a callout: the editor reflows it and
    // adds an empty paragraph after the callout.
    const loaded = '<p>Salom\nhammaga</p>\n<div data-callout="info"><p>Bekzodga yozing</p></div>\n';
    const models: string[] = [];
    const { wrapper, inner } = mountWithProviders(RichEditor, {
      props: { modelValue: loaded, upload: vi.fn(), "onUpdate:modelValue": (html: string) => models.push(html) },
      plugins: app.plugins,
    });
    // Tiptap says "created" on the next tick.
    await new Promise((resolve) => setTimeout(resolve, 20));
    await flushPromises();
    const [[ready]] = inner.emitted<[string]>("ready")!;
    expect(ready).toContain('<div data-callout="info"><p>Bekzodga yozing</p></div>');
    expect(ready).not.toContain("\n");
    expect(models.at(-1)).toBe(ready);
    expect(normalizeBody(ready)).toBe('<p>Salom hammaga</p><div data-callout="info"><p>Bekzodga yozing</p></div>');
    wrapper.unmount();
  });

  it("ignores the editor's empty last paragraph when comparing bodies", () => {
    expect(normalizeBody("<p>A</p><p></p>")).toBe("<p>A</p>");
    expect(normalizeBody("<p>A</p><p><br></p> <p></p>")).toBe("<p>A</p>");
    expect(normalizeBody("<p>A</p><p></p><p>B</p>")).toBe("<p>A</p><p></p><p>B</p>");
  });
});

describe("reading", () => {
  it("cleans the body once more and keeps checklists read-only", async () => {
    const clean = await safeBody('<p onclick="x()">Hi</p><script>alert(1)</script><ul data-type="taskList"><li data-type="taskItem" data-checked="false"><label><input type="checkbox"></label><div><p>Do</p></div></li></ul>');
    expect(clean).not.toContain("script");
    expect(clean).not.toContain("onclick");
    expect(clean).toContain('<input type="checkbox" disabled');
  });

  it("puts each table in a scrolling wrapper, so a wide table never widens the page", async () => {
    const clean = await safeBody("<table><tbody><tr><td>Insulin</td><td>+2…+8 °C</td></tr></tbody></table><p>Then</p><table><tbody><tr><td>B</td></tr></tbody></table>");
    expect(clean).toBe(
      '<div class="tableWrapper"><table><tbody><tr><td>Insulin</td><td>+2…+8 °C</td></tr></tbody></table></div><p>Then</p><div class="tableWrapper"><table><tbody><tr><td>B</td></tr></tbody></table></div>',
    );
  });

  it("wraps tables as elements, so a link that mentions a table stays a link", async () => {
    // Inside an attribute "<table" is text: rewriting the cleaned HTML as a string would close the
    // attribute early and let the rest of the address become attributes of a real table.
    const clean = await safeBody('<p><a href="https://x.uz/&lt;table onmouseover=alert(1)//">Link</a></p><table><tbody><tr><td>A</td></tr></tbody></table>');
    const doc = new DOMParser().parseFromString(clean, "text/html");
    expect(doc.querySelectorAll("[onmouseover]")).toHaveLength(0);
    expect(doc.querySelectorAll("table")).toHaveLength(1);
    expect(doc.querySelector("a")?.getAttribute("href")).toContain("x.uz/<table");
    expect(doc.querySelector(".tableWrapper > table")).not.toBeNull();
  });

  it("renders a page body", async () => {
    const app = await testApp("/c/1/knowledge/p/5");
    const { wrapper } = mountWithProviders(PageBody, { props: { html: "<h2>Steps</h2><p>Count</p>" }, plugins: app.plugins });
    await flushPromises();
    await vi.waitFor(() => expect(wrapper.find("article.kb-prose h2").text()).toBe("Steps"));
  });

  it("lets a reader confirm a must-read page at once, and rolls back if refused", async () => {
    const calls = stubApi({
      "GET knowledge/pages/5/": () => json(detail({ can_edit: false, read: null })),
      "POST knowledge/pages/5/ack/": () => json({ detail: "No." }, 403),
    });
    const app = await testApp("/c/1/knowledge/p/5");
    useSessionStore().me = me([company({ is_owner: false, permissions: ["dashboard.access"], role: { id: 3, name: "Employee" } })]);
    await app.router.replace({ path: "/c/1/knowledge/p/5" });
    const router = app.router;
    router.addRoute({ path: "/c/:companyId/knowledge/p/:pageId", component: { render: () => null } });
    await router.replace("/c/1/knowledge/p/5");
    const { wrapper } = mountWithProviders(PageView, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("Please read this page");
    const button = wrapper.findAll("button").find((b) => b.text() === "I’ve read it")!;
    await button.trigger("click");
    await flushPromises();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("knowledge/pages/5/ack/"))).toBe(true);
    // Refused: the page asks again.
    expect(wrapper.text()).toContain("Please read this page");
  });
});

describe("archive", () => {
  it("lists archived spaces and top archived pages, and restores one", async () => {
    const space = { id: 7, name: "Eski qoidalar", icon: "🗂", description: "", audience_all: true, positions: [], position: 3, archived: true, archived_at: "2026-10-12T10:00:00+05:00", counts: { pages: 2, published: 2, drafts: 0 }, created_at: "", updated_at: "" };
    const live = { ...space, id: 8, name: "Savdo zali", archived: false, archived_at: null };
    const parent = { ...detail({ id: 20, title: "Eski kassa tartibi", archived: true, parent_id: null }), archived_at: "2026-10-15T10:00:00+05:00" };
    const child = { ...detail({ id: 21, title: "Ichki sahifa", archived: true, parent_id: 20 }), archived_at: "2026-10-15T10:00:00+05:00" };
    const calls = stubApi({
      "GET knowledge/spaces/": () => json([space, live]),
      "GET knowledge/pages/": () => json({ count: 2, next: null, previous: null, results: [parent, child] }),
      "POST knowledge/pages/20/restore/": () => json(detail({ id: 20 })),
    });
    const app = await testApp("/c/1/knowledge?archive=1");
    const { wrapper } = mountWithProviders(ArchiveDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    const text = document.body.textContent ?? "";
    expect(text).toContain("Eski qoidalar");
    expect(text).not.toContain("Savdo zali"); // not archived
    expect(text).toContain("Eski kassa tartibi");
    expect(text).not.toContain("Ichki sahifa"); // comes back with the page above it
    expect(calls.find((c) => c.url.includes("knowledge/pages/"))!.url).toContain("status=archived");

    const restore = Array.from(document.body.querySelectorAll("button")).filter((b) => b.textContent?.includes("Restore"));
    restore.at(-1)!.click();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("knowledge/pages/20/restore/"))).toBe(true);
    wrapper.unmount();
  });

  it("asks for nothing while closed", async () => {
    const calls = stubApi({});
    const app = await testApp("/c/1/knowledge");
    const { wrapper } = mountWithProviders(ArchiveDrawer, { plugins: app.plugins });
    await flushPromises();
    expect(calls).toHaveLength(0);
    wrapper.unmount();
  });
});
