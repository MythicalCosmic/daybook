/**
 * What the org chart page shares with every node and person inside it (provide/inject): what is
 * folded, who is found or picked up, the drag in progress, and the actions (open a person, move
 * them, drop on a node). The page owns the state; the parts only read it and call back.
 */
import { inject, type InjectionKey, type Ref } from "vue";

import type { OrgNode } from "./tree";
import type { OrgCan, OrgPerson, OrgPosition, OrgView } from "./types";

export interface OrgContext {
  today: Ref<string>;
  can: Ref<OrgCan>;
  view: Ref<OrgView>;
  positions: Ref<Map<number, OrgPosition>>;
  /** Department or branch names by id, for the hover card. */
  departmentName: (id: number | null) => string | null;
  branchName: (id: number | null) => string | null;
  personName: (id: number | null) => string | null;
  /** Node keys folded away, group keys opened past their first few. */
  isCollapsed: (key: string) => boolean;
  toggle: (key: string) => void;
  isGroupOpen: (key: string) => boolean;
  openGroup: (key: string) => void;
  /** A colour per top part of the tree (a CSS variable), so a department's family reads as one. */
  accent: (key: string) => string;
  /** The person search found (scrolled to and ringed). */
  highlight: Ref<number | null>;
  /** Someone picked up with the keyboard, and the node they are over. */
  picked: Ref<{ person: OrgPerson; over: string | null } | null>;
  dragging: Ref<OrgPerson | null>;
  over: Ref<string | null>;
  profileUrl: (id: number) => string;
  vacancyUrl: (id: number) => string;
  openPerson: (person: OrgPerson) => void;
  /** "Move…": choose where (the menu and the hover card). */
  startMove: (person: OrgPerson) => void;
  dragStart: (person: OrgPerson, event: DragEvent) => void;
  dragEnd: () => void;
  canDrop: (node: OrgNode) => boolean;
  drop: (node: OrgNode) => void;
  /** Space, arrows, Escape on a person (the keyboard move). */
  personKey: (person: OrgPerson, event: KeyboardEvent) => void;
}

export const ORG_CONTEXT: InjectionKey<OrgContext> = Symbol("org-chart");

export function useOrgContext(): OrgContext {
  const context = inject(ORG_CONTEXT);
  if (!context) throw new Error("The org chart's parts live inside OrgChartPage.");
  return context;
}

/** The accent colours of the top parts, in turn. */
export const ACCENTS = ["var(--c-chart-1)", "var(--c-chart-2)", "var(--c-chart-3)", "var(--c-chart-4)", "var(--c-chart-5)", "var(--c-chart-6)", "var(--c-chart-7)", "var(--c-chart-8)"];
