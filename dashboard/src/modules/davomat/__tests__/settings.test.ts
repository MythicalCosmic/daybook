/**
 * Davomat's Settings: the page (its sections in this edition, what a role sees, an unknown panel)
 * and each panel against the contract in docs/DAVOMAT.md §1: Organization (the save and the brand
 * refresh), Users and roles (the list, a new user with a suggested password and their sign-in
 * details), Telegram (the token checked and saved, Telegram's refusal, the test message) and Your
 * account (the password change and its errors).
 */
// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { DAYBOOK_INFO, setEditionInfo } from "@/core/edition";
import { applyEdition } from "@/core/modules";
import type { Perm } from "@/core/perms";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";

import type { RoleOption } from "../api";
import { assignableRoles, roleKind } from "../components/settings/roles";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import settingsEn from "../i18n/en.json";
import settingsRu from "../i18n/ru.json";
import settingsUz from "../i18n/uz.json";
import AccountPanel from "../panels/AccountPanel.vue";
import OrganizationPanel from "../panels/OrganizationPanel.vue";
import TelegramPanel from "../panels/TelegramPanel.vue";
import UsersPanel from "../panels/UsersPanel.vue";
import SettingsPage from "../pages/SettingsPage.vue";
import type { TelegramSettings, User } from "../types";

mergeModuleMessages("davomat", { en: { ...en, ...settingsEn }, ru: { ...ru, ...settingsRu }, uz: { ...uz, ...settingsUz } });

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
      const body = init?.body instanceof FormData ? init.body : init?.body ? JSON.parse(String(init.body)) : undefined;
      const call = { method: init?.method ?? "GET", url, body };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").replace("/api/v1", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const DAVOMAT_COMPANY = { name: "Namuna MChJ", features: ["attendance", "face_id"] as never, branches: [{ id: 1, name: "Bosh ofis", code: "BO" }] };

let wrappers: VueWrapper[] = [];

async function app(path = "/c/1/settings", overrides: Parameters<typeof company>[0] = {}): Promise<{ router: Router; plugins: unknown[] }> {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = { ...me([company({ ...DAVOMAT_COMPANY, ...overrides })]), user: { id: 7, telegram_id: null, first_name: "Dilnoza", last_name: "Karimova", full_name: "Dilnoza Karimova", username: "dilnoza", photo_url: null } };
  useCompanyStore().setCurrent(1);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/c/:companyId(\\d+)/settings/:panel?", name: "davomat.settings", component: SettingsPage },
      { path: "/:any(.*)*", component: { render: () => null } },
    ],
  });
  await router.push(path);
  await setLanguage("en");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { router, plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] };
}

function render(component: object, plugins: unknown[]): VueWrapper {
  const wrapper = mount(component as never, { global: { plugins: plugins as never }, attachTo: document.body });
  wrappers.push(wrapper);
  return wrapper;
}

/** Sets an input's value the way typing does (TextInput listens to `input`). */
async function type(input: Element | null | undefined, value: string): Promise<void> {
  const element = input as HTMLInputElement;
  element.value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
  await flushPromises();
}

const byText = (text: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === text);

beforeAll(() => {
  setEditionInfo({ ...DAYBOOK_INFO, edition: "davomat", product: "Davomat", organization: { name: "Namuna MChJ", logo_url: null } });
  applyEdition("davomat");
});

afterAll(() => {
  applyEdition("daybook");
  setEditionInfo(DAYBOOK_INFO);
});

afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount());
  wrappers = [];
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("roles", () => {
  const roles: RoleOption[] = [
    { id: 4, name: "Kuzatuvchi", kind: "viewer", is_owner: false },
    { id: 1, name: "Egasi", kind: "owner", is_owner: true },
    { id: 3, name: "Menejer", kind: "manager", is_owner: false },
    { id: 2, name: "Administrator", kind: "admin", is_owner: false },
  ];

  it("reads a role's kind from the server, else the owner flag or the name", () => {
    expect(roleKind({ name: "Rahbar", kind: "admin" })).toBe("admin");
    expect(roleKind({ name: "Ega", is_owner: true })).toBe("owner");
    expect(roleKind({ name: "Менеджер" })).toBe("manager");
    expect(roleKind({ name: "Employee" })).toBe("other");
    expect(roleKind(null)).toBe("other");
  });

  it("offers administrator, manager and viewer, strongest first; the owner's role only to an owner", () => {
    expect(assignableRoles(roles).map((role) => role.id)).toEqual([2, 3, 4]);
    expect(assignableRoles(roles, { owner: true }).map((role) => role.id)).toEqual([1, 2, 3, 4]);
  });
});

describe("SettingsPage", () => {
  it("groups this edition's panels and links Face ID's own settings", async () => {
    stub({});
    const { plugins } = await app("/c/1/settings");
    const wrapper = render(SettingsPage, plugins);
    await flushPromises();

    const sections = wrapper.findAll("[data-section]").map((section) => section.attributes("data-section"));
    expect(sections).toEqual(["organization", "access", "integrations", "rules", "account"]);
    expect(wrapper.find('[data-panel="users"]').exists()).toBe(true);
    expect(wrapper.find('[data-panel="telegram"]').exists()).toBe(true);
    expect(wrapper.find('[data-link="faceid"]').attributes("href")).toBe("/c/1/faceid/settings");
    // A desktop opens the first panel, with its header.
    expect(wrapper.find("[data-panel-body]").attributes("data-panel-body")).toBe("organization");
    expect(wrapper.find("[data-panel-header]").text()).toContain("Organization");
    expect(wrapper.find("[data-org-card]").text()).toContain("Namuna MChJ");
  });

  it("shows a viewer only what their role allows", async () => {
    stub({});
    const viewer: Perm[] = ["attendance.view", "members.view", "reports.view", "dashboard.access"];
    const { plugins } = await app("/c/1/settings/account", { is_owner: false, role: { id: 4, name: "Viewer" }, permissions: viewer });
    const wrapper = render(SettingsPage, plugins);
    await flushPromises();

    expect(wrapper.find('[data-panel="users"]').exists()).toBe(false);
    expect(wrapper.find('[data-panel="telegram"]').exists()).toBe(false);
    expect(wrapper.find('[data-link="faceid"]').exists()).toBe(false);
    expect(wrapper.find("[data-panel-body]").attributes("data-panel-body")).toBe("account");
  });

  it("goes back to the list for a panel that isn't there", async () => {
    stub({});
    const { router, plugins } = await app("/c/1/settings/payroll");
    render(SettingsPage, plugins);
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/c/1/settings");
  });
});

const ORG = { id: 1, name: "Namuna MChJ", logo: null, timezone: "Asia/Tashkent", default_language: "uz" as const };

const EXTRAS = { product_name: "Davomat", auto_create_employees: true };

