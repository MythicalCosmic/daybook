/**
 * Davomat's own pages outside Team and Settings: the module's shape, the password sign-in (wrong
 * pair, lockout, show/hide, Remember me), the setup wizard (validation, the request, the server's
 * nested errors, the done step) and the Overview (its numbers, feed chips, who's here).
 */
// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DAYBOOK_INFO, editionInfo, normalizeEdition, setEditionInfo } from "@/core/edition";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { attentionOf, insideNow, kpisOf, type Board, type BoardRow, type Scan } from "../components/overview/overviewApi";
import DayTimeline from "../components/team/DayTimeline.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import { generatePassword, passwordStrength, suggestUsername } from "../lib/password";
import LoginPage from "../pages/LoginPage.vue";
import OverviewPage from "../pages/OverviewPage.vue";
import SetupPage from "../pages/SetupPage.vue";

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
      const call = { method: init?.method ?? "GET", url: input, body: init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/", "").replace("companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const mounted: Array<{ unmount: () => void }> = [];
function mount(component: object, plugins: Awaited<ReturnType<typeof testApp>>["plugins"]) {
  const { wrapper } = mountWithProviders(component, { plugins });
  mounted.push(wrapper);
  return wrapper;
}

beforeEach(() => {
  mergeModuleMessages("davomat", { en, ru: en, uz: en });
  setEditionInfo(normalizeEdition({ edition: "davomat", product: "Davomat", organization: { name: "Namuna MChJ", logo_url: null }, needs_setup: false }));
  try {
    window.localStorage.clear();
  } catch {
    // jsdom has storage.
  }
});

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.unstubAllGlobals();
  setEditionInfo(DAYBOOK_INFO);
  document.body.innerHTML = "";
});

describe("module", () => {
  it("is Davomat's only, serves the home and brings its own sign-in and setup", () => {
    expect(module.editions).toEqual(["davomat"]);
    expect(module.index).toBe(true);
    expect(module.publicRoutes?.map((route) => route.name)).toEqual(["login", "setup"]);
    expect(module.nav?.filter((item) => item.row).map((item) => item.row!.key)).toEqual(["davomat.team", "davomat.settings"]);
  });

  it("has every word in all three languages, plurals in the house shape", () => {
    const keys = Object.keys(en).sort();
    expect(Object.keys(uz).sort()).toEqual(keys);
    expect(Object.keys(ru).sort()).toEqual(keys);
    for (const dictionary of [en, uz, ru] as Record<string, string>[]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(value.trim(), key).not.toBe("");
        const forms = value.split(" | ");
        if (forms.length > 1) expect(forms, key).toHaveLength(3);
      }
    }
  });
});

describe("passwords", () => {
  it("rates weak, common and strong passwords", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("abc")).toBe(1);
    expect(passwordStrength("12345678")).toBe(1);
    expect(passwordStrength("Password1")).toBe(1);
    expect(passwordStrength("aliyev2026", "aliyev")).toBe(1);
    expect(passwordStrength("kitob-qalam-7")).toBeGreaterThanOrEqual(3);
    expect(passwordStrength(generatePassword())).toBeGreaterThanOrEqual(3);
  });

  it("suggests a Latin username from a name, Cyrillic and apostrophes included", () => {
    expect(suggestUsername("Gʻayrat", "O‘tkirov")).toBe("gayrat.otkirov");
    expect(suggestUsername("Дилноза", "Каримова")).toBe("dilnoza.karimova");
    expect(suggestUsername("", "")).toBe("");
  });
});

