/**
 * Markdown to safe HTML for MarkdownView (plan §6.3): markdown-it with raw HTML off, then DOMPurify
 * with a short allow-list. Record references become chips that link inside the console:
 * a bare `member:17` or `task:345` (as the AI writes them), or a link `[Dilnoza](member:17)`.
 */
import DOMPurify from "dompurify";
import MarkdownIt, { type Token } from "markdown-it";

/** Record kind → path inside the company ("people/17"). Modules' pages own these URLs (plan §6.1). */
export const RECORD_KINDS: Record<string, (id: string) => string> = {
  member: (id) => `people/${id}`,
  task: (id) => `tasks?task=${id}`,
  routine: (id) => `routines/${id}`,
  project: (id) => `projects/${id}`,
  shift: (id) => `sales/shifts/${id}`,
  invoice: (id) => `sales/invoices/${id}`,
  customer: (id) => `sales/customers/${id}`,
  product: (id) => `stock/products?product=${id}`,
  txn: (id) => `finance/transactions?txn=${id}`,
  counterparty: (id) => `finance/counterparties/${id}`,
  payroll: (id) => `payroll/runs/${id}`,
  vacancy: (id) => `hr/hiring/${id}`,
  announcement: (id) => `announcements/${id}`,
  deal: (id) => `crm?deal=${id}`,
  page: (id) => `knowledge/${id}`,
};

export interface MarkdownOptions {
  /** Base for chip links, e.g. "/dashboard/c/12". Without it chips render as plain labels. */
  base?: string | null;
  /** Label of a bare reference ("Task #345"). */
  label: (kind: string, id: string) => string;
  /** Extra or replaced record kinds. */
  kinds?: Record<string, (id: string) => string>;
  allowImages?: boolean;
  /** Single newlines become line breaks (chat answers). Default true. */
  breaks?: boolean;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
}

function kindAlternation(kinds: Record<string, unknown>): string {
  return Object.keys(kinds)
    .sort((a, b) => b.length - a.length)
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
}

function chipOpen(kind: string, id: string, href: string | null): string {
  const attrs = `class="md-chip" data-record="${escapeHtml(kind)}" data-id="${escapeHtml(id)}"`;
  return href ? `<a ${attrs} href="${escapeHtml(href)}">` : `<span ${attrs}>`;
}

const engines = new Map<string, MarkdownIt>();

