/**
 * Page bodies come from the server already cleaned against its allow-list. The app checks them
 * once more before showing them (no third-party sanitizer here): only known tags and attributes
 * survive, links keep only http(s)/mailto/tel and open outside, checklists are read-only.
 */

const TAGS = new Set([
  "P", "H1", "H2", "H3", "H4", "STRONG", "B", "EM", "I", "U", "S", "STRIKE", "CODE", "PRE", "BLOCKQUOTE", "BR", "HR",
  "UL", "OL", "LI", "LABEL", "INPUT", "SPAN", "DIV", "A", "IMG", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "COLGROUP", "COL",
]);
const ATTRIBUTES: Record<string, readonly string[]> = {
  A: ["href"],
  IMG: ["src", "alt", "data-image-id"],
  UL: ["data-type"],
  OL: ["start"],
  LI: ["data-type", "data-checked"],
  INPUT: ["type", "checked"],
  DIV: ["data-callout"],
  TH: ["colspan", "rowspan"],
  TD: ["colspan", "rowspan"],
};
const DROP = new Set(["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "TEMPLATE", "SVG", "MATH", "FORM", "TEXTAREA", "SELECT", "BUTTON"]);
const SAFE_URL = /^(https?:|mailto:|tel:)/i;
const SAFE_SRC = /^(\/api\/v1\/files\/|https?:)/i;

function clean(node: Element): void {
  for (const child of Array.from(node.children)) {
    if (DROP.has(child.tagName)) {
      child.remove();
      continue;
    }
    clean(child);
    if (!TAGS.has(child.tagName)) {
      child.replaceWith(...Array.from(child.childNodes));
      continue;
    }
    const allowed = ATTRIBUTES[child.tagName] ?? [];
    for (const attribute of Array.from(child.attributes)) {
      if (!allowed.includes(attribute.name)) child.removeAttribute(attribute.name);
    }
    if (child.tagName === "A") {
      const href = child.getAttribute("href") ?? "";
      if (!SAFE_URL.test(href)) child.removeAttribute("href");
      child.setAttribute("target", "_blank");
      child.setAttribute("rel", "noopener noreferrer");
    }
    if (child.tagName === "IMG" && !SAFE_SRC.test(child.getAttribute("src") ?? "")) child.remove();
    if (child.tagName === "INPUT") {
      if (child.getAttribute("type") !== "checkbox") child.remove();
      else child.setAttribute("disabled", "");
    }
  }
}

export function safeHtml(html: string): string {
  if (typeof document === "undefined" || !html) return "";
  // An inert document: nothing in it loads or runs while it is being cleaned.
  const inert = document.implementation.createHTMLDocument("");
  const root = inert.createElement("div");
  root.innerHTML = html;
  clean(root);
  return root.innerHTML;
}
