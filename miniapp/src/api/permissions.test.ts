import { describe, expect, it } from "vitest";

import { checksWork, givesWork, leadsTeam } from "./permissions";

describe("department heads", () => {
  it("give and check work through their team, whatever their role", () => {
    const head = { permissions: [], team_size: 3 };
    expect(leadsTeam(head)).toBe(true);
    expect(givesWork(head)).toBe(true);
    expect(checksWork(head)).toBe(true);
  });

  it("leave everyone else to their role's permissions", () => {
    expect(givesWork({ permissions: [], team_size: 0 })).toBe(false);
    expect(givesWork({ permissions: ["tasks.assign"] })).toBe(true);
    expect(checksWork({ permissions: ["tasks.confirm"], team_size: 0 })).toBe(true);
    expect(checksWork({ permissions: ["tasks.assign"] })).toBe(false);
  });
});