function engine(options: MarkdownOptions): MarkdownIt {
  const kinds = { ...RECORD_KINDS, ...options.kinds };
  const key = `${options.breaks !== false}|${options.allowImages ? 1 : 0}|${Object.keys(kinds).join(",")}`;
  // The renderer reads base and label from env, so one engine serves every company and language.
  let md = engines.get(key);
  if (md) return md;
  md = new MarkdownIt({ html: false, linkify: true, breaks: options.breaks !== false, typographer: false });
  if (!options.allowImages) md.disable("image");
  const names = kindAlternation(kinds);
  // A bare reference stands alone: not part of a word, a path or a URL ("http://x/task:3" stays text).
  const pattern = new RegExp(`(?<![\\w/:.-])(${names}):(\\d{1,12})(?![\\w:])`, "g");
  const exact = new RegExp(`^(${names}):(\\d{1,12})$`);

  md.core.ruler.push("record_chips", (state) => {
    for (const block of state.tokens) {
      if (block.type !== "inline" || !block.children) continue;
      const out: Token[] = [];
      let insideLink = 0;
      for (const token of block.children) {
        if (token.type === "link_open") insideLink += 1;
        if (token.type === "link_close") insideLink -= 1;
        if (token.type !== "text" || insideLink > 0) {
          out.push(token);
          continue;
        }
        const text = token.content;
        let last = 0;
        pattern.lastIndex = 0;
        for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
          if (match.index > last) {
            const piece = new state.Token("text", "", 0);
            piece.content = text.slice(last, match.index);
            out.push(piece);
          }
          const chip = new state.Token("record_chip", "", 0);
          chip.meta = { kind: match[1], id: match[2] };
          out.push(chip);
          last = match.index + match[0].length;
        }
        if (last === 0) out.push(token);
        else if (last < text.length) {
          const rest = new state.Token("text", "", 0);
          rest.content = text.slice(last);
          out.push(rest);
        }
      }
      block.children = out;
    }
  });

  md.renderer.rules.record_chip = (tokens, index, _options, env: RenderEnv) => {
    const { kind, id } = tokens[index]!.meta as { kind: string; id: string };
    const path = kinds[kind]?.(id);
    const href = env.base && path ? `${env.base}/${path}` : null;
    return `${chipOpen(kind, id, href)}${escapeHtml(env.label(kind, id))}${href ? "</a>" : "</span>"}`;
  };

  const defaultLinkOpen = md.renderer.rules.link_open ?? ((tokens, index, opts, _env, self) => self.renderToken(tokens, index, opts));
  const defaultLinkClose = md.renderer.rules.link_close ?? ((tokens, index, opts, _env, self) => self.renderToken(tokens, index, opts));
  md.renderer.rules.link_open = (tokens, index, opts, env: RenderEnv, self) => {
    const href = tokens[index]!.attrGet("href") ?? "";
    const match = exact.exec(href);
    if (match) {
      const [, kind, id] = match as unknown as [string, string, string];
      const path = kinds[kind]?.(id);
      tokens[index]!.meta = { chip: true, linked: !!(env.base && path) };
      return chipOpen(kind, id, env.base && path ? `${env.base}/${path}` : null);
    }
    return defaultLinkOpen(tokens, index, opts, env, self);
  };
  md.renderer.rules.link_close = (tokens, index, opts, env: RenderEnv, self) => {
    // Find the matching open token to close a chip the same way it was opened.
    for (let i = index - 1; i >= 0; i--) {
      const token = tokens[i]!;
      if (token.type === "link_open") {
        const meta = token.meta as { chip?: boolean; linked?: boolean } | null;
        if (meta?.chip) return meta.linked ? "</a>" : "</span>";
        break;
      }
    }
    return defaultLinkClose(tokens, index, opts, env, self);
  };
  engines.set(key, md);
  return md;
}

interface RenderEnv {
  base: string | null;
  label: (kind: string, id: string) => string;
}

let purifier: ReturnType<typeof DOMPurify> | null = null;

function sanitizer(): ReturnType<typeof DOMPurify> {
  if (purifier) return purifier;
  purifier = DOMPurify(window);
  // Only the chips' two data attributes survive (ALLOW_DATA_ATTR stays off for everything else).
  purifier.addHook("uponSanitizeAttribute", (_node, data) => {
    if (data.attrName === "data-record" || data.attrName === "data-id") data.forceKeepAttr = true;
  });
  purifier.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      const href = node.getAttribute("href") ?? "";
      if (/^https?:\/\//i.test(href)) {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer nofollow");
      } else {
        node.removeAttribute("target");
      }
    }
    // Only our own classes survive (markdown-it adds "language-…" to code blocks).
    const classes = node.getAttribute?.("class");
    if (classes) {
      const kept = classes.split(/\s+/).filter((name) => name === "md-chip" || /^language-[\w-]+$/.test(name));
      if (kept.length) node.setAttribute("class", kept.join(" "));
      else node.removeAttribute("class");
    }
  });
  return purifier;
}

const TAGS = ["p", "br", "strong", "em", "b", "i", "s", "del", "code", "pre", "blockquote", "ul", "ol", "li", "a", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "table", "thead", "tbody", "tr", "th", "td", "span"];
const ATTRS = ["href", "title", "class", "data-record", "data-id", "target", "rel", "start", "colspan", "rowspan", "align"];

/** Markdown → sanitized HTML. */
export function renderMarkdown(source: string, options: MarkdownOptions): string {
  const md = engine(options);
  const env: RenderEnv = { base: options.base ?? null, label: options.label };
  const html = md.render(source ?? "", env);
  return sanitizer().sanitize(html, {
    ALLOWED_TAGS: options.allowImages ? [...TAGS, "img"] : TAGS,
    ALLOWED_ATTR: options.allowImages ? [...ATTRS, "src", "alt"] : ATTRS,
    ALLOW_DATA_ATTR: false,
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|tel:|\/(?!\/)|#)/i,
  });
}
