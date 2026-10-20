/**
 * Links that come from the server (notification and queue `url`s, search hits) and from the
 * address bar (`?next=`), turned into safe in-app paths.
 */

/**
 * A server-sent dashboard link as a router path inside the company:
 *   "/c/12/sales/shifts/4" → itself; "/dashboard/c/12/x" → "/c/12/x"; "sales/shifts/4" or
 *   "/sales/shifts/4" → "/c/{companyId}/sales/shifts/4". Links to other sites never leave the app:
 *   they fall back to the company's home.
 */
export function companyUrl(companyId: number | null, url: string | null | undefined): string {
  const home = companyId === null ? "/" : `/c/${companyId}`;
  const raw = (url ?? "").trim();
  if (!raw || /^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith("//") || raw.startsWith("/\\")) return home;
  const path = raw.startsWith("/dashboard/") ? raw.slice("/dashboard".length) : raw;
  if (/^\/c\/\d+(\/|$|\?|#)/.test(path)) return path;
  const relative = path.replace(/^\/+/, "");
  return relative ? `${home === "/" ? "" : home}/${relative}` : home;
}

/** Only same-app paths are accepted after login (no open redirects). */
export function safeNext(value: unknown): string {
  const next = Array.isArray(value) ? value[0] : value;
  if (typeof next !== "string" || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  return next;
}
