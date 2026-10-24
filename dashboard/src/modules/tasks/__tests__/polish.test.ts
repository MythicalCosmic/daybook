// Tonight's task polish: send-back reasons as chips, quick add in "New task", wording that must
// read right in every language.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import ConfirmDialog from "@/components/ConfirmDialog.vue";
import PersonPicker from "@/components/PersonPicker.vue";
import { returnReasonFields } from "@/components/returnReasons";
import { toasts } from "@/components/useToast";
import { i18n, mergeModuleMessages, russianPlural } from "@/i18n";
import commonEn from "@/i18n/en.json";
import commonRu from "@/i18n/ru.json";
import commonUz from "@/i18n/uz.json";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import CreateTaskDialog from "../components/CreateTaskDialog.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { forgetQuickAddAvailability, QUICK_ADD_DEBOUNCE_MS, recognised, resultKey } from "../quickAdd";

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
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const buttons = () => [...document.body.querySelectorAll("button")];
const button = (label: string) => buttons().find((b) => b.textContent?.trim() === label);

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
  forgetQuickAddAvailability();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("send back with a reason (contract 4)", () => {
  async function dialog() {
    const app = await testApp("/c/1/tasks/reviews");
    const t = (key: string) => i18n.global.t(key);
    const onConfirm = vi.fn();
    const { wrapper } = mountWithProviders(ConfirmDialog, {
      plugins: app.plugins,
      props: { open: true, title: "Send back for another go", tone: "danger", confirmLabel: "Send back", ...returnReasonFields(t), onConfirm },
    });
    await flushPromises();
    return { wrapper, onConfirm };
  }

  it("offers the ready reasons as chips, and a chip alone is the reason", async () => {
    const { wrapper, onConfirm } = await dialog();
    const chips = [...document.body.querySelectorAll("[data-testid=reason-chips] button")].map((b) => b.textContent?.trim());
    expect(chips).toEqual(["Photo is unclear", "Not finished", "Wrong item", "Other…"]);
    button("Photo is unclear")!.click();
    await nextTick();
    expect(button("Photo is unclear")!.getAttribute("aria-pressed")).toBe("true");
    button("Send back")!.click();
    await flushPromises();
    expect(onConfirm).toHaveBeenCalledWith("Photo is unclear");
    wrapper.unmount();
  });

  it("adds a typed note after the chip", async () => {
    const { wrapper, onConfirm } = await dialog();
    const area = document.body.querySelector("textarea")!;
    button("Not finished")!.click();
    await nextTick();
    area.value = "the bottom shelf is left";
    area.dispatchEvent(new Event("input"));
    await nextTick();
    button("Send back")!.click();
    await flushPromises();
    expect(onConfirm).toHaveBeenLastCalledWith("Not finished: the bottom shelf is left");
    wrapper.unmount();
  });

  it("asks for the person's own words after Other", async () => {
    const { wrapper, onConfirm } = await dialog();
    button("Other…")!.click();
    await nextTick();
    button("Send back")!.click();
    await flushPromises();
    expect(onConfirm).not.toHaveBeenCalled();
    // The text is required again (the browser stops the send), while a ready reason needs none.
    expect(document.body.querySelector("textarea")!.required).toBe(true);
    button("Wrong item")!.click();
    await nextTick();
    expect(document.body.querySelector("textarea")!.required).toBe(false);
    wrapper.unmount();
  });

  it("has the reasons in Uzbek and Russian too", () => {
    for (const dictionary of [commonEn, commonUz, commonRu] as Array<Record<string, string>>) {
      for (const key of ["photo", "unfinished", "wrongItem", "other", "note"]) expect(dictionary[`common.returnReason.${key}`]).toBeTruthy();
    }
    expect((commonUz as Record<string, string>)["common.returnReason.photo"]).toBe("Rasm aniq emas");
    expect((commonRu as Record<string, string>)["common.returnReason.unfinished"]).toBe("Не доделано");
  });
});

