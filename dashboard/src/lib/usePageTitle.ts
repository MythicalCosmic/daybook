/**
 * A page names the record it shows ("Yunusobod storage room", "Dilnoza Karimova") for the last
 * breadcrumb and the browser tab, instead of its route's generic `meta.title` ("Project"):
 *
 *   usePageTitle(() => project.value?.name);
 *
 * The name counts only while the page's route is the current one and the page is mounted; an empty
 * value (still loading) falls back to `meta.title`.
 */
import { getCurrentScope, onScopeDispose, shallowRef, toValue, watchEffect, type MaybeRefOrGetter } from "vue";
import { useRoute, type RouteLocationNormalizedLoaded, type RouteRecordNormalized } from "vue-router";

interface PageTitle {
  owner: symbol;
  record: RouteRecordNormalized | undefined;
  title: string;
}

const current = shallowRef<PageTitle | null>(null);

export function usePageTitle(title: MaybeRefOrGetter<string | null | undefined>): void {
  const owner = Symbol("page-title");
  // The page's own route record: tabs (`projects/:id/:tab`) keep it, another page doesn't.
  const record = useRoute().matched.at(-1);
  watchEffect(() => {
    const value = toValue(title)?.trim();
    if (value) current.value = { owner, record, title: value };
    else if (current.value?.owner === owner) current.value = null;
  });
  if (getCurrentScope())
    onScopeDispose(() => {
      if (current.value?.owner === owner) current.value = null;
    });
}

/** The name the page on `route` gave itself, if any (read by the breadcrumb and the tab title). */
export function pageTitleFor(route: RouteLocationNormalizedLoaded): string | null {
  const title = current.value;
  return title && title.record && route.matched.includes(title.record) ? title.title : null;
}