describe("sign-in", () => {
  async function mountLogin() {
    const app = await testApp("/login?next=/c/1/team");
    const session = useSessionStore();
    session.me = null;
    session.setAccess(null);
    const wrapper = mount(LoginPage, app.plugins);
    await flushPromises();
    return { app, wrapper, session };
  }

  it("signs in with the pair, remembers the choice and goes where the person was headed", async () => {
    const calls = stubApi({
      "POST auth/password/": () => json({ access: "tok" }),
      "GET me/": () => json(me()),
    });
    const { app, wrapper, session } = await mountLogin();
    const replace = vi.spyOn(app.router, "replace");
    await wrapper.get("input[data-testid=login-username]").setValue("aziza");
    await wrapper.get("input[data-testid=login-password]").setValue("secret-pass");
    await wrapper.get("[data-testid=login-remember] [role=checkbox]").trigger("click");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/v1/owner/auth/password/", body: { username: "aziza", password: "secret-pass" } });
    expect(session.accessToken).toBe("tok");
    expect(replace).toHaveBeenCalledWith("/c/1/team");
    expect(window.localStorage.getItem("daybook.console.remember")).toBe("false");
  });

  it("says when the pair is wrong, when the account may not sign in and how long a lockout lasts, in its own words", async () => {
    let answer = 400;
    // The server's shapes (apps/davomat): its texts may not be translated; the page uses its codes.
    stubApi({
      "POST auth/password/": () =>
        answer === 400
          ? json({ detail: "Неверный… (untranslated)", code: "wrong_password" }, 400)
          : answer === 403
            ? json({ detail: "This account can't use the web app.", code: "no_access" }, 403)
            : json({ detail: "Too many wrong passwords. Try again in 12 minutes.", code: "locked" }, 429),
    });
    const { wrapper } = await mountLogin();
    await wrapper.get("input[data-testid=login-username]").setValue("aziza");
    await wrapper.get("input[data-testid=login-password]").setValue("nope");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get("[data-testid=login-problem]").text()).toBe(en["davomat.login.wrong"]);
    expect((wrapper.get("input[data-testid=login-password]").element as HTMLInputElement).value).toBe("");
    for (const [code, text] of [
      [403, en["davomat.login.noAccess"]],
      [429, "Too many wrong passwords. Try again in 12 minutes."],
    ] as const) {
      answer = code;
      await wrapper.get("input[data-testid=login-password]").setValue("again");
      await wrapper.get("form").trigger("submit");
      await flushPromises();
      expect(wrapper.get("[data-testid=login-problem]").text()).toBe(text);
    }
  });

  it("asks for both fields before calling, and shows the password on request", async () => {
    const calls = stubApi({});
    const { wrapper } = await mountLogin();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(calls).toHaveLength(0);
    expect(wrapper.get("[data-testid=login-problem]").text()).toContain(en["davomat.login.required"]);
    const input = wrapper.get("input[data-testid=login-password]");
    expect(input.attributes("type")).toBe("password");
    await wrapper.get("[data-testid=login-reveal]").trigger("click");
    expect(wrapper.get("input[data-testid=login-password]").attributes("type")).toBe("text");
  });
});

