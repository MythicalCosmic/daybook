/**
 * Telegram's HTML subset in the browser, mirroring `apps.announcements.telegram_html` on the
 * server (which is the authority: it cleans whatever is sent).
 *
 *   fromEditor(html)   the composer's HTML (paragraphs, <strong>, a spoiler span…) → Telegram HTML
 *   toEditor(text)     stored Telegram HTML → HTML the composer opens
 *   toDisplay(text)    Telegram HTML → safe HTML for the preview bubble (only the allowed tags,
 *                      every text node escaped, links forced to open in a new tab)
 *   plainLength(text)  the length Telegram counts (text without tags)
 */

const INLINE: Record<string, string> = {
  b: "b",
  strong: "b",
  i: "i",
  em: "i",
  u: "u",
  ins: "u",
  s: "s",
  strike: "s",
  del: "s",
  code: "code",
  "tg-spoiler": "tg-spoiler",
  pre: "pre",
  blockquote: "blockquote",
};
const BLOCKS = new Set(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol"]);
const DROPPED = new Set(["script", "style", "template", "iframe", "object"]);
const SAFE_URL = /^(https?:\/\/|tg:\/\/|mailto:)/i;

export function escapeText(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(text: string): string {
  return escapeText(text).replace(/"/g, "&quot;");
}

function parse(html: string): Document {
  return new DOMParser().parseFromString(`<!doctype html><body>${html}</body>`, "text/html");
}

/** The composer's HTML as Telegram HTML (paragraphs become lines). */
export function fromEditor(html: string): string {
  const out: string[] = [];
  const open: string[] = [];

  function newline(): void {
    if (out.length) out.push("\n");
  }

  function walk(node: Node): void {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(escapeText(node.textContent ?? ""));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    if (DROPPED.has(tag)) return;
    if (tag === "br") {
      out.push("\n");
      return;
    }
    if (BLOCKS.has(tag)) {
      if (tag !== "ul" && tag !== "ol" && out.at(-1) !== "• ") newline();
      if (tag === "li") out.push("• ");
      element.childNodes.forEach(walk);
      return;
    }
    let name: string | null = null;
    let opening = "";
    if (tag === "span" && element.classList.contains("tg-spoiler")) {
      name = "tg-spoiler";
      opening = "<tg-spoiler>";
    } else if (tag === "a") {
      const href = (element.getAttribute("href") ?? "").trim();
      if (SAFE_URL.test(href)) {
        name = "a";
        opening = `<a href="${escapeAttr(href)}">`;
      }
    } else if (INLINE[tag]) {
      name = INLINE[tag]!;
      opening = `<${name}>`;
    }
    if (name && open.includes(name)) name = null; // Telegram refuses a tag inside itself
    if (!name) {
      element.childNodes.forEach(walk);
      return;
    }
    open.push(name);
    out.push(opening);
    element.childNodes.forEach(walk);
    out.push(`</${name}>`);
    open.pop();
  }

  parse(html).body.childNodes.forEach(walk);
  let text = out.join("");
  let previous = "";
  while (previous !== text) {
    previous = text;
    text = text.replace(/<(b|i|u|s|code|tg-spoiler|pre|blockquote|a)(?: [^>]*)?><\/\1>/g, "");
  }
  return text
    .split("\n")
    .map((line) => line.replace(/\s+$/, ""))
    .join("\n")
    .trim();
}

/** Stored Telegram HTML as HTML the composer opens: one paragraph per line. */
export function toEditor(text: string): string {
  const lines = toDisplay(text).split("<br>");
  return lines.map((line) => `<p>${line}</p>`).join("");
}

/** Telegram HTML as safe display HTML: allowed tags only, text escaped, line breaks as <br>. */
export function toDisplay(text: string): string {
  const out: string[] = [];
  function walk(node: Node): void {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(escapeText(node.textContent ?? "").replace(/\n/g, "<br>"));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    if (DROPPED.has(tag)) return;
    if (tag === "br") {
      out.push("<br>");
      return;
    }
    let opening: string | null = null;
    let closing = "";
    if (tag === "tg-spoiler" || (tag === "span" && element.classList.contains("tg-spoiler"))) {
      opening = '<span class="tg-spoiler">';
      closing = "</span>";
    } else if (tag === "a") {
      const href = (element.getAttribute("href") ?? "").trim();
      if (SAFE_URL.test(href)) {
        opening = `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">`;
        closing = "</a>";
      }
    } else if (INLINE[tag]) {
      const name = INLINE[tag] === "b" ? "strong" : INLINE[tag] === "i" ? "em" : INLINE[tag]!;
      opening = `<${name}>`;
      closing = `</${name}>`;
    }
    if (opening) out.push(opening);
    element.childNodes.forEach(walk);
    if (opening) out.push(closing);
  }
  parse(text.replace(/\r\n/g, "\n")).body.childNodes.forEach(walk);
  return out.join("");
}

/** What Telegram counts: the text without tags. */
export function plainLength(text: string): number {
  return (parse(text).body.textContent ?? "").length;
}
