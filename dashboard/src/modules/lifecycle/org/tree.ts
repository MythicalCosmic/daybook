/**
 * The org chart's plain logic, tested on its own: the tree for each view (departments with their
 * heads, or branches with their managers; people grouped by position under them; open vacancies as
 * places), the order things appear in (search and keyboard moves walk it), finding a person, what a
 * drop proposes, and the small statuses a person shows.
 */
import type { StatusTone } from "@/components/StatusPill.vue";
import { diffDays } from "@/lib/dates";

import type { OrgChart, OrgPerson, OrgPosition, OrgRef, OrgVacancy, OrgView } from "./types";

/** What dropping someone on a node proposes: a department (null: none) or a home branch. */
export type MoveTarget = { part: "department"; id: number | null; name: string } | { part: "branch"; id: number; name: string };

export interface OrgGroup {
  key: string;
  position: OrgPosition | null;
  people: OrgPerson[];
}

export type NodeKind = "root" | "department" | "branch" | "unplaced";

export interface OrgNode {
  /** "root", "d12", "b3", "none". */
  key: string;
  kind: NodeKind;
  id: number | null;
  name: string;
  /** The department's head, the branch's manager. */
  head: OrgRef | null;
  /** The head as one of the people the viewer sees (statuses, may they be moved). */
  headPerson: OrgPerson | null;
  groups: OrgGroup[];
  vacancies: OrgVacancy[];
  children: OrgNode[];
  /** People directly here, and with everything below. */
  count: number;
  total: number;
  target: MoveTarget | null;
}

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);

function groupByPosition(people: OrgPerson[], positions: OrgPosition[]): OrgGroup[] {
  const order = new Map(positions.map((position, index) => [position.id, index]));
  const found = new Map<number | null, OrgPerson[]>();
  for (const person of people) {
    const key = person.position_id !== null && order.has(person.position_id) ? person.position_id : null;
    const list = found.get(key) ?? [];
    list.push(person);
    found.set(key, list);
  }
  const keys = [...found.keys()].sort((a, b) => (a === null ? 1 : b === null ? -1 : order.get(a)! - order.get(b)!));
  return keys.map((key) => ({
    key: key === null ? "p-none" : `p${key}`,
    position: key === null ? null : positions[order.get(key)!]!,
    people: [...found.get(key)!].sort(byName),
  }));
}

/**
 * The tree of one view. The owners sit on the root card (and nowhere else, so nobody shows
 * twice); the department view hangs the top departments from it, the branch view the branches;
 * people with no department (or no branch the viewer sees) and places with none hang from an
 * "unplaced" node at the end.
 */
