/** The feed keeps working when the backend adds a kind of entry this app doesn't know yet. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Activity } from "../api/types";
import { ctxFor } from "../test/harness";
import { ActivityRow } from "./ActivityRow";

const entry = (kind: string) =>
  ({
    id: 1,
    kind,
    actor: { id: 3, name: "Bekzod Mirzayev", position: null },
    text: "",
    task: { id: 9, title: "Fridge temperature" },
    is_read: false,
    created_at: "2026-10-21T09:00:00+05:00",
  }) as unknown as Activity;

afterEach(cleanup);

describe("a feed entry", () => {
  it("reads the new kinds", () => {
    render(<ActivityRow item={entry("blocked")} ctx={ctxFor("uz")} onOpen={() => undefined} />);
    expect(screen.getByText("Bekzod Mirzayev vazifani bajara olmayapti")).toBeTruthy();
  });

  it("shows an unknown kind as a plain update instead of breaking the screen", () => {
    render(<ActivityRow item={entry("handed_over")} ctx={ctxFor("en")} onOpen={() => undefined} />);
    expect(screen.getByText("Bekzod Mirzayev updated a task")).toBeTruthy();
    expect(screen.getByText("Fridge temperature")).toBeTruthy();
  });
});
