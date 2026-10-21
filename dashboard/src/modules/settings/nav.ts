/**
 * How the Settings list is grouped: like the sidebar. This module's own panels sit where an owner
 * looks for them (Company, Modules and Branches under Company; Invite under People; Notifications
 * and Sessions, which are about the person signed in, under "Your account", last). Every other
 * module's panels go under that module's sidebar group, in sidebar order, then by the panel's own
 * order. Links to pages that live elsewhere (Roles, Positions) follow the People panels.
 */
import type { ModuleGroup, SettingsPanel } from "@/core/modules";

export type SectionId = Exclude<ModuleGroup, "overview"> | "account";

/** Sections top to bottom; empty ones are left out. */
export const SECTION_ORDER: readonly SectionId[] = ["company", "people", "work", "money", "comms", "insights", "account"];

/** Where this module's own panels go. */
const OWN_SECTION: Record<string, SectionId> = {
  company: "company",
  features: "company",
  branches: "company",
  invite: "people",
  notifications: "account",
  sessions: "account",
};

export interface PanelEntry extends SettingsPanel {
  moduleId: string;
  moduleGroup: ModuleGroup;
  moduleOrder: number;
  /** One of the settings module's own panels (they bring their own header). */
  own: boolean;
}

export interface NavLink {
  id: string;
  to: string;
}

export type NavItem = { kind: "panel"; key: string; id: string; panel: PanelEntry; to?: undefined } | { kind: "link"; key: string; id: string; to: string; panel?: undefined };

export interface NavSection {
  id: SectionId;
  items: NavItem[];
}

function sectionOf(panel: PanelEntry): SectionId {
  if (panel.own) return OWN_SECTION[panel.id] ?? "company";
  return panel.moduleGroup === "overview" ? "company" : panel.moduleGroup;
}

export function groupPanels(panels: readonly PanelEntry[], links: readonly NavLink[] = []): NavSection[] {
  const sorted = [...panels].sort(
    (a, b) => Number(b.own) - Number(a.own) || a.moduleOrder - b.moduleOrder || a.moduleId.localeCompare(b.moduleId) || (a.order ?? 0) - (b.order ?? 0),
  );
  const sections = new Map<SectionId, NavItem[]>();
  for (const panel of sorted) {
    const id = sectionOf(panel);
    const items = sections.get(id) ?? [];
    items.push({ kind: "panel", key: `${panel.moduleId}:${panel.id}`, id: panel.id, panel });
    sections.set(id, items);
  }
  if (links.length) {
    const items = sections.get("people") ?? [];
    for (const link of links) items.push({ kind: "link", key: `link:${link.id}`, id: link.id, to: link.to });
    sections.set("people", items);
  }
  return SECTION_ORDER.filter((id) => sections.get(id)?.length).map((id) => ({ id, items: sections.get(id)! }));
}
