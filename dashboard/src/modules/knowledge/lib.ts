/** Small helpers shared by the knowledge base's pages and components (no Vue, easy to test). */
import type { TreeNode } from "@/components/tree";

import type { PageRow, ReadCount, Space, TreeNodeData } from "./types";

/** The tree as TreeList draws it: "🔓 Kassani ochish" with a "Draft" badge on unpublished pages. */
export function toTreeNodes(data: readonly TreeNodeData[], draftLabel: string, ackLabel?: string): TreeNode[] {
  return data.map((node) => ({
    id: node.id,
    label: `${node.emoji ? `${node.emoji} ` : ""}${node.title}`,
    badge: node.published ? (ackLabel && node.require_ack ? ackLabel : undefined) : draftLabel,
    children: node.children.length ? toTreeNodes(node.children, draftLabel, ackLabel) : undefined,
  }));
}

/** Ids of the pages above `id` (top first), to open the tree down to it. */
export function pathTo(data: readonly TreeNodeData[], id: number, trail: number[] = []): number[] | null {
  for (const node of data) {
    if (node.id === id) return trail;
    const found = pathTo(node.children, id, [...trail, node.id]);
    if (found) return found;
  }
  return null;
}

/** A copy of the tree with page `id` moved to `index` under `parentId` (null: the top level). */
export function moveData(data: readonly TreeNodeData[], move: { id: number; parentId: number | null; index: number }): TreeNodeData[] {
  let moved: TreeNodeData | null = null;
  const strip = (list: readonly TreeNodeData[]): TreeNodeData[] =>
    list
      .filter((node) => {
        if (node.id === move.id) moved = node;
        return node.id !== move.id;
      })
      .map((node) => ({ ...node, children: strip(node.children) }));
  const without = strip(data);
  if (!moved) return [...data];
  const insert = (list: TreeNodeData[], parentId: number | null): TreeNodeData[] => {
    if (parentId === move.parentId) {
      const next = [...list];
      next.splice(Math.max(0, Math.min(next.length, move.index)), 0, moved!);
      return next;
    }
    return list.map((node) => ({ ...node, children: insert(node.children, node.id) }));
  };
  return insert(without, null);
}

/** How many pages a tree holds. */
export function countNodes(data: readonly TreeNodeData[]): number {
  return data.reduce((sum, node) => sum + 1 + countNodes(node.children), 0);
}

/** Every page of a tree with its depth, top to bottom (for "put it under…" pickers). */
export function flatten(data: readonly TreeNodeData[], depth = 0): Array<{ node: TreeNodeData; depth: number }> {
  return data.flatMap((node) => [{ node, depth }, ...flatten(node.children, depth + 1)]);
}

/**
 * A body as the editor and the server agree on it: the editor adds an empty paragraph after a
 * last callout, table or picture (so there is somewhere to type), which is not a change.
 */
export function normalizeBody(html: string): string {
  return html.replace(/(?:\s*<p>(?:<br\s*\/?>)?<\/p>)+\s*$/i, "").trim();
}

export function displayTitle(page: Pick<PageRow, "emoji" | "title">): string {
  return `${page.emoji ? `${page.emoji} ` : ""}${page.title}`;
}

export function readRatio(read: ReadCount | null | undefined): number {
  if (!read || !read.total) return 0;
  return read.read / read.total;
}

/** The tone of a read progress: green when everyone read it, ochre past half, red below. */
export function readTone(read: ReadCount | null | undefined): "success" | "warning" | "danger" | "neutral" {
  if (!read || !read.total) return "neutral";
  const ratio = read.read / read.total;
  if (ratio >= 1) return "success";
  return ratio >= 0.5 ? "warning" : "danger";
}

/** "Everyone" or the positions a space is read by. */
export function audienceText(space: Pick<Space, "audience_all" | "positions">, everyone: string): string {
  return space.audience_all ? everyone : space.positions.map((position) => position.name).join(", ");
}

/**
 * The server cleaned the body against its allow-list; the browser cleans it again before showing it
 * (defence in depth), makes checklists read-only in the reading view and puts each table in the
 * editor's scrolling wrapper, so a wide table scrolls on a phone instead of widening the page.
 */
export async function safeBody(html: string): Promise<string> {
  const { default: DOMPurify } = await import("dompurify");
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      "p", "h1", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "strike", "code", "pre", "blockquote", "br", "hr",
      "ul", "ol", "li", "label", "input", "span", "div", "a", "img", "table", "thead", "tbody", "tr", "th", "td", "colgroup", "col",
    ],
    ALLOWED_ATTR: ["href", "target", "rel", "src", "alt", "data-image-id", "data-type", "data-checked", "data-callout", "type", "checked", "disabled", "colspan", "rowspan", "start"],
    ALLOW_DATA_ATTR: false,
  });
  return clean
    .replace(/<input type="checkbox"/g, '<input type="checkbox" disabled')
    .replace(/<table\b/g, '<div class="tableWrapper"><table')
    .replace(/<\/table>/g, "</table></div>");
}

/** A short emoji set for pages and spaces: rules, money, goods, medicines, people, time, safety. */
export const EMOJIS = [
  "📘", "📗", "📕", "📙", "📒", "📚", "📖", "📝", "✅", "☑️", "⚠️", "❗",
  "💡", "📌", "🔒", "🔓", "💰", "💳", "🧾", "🏦", "📦", "🚚", "🛒", "🛍",
  "🏪", "🏬", "🧹", "🧼", "👕", "👔", "👋", "🙋", "🤝", "📞", "📱", "💬",
  "📣", "📅", "🕘", "⏰", "🏖", "🎉", "🎂", "💊", "🩺", "🌡️", "🧴", "🧊",
  "🔥", "🧯", "🚨", "🔧", "🛠", "⚙️", "📈", "📊", "🗂", "🏷", "🎯", "⭐",
  "🌿", "🧑‍⚕️", "👩‍💼", "🧑‍🔧",
];
