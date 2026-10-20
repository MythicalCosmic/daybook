import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Receipt, Wallet } from "lucide-react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Me, Membership, Summary } from "../api/types";
import { I18nProvider, type Lang } from "../i18n";
import { NavigationProvider, useNavigation, type Navigation } from "../state/navigation";
import { SessionProvider, type Member } from "../state/session";
import { FeatureSlot } from "./FeatureSlot";
import { useReplacedEntries } from "./hosts";
import {
  collectFeatures,
  defineFeature,
  findPage,
  findSheet,
  homeSlots,
  meItemsByGroup,
  plusActions,
  replacedEntries,
  suspendedGate,
  visibleFeatures,
  type Feature,
  type PageProps,
  type SheetProps,
  type SlotProps,
} from "./registry";

// The hosts read the app's feature list; tests fill it with fixtures.
const registry = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("./registry", async (importOriginal) => {
  const real = await importOriginal<typeof import("./registry")>();
  return { ...real, features: registry.list };
});

const Page = (_: PageProps) => null;
const SheetBody = (_: SheetProps) => null;

function Hero({ member, summary }: SlotProps) {
  return <div data-testid="alpha-hero">{`Hero for ${member.first_name}: ${summary?.today_total ?? "?"}`}</div>;
}
const Card = (label: string) =>
  function SlotCard() {
    return <div data-testid="card">{label}</div>;
  };
function Crash(): ReactNode {
  throw new Error("slot exploded");
}

const alpha: Feature = defineFeature({
  id: "alpha",
  messages: {
    en: { "me.pay": "Pay", "plus.advance": "Advance", "plus.task": "Days off" },
    ru: { "me.pay": "Зарплата", "plus.advance": "Аванс", "plus.task": "Выходные" },
    uz: { "me.pay": "Maosh", "plus.advance": "Avans", "plus.task": "Dam olish" },
  },
  pages: { pay: Page },
  sheets: { advance: SheetBody },
  homeHero: [{ id: "hero", component: Hero }],
  homeCards: [{ id: "late-card", component: Card("alpha card"), order: 50 }],
  meItems: [
    {
      id: "pay",
      group: "money",
      label: "me.pay",
      icon: Wallet,
      open: { page: "pay", params: { month: "2026-10" } },
      useStatus: () => ({ value: "3 days", badge: 2 }),
    },
  ],
  plusActions: [
    { id: "advance", label: "plus.advance", icon: Wallet, open: { sheet: "advance" } },
    { id: "task", label: "plus.task", icon: Receipt, open: { feature: "core", sheet: "timeOff" }, order: 200 },
  ],
});

const beta: Feature = defineFeature({
  id: "beta",
  messages: { en: { leave: "Time off" }, ru: { leave: "Отпуск" }, uz: { leave: "Ta’til" } },
  visible: (member) => member.permissions.includes("reports.view"),
  pages: { leave: Page },
  homeCards: [{ id: "first", component: Card("beta card"), order: 10 }],
  replaces: ["timeOff"],
  meItems: [{ id: "leave", group: "work", label: "leave", icon: Receipt, open: { page: "leave" } }],
});

const hidden: Feature = defineFeature({
  id: "hidden",
  messages: { en: { x: "X" }, ru: { x: "X" }, uz: { x: "X" } },
  visible: () => false,
  pages: { x: Page },
  replaces: ["teamResults"],
  meItems: [{ id: "x", group: "team", label: "x", icon: Receipt, open: { page: "x" } }],
});

const crashing: Feature = defineFeature({
  id: "crashing",
  messages: { en: {}, ru: {}, uz: {} },
  homeCards: [{ id: "boom", component: Crash, order: 20 }],
});

const throwsInVisible: Feature = defineFeature({
  id: "throws",
  messages: { en: {}, ru: {}, uz: {} },
  visible: () => {
    throw new Error("bad rule");
  },
  homeCards: [{ id: "never", component: Card("never shown") }],
});

function membership(permissions: string[]): Membership {
  return {
    id: 7,
    company: {
      id: 1,
      name: "Demo Shop",
      timezone: "Asia/Tashkent",
      features: [],
      owner_sees_personal_tasks: false,
      base_currency: "UZS",
      team_directory_phones: false,
    },
    status: "approved",
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Employee",
    permissions: permissions as Membership["permissions"],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    home_branch: null,
    branch_ids: [],
    suspended_until: null,
  };
}

