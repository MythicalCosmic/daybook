/** Recognition in the mini app: the chip, achievements, the podium, thanks and the celebrations. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, Membership } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { NavigationProvider, useNavigation, type Navigation } from "../../state/navigation";
import { SessionProvider, type Member } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import { featureVisible } from "../registry";
import AchievementsPage from "./AchievementsPage";
import { recognitionKeys, type Leaderboard, type RecognitionMe } from "./api";
import CelebrationSheet from "./CelebrationSheet";
import { HeroChip, resetCelebrationForTests } from "./HeroChip";
import KudosSheet from "./KudosSheet";
import LeaderboardPage from "./LeaderboardPage";
import { celebrateTaskDone } from "./parts";
import { ThankedCard } from "./ThankedCard";

const api = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", async (importOriginal) => ({ ...(await importOriginal<object>()), api }));
const burst = vi.hoisted(() => vi.fn(() => () => {}));
vi.mock("../../ui/celebrate", () => ({ celebrate: burst, prefersReducedMotion: () => false }));

const { default: feature } = await import("./index");

function membership(features: string[] = ["recognition"]): Membership {
  return {
    id: 7,
    company: { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features, owner_sees_personal_tasks: false, base_currency: "UZS", team_directory_phones: false },
    status: "approved",
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Pharmacist",
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

const member = (features?: string[]): Member => ({ ...membership(features), timeZone: "Asia/Tashkent", companyId: 1 });

const person = (id: number, name: string) => ({ id, name, avatar_url: null, position: "Farmatsevt" });

function me(overrides: Partial<RecognitionMe> = {}): RecognitionMe {
  return {
    enabled: true,
    points: 310,
    week_points: 45,
    level: { number: 3, name: "Active", starts_at: 250, next_at: 500, next_name: "Knowledgeable" },
    streak: 5,
    best_streak: 9,
    badges: [{ key: "first_lesson", ref: "", name: "First lesson", description: "Watch a video lesson to the end.", icon: "circle-play", tier: "bronze", awarded_at: "2026-11-02T09:00:00Z" }],
    locked: [{ key: "top3_month", name: "Top three of the month", description: "Be one of the three with the most points in a month.", icon: "trophy", tier: "gold" }],
    recent: [{ id: 1, points: 20, reason: "quiz", label: "Quiz passed", detail: "Sovuq zanjir testi", at: "2026-11-06T10:00:00Z" }],
    unseen: [],
    kudos_enabled: true,
    kudos_left: 3,
    kudos_today: [],
    leaderboard: true,
    ...overrides,
  };
}

let navigation: Navigation;
function Probe() {
  navigation = useNavigation();
  return null;
}

function renderWith(node: ReactNode, client: QueryClient, features?: string[]) {
  const session = { id: 1, telegram_id: 1004, telegram_username: "", first_name: "Alisher", last_name: "Valiyev", phone: "", memberships: [membership(features)] } as Me;
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={session}>
            <NavigationProvider>
              <Probe />
              {node}
            </NavigationProvider>
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });

beforeEach(() => resetCelebrationForTests());
afterEach(() => {
  cleanup();
  api.mockReset();
  burst.mockClear();
});

describe("the feature", () => {
  it("shows only while the company runs recognition", () => {
    expect(featureVisible(feature, { member: member(), summary: undefined })).toBe(true);
    expect(featureVisible(feature, { member: member([]), summary: undefined })).toBe(false);
  });
});

describe("HeroChip", () => {
  it("shows the level, this week's points and the streak, and opens the achievements", () => {
    const client = newClient();
    client.setQueryData(recognitionKeys.me(1), me());
    renderWith(<HeroChip member={member()} summary={undefined} />, client);
    const chip = screen.getByTestId("recognition-chip");
    expect(within(chip).getByText("Active")).toBeTruthy();
    expect(within(chip).getByText("+45 this week")).toBeTruthy();
    expect(within(chip).getByText("5")).toBeTruthy();
    expect(chip.getAttribute("aria-label")).toBe("Level 3, Active. 45 points this week. Open my achievements");
    fireEvent.click(chip);
    expect(navigation.top).toEqual({ feature: "recognition", page: "achievements" });
  });

  it("stays away while points are off, and opens the celebration once for something new", () => {
    const client = newClient();
    client.setQueryData(recognitionKeys.me(1), me({ enabled: false }));
    const { unmount } = renderWith(<HeroChip member={member()} summary={undefined} />, client);
    expect(screen.queryByTestId("recognition-chip")).toBeNull();
    unmount();
    client.setQueryData(recognitionKeys.me(1), me({ unseen: [{ type: "level", number: 3, name: "Active", starts_at: 250, next_at: 500 }] }));
    renderWith(<HeroChip member={member()} summary={undefined} />, client);
    expect(navigation.sheet).toEqual({ kind: "feature", feature: "recognition", sheet: "celebrate" });
    act(() => navigation.closeSheet());
    cleanup();
    renderWith(<HeroChip member={member()} summary={undefined} />, client);
    expect(navigation.sheet).toBeNull(); // once per session
  });
});

describe("AchievementsPage", () => {
  it("shows the level, the next one, the streak, badges earned and to earn, and the points", () => {
    const client = newClient();
    client.setQueryData(recognitionKeys.me(1), me());
    renderWith(<AchievementsPage params={{}} />, client);
    expect(screen.getByText("Level 3")).toBeTruthy();
    expect(screen.getByText("190 points to «Knowledgeable»")).toBeTruthy();
    expect(screen.getByText("5 days in a row")).toBeTruthy();
    expect(screen.getByText(/Best: 9 days/)).toBeTruthy();
    expect(within(screen.getByTestId("badges-earned")).getByText("First lesson")).toBeTruthy();
    expect(within(screen.getByTestId("badges-locked")).getByText("Be one of the three with the most points in a month.")).toBeTruthy();
    expect(screen.getByText("Quiz passed")).toBeTruthy();
    expect(screen.getByText("+20")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Leaderboard/ }));
    expect(navigation.top).toEqual({ feature: "recognition", page: "leaderboard" });
  });
});

describe("LeaderboardPage", () => {
  const board = (overrides: Partial<Leaderboard> = {}): Leaderboard => ({
    visible: true,
    period: "week",
    scope: "company",
    start: null,
    end: null,
    rows: [
      { place: 1, member: person(3, "Madina Saidova"), points: 120, level: { number: 3, name: "Active" } },
      { place: 2, member: person(5, "Nigora Azimova"), points: 90, level: { number: 2, name: "Learner" } },
      { place: 3, member: person(9, "Jasur Tursunov"), points: 40, level: { number: 1, name: "Newcomer" } },
      { place: 4, member: person(7, "Alisher Valiyev"), points: 25, level: { number: 1, name: "Newcomer" } },
    ],
    me: { place: 4, points: 25 },
    ...overrides,
  });

  it("puts the top three on the podium, second first, and the rest in the list", async () => {
    api.mockResolvedValue(board());
    renderWith(<LeaderboardPage params={{}} />, newClient());
    const podium = await screen.findByTestId("podium");
    const names = [...podium.querySelectorAll(".rcg-podium-name")].map((node) => node.textContent);
    expect(names).toEqual(["Nigora", "Madina", "Jasur"]);
    expect(screen.getByText("Alisher Valiyev")).toBeTruthy();
    expect(within(screen.getByTestId("board-me")).getByText("#4 · 25 points")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/companies/1/recognition/leaderboard/?period=week&scope=company");
    fireEvent.click(screen.getByRole("radio", { name: "This month" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/companies/1/recognition/leaderboard/?period=month&scope=company"));
  });

  it("says so when the company keeps it from staff", async () => {
    api.mockResolvedValue(board({ visible: false, rows: [], me: { place: null, points: 10 } }));
    renderWith(<LeaderboardPage params={{}} />, newClient());
    expect(await screen.findByText("The leaderboard isn’t shown in your company.")).toBeTruthy();
  });
});

describe("KudosSheet", () => {
  it("thanks the colleague the link named, with a reason and a note", async () => {
    const close = vi.fn();
    api.mockImplementation((path: string, options?: { method?: string; json?: unknown }) => {
      if (options?.method === "POST") return Promise.resolve({ id: 11 });
      if (path.includes("colleagues")) return Promise.resolve({ per_day: 3, left: 2, results: [{ ...person(3, "Madina Saidova"), branch: "Chilonzor" }] });
      return Promise.resolve(me());
    });
    renderWith(<KudosSheet params={{ to: 3 }} close={close} />, newClient());
    expect(await screen.findByText("Madina Saidova")).toBeTruthy();
    expect(screen.getByText("You can thank 2 more colleagues today")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /Careful work/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  Muzlatgichni tekshirding " } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send thanks" })));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(api).toHaveBeenCalledWith("/companies/1/recognition/kudos/", { method: "POST", json: { to: 3, badge: "careful", message: "Muzlatgichni tekshirding" } });
    expect(burst).toHaveBeenCalledWith(expect.objectContaining({ pieces: 40 }));
  });

  it("can't send once today's thanks are used", async () => {
    api.mockResolvedValue({ per_day: 3, left: 0, results: [{ ...person(3, "Madina Saidova"), branch: null }] });
    renderWith(<KudosSheet params={{ to: 3 }} close={vi.fn()} />, newClient());
    expect(await screen.findByText("You’ve used today’s thanks. More tomorrow.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Send thanks" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("celebrations", () => {
  it("steps through what's new with confetti and tells the server once", async () => {
    const client = newClient();
    client.setQueryData(
      recognitionKeys.me(1),
      me({
        unseen: [
          { type: "level", number: 3, name: "Active", starts_at: 250, next_at: 500 },
          { type: "badge", key: "perfect_score", ref: "", name: "Perfect score", description: "Answer every question of a test right.", icon: "target", tier: "silver", awarded_at: "2026-11-07T08:00:00Z" },
        ],
      }),
    );
    api.mockResolvedValue(undefined);
    const close = vi.fn();
    renderWith(<CelebrationSheet params={{}} close={close} />, client);
    expect(screen.getByText("New level!")).toBeTruthy();
    expect(screen.getByText("You reached level 3: Active.")).toBeTruthy();
    expect(burst).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/companies/1/recognition/seen/", { method: "POST", json: {} }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Perfect score")).toBeTruthy();
    expect(screen.getByText("Silver")).toBeTruthy();
    expect(burst).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Wonderful" }));
    expect(close).toHaveBeenCalled();
    expect(api.mock.calls.filter(([path]) => String(path).endsWith("/seen/"))).toHaveLength(1);
  });

  it("bursts for shared work done on time only, while recognition is on", () => {
    const done = { kind: "assigned", status: "done", due_at: "2026-11-07T13:00:00Z", completed_at: "2026-11-07T12:00:00Z" } as const;
    expect(celebrateTaskDone(member(), done)).toBe(true);
    expect(burst).toHaveBeenCalledWith(expect.objectContaining({ pieces: 36, haptic: null }));
    expect(celebrateTaskDone(member(), { ...done, status: "review" })).toBe(true);
    expect(celebrateTaskDone(member(), { ...done, completed_at: "2026-11-07T13:05:00Z" })).toBe(false);
    expect(celebrateTaskDone(member(), { ...done, kind: "personal" })).toBe(false);
    expect(celebrateTaskDone(member(), { ...done, due_at: null })).toBe(false);
    expect(celebrateTaskDone(member([]), done)).toBe(false);
  });
});

describe("ThankedCard", () => {
  it("names who thanked today and opens the thanks", () => {
    const client = newClient();
    const kudos = { id: 4, from: person(3, "Madina Saidova"), to: person(7, "Alisher Valiyev"), badge: "careful" as const, badge_label: "Careful work", message: "Rahmat", task: null, at: "2026-11-07T08:00:00Z", seen: false, mine: false };
    client.setQueryData(recognitionKeys.me(1), me({ kudos_today: [kudos] }));
    renderWith(<ThankedCard member={member()} summary={undefined} />, client);
    expect(screen.getByText("Madina thanked you")).toBeTruthy();
    expect(screen.getByText("Careful work · «Rahmat»")).toBeTruthy();
    fireEvent.click(screen.getByText("Madina thanked you"));
    expect(navigation.top).toEqual({ feature: "recognition", page: "kudos" });
    cleanup();
    client.setQueryData(recognitionKeys.me(1), me({ kudos_today: [{ ...kudos, seen: true }] }));
    const { container } = renderWith(<ThankedCard member={member()} summary={undefined} />, client);
    expect(container.querySelector(".banner")).toBeNull();
  });
});