describe("setup wizard", () => {
  beforeEach(() => setEditionInfo(normalizeEdition({ edition: "davomat", product: "Davomat", organization: null, needs_setup: true })));

  async function mountSetup() {
    const app = await testApp("/setup");
    const session = useSessionStore();
    session.me = null;
    session.setAccess(null);
    const wrapper = mount(SetupPage, app.plugins);
    await flushPromises();
    return { app, wrapper, session };
  }

  async function fillAdmin(wrapper: Awaited<ReturnType<typeof mountSetup>>["wrapper"]) {
    await wrapper.get("input[data-testid=setup-name]").setValue("Namuna MChJ");
    await wrapper.get("[data-testid=setup-organization]").trigger("submit");
    await flushPromises();
    await wrapper.get("input[data-testid=setup-first]").setValue("Aziza");
    await wrapper.get("[data-testid=setup-admin] input[autocomplete=family-name]").setValue("Rahimova");
    await flushPromises();
    const passwords = wrapper.findAll("[data-testid=setup-admin] input[autocomplete=new-password]");
    await passwords[0]!.setValue("kitob-qalam-7");
    await passwords[1]!.setValue("kitob-qalam-7");
  }

  it("needs the organization's name before going on", async () => {
    stubApi({});
    const { wrapper } = await mountSetup();
    await wrapper.get("[data-testid=setup-organization]").trigger("submit");
    await flushPromises();
    expect(wrapper.find("[data-testid=setup-admin]").exists()).toBe(false);
    expect(wrapper.text()).toContain("Required");
  });

  it("creates the organization and its administrator, signs in and offers the first terminal", async () => {
    const calls = stubApi({
      "POST edition/setup/": () => json({ access: "tok" }, 201),
      "GET me/": () => json(me([company({ id: 1, name: "Namuna MChJ" })])),
      "GET edition/": () => json({ edition: "davomat", product: "Davomat", organization: { name: "Namuna MChJ", logo_url: null }, needs_setup: false }),
    });
    const { wrapper, session } = await mountSetup();
    // An install without a setup code: no field for it, and nothing about it in the request.
    expect(wrapper.find("[data-testid=setup-code]").exists()).toBe(false);
    await fillAdmin(wrapper);
    // The username follows the name until it is typed.
    expect((wrapper.get("input[data-testid=setup-username]").element as HTMLInputElement).value).toBe("aziza.rahimova");
    await wrapper.get("[data-testid=setup-admin]").trigger("submit");
    await flushPromises();
    const setup = calls.find((call) => call.url.endsWith("/owner/edition/setup/"))!;
    expect(setup.body).toMatchObject({
      organization: "Namuna MChJ",
      timezone: expect.any(String),
      language: "en",
      admin: { username: "aziza.rahimova", password: "kitob-qalam-7", first_name: "Aziza", last_name: "Rahimova" },
    });
    expect(setup.body).not.toHaveProperty("setup_token");
    expect(session.accessToken).toBe("tok");
    expect(editionInfo.value.needs_setup).toBe(false);
    expect(wrapper.find("[data-testid=setup-done]").exists()).toBe(true);
    expect(wrapper.get("[data-testid=setup-terminal]").attributes("href")).toContain("/c/1/faceid/terminals?add=1");
  });

  it("puts the server's nested errors on their fields and says when the passwords differ", async () => {
    stubApi({ "POST edition/setup/": () => json({ admin: { password: ["This password is too common."] } }, 400) });
    const { wrapper } = await mountSetup();
    await fillAdmin(wrapper);
    const passwords = wrapper.findAll("[data-testid=setup-admin] input[autocomplete=new-password]");
    await passwords[1]!.setValue("different-1");
    await wrapper.get("[data-testid=setup-admin]").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain(en["davomat.setup.admin.mismatch"]);
    await passwords[1]!.setValue("kitob-qalam-7");
    await wrapper.get("[data-testid=setup-admin]").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("This password is too common.");
  });

  it("says so when someone set the server up already", async () => {
    stubApi({ "POST edition/setup/": () => json({ detail: "The organization is already set up. Sign in instead.", code: "setup_done" }, 409) });
    const { wrapper } = await mountSetup();
    await fillAdmin(wrapper);
    await wrapper.get("[data-testid=setup-admin]").trigger("submit");
    await flushPromises();
    expect(wrapper.find("[data-testid=setup-taken]").exists()).toBe(true);
  });

  it("asks for the installer's setup code when the install has one, sends it, and keeps the form on a wrong one", async () => {
    setEditionInfo(normalizeEdition({ edition: "davomat", product: "Davomat", organization: null, needs_setup: true, setup_token_required: true }));
    let right = false;
    const calls = stubApi({
      "POST edition/setup/": () => (right ? json({ access: "tok" }, 201) : json({ detail: "This setup code is wrong.", code: "setup_token" }, 403)),
      "GET me/": () => json(me([company({ id: 1, name: "Namuna MChJ" })])),
      "GET edition/": () => json({ edition: "davomat", product: "Davomat", organization: { name: "Namuna MChJ", logo_url: null }, needs_setup: false }),
    });
    const { wrapper } = await mountSetup();
    // Needed before going on.
    await wrapper.get("input[data-testid=setup-name]").setValue("Namuna MChJ");
    await wrapper.get("[data-testid=setup-organization]").trigger("submit");
    await flushPromises();
    expect(wrapper.find("[data-testid=setup-admin]").exists()).toBe(false);
    await wrapper.get("input[data-testid=setup-code]").setValue("WRONG-CODE");
    await fillAdmin(wrapper);
    await wrapper.get("[data-testid=setup-admin]").trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.url.endsWith("/owner/edition/setup/"))!.body).toMatchObject({ organization: "Namuna MChJ", setup_token: "WRONG-CODE" });
    // Back on the first step, the message on the code, everything typed kept.
    expect(wrapper.find("[data-testid=setup-organization]").exists()).toBe(true);
    expect(wrapper.text()).toContain(en["davomat.setup.org.codeWrong"]);
    expect((wrapper.get("input[data-testid=setup-name]").element as HTMLInputElement).value).toBe("Namuna MChJ");
    right = true;
    await wrapper.get("input[data-testid=setup-code]").setValue(" Kd7-Q2pX ");
    await wrapper.get("[data-testid=setup-organization]").trigger("submit");
    await flushPromises();
    expect((wrapper.get("input[data-testid=setup-first]").element as HTMLInputElement).value).toBe("Aziza");
    await wrapper.get("[data-testid=setup-admin]").trigger("submit");
    await flushPromises();
    expect(calls.filter((call) => call.url.endsWith("/owner/edition/setup/"))[1]!.body).toMatchObject({ setup_token: "Kd7-Q2pX" });
    expect(wrapper.find("[data-testid=setup-done]").exists()).toBe(true);
  });
});

