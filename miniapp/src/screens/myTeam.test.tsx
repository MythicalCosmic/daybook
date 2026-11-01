/** A department head's My team: their people with counts, one person's open and finished work. */
import type { QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keys } from "../api/hooks";
import { makeTask, membership, navigationState, person, renderApp } from "../test/harness";
import { Home } from "./Home";
import { MyTeam } from "./MyTeam";
import { Profile } from "./Profile";
import { Tasks } from "./Tasks";
import { TeamPerson } from "./TeamPerson";

const api = vi.hoisted(() => vi.fn((_path: string): Promise<unknown> => Promise.reject(new Error("no network in tests"))));
vi.mock("../api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api/client")>()), api }));

afterEach(() => cleanup());

const head = () => person([membership({ heads: ["Moliya Bolimi"], team_size: 1 } as never)]);

describe("My team", () => {
  it("lists the head's people with open, late and done counts", () => {
    renderApp(<MyTeam />, {
      me: head(),
      seed: (client) =>
        client.setQueryData(keys.myTeam(1), {
          departments: ["Moliya Bolimi"],
          people: [{ id: 9, name: "Alisher Valiyev", position: "Kassir", department: "Moliya Bolimi", open: 3, late: 1, done_week: 5 }],
        }),
    });
    expect(screen.getByText("My team")).toBeTruthy();
    expect(screen.getByText("Alisher Valiyev")).toBeTruthy();
    expect(screen.getByText("3 open")).toBeTruthy();
    expect(screen.getByText("1 late")).toBeTruthy();
    expect(screen.getByText("5 done this week")).toBeTruthy();
  });

  it("shows a person's open work and what they finished, with the proof photo", () => {
    renderApp(<TeamPerson memberId={9} />, {
      me: head(),
      seed: (client) =>
        client.setQueryData(keys.teamPerson(1, 9), {
          person: { id: 9, name: "Alisher Valiyev", position: "Kassir", department: "Moliya Bolimi", open: 1, late: 0, done_week: 1 },
          open: [makeTask({ id: 1, title: "Kassani sanash" })],
          done: [makeTask({ id: 2, title: "Muzlatgich harorati", status: "done", proof_thumb: "/media/t.webp" } as never)],
        }),
    });
    expect(screen.getByText("Kassani sanash")).toBeTruthy();
    expect(screen.getByText("Muzlatgich harorati")).toBeTruthy();
    expect(screen.getByAltText("Proof photo")).toBeTruthy();
  });

  it("waits at the top of Home and Tasks for a head, with how many of their tasks are late", () => {
    for (const page of [<Home key="home" />, <Tasks key="tasks" />]) {
      renderApp(page, {
        me: head(),
        seed: (client) =>
          client.setQueryData(keys.myTeam(1), {
            departments: ["Moliya Bolimi"],
            people: [{ id: 9, name: "Alisher Valiyev", position: "Kassir", department: "Moliya Bolimi", open: 3, late: 2, done_week: 5 }],
          }),
      });
      expect(screen.getByRole("button", { name: /My team/ })).toBeTruthy();
      expect(screen.getByText("Moliya Bolimi · People: 1 · 2 late")).toBeTruthy();
      cleanup();
    }
    renderApp(<Home />, { me: person([membership()]) });
    expect(screen.queryByRole("button", { name: /My team/ })).toBeNull();
  });

  it("draws each person as a row (avatar, numbers, chevron), a borderless card button", () => {
    renderApp(<MyTeam />, {
      me: head(),
      seed: (client) =>
        client.setQueryData(keys.myTeam(1), {
          departments: ["Moliya Bolimi"],
          people: [{ id: 9, name: "Alisher Valiyev", position: "Kassir", department: "Moliya Bolimi", open: 3, late: 0, done_week: 5 }],
        }),
    });
    // Was a plain `.card` button: a column with everything centred and the button's own border.
    const row = screen.getByRole("button", { name: /Alisher Valiyev/ });
    expect(row.classList.contains("card--row")).toBe(true);
    expect(row.classList.contains("card--tap")).toBe(true);
    expect(row.querySelector(".avatar")?.textContent).toBe("AV");
  });

  it("has a way back on My team, a person and team results where Telegram draws no back button", () => {
    const seed = (client: QueryClient) => {
      client.setQueryData(keys.myTeam(1), { departments: ["Moliya Bolimi"], people: [] });
      client.setQueryData(keys.teamPerson(1, 9), {
        person: { id: 9, name: "Alisher Valiyev", position: "Kassir", department: "Moliya Bolimi", open: 0, late: 0, done_week: 0 },
        open: [],
        done: [],
      });
    };
    for (const page of [<MyTeam key="team" />, <TeamPerson key="person" memberId={9} />]) {
      renderApp(page, { me: head(), seed, init: { stack: [{ feature: "core", page: "myTeam" }, { feature: "core", page: "teamPerson", params: { id: 9 } }] } });
      fireEvent.click(screen.getByRole("button", { name: "Back" }));
      expect(navigationState().stack).toHaveLength(1);
      cleanup();
    }
  });

  it("is on Me only for someone who heads a department", () => {
    renderApp(<Profile />, { me: head() });
    expect(screen.getByRole("button", { name: /My team/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /My team/ }));
    cleanup();
    renderApp(<Profile />, { me: person([membership()]) });
    expect(screen.queryByRole("button", { name: /My team/ })).toBeNull();
  });
});
