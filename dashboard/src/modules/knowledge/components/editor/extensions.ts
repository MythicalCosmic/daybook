/**
 * The editor's document model (Tiptap 3): StarterKit (headings, lists, quote, code, links,
 * underline, undo), checklists, callouts, tables and pictures. What it writes is exactly what the
 * server's allow-list keeps (apps/knowledge/sanitize.py):
 *   - checklists: `<ul data-type="taskList"><li data-type="taskItem" data-checked>…`
 *   - callouts:   `<div data-callout="info|success|warning|danger|note">…</div>`
 *   - pictures:   `<img data-image-id="12" alt="…">` (the `src` is a signed link the server drops)
 *   - tables:     `<table><tbody><tr><th|td>…`
 * Tables use prosemirror-tables (shipped inside @tiptap/pm) for cell selection and Tab navigation.
 */
import { Extension, mergeAttributes, Node, type CommandProps, type Editor } from "@tiptap/core";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { Placeholder } from "@tiptap/extensions";
import type { Node as PMNode, Schema } from "@tiptap/pm/model";
import type { EditorState, Transaction } from "@tiptap/pm/state";
import {
  addColumnAfter,
  addRowAfter,
  deleteColumn,
  deleteRow,
  deleteTable,
  goToNextCell,
  isInTable,
  tableEditing,
  toggleHeaderRow,
} from "@tiptap/pm/tables";
import StarterKit from "@tiptap/starter-kit";

export type CalloutTone = "info" | "success" | "warning" | "danger" | "note";
export const CALLOUT_TONES: readonly CalloutTone[] = ["info", "success", "warning", "danger", "note"];

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    callout: {
      setCallout: (tone?: CalloutTone) => ReturnType;
      unsetCallout: () => ReturnType;
      setCalloutTone: (tone: CalloutTone) => ReturnType;
    };
    kbImage: {
      insertImage: (attrs: { id: number; src: string; alt?: string }) => ReturnType;
    };
    kbTable: {
      insertTable: (rows?: number, cols?: number) => ReturnType;
      tableCommand: (name: TableCommand) => ReturnType;
    };
  }
}

export const Callout = Node.create({
  name: "callout",
  group: "block",
  content: "block+",
  defining: true,

  addAttributes() {
    return {
      tone: {
        default: "info",
        parseHTML: (element: HTMLElement) => {
          const tone = element.getAttribute("data-callout") as CalloutTone | null;
          return tone && CALLOUT_TONES.includes(tone) ? tone : "info";
        },
        renderHTML: (attributes: { tone: CalloutTone }) => ({ "data-callout": attributes.tone }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-callout]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes), 0];
  },

  addCommands() {
    return {
      setCallout:
        (tone: CalloutTone = "info") =>
        ({ commands }: CommandProps) =>
          commands.wrapIn(this.name, { tone }),
      unsetCallout:
        () =>
        ({ commands }: CommandProps) =>
          commands.lift(this.name),
      setCalloutTone:
        (tone: CalloutTone) =>
        ({ commands }: CommandProps) =>
          commands.updateAttributes(this.name, { tone }),
    };
  },
});

export const KbImage = Node.create({
  name: "image",
  group: "block",
  atom: true,
  draggable: true,
  selectable: true,

  addAttributes() {
    return {
      id: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-image-id"),
        renderHTML: (attributes: { id: string | number | null }) => (attributes.id ? { "data-image-id": String(attributes.id) } : {}),
      },
      src: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("src"),
        renderHTML: (attributes: { src: string | null }) => (attributes.src ? { src: attributes.src } : {}),
      },
      alt: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("alt") ?? "",
        renderHTML: (attributes: { alt: string }) => (attributes.alt ? { alt: attributes.alt } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "img[data-image-id]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["img", mergeAttributes(HTMLAttributes)];
  },

  addCommands() {
    return {
      insertImage:
        (attrs: { id: number; src: string; alt?: string }) =>
        ({ commands }: CommandProps) =>
          commands.insertContent({ type: this.name, attrs: { id: attrs.id, src: attrs.src, alt: attrs.alt ?? "" } }),
    };
  },
});

const cellAttributes = {
  colspan: { default: 1, parseHTML: (el: HTMLElement) => Number(el.getAttribute("colspan") || 1) },
  rowspan: { default: 1, parseHTML: (el: HTMLElement) => Number(el.getAttribute("rowspan") || 1) },
  colwidth: { default: null, rendered: false },
};

