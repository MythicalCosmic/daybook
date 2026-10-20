/**
 * Tree logic behind TreeList (knowledge base pages, departments, finance categories), free of the
 * DOM: flattening the visible rows, moving a node (reorder or re-parent) without breaking the tree,
 * and the targets of drag and keyboard moves.
 */
import type { Component } from "vue";

export type TreeId = string | number;

export interface TreeNode {
  id: TreeId;
  label: string;
  children?: TreeNode[];
  icon?: Component;
  /** A count or short text on the right ("12", "Draft"). */
  badge?: string | number;
  /** Second line or muted text after the label. */
  meta?: string;
  /** Can't be dragged or receive children. */
  locked?: boolean;
}

export interface FlatNode {
  node: TreeNode;
  depth: number;
  parentId: TreeId | null;
  /** Position among its siblings. */
  index: number;
  siblings: number;
  hasChildren: boolean;
  expanded: boolean;
}

export function flattenTree(nodes: readonly TreeNode[], expanded: ReadonlySet<TreeId>, depth = 0, parentId: TreeId | null = null): FlatNode[] {
  const out: FlatNode[] = [];
  nodes.forEach((node, index) => {
    const hasChildren = !!node.children?.length;
    const open = hasChildren && expanded.has(node.id);
    out.push({ node, depth, parentId, index, siblings: nodes.length, hasChildren, expanded: open });
    if (open) out.push(...flattenTree(node.children!, expanded, depth + 1, node.id));
  });
  return out;
}

export interface Located {
  node: TreeNode;
  parentId: TreeId | null;
  index: number;
  depth: number;
}

export function locate(nodes: readonly TreeNode[], id: TreeId, parentId: TreeId | null = null, depth = 0): Located | null {
  for (let index = 0; index < nodes.length; index++) {
    const node = nodes[index]!;
    if (node.id === id) return { node, parentId, index, depth };
    const inner = node.children ? locate(node.children, id, node.id, depth + 1) : null;
    if (inner) return inner;
  }
  return null;
}

/** True when `id` is `ancestorId` itself or somewhere inside it. */
export function isWithin(nodes: readonly TreeNode[], ancestorId: TreeId, id: TreeId): boolean {
  const ancestor = locate(nodes, ancestorId);
  if (!ancestor) return false;
  if (ancestorId === id) return true;
  return !!ancestor.node.children && !!locate(ancestor.node.children, id);
}

export function depthOfSubtree(node: TreeNode): number {
  if (!node.children?.length) return 0;
  return 1 + Math.max(...node.children.map(depthOfSubtree));
}

export interface TreeMove {
  id: TreeId;
  parentId: TreeId | null;
  /** Position among the new siblings, counted without the moved node. */
  index: number;
}

/** A copy of the tree with the node moved; the same tree when the move is impossible (into itself). */
export function moveNode(nodes: readonly TreeNode[], move: TreeMove): TreeNode[] {
  const found = locate(nodes, move.id);
  if (!found) return [...nodes];
  if (move.parentId !== null && isWithin(nodes, move.id, move.parentId)) return [...nodes];
  const strip = (list: readonly TreeNode[]): TreeNode[] =>
    list.filter((node) => node.id !== move.id).map((node) => (node.children ? { ...node, children: strip(node.children) } : node));
  const without = strip(nodes);
  const insert = (list: TreeNode[], parentId: TreeId | null): TreeNode[] => {
    if (parentId === move.parentId) {
      const next = [...list];
      next.splice(Math.max(0, Math.min(next.length, move.index)), 0, found.node);
      return next;
    }
    return list.map((node) => (node.children || node.id === move.parentId ? { ...node, children: insert(node.children ?? [], node.id) } : node));
  };
  return insert(without, null);
}

export type DropZone = "before" | "after" | "inside";

/** Which part of a row the pointer is over: top quarter before, bottom quarter after, middle inside. */
export function zoneAt(offsetY: number, height: number, canNest: boolean): DropZone {
  const ratio = height > 0 ? offsetY / height : 0.5;
  if (!canNest) return ratio < 0.5 ? "before" : "after";
  if (ratio < 0.28) return "before";
  if (ratio > 0.72) return "after";
  return "inside";
}

/**
 * The move for dropping `dragId` relative to the row `over`; null when not allowed (onto itself,
 * into its own subtree, past `maxDepth`, into a locked node).
 */
export function dropMove(nodes: readonly TreeNode[], dragId: TreeId, over: FlatNode, zone: DropZone, maxDepth = Infinity): TreeMove | null {
  if (over.node.id === dragId || isWithin(nodes, dragId, over.node.id)) return null;
  const dragged = locate(nodes, dragId);
  if (!dragged) return null;
  const subtree = depthOfSubtree(dragged.node);
  if (zone === "inside") {
    if (over.node.locked || over.depth + 1 + subtree > maxDepth) return null;
    return { id: dragId, parentId: over.node.id, index: over.node.children?.length ?? 0 };
  }
  if (over.depth + subtree > maxDepth) return null;
  let index = zone === "before" ? over.index : over.index + 1;
  // Moving down within the same parent: the node's own slot disappears first.
  if (dragged.parentId === over.parentId && dragged.index < index) index -= 1;
  return { id: dragId, parentId: over.parentId, index };
}

/** Alt + arrow moves: up/down among siblings, indent under the previous sibling, outdent after the parent. */
export function keyboardMove(nodes: readonly TreeNode[], id: TreeId, action: "up" | "down" | "indent" | "outdent", maxDepth = Infinity): TreeMove | null {
  const found = locate(nodes, id);
  if (!found) return null;
  const siblings = found.parentId === null ? nodes : (locate(nodes, found.parentId)?.node.children ?? []);
  switch (action) {
    case "up":
      return found.index > 0 ? { id, parentId: found.parentId, index: found.index - 1 } : null;
    case "down":
      return found.index < siblings.length - 1 ? { id, parentId: found.parentId, index: found.index + 1 } : null;
    case "indent": {
      const previous = siblings[found.index - 1];
      if (!previous || previous.locked || found.depth + 1 + depthOfSubtree(found.node) > maxDepth) return null;
      return { id, parentId: previous.id, index: previous.children?.length ?? 0 };
    }
    case "outdent": {
      if (found.parentId === null) return null;
      const parent = locate(nodes, found.parentId)!;
      return { id, parentId: parent.parentId, index: parent.index + 1 };
    }
  }
}