export function buildTree(chart: OrgChart, view: OrgView): OrgNode {
  const owners = new Set(chart.owners.map((owner) => owner.id));
  const people = new Map(chart.people.map((person) => [person.id, person]));
  const visible = chart.people.filter((person) => !owners.has(person.id));
  const root: OrgNode = {
    key: "root",
    kind: "root",
    id: null,
    name: chart.company.name,
    head: null,
    headPerson: null,
    groups: [],
    vacancies: [],
    children: [],
    count: chart.owners.length,
    total: chart.people.length,
    target: null,
  };

  if (view === "department") {
    const nodes = new Map<number, OrgNode>();
    for (const department of chart.departments) {
      const head = department.head;
      const here = visible.filter((person) => person.department_id === department.id && person.id !== head?.id);
      nodes.set(department.id, {
        key: `d${department.id}`,
        kind: "department",
        id: department.id,
        name: department.name,
        head,
        headPerson: head ? (people.get(head.id) ?? null) : null,
        groups: groupByPosition(here, chart.positions),
        vacancies: chart.vacancies.filter((vacancy) => vacancy.department_id === department.id),
        children: [],
        count: department.headcount,
        total: department.total,
        target: { part: "department", id: department.id, name: department.name },
      });
    }
    for (const department of chart.departments) {
      const node = nodes.get(department.id)!;
      const parent = department.parent_id !== null ? nodes.get(department.parent_id) : undefined;
      (parent ? parent.children : root.children).push(node);
    }
    const known = new Set(chart.departments.map((department) => department.id));
    const loose = visible.filter((person) => person.department_id === null || !known.has(person.department_id));
    const places = chart.vacancies.filter((vacancy) => vacancy.department_id === null || !known.has(vacancy.department_id));
    if (loose.length || places.length) {
      root.children.push({
        key: "none",
        kind: "unplaced",
        id: null,
        name: "",
        head: null,
        headPerson: null,
        groups: groupByPosition(loose, chart.positions),
        vacancies: places,
        children: [],
        count: loose.length,
        total: loose.length,
        target: chart.departments.length ? { part: "department", id: null, name: "" } : null,
      });
    }
    return root;
  }

  for (const branch of chart.branches) {
    const manager = branch.manager;
    const here = visible.filter((person) => person.branch_id === branch.id && person.id !== manager?.id);
    root.children.push({
      key: `b${branch.id}`,
      kind: "branch",
      id: branch.id,
      name: branch.name,
      head: manager,
      headPerson: manager ? (people.get(manager.id) ?? null) : null,
      groups: groupByPosition(here, chart.positions),
      vacancies: chart.vacancies.filter((vacancy) => vacancy.branch_id === branch.id),
      children: [],
      count: branch.headcount,
      total: branch.headcount,
      target: { part: "branch", id: branch.id, name: branch.name },
    });
  }
  const shown = new Set(chart.branches.map((branch) => branch.id));
  const loose = visible.filter((person) => person.branch_id === null || !shown.has(person.branch_id));
  const places = chart.vacancies.filter((vacancy) => vacancy.branch_id === null || !shown.has(vacancy.branch_id));
  if (loose.length || places.length) {
    root.children.push({
      key: "none",
      kind: "unplaced",
      id: null,
      name: "",
      head: null,
      headPerson: null,
      groups: groupByPosition(loose, chart.positions),
      vacancies: places,
      children: [],
      count: loose.length,
      total: loose.length,
      target: null,
    });
  }
  return root;
}

/** Which views the company has: by department when it has departments, by branch always. */
export function availableViews(chart: Pick<OrgChart, "departments" | "branches">): OrgView[] {
  const views: OrgView[] = [];
  if (chart.departments.length) views.push("department");
  if (chart.branches.length || !chart.departments.length) views.push("branch");
  return views;
}

/** Every node, parents before children, in the order they are drawn. */
export function walk(root: OrgNode): OrgNode[] {
  const out: OrgNode[] = [];
  const stack = [root];
  while (stack.length) {
    const node = stack.pop()!;
    out.push(node);
    for (let index = node.children.length - 1; index >= 0; index -= 1) stack.push(node.children[index]!);
  }
  return out;
}

/** Each person once, in the order the chart shows them (a head on their node's card first). */
export function peopleInOrder(root: OrgNode): OrgPerson[] {
  const seen = new Set<number>();
  const out: OrgPerson[] = [];
  const add = (person: OrgPerson | null) => {
    if (person && !seen.has(person.id)) {
      seen.add(person.id);
      out.push(person);
    }
  };
  for (const node of walk(root)) {
    add(node.headPerson);
    for (const group of node.groups) for (const person of group.people) add(person);
  }
  return out;
}

