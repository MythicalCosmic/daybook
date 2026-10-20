/**
 * The console's message compiler: vue-i18n's runtime build plus this ~1 KB function instead of the
 * full message compiler (~10 KB gzipped), so the first load stays inside the 180 KB budget
 * (plan §6.5).
 *
 * Supported syntax (all the console uses):
 *   - named values: "Hi, {name}" → t(key, { name });
 *   - list values: "{0} of {1}" → t(key, [a, b]);
 *   - literal text: "{'{'}" → "{";
 *   - plural forms separated by " | ": "{n} task | {n} tasks" → t(key, { n }, n), chosen by the
 *     language's plural rule (i18n/index.ts).
 * Not supported: linked messages ("@:key") and modifiers; "@" and "$" are plain text.
 */
import type { MessageCompiler, MessageContext } from "vue-i18n";

type Part = string | { named: string } | { index: number };

/** Splits plural forms on "|" outside braces; "\|" is a literal bar. */
function splitForms(source: string): string[] {
  const forms: string[] = [];
  let current = "";
  let depth = 0;
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i]!;
    if (char === "\\" && source[i + 1] === "|") {
      current += "|";
      i += 1;
    } else if (char === "{") {
      depth += 1;
      current += char;
    } else if (char === "}") {
      depth = Math.max(0, depth - 1);
      current += char;
    } else if (char === "|" && depth === 0) {
      forms.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  forms.push(forms.length ? current.trim() : current);
  return forms;
}

/** "Hi, {name}!" → ["Hi, ", { named: "name" }, "!"]. */
export function parseMessage(source: string): Part[] {
  const parts: Part[] = [];
  const pattern = /\{\s*(?:'([^']*)'|(\d+)|([A-Za-z_$][\w$]*))\s*\}/g;
  let last = 0;
  for (const match of source.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(source.slice(last, index));
    if (match[1] !== undefined) parts.push(match[1]);
    else if (match[2] !== undefined) parts.push({ index: Number(match[2]) });
    else parts.push({ named: match[3]! });
    last = index + match[0].length;
  }
  if (last < source.length) parts.push(source.slice(last));
  return parts;
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function render(parts: Part[], ctx: MessageContext<string>): string {
  let out = "";
  for (const part of parts) {
    if (typeof part === "string") out += part;
    else if ("named" in part) out += show(ctx.named(part.named));
    else out += show(ctx.list(part.index));
  }
  return out;
}

const cache = new Map<string, Part[][]>();

export const compileMessage: MessageCompiler<string, unknown> = (message, context) => {
  if (typeof message !== "string") {
    // Precompiled ASTs come only from a bundler plugin the console doesn't use.
    context.onError?.(new Error(`Unsupported message for "${context.key}"`) as never);
    return () => context.key;
  }
  let forms = cache.get(message);
  if (!forms) {
    forms = splitForms(message).map(parseMessage);
    cache.set(message, forms);
  }
  const compiled = forms;
  return (ctx: MessageContext<string>) =>
    compiled.length > 1 ? ctx.plural(compiled.map((parts) => render(parts, ctx))) : render(compiled[0]!, ctx);
};
