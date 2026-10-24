/**
 * Changing the language switches the app at once, saves it on the server (which relabels the
 * bot's chat), says so in the new language, and goes back if the server refuses.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { keys, useMe } from "../api/hooks";
import type { Me } from "../api/types";
import { asLang, I18nProvider } from "../i18n";
import { NavigationProvider } from "../state/navigation";
import { SessionProvider } from "../state/session";
import { ToastProvider } from "../state/toast";
import { membership, person } from "../test/harness";
import { Sheets } from "./Sheets";

const api = vi.hoisted(() => vi.fn());
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

/** The app's own wiring: the language comes from `me`, as App.tsx reads it. */
function Shell() {
  const me = useMe();
  return me.data ? (
    <I18nProvider lang={asLang(me.data.language)}>
      <ToastProvider>
        <SessionProvider me={me.data}>
          <NavigationProvider initial={{ sheet: { kind: "language" } }}>
            <Sheets />
          </NavigationProvider>
        </SessionProvider>
      </ToastProvider>
    </I18nProvider>
  ) : null;
}

function renderShell() {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(keys.me, person([membership()], "uz"));
  render(
    <QueryClientProvider client={client}>
      <Shell />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => document.documentElement.removeAttribute("lang"));
afterEach(() => {
  cleanup();
  api.mockReset();
});

describe("the language sheet", () => {
  it("switches at once, saves it, and confirms in the new language", async () => {
    let answer: (me: Me) => void = () => undefined;
    api.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const client = renderShell();
    expect(screen.getByText("Botning menyusi va xabarlari ham shu tilga o‘tadi.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Русский" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/me/", { method: "PATCH", json: { language: "ru" } }));
    // Russian before the server has answered.
    await waitFor(() => expect(client.getQueryData<Me>(keys.me)?.language).toBe("ru"));
    expect(await screen.findByText("Меню и сообщения бота тоже переключатся.")).toBeTruthy();
    act(() => answer(person([membership()], "ru")));
    expect(await screen.findByText("Язык изменён. Бот тоже будет писать по-русски.")).toBeTruthy();
  });

  it("goes back to the old language if the server refuses", async () => {
    api.mockRejectedValue(new ApiError(400, { language: ["Not allowed."] }));
    const client = renderShell();
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(await screen.findByText("Not allowed.")).toBeTruthy();
    expect(client.getQueryData<Me>(keys.me)?.language).toBe("uz");
  });

  it("does nothing for the language already chosen", () => {
    renderShell();
    fireEvent.click(screen.getByRole("radio", { name: "O‘zbekcha" }));
    expect(api).not.toHaveBeenCalled();
  });
});
