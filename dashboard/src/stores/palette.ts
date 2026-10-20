/** Command palette state: open, the query it opened with, and recently visited pages per company. */
import { defineStore } from "pinia";
import { ref } from "vue";

import { readStored, writeStored } from "@/lib/storage";

export interface RecentPage {
  path: string;
  /** i18n key of the page title. */
  title: string;
  moduleId: string;
}

const MAX_RECENT = 5;

const isRecentList = (value: unknown): value is RecentPage[] =>
  Array.isArray(value) &&
  value.every((v) => v && typeof v === "object" && typeof (v as RecentPage).path === "string" && typeof (v as RecentPage).title === "string");

export const usePaletteStore = defineStore("palette", () => {
  const open = ref(false);
  const initialQuery = ref("");

  function show(query = ""): void {
    initialQuery.value = query;
    open.value = true;
  }

  function hide(): void {
    open.value = false;
  }

  function toggle(): void {
    if (open.value) hide();
    else show();
  }

  function recent(companyId: number): RecentPage[] {
    return readStored(`recent.${companyId}`, [], isRecentList);
  }

  function remember(companyId: number, page: RecentPage): void {
    const list = [page, ...recent(companyId).filter((p) => p.path !== page.path)].slice(0, MAX_RECENT);
    writeStored(`recent.${companyId}`, list);
  }

  return { open, initialQuery, show, hide, toggle, recent, remember };
});