describe("OrganizationPanel", () => {
  it("saves the name, time zone and language, then refreshes the brand", async () => {
    const calls = stub({
      "GET settings/": () => json(ORG),
      "GET davomat/settings/": () => json(EXTRAS),
      "PATCH settings/": (call) => json({ ...ORG, ...(call.body as object) }),
      "GET /owner/me/": () => json(me([company(DAVOMAT_COMPANY)])),
      "GET /owner/edition/": () => json({ edition: "davomat", product: "Davomat", organization: { name: "Namuna Group", logo_url: null }, needs_setup: false }),
    });
    const { plugins } = await app("/c/1/settings/organization");
    const wrapper = render(OrganizationPanel, plugins);
    await flushPromises();

    expect(wrapper.find("[data-local-time]").exists()).toBe(true);
    await type(wrapper.find('input[data-field="name"]').element, "Namuna Group");
    expect(document.body.textContent).toContain("You have unsaved changes");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toEqual({ name: "Namuna Group", timezone: "Asia/Tashkent", default_language: "uz" });
    // Nothing of the install's own settings changed: no second request.
    expect(calls.some((call) => call.method === "PATCH" && call.url.includes("davomat/settings/"))).toBe(false);
    expect(calls.some((call) => call.url.endsWith("/owner/me/"))).toBe(true);
    expect(calls.some((call) => call.url.endsWith("/owner/edition/"))).toBe(true);
  });

  it("renames the product and stops adding unknown faces as employees", async () => {
    const calls = stub({
      "GET settings/": () => json(ORG),
      "PATCH settings/": () => json(ORG),
      "GET davomat/settings/": () => json(EXTRAS),
      "PATCH davomat/settings/": (call) => json({ ...EXTRAS, ...(call.body as object) }),
      "GET /owner/me/": () => json(me([company(DAVOMAT_COMPANY)])),
      "GET /owner/edition/": () => json({ edition: "davomat", product: "Namuna Davomat" }),
    });
    const { plugins } = await app("/c/1/settings/organization");
    const wrapper = render(OrganizationPanel, plugins);
    await flushPromises();

    await type(wrapper.find('input[data-field="product_name"]').element, "Namuna Davomat");
    await wrapper.find('[data-field="auto_create_employees"] button, button[role="switch"]').trigger("click");
    await flushPromises();
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH" && call.url.includes("davomat/settings/"))?.body).toEqual({ product_name: "Namuna Davomat", auto_create_employees: false });
  });

  it("is read-only without company.settings", async () => {
    stub({ "GET settings/": () => json(ORG), "GET davomat/settings/": () => json(EXTRAS) });
    const { plugins } = await app("/c/1/settings/organization", { is_owner: false, permissions: ["dashboard.access", "attendance.view"] });
    const wrapper = render(OrganizationPanel, plugins);
    await flushPromises();
    expect(wrapper.text()).toContain("You can look, not change");
    expect(wrapper.find("[data-logo-upload]").exists()).toBe(false);
    expect((wrapper.find('input[maxlength="200"]').element as HTMLInputElement).disabled).toBe(true);
  });
});

/** `GET users/roles/` as the server sends it (api.ts adds `is_owner`). */
const ROLES = [
  { id: 1, name: "Owner", kind: "owner" },
  { id: 2, name: "Administrator", kind: "admin" },
  { id: 3, name: "Manager", kind: "manager" },
  { id: 4, name: "Viewer", kind: "viewer" },
];
const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

function user(overrides: Partial<User>): User {
  return {
    id: 20,
    username: "aziz",
    first_name: "Aziz",
    last_name: "Rahimov",
    role: { id: 3, name: "Manager", kind: "manager" },
    branch_ids: [1],
    is_active: true,
    last_login: "2026-11-09T05:10:00Z",
    telegram_linked: false,
    ...overrides,
  };
}

