/** The company the console is looking at (from the URL), and the branch filter inside it. */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import type { Company } from "@/api/types";
import { hasFeature, type CompanyFeature } from "@/core/features";
import { hasPerm, type PermRequirement } from "@/core/perms";
import { isNumber, readStored, writeStored } from "@/lib/storage";
import { useSessionStore } from "@/stores/session";

const DEFAULT_TIMEZONE = "Asia/Tashkent";

export const useCompanyStore = defineStore("company", () => {
  const session = useSessionStore();
  const currentId = ref<number | null>(null);
  const lastId = ref<number | null>(readStored<number | null>("lastCompany", null, (v): v is number | null => v === null || isNumber(v)));

  const companies = computed<Company[]>(() => session.me?.companies ?? []);
  const current = computed<Company | null>(() => companies.value.find((c) => c.id === currentId.value) ?? null);
  const isOwner = computed(() => current.value?.is_owner ?? false);
  const timezone = computed(() => current.value?.timezone ?? DEFAULT_TIMEZONE);
  const currency = computed(() => current.value?.base_currency ?? "UZS");

  /** Branch ids picked in the global branch filter; empty means every branch in scope. */
  const branchFilter = ref<number[]>([]);

  function setCurrent(id: number | null): void {
    currentId.value = id;
    if (id !== null) {
      lastId.value = id;
      writeStored("lastCompany", id);
    }
  }

  /**
   * Where "/" goes: the company the person works in everywhere (`bot_company`, moved by a pick in the
   * bot, the mini app or here), else the last one used in this browser when still allowed. A first visit opens
   * the main business, not the alphabetically first: one the person owns, that is set up, with the
   * most branches (a pharmacy chain before its small distributor); the list's order breaks ties.
   */
  function defaultCompanyId(): number | null {
    const list = companies.value;
    // One company everywhere: the one picked last in the bot, the mini app or here.
    const working = session.me?.bot_company ?? null;
    if (list.some((c) => c.id === working)) return working;
    if (list.some((c) => c.id === lastId.value)) return lastId.value;
    const main = [...list].sort(
      (a, b) => Number(b.is_owner) - Number(a.is_owner) || Number(b.setup_completed) - Number(a.setup_completed) || b.branches.length - a.branches.length,
    );
    return main[0]?.id ?? null;
  }

  function has(id: number): boolean {
    return companies.value.some((c) => c.id === id);
  }

  function can(perm?: PermRequirement): boolean {
    return hasPerm(current.value, perm);
  }

  function enabled(feature?: CompanyFeature): boolean {
    return hasFeature(current.value, feature);
  }

  function setBranchFilter(ids: number[]): void {
    branchFilter.value = [...ids];
    if (currentId.value !== null) writeStored(`branches.${currentId.value}`, ids);
  }

  watch(currentId, (id) => {
    const scope = current.value?.branch_scope ?? null;
    const saved = id === null ? [] : readStored<number[]>(`branches.${id}`, [], (v): v is number[] => Array.isArray(v) && v.every(isNumber));
    // Never keep a branch the person can no longer see.
    branchFilter.value = scope ? saved.filter((b) => scope.includes(b)) : saved;
  });

  return { currentId, current, isOwner, companies, timezone, currency, branchFilter, setCurrent, defaultCompanyId, has, can, enabled, setBranchFilter };
});