const member = (permissions: string[] = []): Member => ({ ...membership(permissions), timeZone: "Asia/Tashkent", companyId: 1 });
const summary = { today_total: 8, today_done: 3 } as Summary;

describe("registry helpers", () => {
  const all = [alpha, beta, hidden, crashing, throwsInVisible];
  let errors: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => errors.mockRestore());

  it("hides features whose rule says no, or whose rule throws", () => {
    expect(visibleFeatures(all, { member: member(), summary }).map((f) => f.id)).toEqual(["alpha", "crashing"]);
    expect(visibleFeatures(all, { member: member(["reports.view"]), summary }).map((f) => f.id)).toEqual(["alpha", "beta", "crashing"]);
    expect(errors).toHaveBeenCalled();
  });

  it("orders slots by order, then feature, then declaration", () => {
    const context = { member: member(["reports.view"]), summary };
    expect(homeSlots(all, "home.cards", context).map(({ feature, item }) => `${feature.id}.${item.id}`)).toEqual([
      "beta.first",
      "crashing.boom",
      "alpha.late-card",
    ]);
    expect(homeSlots(all, "home.hero", context).map(({ item }) => item.id)).toEqual(["hero"]);
  });

  it("groups Me rows", () => {
    const groups = meItemsByGroup(all, { member: member(["reports.view"]), summary });
    expect(groups.money.map(({ item }) => item.id)).toEqual(["pay"]);
    expect(groups.work.map(({ item }) => item.id)).toEqual(["leave"]);
    expect(groups.team).toEqual([]);
    expect(groups.documents).toEqual([]);
  });

  it("lets a visible feature replace a built-in entry, and only then", () => {
    expect([...replacedEntries(all, { member: member(["reports.view"]), summary })]).toEqual(["timeOff"]);
    // beta is invisible without reports.view; hidden is never visible, so team results stay.
    expect([...replacedEntries(all, { member: member(), summary })]).toEqual([]);
  });

  it("collects (+) actions", () => {
    expect(plusActions(all, { member: member(), summary }).map(({ feature, item }) => `${feature.id}.${item.id}`)).toEqual(["alpha.advance", "alpha.task"]);
  });

  it("finds pages and sheets", () => {
    expect(findPage(all, { feature: "alpha", page: "pay" })).toBe(Page);
    expect(findPage(all, { feature: "alpha", page: "nope" })).toBeNull();
    expect(findPage(all, { feature: "ghost", page: "pay" })).toBeNull();
    expect(findSheet(all, "alpha", "advance")).toBe(SheetBody);
    expect(findSheet(all, "beta", "advance")).toBeNull();
  });

  it("checks discovered folders", () => {
    const { features, problems } = collectFeatures({
      "./alpha/index.ts": { default: alpha },
      "./wallet/index.ts": { default: beta },
      "./empty/index.ts": {},
      "./nomsg/index.ts": { default: { id: "nomsg", messages: { en: {} } } },
      "./badtarget/index.ts": {
        default: { id: "badtarget", messages: { en: {}, ru: {}, uz: {} }, meItems: [{ id: "a", group: "money", label: "a", icon: Wallet, open: { page: "missing" } }] },
      },
      "./badbuiltin/index.ts": {
        default: { id: "badbuiltin", messages: { en: {}, ru: {}, uz: {} }, replaces: ["profile"] },
      },
    });
    expect(features.map((f) => f.id)).toEqual(["alpha"]);
    expect(problems).toHaveLength(5);
    expect(problems.join("\n")).toMatch(/id "beta" must match its folder "wallet"/);
    expect(problems.join("\n")).toMatch(/no default export/);
    expect(problems.join("\n")).toMatch(/messages need en, ru and uz/);
    expect(problems.join("\n")).toMatch(/unknown targets/);
    expect(problems.join("\n")).toMatch(/replaces unknown built-in profile/);
  });

  it("finds a feature's screen for suspended people", () => {
    const Paused = () => null;
    const lifecycle: Feature = defineFeature({ id: "lifecycle", messages: { en: {}, ru: {}, uz: {} }, gates: { suspended: Paused } });
    expect(suspendedGate([alpha, lifecycle])).toBe(Paused);
    expect(suspendedGate([alpha])).toBeNull();
  });
});

