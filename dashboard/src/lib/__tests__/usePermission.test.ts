import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useCan, usePermission } from "@/lib/usePermission";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, manager, me } from "@/test/fixtures";

describe("usePermission", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const session = useSessionStore();
    session.me = me([company(), manager(["members.view", "sales.view"], { features: ["sales"] })]);
    session.accessToken = "token";
  });

  it("owners hold every permission", () => {
    useCompanyStore().setCurrent(1);
    const { can, canAll, isOwner } = usePermission();
    expect(can("payroll.finalize")).toBe(true);
    expect(canAll(["finance.view", "hr.sensitive"])).toBe(true);
    expect(isOwner.value).toBe(true);
  });

  it("other roles hold only what the role grants", () => {
    const store = useCompanyStore();
    store.setCurrent(2);
    const { can, canAll, enabled } = usePermission();
    expect(can("sales.view")).toBe(true);
    expect(can(["finance.view", "members.view"])).toBe(true);
    expect(can("finance.view")).toBe(false);
    expect(canAll(["sales.view", "finance.view"])).toBe(false);
    expect(can()).toBe(true);
    expect(enabled("sales")).toBe(true);
    expect(enabled("finance")).toBe(false);
    const canExport = useCan("data.export");
    expect(canExport.value).toBe(false);
    store.setCurrent(1);
    expect(canExport.value).toBe(true);
  });

  it("nothing is allowed outside a company", () => {
    useCompanyStore().setCurrent(99);
    expect(usePermission().can()).toBe(false);
  });
});
