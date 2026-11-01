/** What a change to someone's work refreshes. */
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { keys, refreshAfterTaskChange } from "./hooks";

describe("after a task changes", () => {
  it("fetches again everything it shows up in, a head's My team and a person's work included", () => {
    const client = new QueryClient();
    const seeded = [keys.board(1), keys.review(1), keys.summary(1), keys.activity(1), keys.myTeam(1), keys.teamPerson(1, 9)];
    for (const key of seeded) client.setQueryData(key, []);
    client.setQueryData(keys.myTeam(2), []);
    refreshAfterTaskChange(client, 1);
    for (const key of seeded) expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    // Another company's numbers stay as they are.
    expect(client.getQueryState(keys.myTeam(2))?.isInvalidated).toBe(false);
  });
});