function Providers({ lang = "en", permissions = [], children }: { lang?: Lang; permissions?: string[]; children: ReactNode }) {
  const [client] = useState(() => {
    const queries = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    queries.setQueryData(keys.summary(1), summary);
    return queries;
  });
  const me = { id: 1, telegram_id: 4242, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", memberships: [membership(permissions)] } as Me;
  return (
    <QueryClientProvider client={client}>
      <I18nProvider lang={lang}>
        <SessionProvider me={me}>
          <NavigationProvider>{children}</NavigationProvider>
        </SessionProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

describe("feature slots", () => {
  let errors: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => {
    errors.mockRestore();
    registry.list.splice(0);
    cleanup();
  });

  const teamRow = <button className="list-item">Team results</button>;

  it("render only the built-in rows when there are no feature folders", () => {
    const { container } = render(
      <Providers>
        <FeatureSlot name="home.hero" />
        <FeatureSlot name="me.items" builtIns={{ team: teamRow }} />
        <FeatureSlot name="plus.actions" />
      </Providers>,
    );
    expect(container.innerHTML).toBe(
      '<div class="section-head section-head--small">Team</div><div class="card list-card"><button class="list-item">Team results</button></div>',
    );
  });

  it("render home slots in order, giving each the member and summary, and contain a crash", () => {
    registry.list.push(alpha, beta, crashing);
    render(
      <Providers permissions={["reports.view"]}>
        <FeatureSlot name="home.hero" />
        <FeatureSlot name="home.cards" />
      </Providers>,
    );
    expect(screen.getByTestId("alpha-hero").textContent).toBe("Hero for Alisher: 8");
    expect(screen.getAllByTestId("card").map((node) => node.textContent)).toEqual(["beta card", "alpha card"]);
    expect(errors).toHaveBeenCalled();
  });

  it("group Me rows under headings, translated, with status, opening the feature page", () => {
    registry.list.push(alpha, beta);
    let nav: Navigation | null = null;
    function Probe() {
      nav = useNavigation();
      return null;
    }
    const { container } = render(
      <Providers lang="uz" permissions={["reports.view"]}>
        <FeatureSlot name="me.items" builtIns={{ team: teamRow }} />
        <Probe />
      </Providers>,
    );
    const headings = [...container.querySelectorAll(".section-head")].map((node) => node.textContent);
    expect(headings).toEqual(["Pul", "Ish", "Jamoa"]);
    const pay = screen.getByRole("button", { name: /Maosh/ });
    expect(pay.textContent).toContain("3 days");
    expect(pay.querySelector(".ui-count")?.textContent).toBe("2");
    act(() => fireEvent.click(pay));
    expect(nav!.stack).toEqual([{ feature: "alpha", page: "pay", params: { month: "2026-10" } }]);
  });

  it("show (+) actions that open the feature's sheet", () => {
    registry.list.push(alpha);
    let nav: Navigation | null = null;
    function Probe() {
      nav = useNavigation();
      return null;
    }
    render(
      <Providers lang="ru">
        <FeatureSlot name="plus.actions" />
        <Probe />
      </Providers>,
    );
    expect(screen.getByText("Быстро добавить")).toBeTruthy();
    act(() => fireEvent.click(screen.getByRole("button", { name: "Аванс" })));
    expect(nav!.sheet).toEqual({ kind: "feature", feature: "alpha", sheet: "advance", params: undefined });
    // An action may open one of the app's own sheets by name.
    act(() => fireEvent.click(screen.getByRole("button", { name: "Выходные" })));
    expect(nav!.sheet).toEqual({ kind: "timeOff" });
  });

  it("tell screens which built-ins are replaced for this person", () => {
    registry.list.push(beta, hidden);
    const seen: string[][] = [];
    function Probe() {
      seen.push([...useReplacedEntries()]);
      return null;
    }
    render(
      <Providers permissions={["reports.view"]}>
        <Probe />
      </Providers>,
    );
    expect(seen.at(-1)).toEqual(["timeOff"]);
  });
});
