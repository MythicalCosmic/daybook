/**
 * Departments as a tree, free of the DOM: the org chart, the parent picker (never a department
 * itself or one below it), the department pickers and the Team filter all read the flat list of
 * `GET departments/` through these.
 */
import type { SelectOption } from "@/components/options";

import type { Department, PersonRef } from "./types";

export interface DepartmentNode {
  department: Department;
  children: DepartmentNode[];
  /** 0 for a top-level department. */
  depth: number;
}

/** Each department's parent, with dangling parents (not in the list) and any cycle cut to the top. */
function parentMap(list: readonly Department[]): Map<number, number | null> {
  const ids = new Set(list.map((d) => d.id));
  const parents = new Map<number, number | null>();
  for (const d of list) parents.set(d.id, d.parent_id !== null && d.parent_id !== d.id && ids.has(d.parent_id) ? d.parent_id : null);
  // The server never sends a cycle; if it ever did, its departments would vanish from a tree drawn
  // from the top, so the first one met on the loop is shown at the top instead.
  for (const d of list) {
    const seen = new Set<number>([d.id]);
    let up = parents.get(d.id) ?? null;
    while (up !== null) {
      if (seen.has(up)) {
        parents.set(d.id, null);
        break;
      }
      seen.add(up);
      up = parents.get(up) ?? null;
    }
  }
  return parents;
}

/**
 * The flat list as a tree. Siblings keep the server's order (by name); a department whose parent
 * isn't in the list shows at the top rather than disappearing.
 */
export function buildDepartmentTree(list: readonly Department[]): DepartmentNode[] {
  const parents = parentMap(list);
  const nodes = new Map<number, DepartmentNode>(list.map((d) => [d.id, { department: d, children: [], depth: 0 }]));
  const roots: DepartmentNode[] = [];
  for (const d of list) {
    const node = nodes.get(d.id)!;
    const parentId = parents.get(d.id) ?? null;
    if (parentId === null) roots.push(node);
    else nodes.get(parentId)!.children.push(node);
  }
  const setDepth = (node: DepartmentNode, depth: number): void => {
    node.depth = depth;
    for (const child of node.children) setDepth(child, depth + 1);
  };
  for (const root of roots) setDepth(root, 0);
  return roots;
}

/** Every department in tree order (parents first), with its depth. */
export function flattenDepartments(list: readonly Department[]): DepartmentNode[] {
  const out: DepartmentNode[] = [];
  const walk = (nodes: DepartmentNode[]): void => {
    for (const node of nodes) {
      out.push(node);
      walk(node.children);
    }
  };
  walk(buildDepartmentTree(list));
  return out;
}

/** Ids of every department below `id` (not `id` itself). */
export function descendantIds(list: readonly Department[], id: number): Set<number> {
  const parents = parentMap(list);
  const below = new Set<number>();
  for (const d of list) {
    let up = parents.get(d.id) ?? null;
    while (up !== null) {
      if (up === id) {
        below.add(d.id);
        break;
      }
      up = parents.get(up) ?? null;
    }
  }
  return below;
}

/**
 * Where a department may go: every department except itself and the ones below it (a department
 * can't sit under its own sub-department). `movingId` null (a new department) allows them all.
 */
export function allowedParents(list: readonly Department[], movingId: number | null): DepartmentNode[] {
  const all = flattenDepartments(list);
  if (movingId === null) return all;
  const below = descendantIds(list, movingId);
  return all.filter((node) => node.department.id !== movingId && !below.has(node.department.id));
}

/** "Rahbariyat › Savdo": the departments above this one, top first (empty for a top-level one). */
export function parentPath(department: Department): string {
  return department.path.slice(0, -1).join(" › ");
}

/** Department choices for pickers and filters: the name, and the departments above it on the second line. */
export function departmentOptions<V extends string | number>(nodes: readonly DepartmentNode[], value: (d: Department) => V): SelectOption<V>[] {
  return nodes.map(({ department }) => ({
    value: value(department),
    label: department.name,
    description: parentPath(department) || undefined,
    keywords: department.path,
  }));
}

/** The value the parent picker uses for "the top level" (the API's `parent_id: null`). */
export const TOP_LEVEL = 0;

/**
 * What a department's card counts: the people directly in it and, when sub-departments add people,
 * everyone with them.
 */
export function departmentCounts(department: Department, hasChildren: boolean): { direct: number; total: number | null } {
  const showTotal = hasChildren && department.total_count !== department.member_count;
  return { direct: department.member_count, total: showTotal ? department.total_count : null };
}

/** People placed in some department (each person is in at most one). */
export function placedCount(list: readonly Department[]): number {
  return list.reduce((sum, d) => sum + d.member_count, 0);
}

/**
 * The head a department's head reports to: the nearest head above who isn't the same person (a
 * head of two levels reports further up). null at the top.
 */
export function headAbove(list: readonly Department[], id: number): { head: PersonRef; department: Department } | null {
  const byId = new Map(list.map((d) => [d.id, d]));
  const parents = parentMap(list);
  const own = byId.get(id)?.head?.id ?? null;
  let up = parents.get(id) ?? null;
  while (up !== null) {
    const department = byId.get(up)!;
    if (department.head && department.head.id !== own) return { head: department.head, department };
    up = parents.get(up) ?? null;
  }
  return null;
}

/** The departments someone heads, in tree order. */
export function headedBy(list: readonly Department[], memberId: number): Department[] {
  return flattenDepartments(list)
    .map((node) => node.department)
    .filter((d) => d.head?.id === memberId);
}

/**
 * How many columns the sub-departments of one card take in the org chart: as many as fit at
 * `minWidth` each, never more than there are, at least one (an indented list on a phone).
 */
export function columnsFor(width: number, count: number, minWidth: number, gap: number): number {
  if (count <= 1 || width <= 0) return 1;
  return Math.max(1, Math.min(count, Math.floor((width + gap) / (minWidth + gap))));
}

/** Items in rows of `size`. */
export function rowsOf<T>(items: readonly T[], size: number): T[][] {
  const rows: T[][] = [];
  const step = Math.max(1, size);
  for (let i = 0; i < items.length; i += step) rows.push(items.slice(i, i + step));
  return rows;
}