const row = (id: number, extra: Partial<BoardRow> = {}): BoardRow => ({
  member: { id, name: `Person ${id}`, photo_url: null, position: null, home_branch: null, status: "approved" },
  branch: { id: 1, name: "Bosh ofis", code: "BO" },
  state: "in",
  reason: null,
  shift: { id: id * 10, starts_at: "2026-11-10T04:00:00Z", ends_at: "2026-11-10T13:00:00Z", start: "09:00", end: "18:00", branch: null },
  record: { id: id * 100, status: "open", check_in_at: `2026-11-10T03:5${id}:00Z`, check_out_at: null, late_minutes: 0, early_leave_minutes: 0, worked_minutes: 0, is_late: false },
  ...extra,
});

const board = (): Board => ({
  date: "2026-11-10",
  is_today: true,
  now: "2026-11-10T09:30:00+05:00",
  holiday: null,
  totals: { in: 2, late: 1, not_yet: 1, absent: 0, off: 1, rostered: 5, late_missing: 1, present: 3, left: 0 },
  people: [
    row(1),
    row(2),
    row(3, { state: "late", record: { id: 300, status: "open", check_in_at: "2026-11-10T04:14:00Z", check_out_at: null, late_minutes: 14, early_leave_minutes: 0, worked_minutes: 0, is_late: true } }),
    row(4, { state: "not_yet", reason: "late", record: null }),
    row(5, { state: "off", reason: "leave", record: null, shift: null }),
  ],
});

describe("a person's day", () => {
  it("draws the shift, the time at work with the late part, a tick per scan, and says when they came and went", async () => {
    const day = "2026-11-09";
    const at = (time: string) => `${day}T${time}:00+05:00`;
    const person = row(7, {
      state: "late",
      shift: { id: 70, starts_at: at("09:00"), ends_at: at("18:00"), start: "09:00", end: "18:00", branch: null },
      record: { id: 700, status: "closed", check_in_at: at("09:22"), check_out_at: at("18:24"), late_minutes: 22, early_leave_minutes: 0, worked_minutes: 482, is_late: true },
    });
    const scan = (id: number, time: string, action: Scan["action"]): Scan => ({
      id,
      event_at: at(time),
      received_at: at(time),
      device: { id: 1, name: "Kirish" },
      branch: { id: 1, name: "Bosh ofis", code: "BO" },
      kind: "person",
      action,
      employee_no: "00000007",
      name_on_device: "Person 7",
      member: person.member,
      record: { id: 700, status: "closed", check_in_at: at("09:22"), check_out_at: at("18:24"), is_late: true, late_minutes: 22, worked_minutes: 482 },
      photo_url: null,
    });
    stubApi({
      "GET attendance/board/": () => json({ ...board(), date: day, is_today: false, people: [person] }),
      "GET faceid/events/": () => json({ count: 2, next: null, previous: null, results: [scan(2, "18:24", "checked_out"), scan(1, "09:22", "checked_in")] }),
    });
    const app = await testApp("/c/1/team/7");
    const { wrapper } = mountWithProviders(DayTimeline, { plugins: app.plugins, props: { memberId: 7, day } });
    mounted.push(wrapper);
    await flushPromises();
    await flushPromises();
    const timeline = wrapper.get("[data-testid=day-timeline]");
    expect(timeline.findAll("[data-tick]")).toHaveLength(2);
    expect(timeline.text()).toContain("In 09:22 · Out 18:24 · 8h 2m at work");
    expect(timeline.find('[title="09:00–18:00"]').exists()).toBe(true);
    // The two ticks sit in order along the bar.
    const lefts = timeline.findAll("[data-tick]").map((tick) => parseFloat((tick.element as HTMLElement).style.left));
    expect(lefts[0]).toBeLessThan(lefts[1]!);
  });
});

