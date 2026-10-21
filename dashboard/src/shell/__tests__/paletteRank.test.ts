import { describe, expect, it } from "vitest";

import { byMatch, bySectionMatch, groupWeight, keepLocal, matchOf, plain } from "../paletteRank";

const item = (title: string, keywords: string[] = []) => ({ title, keywords });

describe("palette ranking", () => {
  it("compares text without Uzbek apostrophes, case or the emoji a title opens with", () => {
    expect(plain("Ta’til")).toBe("tatil");
    expect(plain("Ko‘kterak Farm")).toBe("kokterak farm");
    expect(plain("🧾 Dorilar qaytarilmaydi")).toBe("dorilar qaytarilmaydi");
    expect(plain("O'zbekcha")).toBe("ozbekcha");
  });

  it("tells a title that starts with the query from a word that does, a match inside a word and a typo", () => {
    expect(matchOf(["Ta’til"], "tatil")).toBe(0);
    expect(matchOf(["🧾 Dorilar qaytarilmaydi"], "dori")).toBe(0);
    expect(matchOf(["Sergeli dorixonasini ochish"], "dori")).toBe(1);
    expect(matchOf(["⏰ Eslatma: ertaga Chilonzor dorixonasida"], "chilonzor")).toBe(1);
    expect(matchOf(["Kiruvchilar"], "chil")).toBe(2);
    expect(matchOf(["Finance"], "finanse")).toBe(3);
  });

  it("keeps pages a word starts with and close typos, never a query found inside a word", () => {
    // Inbox's Uzbek title is "Kiruvchilar": "Chil" is meant for Chilonzor.
    expect(keepLocal(item("Inbox", ["Kiruvchilar", "Входящие"]), "Chil", 0.05, 0.2)).toBe(false);
    expect(keepLocal(item("Inbox", ["Kiruvchilar", "Входящие"]), "kiruv", 0.05, 0.2)).toBe(true);
    expect(keepLocal(item("Time off", ["Ta’til", "Отпуска"]), "tatil", 0.1, 0.2)).toBe(true);
    expect(keepLocal(item("Finance", ["Moliya", "Финансы"]), "finanse", 0.15, 0.2)).toBe(true);
    // Two letters off the Uzbek "xarajat": too loose.
    expect(keepLocal(item("Record an expense", ["Xarajat yozish"]), "Barakat", 0.28, 0.2)).toBe(false);
  });

  it("lists the best match first and keeps the server's order among equals", () => {
    const tasks = [item("Yangi xodimlar uchun GPP yo‘riqnomasi"), item("Xodimlar uchun GPP treningi"), item("GPP talablari bo‘yicha o‘z-o‘zini tekshirish")];
    expect(byMatch(tasks, "GPP").map((task) => task.title)).toEqual([
      "GPP talablari bo‘yicha o‘z-o‘zini tekshirish",
      "Yangi xodimlar uchun GPP yo‘riqnomasi",
      "Xodimlar uchun GPP treningi",
    ]);
  });

  it("orders pages and record groups together: the best answer, then records before what mentions them", () => {
    const sections = [
      { id: "jump", items: [item("Tills & methods", ["Kassalar va to‘lov usullari"])], weight: -1 },
      { id: "transactions", items: [item("CHL-178 · Uzum")], weight: groupWeight("shell.searchType.transactions") },
      { id: "shifts", items: [item("CHL-178 · Gulnora Ismoilova")], weight: groupWeight("shell.searchType.shifts") },
      { id: "branches", items: [item("Chilonzor")], weight: groupWeight("shell.searchType.branches") },
    ];
    // "CHL-17": the shifts it names before the payments that mention them; no page starts with it.
    expect(bySectionMatch(sections, "CHL-17").map((section) => section.id)).toEqual(["shifts", "transactions", "jump", "branches"]);
    // "Chil": the branch before anything else.
    expect(bySectionMatch(sections, "Chil")[0]!.id).toBe("branches");
    // "kassa": a page wins a tie with records.
    const kassa = [{ id: "tasks", items: [item("Kassa lentasidan buyurtma berish")], weight: groupWeight("shell.searchType.tasks") }, sections[0]!];
    expect(bySectionMatch(kassa, "kassa").map((section) => section.id)).toEqual(["jump", "tasks"]);
  });

  it("puts groups it doesn't know between records and the rows that mention them", () => {
    expect(groupWeight("shell.searchType.people")).toBeLessThan(groupWeight("shell.searchType.invoices"));
    expect(groupWeight("shell.searchType.invoices")).toBeLessThan(groupWeight("shell.searchType.announcements"));
    expect(groupWeight(null)).toBeLessThan(groupWeight("shell.searchType.transactions"));
  });
});
