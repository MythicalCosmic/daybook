/**
 * The real Home, Me and add sheet with fake feature folders registered: every slot host,
 * `replaces` and `plusActions` work in place (PLAN-OWNER §9.4 item 13 keeps this green).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CalendarCheck, HandCoins, Receipt, Trophy } from "lucide-react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Me, Membership, Summary } from "../api/types";
import { I18nProvider } from "../i18n";
import { Home } from "../screens/Home";
import { Profile } from "../screens/Profile";
import { Sheets } from "../sheets/Sheets";
import { NavigationProvider, useNavigation, type Navigation, type NavigationInit } from "../state/navigation";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";
import { defineFeature, type Feature, type PageProps, type SheetProps, type SlotProps } from "./registry";

const registry = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock("./registry", async (importOriginal) => {
  const real = await importOriginal<typeof import("./registry")>();
  return { ...real, features: registry.list };
});

const Page = (_: PageProps) => <div className="detail-layer">page</div>;
const SheetBody = (_: SheetProps) => <div>sheet</div>;

const attendance: Feature = defineFeature({
  id: "attendance",
  messages: {
    en: { me: "Attendance", plus: "Swap a shift" },
    ru: { me: "Посещаемость", plus: "Обменять смену" },
    uz: { me: "Davomat", plus: "Smenani almashtirish" },
  },
  pages: { month: Page },
  sheets: { swap: SheetBody },
  homeHero: [{ id: "checkin", component: ({ member }: SlotProps) => <div data-testid="hero">{`Check in, ${member.first_name}`}</div> }],
  meItems: [{ id: "month", group: "work", label: "me", icon: CalendarCheck, open: { page: "month" }, useStatus: () => ({ value: "21/22" }) }],
  plusActions: [{ id: "swap", label: "plus", icon: CalendarCheck, open: { sheet: "swap" } }],
});

const wallet: Feature = defineFeature({
  id: "wallet",
  messages: { en: { me: "Pay" }, ru: { me: "Зарплата" }, uz: { me: "Maosh" } },
  pages: { home: Page },
  homeCards: [{ id: "earned", component: ({ summary }: SlotProps) => <div data-testid="card">{`Done today: ${summary?.today_done}`}</div> }],
  meItems: [{ id: "pay", group: "money", label: "me", icon: HandCoins, open: { page: "home" }, useStatus: () => ({ badge: 1 }) }],
});

const leave: Feature = defineFeature({
  id: "leave",
  messages: { en: { me: "Time off" }, ru: { me: "Отпуск" }, uz: { me: "Ta’til" } },
  replaces: ["timeOff"],
  pages: { home: Page },
  meItems: [{ id: "leave", group: "work", label: "me", icon: Receipt, open: { page: "home" }, order: 10 }],
});

const kudos: Feature = defineFeature({
  id: "kudos",
  messages: { en: { me: "Leaderboard" }, ru: { me: "Рейтинг" }, uz: { me: "Reyting" } },
  replaces: ["teamResults"],
  visible: (member) => member.permissions.includes("reports.view"),
  pages: { board: Page },
  meItems: [{ id: "board", group: "team", label: "me", icon: Trophy, open: { page: "board" } }],
});

function membership(permissions: string[]): Membership {
  return {
    id: 7,
    company: { id: 1, name: "Demo Shop", timezone: "Asia/Tashkent" },
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
  };
}

const summary: Summary = {
  today_total: 8,
  today_done: 3,
  late: 0,
  streak_days: 0,
  week: [],
  month_done: 8,
  month_on_time_percent: 67,
  quiet_from: null,
  quiet_until: null,
  unread_activity: 0,
  awaiting_review: 0,
  off_today: null,
};

let nav: Navigation | null = null;
function Probe() {
  nav = useNavigation();
  return null;
}

function renderWith(node: ReactNode, { permissions = [] as string[], initial = undefined as NavigationInit | undefined } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(keys.summary(1), summary);
  client.setQueryData(keys.board(1), []);
  client.setQueryData(keys.activity(1), []);
  client.setQueryData(keys.timeOff(1), []);
  client.setQueryData(keys.holidays(1), []);
  const me = { id: 1, telegram_id: 4242, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", memberships: [membership(permissions)] } as Me;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={me}>
            <NavigationProvider initial={initial}>
              {node}
              <Probe />
            </NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  registry.list.push(attendance, wallet, leave, kudos);
});

afterEach(() => {
  registry.list.splice(0);
  cleanup();
});

describe("feature hosts in the real screens", () => {
  it("put the hero under the greeting and cards after the banners on Home", () => {
    const { container } = renderWith(<Home />);
    const hero = screen.getByTestId("hero");
    const card = screen.getByTestId("card");
    expect(hero.textContent).toBe("Check in, Alisher");
    expect(card.textContent).toBe("Done today: 3");
    const order = [...container.querySelectorAll("[data-testid], .page-head, .section-head")].map((node) =>
      node.getAttribute("data-testid") ?? node.className,
    );
    expect(order.slice(0, 4)).toEqual(["page-head", "hero", "card", "section-head"]);
  });

  it("group feature rows on Me and let features take over time off and team results", () => {
    const { container } = renderWith(<Profile />, { permissions: ["reports.view"] });
    const headings = [...container.querySelectorAll(".section-head")].map((node) => node.textContent);
    expect(headings).toEqual(["Money", "Work", "Team", "Settings"]);
    expect(screen.queryByText("Ask for days off")).toBeNull();
    expect(screen.queryByText("Team results")).toBeNull();
    const work = [...container.querySelectorAll(".card.list-card")][1];
    expect([...work.querySelectorAll(".list-item-label")].map((node) => node.textContent)).toEqual(["Time off", "Attendance"]);
    expect(screen.getByRole("button", { name: /Attendance/ }).textContent).toContain("21/22");
    act(() => fireEvent.click(screen.getByRole("button", { name: /Pay/ })));
    expect(nav!.stack).toEqual([{ feature: "wallet", page: "home", params: undefined }]);
  });

  it("keep the built-in entries for people the replacing feature isn't for", () => {
    renderWith(<Profile />, { permissions: [] });
    // kudos is hidden without reports.view (and so is the built-in team row); leave is visible.
    expect(screen.queryByText("Leaderboard")).toBeNull();
    expect(screen.queryByText("Team results")).toBeNull();
    expect(screen.queryByText("Ask for days off")).toBeNull();
    registry.list.splice(registry.list.indexOf(leave), 1);
    cleanup();
    renderWith(<Profile />, { permissions: [] });
    expect(screen.getByText("Ask for days off")).toBeTruthy();
  });

  it("show quick-add actions above the personal task form", () => {
    const { container } = renderWith(<Sheets />, { initial: { sheet: { kind: "add" } } });
    const sheet = container.querySelector(".sheet")!;
    const firstLabel = sheet.querySelector(".field-label")?.textContent;
    expect(firstLabel).toBe("Quick add");
    expect(sheet.querySelector(".heading")?.textContent).toBe("New task");
    act(() => fireEvent.click(screen.getByRole("button", { name: "Swap a shift" })));
    expect(nav!.sheet).toEqual({ kind: "feature", feature: "attendance", sheet: "swap", params: undefined });
    expect(screen.getByText("sheet")).toBeTruthy();
  });
});