function cellHtml(attributes: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  if (Number(attributes.colspan) > 1) out.colspan = String(attributes.colspan);
  if (Number(attributes.rowspan) > 1) out.rowspan = String(attributes.rowspan);
  return out;
}

export const Table = Node.create({
  name: "table",
  group: "block",
  content: "tableRow+",
  isolating: true,
  parseHTML() {
    return [{ tag: "table" }];
  },
  renderHTML() {
    return ["table", ["tbody", 0]];
  },
  addProseMirrorPlugins() {
    return [tableEditing()];
  },
  addKeyboardShortcuts() {
    return {
      Tab: () => this.editor.commands.command(({ state, dispatch }) => (isInTable(state) ? goToNextCell(1)(state, dispatch) : false)),
      "Shift-Tab": () => this.editor.commands.command(({ state, dispatch }) => (isInTable(state) ? goToNextCell(-1)(state, dispatch) : false)),
    };
  },
  addCommands() {
    return {
      insertTable:
        (rows = 3, cols = 3) =>
        ({ commands, editor }: CommandProps) =>
          commands.insertContent(buildTable(editor.schema, rows, cols).toJSON()),
      tableCommand:
        (name: TableCommand) =>
        ({ state, dispatch }: CommandProps) =>
          TABLE_COMMANDS[name](state, dispatch),
    };
  },
});

export const TableRow = Node.create({
  name: "tableRow",
  content: "(tableHeader | tableCell)*",
  parseHTML() {
    return [{ tag: "tr" }];
  },
  renderHTML() {
    return ["tr", 0];
  },
});

export const TableCell = Node.create({
  name: "tableCell",
  content: "block+",
  isolating: true,
  addAttributes() {
    return cellAttributes;
  },
  parseHTML() {
    return [{ tag: "td" }];
  },
  renderHTML({ node }) {
    return ["td", cellHtml(node.attrs), 0];
  },
});

export const TableHeader = Node.create({
  name: "tableHeader",
  content: "block+",
  isolating: true,
  addAttributes() {
    return cellAttributes;
  },
  parseHTML() {
    return [{ tag: "th" }];
  },
  renderHTML({ node }) {
    return ["th", cellHtml(node.attrs), 0];
  },
});

/** prosemirror-tables needs `tableRole` on the table nodes' specs. */
const TableRoles = Extension.create({
  name: "tableRoles",
  extendNodeSchema(extension) {
    const roles: Record<string, string> = { table: "table", tableRow: "row", tableCell: "cell", tableHeader: "header_cell" };
    return roles[extension.name] ? { tableRole: roles[extension.name] } : {};
  },
});

type Dispatch = ((tr: Transaction) => void) | undefined;
export type TableCommand = "addRow" | "addColumn" | "deleteRow" | "deleteColumn" | "deleteTable" | "toggleHeader";
const TABLE_COMMANDS: Record<TableCommand, (state: EditorState, dispatch: Dispatch) => boolean> = {
  addRow: addRowAfter,
  addColumn: addColumnAfter,
  deleteRow,
  deleteColumn,
  deleteTable,
  toggleHeader: toggleHeaderRow,
};

function buildTable(schema: Schema, rows: number, cols: number): PMNode {
  const { table, tableRow, tableCell, tableHeader, paragraph } = schema.nodes;
  const cell = (type: typeof tableCell) => type!.create(null, paragraph!.create());
  const header = tableRow!.create(null, Array.from({ length: cols }, () => cell(tableHeader)));
  const body = Array.from({ length: Math.max(1, rows - 1) }, () => tableRow!.create(null, Array.from({ length: cols }, () => cell(tableCell))));
  return table!.create(null, [header, ...body]);
}

export function inTable(editor: Editor): boolean {
  return isInTable(editor.state);
}

export function buildExtensions(placeholder: string) {
  return [
    StarterKit.configure({
      heading: { levels: [2, 3, 4] },
      codeBlock: {},
      link: { openOnClick: false, autolink: true, defaultProtocol: "https", protocols: ["mailto", "tel"] },
    }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Callout,
    KbImage,
    TableRoles,
    Table,
    TableRow,
    TableHeader,
    TableCell,
    Placeholder.configure({ placeholder }),
  ];
}
