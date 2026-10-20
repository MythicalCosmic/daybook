import { describe, expect, it } from "vitest";

import {
  baseCurrency,
  branchIds,
  hasModule,
  homeBranch,
  isSuspended,
  ownerSeesPersonalTasks,
  suspendedUntil,
  teamDirectoryPhones,
} from "./membership";
import type { Membership } from "./types";

/** A membership as `me/` sends it, with or without the phase 2 fields. */
function membership(company: Record<string, unknown> = {}, extra: Record<string, unknown> = {}): Membership {
  return {
    id: 7,
    company: { id: 1, name: "Demo Shop", timezone: "Asia/Tashkent", ...company },
    status: "approved",
    first_name: "Alisher",
    last_name: "Valiyev",
    position: null,
    role: "Employee",
    permissions: [],
    is_onboarded: true,
    onboarded_at: null,
    decided_at: null,
    rejoin_available_at: null,
    ...extra,
  } as unknown as Membership;
}

describe("membership facts", () => {
  it("read the company's module switches", () => {
    const shop = membership({ features: ["sales", "payroll"] });
    expect(hasModule(shop, "sales")).toBe(true);
    expect(hasModule(shop, "attendance")).toBe(false);
  });

  it("read the company's settings and the person's branches", () => {
    const shop = membership(
      { owner_sees_personal_tasks: false, team_directory_phones: true, base_currency: "USD" },
      { home_branch: { id: 3, name: "Chilonzor" }, branch_ids: [3, 4] },
    );
    expect(ownerSeesPersonalTasks(shop)).toBe(false);
    expect(teamDirectoryPhones(shop)).toBe(true);
    expect(baseCurrency(shop)).toBe("USD");
    expect(homeBranch(shop)).toEqual({ id: 3, name: "Chilonzor" });
    expect(branchIds(shop)).toEqual([3, 4]);
  });

  it("fall back to the safe answer when an older server leaves a field out", () => {
    const old = membership();
    expect(hasModule(old, "sales")).toBe(false);
    expect(ownerSeesPersonalTasks(old)).toBe(true);
    expect(teamDirectoryPhones(old)).toBe(false);
    expect(baseCurrency(old)).toBe("UZS");
    expect(homeBranch(old)).toBeNull();
    expect(branchIds(old)).toEqual([]);
  });

  it("tell a suspended membership apart", () => {
    expect(isSuspended(membership({}, { status: "suspended" }))).toBe(true);
    expect(isSuspended(membership())).toBe(false);
    expect(suspendedUntil(membership({}, { status: "suspended", suspended_until: "2026-11-12" }))).toBe("2026-11-12");
    expect(suspendedUntil(membership({}, { status: "suspended", suspended_until: null }))).toBeNull();
  });
});
