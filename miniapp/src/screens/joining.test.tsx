/**
 * The first screens a new employee sees: creating the account (name, phone, position), the
 * waiting room and its welcome, the "can't get in" screens, and the app opened without a
 * sign-in (from a keyboard button) or outside Telegram.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import type { Me, Membership } from "../api/types";
import { I18nProvider } from "../i18n";
import { revealFocusedField } from "../lib/keyboard";
import { formatPhone } from "../lib/phone";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";
import { CreateAccount } from "./CreateAccount";
import { Left } from "./Gate";
import { Waiting } from "./Waiting";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

function membership(extra: Partial<Membership> = {}): Membership {
  return {
    id: 7,
    company: { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent" },
    status: "pending",
    first_name: "Javohir",
    last_name: "Rasulov",
    position: null,
    role: null,
    permissions: [],
    is_onboarded: false,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    ...extra,
  } as unknown as Membership;
}

function person(phone = "", member = membership()): Me {
  return { id: 1, telegram_id: 5001, telegram_username: "", first_name: "Javohir", last_name: "Rasulov", phone, language: "en", memberships: [member] } as Me;
}

const positions = [
  { id: 11, name: "Farmatsevt" },
  { id: 12, name: "Kassir" },
];

function renderWith(node: ReactNode, me: Me) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(keys.me, me);
  client.setQueryData(keys.positions(1), positions);
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider lang="en">
        <ToastProvider>
          <SessionProvider me={me}>{node}</SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const bar = () => document.querySelector<HTMLButtonElement>(".action-bar .btn-primary")!;

afterEach(() => {
  cleanup();
  api.mockReset();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("creating the account", () => {
  it("names the company being joined and keeps each step's action in the bottom bar", () => {
    renderWith(<CreateAccount membership={membership()} />, person());
    expect(screen.getByText("Demo Dorixona")).toBeTruthy();
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
    // One action, at the foot of the page (Telegram's main button inside Telegram).
    expect(bar().textContent).toBe("Continue");
    expect(bar().disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Last name"), { target: { value: " " } });
    expect(bar().disabled).toBe(true);
  });

  it("moves from the first name to the last name with the keyboard's Next, and on with Go", () => {
    renderWith(<CreateAccount membership={membership()} />, person());
    const first = screen.getByLabelText("First name");
    first.focus();
    fireEvent.keyDown(first, { key: "Enter" });
    expect(document.activeElement).toBe(screen.getByLabelText("Last name"));
    fireEvent.keyDown(screen.getByLabelText("Last name"), { key: "Enter" });
    expect(screen.getByText("Your phone number")).toBeTruthy();
  });

  it("makes sharing the phone the phone step's action, and says why it can't when Telegram can't", () => {
    renderWith(<CreateAccount membership={membership()} />, person());
    fireEvent.click(bar());
    expect(screen.getByText("Not shared yet")).toBeTruthy();
    expect(bar().textContent).toBe("Share my phone number");
    // Outside Telegram (or on a client older than Bot API 6.9) there is no contact request.
    fireEvent.click(bar());
    expect(screen.getByRole("status").textContent).toMatch(/can't share your number from here/);
  });

  it("shows the verified number, written the Uzbek way, and goes on to the position", () => {
    renderWith(<CreateAccount membership={membership()} />, person("+998901234567"));
    fireEvent.click(bar());
    expect(screen.getByText("+998 90 123 45 67")).toBeTruthy();
    expect(screen.getByText("Verified by Telegram")).toBeTruthy();
    expect(bar().textContent).toBe("Continue");
    fireEvent.click(bar());
    expect(screen.getByText("What's your position?")).toBeTruthy();
  });

  it("sends the request only once a position is chosen", async () => {
    api.mockResolvedValue(membership({ is_onboarded: true }));
    renderWith(<CreateAccount membership={membership()} />, person("+998901234567"));
    fireEvent.click(bar());
    fireEvent.click(bar());
    expect(bar().textContent).toBe("Send my request");
    expect(bar().disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "Kassir" }));
    expect(bar().disabled).toBe(false);
    fireEvent.click(bar());
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/companies/1/onboarding/", { json: { first_name: "Javohir", last_name: "Rasulov", position_id: 12 } }),
    );
  });

  it("waits for the bot after Telegram shares the phone, and offers to share again when it's slow", async () => {
    // A Telegram client that can ask for the contact (but draws no main button, so the action
    // stays in the page): telegram.ts reads it when it loads, hence a fresh module graph.
    const requestContact = vi.fn((done: (shared: boolean) => void) => done(true));
    vi.stubGlobal("Telegram", { WebApp: { platform: "android", initData: "", isVersionAtLeast: () => true, requestContact } });
    vi.resetModules();
    const [{ I18nProvider: I18n }, { SessionProvider: Session }, { ToastProvider: Toasts }, { CreateAccount: Fresh }] = await Promise.all([
      import("../i18n"),
      import("../state/session"),
      import("../state/toast"),
      import("./CreateAccount"),
    ]);
    api.mockResolvedValue(person()); // the bot hasn't got the contact yet
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    client.setQueryData(keys.me, person());
    vi.useFakeTimers();
    try {
      render(
        <QueryClientProvider client={client}>
          <I18n lang="en">
            <Toasts>
              <Session me={person()}>
                <Fresh membership={membership()} />
              </Session>
            </Toasts>
          </I18n>
        </QueryClientProvider>,
      );
      fireEvent.click(bar());
      await act(async () => fireEvent.click(bar()));
      expect(requestContact).toHaveBeenCalledOnce();
      expect(bar().textContent).toContain("Waiting for Telegram…");
      expect(screen.getByText("This takes a few seconds.")).toBeTruthy();

      await act(async () => vi.advanceTimersByTime(12_500));
      expect(bar().textContent).toBe("Share again");
      expect(screen.getByRole("status").textContent).toMatch(/hasn't reached us yet/);
    } finally {
      vi.useRealTimers();
    }
  }, 20_000);
});

describe("the waiting room", () => {
  it("shows the request while it's checked, and the welcome without it once approved", () => {
    const pending = membership({ is_onboarded: true, onboarded_at: "2026-10-21T08:00:00Z", position: { id: 12, name: "Kassir" } as never });
    renderWith(<Waiting membership={pending} onOpen={() => undefined} />, person("+998935550202", pending));
    expect(screen.getByText("Almost there")).toBeTruthy();
    expect(screen.getByText("Your request")).toBeTruthy();
    expect(screen.getByText("+998 93 555 02 02")).toBeTruthy();
    expect(screen.getByText("Your manager checks it")).toBeTruthy();
    cleanup();

    const onOpen = vi.fn();
    const approved = { ...pending, status: "approved" } as Membership;
    renderWith(<Waiting membership={approved} onOpen={onOpen} />, person("+998935550202", approved));
    expect(screen.getByText("You're in, Javohir!")).toBeTruthy();
    expect(screen.queryByText("Your request")).toBeNull();
    fireEvent.click(bar());
    expect(onOpen).toHaveBeenCalled();
  });

  it("welcomes someone a team link let in, without the steps of an approval nobody made", () => {
    const joined = membership({ status: "approved", is_onboarded: true, onboarded_at: "2026-10-26T08:00:00Z", joined_by_link: true } as never);
    const onOpen = vi.fn();
    renderWith(<Waiting membership={joined} onOpen={onOpen} />, person("+998935550202", joined));
    expect(screen.getByText("Welcome to the team, Javohir!")).toBeTruthy();
    expect(screen.getByText("You've joined Demo Dorixona. Your tasks will show up here.")).toBeTruthy();
    expect(screen.queryByText("Your manager checks it")).toBeNull();
    fireEvent.click(bar());
    expect(onOpen).toHaveBeenCalled();
  });
});

describe("the gate screens", () => {
  it("thank someone who left instead of telling them they aren't in a company yet", () => {
    const left = membership({ status: "left", is_onboarded: true } as Partial<Membership>);
    renderWith(<Left membership={left} />, person("", left));
    expect(screen.getByText("You're no longer on the team")).toBeTruthy();
    expect(screen.getByText(/Thank you for your work at Demo Dorixona/)).toBeTruthy();
  });
});

describe("opening the app", () => {
  async function loadApp(webApp: Record<string, unknown> | undefined) {
    vi.stubEnv("VITE_DEV_INIT_DATA", "");
    vi.stubGlobal("Telegram", webApp ? { WebApp: { isVersionAtLeast: () => true, onEvent: vi.fn(), offEvent: vi.fn(), initDataUnsafe: {}, ...webApp } } : undefined);
    vi.resetModules();
    const { App } = await import("../App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );
  }

  it("speaks Uzbek when nothing else is known, whatever the phone or Telegram is in", async () => {
    await loadApp({ platform: "android", initData: "", sendData: vi.fn(), close: vi.fn(), initDataUnsafe: { user: { language_code: "en" } } });
    expect(await screen.findByText("Daybookni chatdan oching")).toBeTruthy();
    // The phone's button, as the bot labels it: words only, no emoji.
    expect(document.querySelector(".gate-hint-app")?.textContent).toBe("Ilovani ochish");
  }, 20_000);

  it("inside Telegram without a sign-in, points to the chat's buttons and asks the bot for one", async () => {
    const sendData = vi.fn();
    localStorage.setItem("daybook.lang", "en");
    await loadApp({ platform: "android", initData: "", sendData, close: vi.fn() });
    localStorage.removeItem("daybook.lang");
    expect(await screen.findByText("Open Daybook from the chat")).toBeTruthy();
    expect(screen.getByText(/button at the bottom left of the chat/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send me a button" }));
    expect(sendData).toHaveBeenCalledWith("open_app");
    expect(screen.getByRole("button", { name: "Back to the chat" })).toBeTruthy();
  }, 20_000);

  it("speaks the language the person last used the app in when nobody is signed in", async () => {
    localStorage.setItem("daybook.lang", "uz");
    try {
      await loadApp({ platform: "android", initData: "", sendData: vi.fn(), close: vi.fn() });
      expect(await screen.findByText("Daybookni chatdan oching")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Menga tugma yuboring" })).toBeTruthy();
    } finally {
      localStorage.removeItem("daybook.lang");
    }
  }, 20_000);

  it("in a browser, says the app lives in Telegram", async () => {
    await loadApp({ platform: "unknown", initData: "" });
    // Uzbek first, then English when it was the language used last.
    expect(await screen.findByText("Daybookni Telegramda oching")).toBeTruthy();
    cleanup();
    localStorage.setItem("daybook.lang", "en");
    await loadApp({ platform: "unknown", initData: "" });
    localStorage.removeItem("daybook.lang");
    expect(await screen.findByText("Open Daybook in Telegram")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send me a button" })).toBeNull();
  }, 20_000);
});

describe("the on-screen keyboard", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 520 });
  });

  function field(top: number) {
    const input = document.createElement("input");
    document.body.append(input);
    input.getBoundingClientRect = () => ({ top, bottom: top + 54, left: 0, right: 300, width: 300, height: 54, x: 0, y: top, toJSON: () => ({}) });
    input.scrollIntoView = vi.fn();
    input.focus();
    return input;
  }

  it("brings a field the keyboard covers back into view, and leaves a visible one alone", () => {
    const hidden = field(600);
    revealFocusedField();
    expect(hidden.scrollIntoView).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
    hidden.remove();

    const visible = field(200);
    revealFocusedField();
    expect(visible.scrollIntoView).not.toHaveBeenCalled();
    visible.remove();
  });

  it("counts the box the field scrolls in: a field cut off at its edge is hidden too", () => {
    const box = document.createElement("div");
    box.style.overflowY = "auto";
    box.getBoundingClientRect = () => ({ top: 56, bottom: 456, left: 0, right: 390, width: 390, height: 400, x: 0, y: 56, toJSON: () => ({}) });
    document.body.append(box);
    const input = document.createElement("input");
    box.append(input);
    input.getBoundingClientRect = () => ({ top: 420, bottom: 474, left: 0, right: 300, width: 300, height: 54, x: 0, y: 420, toJSON: () => ({}) });
    input.scrollIntoView = vi.fn();
    input.focus();
    revealFocusedField();
    expect(input.scrollIntoView).toHaveBeenCalled();
    box.remove();
  });

  it("counts the page's action bar as covering the foot of the page", () => {
    const actionBar = document.createElement("div");
    actionBar.className = "action-bar";
    actionBar.getBoundingClientRect = () => ({ top: 430, bottom: 520, left: 0, right: 390, width: 390, height: 90, x: 0, y: 430, toJSON: () => ({}) });
    document.body.append(actionBar);
    const underBar = field(400);
    revealFocusedField();
    expect(underBar.scrollIntoView).toHaveBeenCalled();
    underBar.remove();
    actionBar.remove();
  });
});

describe("phone numbers", () => {
  it("are written the Uzbek way when they are Uzbek, and left alone otherwise", () => {
    expect(formatPhone("+998901234567")).toBe("+998 90 123 45 67");
    expect(formatPhone("998901234567")).toBe("+998 90 123 45 67");
    expect(formatPhone("+447700900123")).toBe("+447700900123");
  });
});
