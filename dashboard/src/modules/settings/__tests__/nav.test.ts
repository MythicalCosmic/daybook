// How the Settings list groups every module's panels (nav.ts).
import { describe, expect, it } from "vitest";
import { defineComponent } from "vue";

import type { ModuleGroup } from "@/core/modules";

import { groupPanels, type PanelEntry } from "../nav";

const Panel = defineComponent({ render: () => null });

function entry(moduleId: string, id: string, moduleGroup: ModuleGroup, moduleOrder: number, order?: number): PanelEntry {
  return { id, title: `${moduleId}.${id}`, component: Panel, moduleId, moduleGroup, moduleOrder, order, own: moduleId === "settings" };
}

describe("groupPanels", () => {
  it("groups like the sidebar, the person's own panels last, links after the People panels", () => {
    const sections = groupPanels(
      [
        entry("finance", "finance", "money", 20, 40),
        entry("settings", "sessions", "company", 90, 60),
        entry("attendance", "attendance", "people", 20, 40),
        entry("settings", "company", "company", 90, 10),
        entry("sales", "registers", "money", 10, 41),
        entry("sales", "sales", "money", 10, 40),
        entry("settings", "invite", "company", 90, 40),
        entry("settings", "notifications", "company", 90, 50),
        entry("projects", "projects", "work", 15),
        entry("reminders", "reminders.defaults", "work", 40, 60),
        entry("settings", "branches", "company", 90, 30),
      ],
      [
        { id: "roles", to: "/c/1/people/roles" },
        { id: "positions", to: "/c/1/people/positions" },
      ],
    );
    expect(sections.map((section) => [section.id, section.items.map((item) => item.id)])).toEqual([
      ["company", ["company", "branches"]],
      ["people", ["invite", "attendance", "roles", "positions"]],
      ["work", ["projects", "reminders.defaults"]],
      ["money", ["sales", "registers", "finance"]],
      ["account", ["notifications", "sessions"]],
    ]);
    const links = sections.flatMap((section) => section.items).filter((item) => item.kind === "link");
    expect(links.map((item) => item.to)).toEqual(["/c/1/people/roles", "/c/1/people/positions"]);
  });

  it("leaves out empty sections and keys every row by module", () => {
    const sections = groupPanels([entry("settings", "company", "company", 90, 10), entry("agenda", "agenda", "comms", 30)]);
    expect(sections.map((section) => section.id)).toEqual(["company", "comms"]);
    expect(sections[1]!.items[0]!.key).toBe("agenda:agenda");
  });
});