/** Lower case without the Uzbek o‘/g‘ marks and apostrophes, so "Ga'fur" finds "G‘afur". */
export function fold(text: string): string {
  return text
    .toLocaleLowerCase()
    .replace(/[‘’'`ʻʼ]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** People whose name or job title holds `query`, in chart order. */
export function searchPeople(root: OrgNode, positions: OrgPosition[], query: string): OrgPerson[] {
  const needle = fold(query);
  if (!needle) return [];
  const titles = new Map(positions.map((position) => [position.id, fold(position.name)]));
  return peopleInOrder(root).filter((person) => fold(person.name).includes(needle) || (person.position_id !== null && (titles.get(person.position_id) ?? "").includes(needle)));
}

/** The keys of the nodes from the root down to where `personId` is (to open them), and their group. */
export function pathTo(root: OrgNode, personId: number): { nodes: string[]; group: string | null } | null {
  const visit = (node: OrgNode, trail: string[]): { nodes: string[]; group: string | null } | null => {
    const here = [...trail, node.key];
    if (node.headPerson?.id === personId) return { nodes: here, group: null };
    for (const group of node.groups) if (group.people.some((person) => person.id === personId)) return { nodes: here, group: group.key };
    for (const child of node.children) {
      const found = visit(child, here);
      if (found) return found;
    }
    return null;
  };
  return visit(root, []);
}

/** The node someone sits in (or heads) in this tree. */
export function nodeOf(root: OrgNode, personId: number): OrgNode | null {
  const path = pathTo(root, personId);
  if (!path) return null;
  const key = path.nodes[path.nodes.length - 1];
  return walk(root).find((node) => node.key === key) ?? null;
}

/** Where someone may be dropped, in chart order. */
export function moveTargets(root: OrgNode): OrgNode[] {
  return walk(root).filter((node) => node.target !== null);
}

/** Whether dropping `person` on `target` changes nothing (they are there already). */
export function sameTarget(person: OrgPerson, target: MoveTarget): boolean {
  return target.part === "department" ? person.department_id === target.id : person.home_branch_id === target.id;
}

/** The next target from `current` in `direction` (wrapping), skipping where they are already. */
export function nextTarget(targets: OrgNode[], person: OrgPerson, current: string | null, direction: 1 | -1): OrgNode | null {
  const usable = targets.filter((node) => node.target && !sameTarget(person, node.target));
  if (!usable.length) return null;
  const index = usable.findIndex((node) => node.key === current);
  if (index < 0) return direction === 1 ? usable[0]! : usable[usable.length - 1]!;
  return usable[(index + direction + usable.length) % usable.length]!;
}

/** What the job change dialog starts with for a drop. */
export interface MovePreset {
  parts: ("department" | "branch")[];
  department?: number | null;
  branch?: number | null;
  reason: string;
}

export function movePreset(target: MoveTarget, reason: string): MovePreset {
  return target.part === "department"
    ? { parts: ["department"], department: target.id, reason }
    : { parts: ["branch"], branch: target.id, reason };
}

/** A person's small statuses, the most telling first: suspended, leaving, on leave, a change waiting. */
export interface PersonBadge {
  key: "suspended" | "leaving" | "asked" | "away" | "change";
  tone: StatusTone;
  /** The day it is about (until, the last day, from). */
  day: string | null;
}

export function badges(person: OrgPerson): PersonBadge[] {
  const out: PersonBadge[] = [];
  if (person.status === "suspended") out.push({ key: "suspended", tone: "danger", day: person.suspended_until });
  if (person.leaving?.status === "agreed") out.push({ key: "leaving", tone: "warning", day: person.leaving.day });
  else if (person.leaving) out.push({ key: "asked", tone: "warning", day: person.leaving.day });
  if (person.on_leave_until) out.push({ key: "away", tone: "info", day: person.on_leave_until });
  if (person.change) out.push({ key: "change", tone: "primary", day: person.change.effective_on });
  return out;
}

/** Days until a status's day (0 on it); null without one. */
export const daysTo = (day: string | null, today: string): number | null => (day ? diffDays(today, day) : null);

/** How many people of a group show before "Show N more" (the rest fold away to keep it calm). */
export const GROUP_PREVIEW = 6;

export function visiblePeople(group: OrgGroup, open: boolean, highlight: number | null = null): { shown: OrgPerson[]; hidden: number } {
  if (open || group.people.length <= GROUP_PREVIEW + 1) return { shown: group.people, hidden: 0 };
  const shown = group.people.slice(0, GROUP_PREVIEW);
  // Someone found by search is always shown.
  const found = highlight !== null ? group.people.find((person) => person.id === highlight) : undefined;
  if (found && !shown.includes(found)) shown.push(found);
  return { shown, hidden: group.people.length - shown.length };
}

/** The zoom that fits `content` into `box` (never above 1, never below `min`). */
export function fitZoom(box: { width: number; height: number }, content: { width: number; height: number }, min = 0.3): number {
  if (content.width <= 0 || content.height <= 0) return 1;
  const scale = Math.min(box.width / content.width, box.height / content.height, 1);
  return Math.max(min, Math.floor(scale * 100) / 100);
}
