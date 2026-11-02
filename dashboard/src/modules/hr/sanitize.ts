/**
 * The contract preview is the server's own sanitized HTML; it is cleaned once more here before it
 * goes into the page, with the short list of tags a contract uses (no scripts, styles, frames,
 * forms or event handlers whatever the server sends).
 */
import DOMPurify from "dompurify";

const TAGS = ["p", "br", "strong", "b", "em", "i", "u", "s", "h1", "h2", "h3", "h4", "ul", "ol", "li", "hr", "table", "thead", "tbody", "tr", "th", "td", "span", "div", "blockquote"];

export function sanitizeContractHtml(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: TAGS, ALLOWED_ATTR: ["colspan", "rowspan"] });
}
