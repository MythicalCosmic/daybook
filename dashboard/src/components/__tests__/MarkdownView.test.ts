import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import MarkdownView from "@/components/MarkdownView.vue";
import { renderMarkdown } from "@/lib/markdown";
import { testApp } from "@/test/plugins";

const label = (kind: string, id: string) => `${kind} #${id}`;
/** Parsed output: escaped text stays text, so checks look at elements and attributes. */
function dom(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host;
}

function attributeNames(host: HTMLElement): string[] {
  return [...host.querySelectorAll("*")].flatMap((el) => [...el.attributes].map((a) => a.name));
}

const render = (source: string, extra: Partial<Parameters<typeof renderMarkdown>[1]> = {}) =>
  renderMarkdown(source, { base: "/dashboard/c/1", label, ...extra });

describe("renderMarkdown: sanitizing", () => {
  it("never lets raw HTML or scripts through", () => {
    const html = render('Hi <script>alert(1)</script> <img src=x onerror="alert(2)"> <b onclick="x()">bold</b>');
    const host = dom(html);
    expect(host.querySelectorAll("script, img, b, iframe")).toHaveLength(0);
    expect(attributeNames(host).filter((name) => name.startsWith("on"))).toEqual([]);
    expect(html).toContain("&lt;script&gt;");
  });

  it("drops dangerous links but keeps their text", () => {
    for (const href of ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "vbscript:msgbox(1)", "//evil.example"]) {
      const html = render(`[click](${href})`);
      expect(html, href).not.toMatch(/href="(javascript|data|vbscript|\/\/)/i);
      expect(html).toContain("click");
    }
  });

  it("opens outside links in a new tab without the opener", () => {
    const html = render("[Kapitalbank](https://kapitalbank.uz) and https://soliq.uz");
    expect(html).toContain('href="https://kapitalbank.uz"');
    expect(html.match(/target="_blank"/g)).toHaveLength(2);
    expect(html).toContain('rel="noopener noreferrer nofollow"');
  });

  it("keeps only its own classes and no inline styles", () => {
    const html = render("```js\nconst a = 1;\n```\n\n**ok**");
    expect(html).toContain('class="language-js"');
    const host = dom(render('<span class="evil" style="position:fixed">x</span>'));
    expect(host.querySelector(".evil, [style]")).toBeNull();
  });

  it("drops images unless allowed", () => {
    expect(render("![receipt](/media/r.jpg)")).not.toContain("<img");
    expect(render("![receipt](/media/r.jpg)", { allowImages: true })).toContain('<img src="/media/r.jpg" alt="receipt">');
    const host = dom(render("![x](javascript:alert(1))", { allowImages: true }));
    expect(host.querySelector("img")).toBeNull();
  });
});

describe("renderMarkdown: record chips", () => {
  it("turns bare references into links inside the company", () => {
    const html = render("Ask member:17 about task:345.");
    expect(html).toContain('<a class="md-chip" data-record="member" data-id="17" href="/dashboard/c/1/people/17">member #17</a>');
    expect(html).toContain('href="/dashboard/c/1/tasks?task=345"');
  });

  it("uses the link text of [Name](kind:id)", () => {
    const html = render("[Dilnoza](member:17) closed [CHL-1042](shift:1042)");
    expect(html).toContain('href="/dashboard/c/1/people/17">Dilnoza</a>');
    expect(html).toContain('href="/dashboard/c/1/sales/shifts/1042">CHL-1042</a>');
  });

  it("leaves code, URLs, unknown kinds and words alone", () => {
    const html = render("`task:3` https://x.uz/task:4 recipe:5 subtask:6");
    expect(html).not.toContain("md-chip");
    expect(html).toContain("<code>task:3</code>");
  });

  it("renders plain chips without a company", () => {
    const html = renderMarkdown("see task:9", { base: null, label });
    expect(html).toContain('<span class="md-chip" data-record="task" data-id="9">task #9</span>');
  });
});

describe("MarkdownView", () => {
  it("navigates inside the app when a chip is clicked", async () => {
    const app = await testApp("/c/1/ai");
    const wrapper = mount(MarkdownView, { props: { source: "Late: task:345", labels: { "task:345": "Fridge check" } }, global: { plugins: app.plugins } });
    // Plain text until the renderer chunk arrives.
    expect(wrapper.text()).toBe("Late: task:345");
    await vi.dynamicImportSettled();
    await flushPromises();
    const chip = wrapper.get("a.md-chip");
    expect(chip.text()).toBe("Fridge check");
    await chip.trigger("click", { button: 0 });
    await flushPromises();
    expect(app.router.currentRoute.value.fullPath).toBe("/c/1/tasks?task=345");
  });
});
