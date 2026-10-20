/** Navigation helpers shared by the guards, the company switcher and the palette. */
import type { RouteLocationNormalizedLoaded, Router } from "vue-router";

function isCatchAll(path: string): boolean {
  return path.includes("pathMatch");
}

/**
 * Where the same view lives in another company. Ids in the path (a person or a shift of one
 * company) mean nothing in another, so the path is cut before the first param; the query is dropped
 * for the same reason (`?task=`). Falls back to the company's overview.
 */
export function pathInCompany(router: Router, route: RouteLocationNormalizedLoaded, companyId: number): string {
  const home = `/c/${companyId}`;
  const deepest = route.matched[route.matched.length - 1];
  if (!deepest || !deepest.path.startsWith("/c/:companyId") || isCatchAll(deepest.path)) return home;
  const kept: string[] = [];
  for (const segment of deepest.path.split("/").slice(3)) {
    if (segment.startsWith(":") || isCatchAll(segment)) break;
    kept.push(segment);
  }
  while (kept.length) {
    const candidate = `${home}/${kept.join("/")}`;
    const resolved = router.resolve(candidate);
    if (resolved.matched.length && !resolved.matched.some((record) => isCatchAll(record.path))) return candidate;
    kept.pop();
  }
  return home;
}

/** A route component given as `() => import(...)` (vue-router's own test for lazy components). */
function isLazyLoader(component: unknown): component is () => Promise<unknown> {
  return typeof component === "function" && !("displayName" in component) && !("props" in component) && !("__vccOpts" in component);
}

/** Starts loading a path's lazy route chunks so the page is ready before the click. */
export function prefetchPath(router: Router, path: string): void {
  try {
    for (const record of router.resolve(path).matched) {
      for (const component of Object.values(record.components ?? {})) {
        if (isLazyLoader(component)) void component().catch(() => undefined);
      }
    }
  } catch {
    // An unknown path: nothing to prefetch.
  }
}