describe("quick add in New task (contract 1)", () => {
  const person = { id: 12, name: "Alisher Valiyev", photo_url: null, position: "Farmatsevt", branch: "Chilonzor", branch_id: 1, position_id: 3 };
  const parsed = {
    title: "Dorilarni sanash",
    due_at: "2026-10-26T10:00:00Z",
    due_label: "Tomorrow, 26 Oct (Mon), 15:00",
    priority: "urgent",
    repeat: null,
    repeat_weekdays: null,
  };

  async function open(routes: Record<string, (call: Call) => Response>) {
    const calls = stub({ "GET tasks/options/": () => json({ people: [person], positions: [], routines: [], policies: [] }), ...routes });
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(CreateTaskDialog, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    return { calls, wrapper };
  }

  async function type(text: string) {
    const input = document.body.querySelector<HTMLInputElement>("input[data-testid=create-title]")!;
    input.value = text;
    input.dispatchEvent(new Event("input"));
    await wait(QUICK_ADD_DEBOUNCE_MS + 30);
    await flushPromises();
  }

  it("reads the deadline and the urgency from the title and says what it understood", async () => {
    const { calls, wrapper } = await open({ "POST tasks/parse/": () => json(parsed) });
    await type("Ertaga 15:00 dorilarni sanash !!");
    expect(calls.filter((c) => c.url.endsWith("/tasks/parse/")).map((c) => c.body)).toEqual([{ text: "Ertaga 15:00 dorilarni sanash !!" }]);
    const line = document.body.querySelector("[data-testid=quick-add-understood]")!.textContent ?? "";
    expect(line).toContain("Dorilarni sanash");
    expect(line).toContain("Tomorrow, 26 Oct (Mon), 15:00");
    expect(line).toContain("Urgent");
    // The form follows: the understood deadline is the chosen one, and Urgent is picked.
    expect(document.body.querySelector("[data-testid=due-parsed]")?.getAttribute("aria-pressed")).toBe("true");
    const urgent = buttons().find((b) => b.textContent?.trim() === "Urgent" && b.closest("[role=radiogroup], [role=group], [role=tablist]"));
    expect(urgent?.getAttribute("aria-checked") ?? urgent?.getAttribute("aria-pressed") ?? urgent?.getAttribute("data-state")).toMatch(/true|on|checked|active/);
    wrapper.unmount();
  });

  it("keeps the words in the title after Not a date", async () => {
    const { wrapper } = await open({ "POST tasks/parse/": () => json(parsed) });
    await type("Ertaga 15:00 dorilarni sanash !!");
    document.body.querySelector<HTMLButtonElement>("[data-testid=quick-add-dismiss]")!.click();
    await nextTick();
    expect(document.body.querySelector("[data-testid=quick-add-understood]")).toBeNull();
    expect(document.body.querySelector("[data-testid=due-parsed]")).toBeNull();
    wrapper.unmount();
  });

  it("says nothing when nothing was understood, and stops asking a backend without the endpoint", async () => {
    const { calls, wrapper } = await open({});
    await type("Kassa hisoboti ertaga");
    expect(document.body.querySelector("[data-testid=quick-add-understood]")).toBeNull();
    await type("Kassa hisoboti ertaga 18:00");
    expect(calls.filter((c) => c.url.endsWith("/tasks/parse/"))).toHaveLength(1);
    // A failed read never toasts: typing must not pop errors.
    expect(toasts).toHaveLength(0);
    wrapper.unmount();
  });

  it("falls back to the default deadline when the understood words are deleted", async () => {
    let call = 0;
    const { wrapper } = await open({ "POST tasks/parse/": () => (call++ === 0 ? json(parsed) : json({ title: "Dorilarni sanash", due_at: null, due_label: null, priority: null, repeat: null, repeat_weekdays: null })) });
    await type("Ertaga 15:00 dorilarni sanash !!");
    document.body.querySelector<HTMLButtonElement>("[data-testid=due-parsed]")!.click();
    await nextTick();
    await type("Dorilarni sanash");
    expect(document.body.querySelector("[data-testid=due-parsed]")).toBeNull();
    expect(button("Tomorrow 09:00")?.getAttribute("aria-pressed")).toBe("true");
    wrapper.unmount();
  });

  it("saves once when Create is pressed twice while the title is still being read", async () => {
    const slow = () => new Promise<Response>((resolve) => setTimeout(() => resolve(json(parsed)), 120));
    const { calls, wrapper } = await open({
      "POST tasks/parse/": slow as never,
      "POST tasks/": () => json({ created: 1, ids: [40] }, 201),
    });
    // Who gets it, as the person picker reports a pick.
    wrapper.findComponent(PersonPicker).vm.$emit("update:modelValue", [12]);
    await nextTick();
    const input = document.body.querySelector<HTMLInputElement>("input[data-testid=create-title]")!;
    input.value = "Ertaga 15:00 dorilarni sanash !!";
    input.dispatchEvent(new Event("input"));
    await nextTick(); // the keystroke's own task ends before the next press
    // Pressed twice at once, before the pause and the reading are over.
    const create = buttons().find((b) => b.textContent?.includes("Create"))!;
    create.click();
    create.click();
    await wait(400);
    await flushPromises();
    const saves = calls.filter((c) => c.method === "POST" && c.url.endsWith("/companies/1/tasks/"));
    expect(saves).toHaveLength(1);
    // What the title said went with it.
    expect(saves[0]!.body).toMatchObject({ title: "Dorilarni sanash", due_at: "2026-10-26T10:00:00Z", priority: "urgent", assignee_ids: [12] });
    wrapper.unmount();
  });

  it("points repeating work to routines", async () => {
    const { wrapper } = await open({ "POST tasks/parse/": () => json({ ...parsed, title: "Kassa hisoboti", priority: null, repeat: "daily" }) });
    await type("Kassa hisoboti har kuni 18:00 xx");
    expect(document.body.querySelector("[data-testid=quick-add-repeat]")?.textContent).toContain("Set up a routine");
    wrapper.unmount();
  });

  it("knows what counts as understood", () => {
    expect(recognised(null)).toBe(false);
    expect(recognised({ ...parsed, due_at: null, due_label: null, priority: null } as never)).toBe(false);
    expect(recognised({ ...parsed, due_at: null, due_label: null } as never)).toBe(true);
    expect(resultKey(parsed as never)).toBe("2026-10-26T10:00:00Z|urgent|");
  });

  it("shows the save shortcut for this platform, not a Mac glyph everywhere", async () => {
    const { wrapper } = await open({});
    const create = buttons().find((b) => b.textContent?.includes("Create"))!;
    expect(create.textContent).not.toContain("⌘");
    expect(create.textContent).toContain("Ctrl");
    wrapper.unmount();
  });
});

describe("layout", () => {
  it("brings today's week into view when the calendar opens on this month (audit D-3)", async () => {
    const scrolled: Array<{ el: Element; options: unknown }> = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element, options?: unknown) {
      scrolled.push({ el: this, options });
    } as typeof Element.prototype.scrollIntoView;
    stub({ "GET tasks/calendar/": () => json({ days: [], items: [], truncated: false }) });
    const app = await testApp("/c/1/tasks?view=calendar");
    const { default: TasksCalendar } = await import("../components/TasksCalendar.vue");
    const { wrapper } = mountWithProviders(TasksCalendar, { plugins: app.plugins, props: { params: {} } });
    await flushPromises();
    await flushPromises();
    Element.prototype.scrollIntoView = original;
    expect(scrolled).toHaveLength(1);
    expect(scrolled[0]!.el.getAttribute("aria-current")).toBe("date");
    expect(scrolled[0]!.options).toMatchObject({ block: "center" });
    wrapper.unmount();
  });

  it("keeps the four numbers on one row on phones (audit D-9)", async () => {
    const app = await testApp("/c/1/tasks");
    const { default: KpiStrip } = await import("@/components/KpiStrip.vue");
    const items = ["Done today", "Late now", "Waiting for check", "On time"].map((label, index) => ({ id: String(index), label, value: index }));
    const { wrapper } = mountWithProviders(KpiStrip, { plugins: app.plugins, props: { items, columns: 4, phone: "line" } });
    const strip = wrapper.find(".kpi-strip");
    expect(strip.attributes("data-phone-columns")).toBe("4");
    expect(strip.classes()).toContain("grid-cols-4");
    wrapper.unmount();
  });
});