describe("UsersPanel", () => {
  it("lists the users with their role, locations and Telegram, the signed-in person first", async () => {
    stub({
      "GET users/": () =>
        json(page([
          user({ id: 30, username: "kamola", first_name: "Kamola", last_name: "Yusupova", role: { id: 4, name: "Viewer", kind: "viewer" }, last_login: null }),
          user({ id: 11, username: "dilnoza", first_name: "Dilnoza", last_name: "Karimova", role: { id: 1, name: "Owner", kind: "owner" }, branch_ids: [], telegram_linked: true, is_self: true }),
          user({}),
          user({ id: 40, username: "old", first_name: "Bobur", last_name: "Aliyev", is_active: false }),
        ])),
      "GET users/roles/": () => json(ROLES),
    });
    const { plugins } = await app("/c/1/settings/users");
    const wrapper = render(UsersPanel, plugins);
    await flushPromises();

    const rows = wrapper.findAll("[data-user]");
    expect(rows.map((row) => row.attributes("data-user"))).toEqual(["dilnoza", "aziz", "kamola"]);
    expect(rows[0]!.text()).toContain("You");
    expect(rows[0]!.text()).toContain("All locations");
    expect(rows[1]!.text()).toContain("Bosh ofis");
    expect(rows[2]!.text()).toContain("Never signed in");
    expect(rows[0]!.find('[data-telegram="true"]').exists()).toBe(true);
    // Deactivated people wait behind their own filter.
    expect(wrapper.text()).toContain("Deactivated");
    expect(wrapper.findAll("[data-role-guide]")).toHaveLength(4);
  });

  it("creates a manager with a suggested password and shows their sign-in details", async () => {
    const calls = stub({
      "GET users/": () => json(page([user({ id: 11, username: "dilnoza", first_name: "Dilnoza", last_name: "Karimova", role: { id: 1, name: "Owner", kind: "owner" }, is_self: true })])),
      "GET users/roles/": () => json(ROLES),
      "POST users/": (call) => json(user({ id: 50, username: (call.body as { username: string }).username, first_name: "Malika", last_name: "Karimova" }), 201),
    });
    const { plugins } = await app("/c/1/settings/users");
    const wrapper = render(UsersPanel, plugins);
    await flushPromises();

    // Only the owner so far: who to add, under the list.
    expect(wrapper.find("[data-invite]").exists()).toBe(true);
    await wrapper.find("[data-add]").trigger("click");
    await flushPromises();
    const dialog = document.body;
    const inputs = [...dialog.querySelectorAll<HTMLInputElement>("#davomat-user-form input")];
    await type(inputs[0], "Malika");
    await type(inputs[1], "Karimova");
    expect(dialog.querySelector<HTMLInputElement>('input[data-field="username"]')?.value).toBe("malika.karimova");

    byText("Suggest a strong password")?.click();
    await flushPromises();
    const manager = [...dialog.querySelectorAll<HTMLButtonElement>('[role="radio"]')].find((radio) => radio.textContent?.includes("Manager"));
    manager?.click();
    await flushPromises();

    dialog.querySelector<HTMLFormElement>("#davomat-user-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();

    const post = calls.find((call) => call.method === "POST");
    const body = post?.body as { username: string; password: string; role_id: number; branch_ids: number[]; first_name: string; last_name: string };
    expect(body).toMatchObject({ first_name: "Malika", last_name: "Karimova", username: "malika.karimova", role_id: 3, branch_ids: [1] });
    expect(body.password).toMatch(/^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$/);
    expect(dialog.querySelector("[data-created]")?.textContent).toContain("malika.karimova");
    expect(dialog.querySelector("[data-password]")?.textContent).toBe(body.password);
  });

  it("asks for a role and a location before creating", async () => {
    const calls = stub({ "GET users/": () => json(page([])), "GET users/roles/": () => json(ROLES) });
    const { plugins } = await app("/c/1/settings/users", { branches: [{ id: 1, name: "Bosh ofis", code: "BO" }, { id: 2, name: "Sklad", code: "SK" }] });
    const wrapper = render(UsersPanel, plugins);
    await flushPromises();
    await wrapper.find("[data-add]").trigger("click");
    await flushPromises();
    const form = document.querySelector<HTMLFormElement>("#davomat-user-form")!;
    const inputs = [...form.querySelectorAll<HTMLInputElement>("input")];
    await type(inputs[0], "Malika");
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(document.body.textContent).toContain("Choose a role");
    expect(document.body.textContent).toContain("At least 8 characters.");

    [...document.querySelectorAll<HTMLButtonElement>('[role="radio"]')].find((radio) => radio.textContent?.includes("Viewer"))?.click();
    await flushPromises();
    form.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(document.body.textContent).toContain("Choose at least one location");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });
});

describe("UserDialog", () => {
  it("asks which employee gets a sign-in when it is for one", async () => {
    const calls = stub({ "GET users/": () => json(page([])), "GET users/roles/": () => json(ROLES), "GET employees/": () => json(page([])) });
    const { plugins } = await app("/c/1/settings/users");
    const wrapper = render(UsersPanel, plugins);
    await flushPromises();
    await wrapper.find("[data-add]").trigger("click");
    await flushPromises();
    document.querySelector<HTMLButtonElement>('[data-from-employee] button[role="switch"]')!.click();
    await flushPromises();
    document.querySelector<HTMLFormElement>("#davomat-user-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(document.body.textContent).toContain("Choose the employee");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("keeps your own role and locations as they are", async () => {
    const self = user({ id: 11, username: "dilnoza", first_name: "Dilnoza", last_name: "Karimova", role: { id: 2, name: "Administrator", kind: "admin" }, branch_ids: [] });
    const calls = stub({
      "GET users/": () => json(page([self, user({})])),
      "GET users/roles/": () => json(ROLES),
      "PATCH users/11/": (call) => json({ ...self, ...(call.body as object) }),
    });
    const { plugins } = await app("/c/1/settings/users", { is_owner: false, role: { id: 2, name: "Administrator" }, permissions: ["roles.manage", "company.settings", "dashboard.access"] });
    const wrapper = render(UsersPanel, plugins);
    await flushPromises();
    await wrapper.find('[data-user="dilnoza"] button').trigger("click");
    await flushPromises();

    expect(document.body.textContent).toContain("You can’t change your own role or locations.");
    expect(document.querySelectorAll('#davomat-user-form [role="radio"]')).toHaveLength(0);
    await type(document.querySelector('#davomat-user-form input'), "Dilnoza B.");
    document.querySelector<HTMLFormElement>("#davomat-user-form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ first_name: "Dilnoza B.", last_name: "Karimova", username: "dilnoza" });
  });
});

const NOT_SET: TelegramSettings = { configured: false, bot_username: null, bot_name: null, status: "not_set", checked_at: null };
const OK: TelegramSettings = { configured: true, bot_username: "namuna_davomat_bot", bot_name: "Namuna Davomat", status: "ok", checked_at: "2026-11-10T03:00:00Z" };
const TOKEN = "123456789:AAEabcdefghijklmnopqrstuvwxyz0123456";

describe("TelegramPanel", () => {
  it("checks the token's shape, saves it and shows the bot", async () => {
    let saved = false;
    const calls = stub({
      "GET telegram/": () => json(saved ? OK : NOT_SET),
      "PUT telegram/": () => ((saved = true), json(OK)),
      "GET users/": () => json(page([])),
      "GET /owner/edition/": () => json({ edition: "davomat", product: "Davomat", telegram: { configured: true, bot_username: "namuna_davomat_bot" } }),
    });
    const { plugins } = await app("/c/1/settings/telegram");
    const wrapper = render(TelegramPanel, plugins);
    await flushPromises();

    expect(wrapper.find('[data-status="not_set"]').exists()).toBe(true);
    expect(wrapper.find("[data-guide]").text()).toContain("/newbot");

    const input = wrapper.find('[data-token-form] input').element;
    await type(input, "not a token");
    await wrapper.find("[data-token-form]").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("That doesn’t look like a bot token.");
    expect(calls.some((call) => call.method === "PUT")).toBe(false);

    await type(input, TOKEN);
    await wrapper.find("[data-token-form]").trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ token: TOKEN });
    expect(wrapper.find('[data-status="ok"]').text()).toContain("Namuna Davomat");
    expect(wrapper.find('[data-status="ok"]').text()).toContain("@namuna_davomat_bot");
    expect(wrapper.find("[data-token-form]").exists()).toBe(false);
    expect(calls.some((call) => call.url.endsWith("/owner/edition/"))).toBe(true);
  });

  it("shows Telegram's refusal next to the token", async () => {
    stub({ "GET telegram/": () => json(NOT_SET), "PUT telegram/": () => json({ token: ["Telegram doesn’t know this token."] }, 400), "GET users/": () => json(page([])) });
    const { plugins } = await app("/c/1/settings/telegram");
    const wrapper = render(TelegramPanel, plugins);
    await flushPromises();
    await type(wrapper.find("[data-token-form] input").element, TOKEN);
    await wrapper.find("[data-token-form]").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Telegram doesn’t know this token.");
  });

  it("says what to do first when the test message can't go", async () => {
    const calls = stub({
      "GET telegram/": () => json(OK),
      "POST telegram/test/": () => json({ detail: "Open the bot in Telegram, press Start, then try again." }, 400),
      "GET users/": () => json(page([])),
    });
    const { plugins } = await app("/c/1/settings/telegram");
    const wrapper = render(TelegramPanel, plugins);
    await flushPromises();
    await wrapper.find("[data-send-test]").trigger("click");
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/telegram/test/"))).toBe(true);
    expect(wrapper.find("[data-test-result]").text()).toContain("press Start");
  });

  it("disconnects the bot after asking", async () => {
    let connected = true;
    const calls = stub({
      "GET telegram/": () => json(connected ? OK : NOT_SET),
      "DELETE telegram/": () => ((connected = false), new Response(null, { status: 204 })),
      "GET users/": () => json(page([])),
    });
    const { plugins } = await app("/c/1/settings/telegram");
    const wrapper = render(TelegramPanel, plugins);
    await flushPromises();
    await wrapper.find("[data-disconnect]").trigger("click");
    await flushPromises();
    expect(confirmQueue.value).toHaveLength(1);
    settleConfirm(confirmQueue.value[0]!.id, { reason: "" }, 0);
    await flushPromises();
    expect(calls.some((call) => call.method === "DELETE" && call.url.endsWith("/telegram/"))).toBe(true);
    expect(wrapper.find('[data-status="not_set"]').exists()).toBe(true);
    expect(wrapper.find("[data-token-form]").exists()).toBe(true);
  });
});

describe("AccountPanel", () => {
  it("changes the password once both new ones match", async () => {
    const calls = stub({ "POST /owner/auth/password/change/": () => new Response(null, { status: 204 }) });
    const { plugins } = await app("/c/1/settings/account");
    const wrapper = render(AccountPanel, plugins);
    await flushPromises();
    expect(wrapper.find("[data-profile]").text()).toContain("Dilnoza Karimova");

    const form = wrapper.find("[data-password-form]");
    const [current, next, confirm] = form.findAll('input:not([readonly])').map((input) => input.element);
    await type(current, "old-password-1");
    await type(next, "Kq7m-Xp3a-Rf9t");
    await type(confirm, "Kq7m-Xp3a-Rf9x");
    await form.trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("The passwords don’t match.");
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    await type(confirm, "Kq7m-Xp3a-Rf9t");
    await form.trigger("submit");
    await flushPromises();
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({ current: "old-password-1", new: "Kq7m-Xp3a-Rf9t" });
    expect(wrapper.text()).toContain("Your other browsers were signed out");
  });

  it("puts the server's answer on the field it is about", async () => {
    stub({ "POST /owner/auth/password/change/": () => json({ current: ["Your current password is wrong."] }, 400) });
    const { plugins } = await app("/c/1/settings/account");
    const wrapper = render(AccountPanel, plugins);
    await flushPromises();
    const form = wrapper.find("[data-password-form]");
    const [current, next, confirm] = form.findAll('input:not([readonly])').map((input) => input.element);
    await type(current, "wrong-one-1");
    await type(next, "Kq7m-Xp3a-Rf9t");
    await type(confirm, "Kq7m-Xp3a-Rf9t");
    await form.trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Your current password is wrong.");
  });
});