describe("overview", () => {
  it("counts who is in, late (with minutes), missing and on leave", () => {
    expect(kpisOf(board())).toEqual({ inside: 3, expected: 5, late: 1, lateMinutes: 14, notIn: 1, leave: 1 });
    expect(insideNow(board()).map((r) => r.member.id)).toEqual([1, 2, 3]);
    expect(attentionOf(board(), null).map((r) => r.member.id)).toEqual([4, 3]);
    expect(attentionOf(board(), "leave").map((r) => r.member.id)).toEqual([5]);
  });

  it("shows the numbers, the feed with its chips and the faces in the building", async () => {
    const scans: Scan[] = [
      {
        id: 2,
        event_at: "2026-11-10T04:14:00Z",
        received_at: "2026-11-10T04:14:01Z",
        device: { id: 1, name: "Kirish" },
        branch: { id: 1, name: "Bosh ofis", code: "BO" },
        kind: "person",
        action: "checked_in",
        employee_no: "00000003",
        name_on_device: "Person 3",
        member: board().people[2]!.member,
        record: { id: 300, status: "open", check_in_at: "2026-11-10T04:14:00Z", check_out_at: null, is_late: true, late_minutes: 14, worked_minutes: 0 },
        photo_url: "/api/v1/files/snap/",
      },
      {
        id: 1,
        event_at: "2026-11-10T04:10:00Z",
        received_at: "2026-11-10T04:10:01Z",
        device: { id: 1, name: "Kirish" },
        branch: { id: 1, name: "Bosh ofis", code: "BO" },
        kind: "stranger",
        action: "stranger",
        employee_no: "",
        name_on_device: "",
        member: null,
        record: null,
        photo_url: null,
      },
    ];
    stubApi({
      "GET attendance/board/": () => json(board()),
      "GET faceid/status/": () => json({ total: 2, online: 1, quiet: 1, never: 0, unlinked: 0, devices: [] }),
      "GET faceid/events/": () => json({ count: 2, next: null, previous: null, results: scans }),
    });
    const app = await testApp("/c/1");
    const wrapper = mount(OverviewPage, app.plugins);
    await flushPromises();
    await flushPromises();
    expect(wrapper.get("[data-testid=kpi-inside]").text()).toContain("3");
    expect(wrapper.get("[data-testid=kpi-late]").text()).toContain("14 min");
    expect(wrapper.get("[data-testid=kpi-terminals]").text()).toContain("1 quiet");
    const feed = wrapper.get("[data-testid=feed-list]").text();
    expect(feed).toContain("Late 14 min");
    expect(feed).toContain("Unknown face");
    expect(wrapper.get("[data-testid=here-now]").text()).toContain("Person");
    // The feed's own filter: only the faces nobody is linked to.
    const unknown = wrapper.get("[data-testid=feed-filter]").findAll("[role=radio]").find((item) => item.text().includes("Unknown faces"))!;
    await unknown.trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-testid=feed-list]").text()).not.toContain("Late 14 min");
    expect(wrapper.get("[data-testid=feed-list]").text()).toContain("Unknown face");
    // A KPI narrows "Needs a look" to its people.
    await wrapper.get("[data-testid=kpi-leave]").trigger("click");
    expect(wrapper.get("[data-testid=attention]").text()).toContain("Person 5");
  });
});