describe("wording", () => {
  it("counts photos in Russian without the «1 фото» bug", () => {
    const forms = (ru as Record<string, string>)["tasks.photos.count"]!.split(" | ");
    for (const n of [1, 2, 5, 21, 22, 25, 101]) expect(forms[russianPlural(n, forms.length)]!.replace("{n}", String(n))).toBe(`${n} фото`);
  });

  it("never names cancelling tasks like closing a dialog", () => {
    for (const [tasks, common] of [
      [en, commonEn],
      [uz, commonUz],
      [ru, commonRu],
    ] as Array<[Record<string, string>, Record<string, string>]>) {
      expect(tasks["tasks.bulk.cancel"]).toBeTruthy();
      expect(tasks["tasks.bulk.cancel"]).not.toBe(common["common.cancel"]);
      expect(tasks["tasks.action.cancel"]).not.toBe(common["common.cancel"]);
    }
  });

  it("follows the glossary: Qabul qilish / Принять, Dalil / Отчёт, Nazorat ro‘yxati, просрочено", () => {
    const uzTasks = uz as Record<string, string>;
    const ruTasks = ru as Record<string, string>;
    expect(uzTasks["tasks.action.confirm"]).toBe("Qabul qilish");
    expect(ruTasks["tasks.action.confirm"]).toBe("Принять");
    expect(uzTasks["tasks.status.todo"]).toBe("Bajarish kerak");
    expect(uzTasks["tasks.drawer.checklist"]).toBe("Nazorat ro‘yxati");
    expect(ruTasks["tasks.drawer.proof"]).toBe("Отчёт");
    expect(ruTasks["tasks.due.lateBy"]).toBe("просрочено на {time}");
    expect(Object.values(ruTasks).join("\n")).not.toMatch(/\((а|ла)\)|одтвержд/);
    // No Uzbek case ending glued to, or after, a placeholder.
    expect(Object.entries(uzTasks).filter(([, value]) => /\} ?(ga|ka|qa|da|dan|ni|ning|gacha|dagi)\b/.test(value))).toEqual([]);
    expect((commonUz as Record<string, string>)["common.undo"]).toBe("Bekor qilish");
  });
});
