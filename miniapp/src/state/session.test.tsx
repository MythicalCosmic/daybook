/**
 * Which company the app opens in for someone in two: the one used last on this phone, else the
 * one used last on another phone (Telegram's cloud), read before the first screen so the company
 * never changes under an open screen.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { membership, person } from "../test/harness";
import { SessionProvider, useSession } from "./session";

function Company() {
  const { membership: current } = useSession();
  return <span>{current?.company.name}</span>;
}

const twoCompanies = () => person([membership({ companyId: 1, companyName: "Demo Dorixona" }), membership({ id: 70, companyId: 2, companyName: "Demo Distribyutor" })]);

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("the company the app opens in", () => {
  it("is the one used last on another phone, from the first screen on", async () => {
    // telegram.ts keeps cloud values in localStorage outside Telegram.
    localStorage.setItem("daybook.cloud.company", "2");
    render(
      <SessionProvider me={twoCompanies()}>
        <Company />
      </SessionProvider>,
    );
    // Nothing is shown in the wrong company first.
    expect(screen.queryByText("Demo Dorixona")).toBeNull();
    expect(await screen.findByText("Demo Distribyutor")).toBeTruthy();
  });

  it("is the one chosen on this phone, at once", () => {
    localStorage.setItem("daybook.company", "1");
    localStorage.setItem("daybook.cloud.company", "2");
    render(
      <SessionProvider me={twoCompanies()}>
        <Company />
      </SessionProvider>,
    );
    expect(screen.getByText("Demo Dorixona")).toBeTruthy();
  });

  it("is the one picked last anywhere, even if this phone remembers another", () => {
    // A switch in the bot or the dashboard moves bot_company; the app follows at its next launch.
    localStorage.setItem("daybook.company", "1");
    render(
      <SessionProvider me={{ ...twoCompanies(), bot_company: 2 }}>
        <Company />
      </SessionProvider>,
    );
    expect(screen.getByText("Demo Distribyutor")).toBeTruthy();
  });

  it("falls back to this phone's choice when the bot's company isn't one the person works in", () => {
    localStorage.setItem("daybook.company", "1");
    render(
      <SessionProvider me={{ ...twoCompanies(), bot_company: 99 }}>
        <Company />
      </SessionProvider>,
    );
    expect(screen.getByText("Demo Dorixona")).toBeTruthy();
  });

  it("is the one the bot and the dashboard use when nothing was chosen on a phone", async () => {
    // The server's choice (a company they own, the most branches), not simply the first listed.
    render(
      <SessionProvider me={{ ...twoCompanies(), bot_company: 2 }}>
        <Company />
      </SessionProvider>,
    );
    expect(await screen.findByText("Demo Distribyutor")).toBeTruthy();
    expect(screen.queryByText("Demo Dorixona")).toBeNull();
  });
});
