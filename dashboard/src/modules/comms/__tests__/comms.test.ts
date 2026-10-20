// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { getAudience, listReceipts, pinAnnouncement, publishAnnouncement, remindUnread, updateAnnouncement } from "../api";
import TelegramBubble from "../components/TelegramBubble.vue";
import en from "../i18n/en.json";
import module from "../index";
import { fromEditor, plainLength, toDisplay, toEditor } from "../telegramHtml";
import { splitIso, zonedIso } from "../when";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? "GET", url: input.replace("/api/v1/owner/companies/1/", ""), body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return json({ id: 1 });
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("comms", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("telegramHtml", () => {
  it("turns the composer's HTML into Telegram's subset", () => {
    expect(fromEditor("<p>Hurmatli <strong>jamoa</strong>!</p><p>Shanba <em>08:00</em></p>")).toBe("Hurmatli <b>jamoa</b>!\nShanba <i>08:00</i>");
    expect(fromEditor('<p>Kod: <span class="tg-spoiler">1234</span> <s>eski</s> <u>yangi</u></p>')).toBe("Kod: <tg-spoiler>1234</tg-spoiler> <s>eski</s> <u>yangi</u>");
    expect(fromEditor("<ul><li>Bir</li><li>Ikki</li></ul>")).toBe("• Bir\n• Ikki");
  });

  it("drops what Telegram refuses: scripts, unsafe links, tags inside themselves, empty tags", () => {
    expect(fromEditor('<p><a href="javascript:alert(1)">bos</a> <a href="https://911.uz">sayt</a></p>')).toBe('bos <a href="https://911.uz">sayt</a>');
    expect(fromEditor("<p><b>a <strong>b</strong></b><script>x()</script><i></i></p>")).toBe("<b>a b</b>");
    expect(fromEditor("<p>1 &lt; 2 &amp; 3</p>")).toBe("1 &lt; 2 &amp; 3");
  });

  it("shows stored text safely and opens it back in the composer", () => {
    expect(toDisplay('<b>Diqqat</b>\n<img src=x onerror="alert(1)"><a href="https://911.uz">havola</a>')).toBe(
      '<strong>Diqqat</strong><br><a href="https://911.uz" target="_blank" rel="noopener noreferrer">havola</a>',
    );
    expect(toDisplay("<tg-spoiler>sir</tg-spoiler>")).toBe('<span class="tg-spoiler">sir</span>');
    expect(toEditor("Bir\n<b>Ikki</b>")).toBe("<p>Bir</p><p><strong>Ikki</strong></p>");
    expect(fromEditor(toEditor("Bir\n<b>Ikki</b> <tg-spoiler>sir</tg-spoiler>"))).toBe("Bir\n<b>Ikki</b> <tg-spoiler>sir</tg-spoiler>");
    expect(plainLength("<b>Salom</b> &amp; xayr")).toBe(12);
  });
});

describe("when", () => {
  it("converts company-local moments to instants and back", () => {
    expect(zonedIso("2026-10-24", "09:00", "Asia/Tashkent")).toBe("2026-10-24T04:00:00.000Z");
    expect(splitIso("2026-10-24T04:00:00.000Z", "Asia/Tashkent")).toEqual({ day: "2026-10-24", time: "09:00" });
    expect(splitIso("2026-10-24T20:30:00Z", "Asia/Tashkent")).toEqual({ day: "2026-10-25", time: "01:30" });
  });
});

describe("api", () => {
  it("calls the announcements endpoints", async () => {
    const calls = stub();
    await publishAnnouncement(1, { text_html: "<p>Salom</p>", position_ids: [3], branch_ids: [], scheduled_for: null, pinned_until: null, expires_at: null });
    await updateAnnouncement(1, 4, { scheduled_for: "2026-10-24T04:00:00.000Z" });
    await listReceipts(1, 4, { state: "unread", page: 1, page_size: 50 });
    await remindUnread(1, 4);
    await pinAnnouncement(1, 4, "2026-10-27T04:00:00.000Z");
    await getAudience(1, { position: [3], branch: [1, 2] });
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST announcements/",
      "PATCH announcements/4/",
      "GET announcements/4/receipts/?state=unread&page=1&page_size=50",
      "POST announcements/4/remind/",
      "POST announcements/4/pin/",
      "GET announcements/audience/?position=3&branch=1&branch=2",
    ]);
    expect(calls[0]!.body).toMatchObject({ text_html: "<p>Salom</p>", position_ids: [3] });
    expect(calls[4]!.body).toEqual({ pinned_until: "2026-10-27T04:00:00.000Z" });
  });

  it("registers behind announcements.send with the announcements pulse key", () => {
    expect(module).toMatchObject({ id: "comms", group: "comms", perm: "announcements.send", hotkey: "m" });
    expect(module.invalidates).toEqual(["announcements"]);
  });
});

describe("TelegramBubble", () => {
  it("previews the message as the bot sends it, with the read button", async () => {
    const app = await testApp("/c/1/announcements/new");
    const { wrapper } = mountWithProviders(TelegramBubble, { plugins: app.plugins, props: { text: "<b>Diqqat</b>\nErtaga <tg-spoiler>sanitariya</tg-spoiler> kuni", author: "Dilnoza Karimova" } });
    await flushPromises();
    expect(wrapper.text()).toContain("Announcement · Dilnoza Karimova");
    expect(wrapper.find("strong").text()).toBe("Diqqat");
    expect(wrapper.find(".tg-spoiler").text()).toBe("sanitariya");
    expect(wrapper.text()).toContain("I’ve read it");
  });
});
