import { describe, expect, it, vi } from "vitest";

import { defineFeature, type Feature, type PageProps, type SheetProps } from "../features/registry";
import { parseScreen, readScreenLink, resolveScreen } from "./deeplink";
import { CORE, taskPage } from "./navigation";

const Page = (_: PageProps) => null;
const SheetBody = (_: SheetProps) => null;

const wallet: Feature = defineFeature({
  id: "wallet",
  messages: { en: { title: "Pay" }, ru: { title: "Зарплата" }, uz: { title: "Maosh" } },
  pages: { home: Page, payslip: Page },
  sheets: { advance: SheetBody },
  routes: {
    wallet: "home",
    payslip: { page: "payslip", tab: "profile" },
    advance: { sheet: "advance", param: "amount" },
    custom: (arg) => (arg ? { tab: "tasks", tasksTab: "review" } : null),
    broken: () => {
      throw new Error("bad route");
    },
  },
});

describe("screen links", () => {
  it("split a name from its argument", () => {
    expect(parseScreen("payslip:12")).toEqual({ name: "payslip", arg: "12" });
    expect(parseScreen("home")).toEqual({ name: "home", arg: null });
    expect(parseScreen("wallet.payslip:12")).toEqual({ name: "wallet.payslip", arg: "12" });
    expect(parseScreen("calendar:2026-10-20")).toEqual({ name: "calendar", arg: "2026-10-20" });
  });

  it("read startapp parameters, where Telegram allows no colon", () => {
    expect(parseScreen("payslip-12", "startapp")).toEqual({ name: "payslip", arg: "12" });
    expect(parseScreen("calendar-2026-10-20", "startapp")).toEqual({ name: "calendar", arg: "2026-10-20" });
    expect(parseScreen("tasks", "startapp")).toEqual({ name: "tasks", arg: null });
    // No "." allowed there either: "__" stands for it.
    expect(parseScreen("wallet__payslip-12", "startapp")).toEqual({ name: "wallet.payslip", arg: "12" });
    expect(parseScreen("time_off", "startapp")).toEqual({ name: "time_off", arg: null });
  });

  it("ignore anything that isn't a name", () => {
    expect(parseScreen("")).toBeNull();
    expect(parseScreen("12:payslip")).toBeNull();
    expect(parseScreen("<script>")).toBeNull();
  });

  it("prefer ?screen= over every form of startapp", () => {
    expect(readScreenLink({ search: "?screen=payslip:3&startapp=task-9", hash: "" }, "home")).toEqual({ name: "payslip", arg: "3" });
    expect(readScreenLink({ search: "?startapp=task-9", hash: "" }, "home")).toEqual({ name: "task", arg: "9" });
    expect(readScreenLink({ search: "", hash: "#tgWebAppData=x&tgWebAppStartParam=team" }, null)).toEqual({ name: "team", arg: null });
    expect(readScreenLink({ search: "", hash: "#tgWebAppData=x" }, "activity")).toEqual({ name: "activity", arg: null });
    expect(readScreenLink({ search: "", hash: "#tgWebAppData=x" }, null)).toBeNull();
  });
});

describe("resolving screen links", () => {
  const resolve = (raw: string, features: Feature[] = [wallet]) => resolveScreen(parseScreen(raw), features);

  it("know the app's own screens", () => {
    expect(resolve("home")).toEqual({ tab: "home" });
    expect(resolve("tasks")).toEqual({ tab: "tasks" });
    expect(resolve("tasks:review")).toEqual({ tab: "tasks", tasksTab: "review" });
    expect(resolve("tasks:nonsense")).toEqual({ tab: "tasks" });
    expect(resolve("task:12")).toEqual({ tab: "home", stack: [taskPage(12)] });
    expect(resolve("task:abc")).toBeNull();
    expect(resolve("team")).toEqual({ tab: "profile", stack: [{ feature: CORE, page: "team" }] });
    expect(resolve("add")).toEqual({ tab: "home", sheet: { kind: "add" } });
    expect(resolve("timeOff")).toEqual({ tab: "profile", sheet: { kind: "timeOff" } });
  });

  it("follow feature routes, with numeric ids as numbers", () => {
    expect(resolve("payslip:12")).toEqual({ tab: "profile", stack: [{ feature: "wallet", page: "payslip", params: { id: 12 } }] });
    expect(resolve("wallet")).toEqual({ tab: "home", stack: [{ feature: "wallet", page: "home", params: {} }] });
    expect(resolve("advance:500000")).toEqual({
      tab: "home",
      sheet: { kind: "feature", feature: "wallet", sheet: "advance", params: { amount: 500000 } },
    });
    expect(resolve("custom:yes")).toEqual({ tab: "tasks", tasksTab: "review" });
  });

  it("reach any feature page as <feature>.<page>", () => {
    expect(resolve("wallet.payslip:7")).toEqual({ tab: "home", stack: [{ feature: "wallet", page: "payslip", params: { id: 7 } }] });
    expect(resolve("wallet.nope:7")).toBeNull();
  });

  it("let the next feature answer when a route points at a page its folder lacks", () => {
    const stale: Feature = defineFeature({
      id: "aaa",
      messages: { en: { t: "Old" }, ru: { t: "Старое" }, uz: { t: "Eski" } },
      pages: { home: Page },
      routes: { payslip: "home" },
    });
    const withoutPage: Feature = { ...stale, pages: {} };
    expect(resolve("payslip:12", [withoutPage, wallet])).toEqual({
      tab: "profile",
      stack: [{ feature: "wallet", page: "payslip", params: { id: 12 } }],
    });
  });

  it("let a feature that takes over time off answer the timeOff link", () => {
    const leave: Feature = defineFeature({
      id: "leave",
      messages: { en: { t: "Time off" }, ru: { t: "Отпуск" }, uz: { t: "Ta’til" } },
      replaces: ["timeOff"],
      pages: { home: Page },
      routes: { timeOff: { page: "home", tab: "profile" } },
    });
    expect(resolve("timeOff", [leave])).toEqual({ tab: "profile", stack: [{ feature: "leave", page: "home", params: {} }] });
    // Without a route of that name the built-in sheet still opens.
    expect(resolve("timeOff", [{ ...leave, routes: {} }])).toEqual({ tab: "profile", sheet: { kind: "timeOff" } });
  });

  it("start normally for unknown names and broken routes", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(resolve("c_invite123")).toBeNull();
    expect(resolve("payslip:12", [])).toBeNull();
    expect(resolve("broken")).toBeNull();
    expect(resolveScreen(null, [wallet])).toBeNull();
    expect(errors).toHaveBeenCalledOnce();
    errors.mockRestore();
  });
});
