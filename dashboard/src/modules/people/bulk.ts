/**
 * Join requests in bulk (People › Join requests): which ready requests are selected, what the bulk
 * approve dialog starts with, the body it sends, and what the answer means for the page (the ones
 * that went through leave, the others stay selected with their reasons).
 */
import { computed, ref, watch } from "vue";

import type { BranchRef } from "@/api/types";

import type { BulkDecisionInput, BulkDecisionResult, JoinRequest, Role } from "./types";

type T = (key: string, params?: Record<string, unknown>, plural?: number) => string;

/** The role choice that means "as their link says": `role_id` left out (each link's role, else the default). */
export const AS_LINK = 0;

/** A selection over a list of ids; ids that leave the list leave the selection too. */
export function useSelection(ids: () => readonly number[]) {
  const selected = ref<number[]>([]);
  watch(ids, (now) => {
    const still = new Set(now);
    if (selected.value.some((id) => !still.has(id))) selected.value = selected.value.filter((id) => still.has(id));
  });
  const all = computed(() => ids().length > 0 && ids().every((id) => selected.value.includes(id)));
  const some = computed(() => selected.value.length > 0 && !all.value);
  return {
    selected,
    all,
    some,
    has: (id: number) => selected.value.includes(id),
    toggle(id: number, on: boolean): void {
      selected.value = on ? (selected.value.includes(id) ? selected.value : [...selected.value, id]) : selected.value.filter((other) => other !== id);
    },
    toggleAll(on: boolean): void {
      selected.value = on ? [...ids()] : [];
    },
    set(list: readonly number[]): void {
      selected.value = [...list];
    },
    clear(): void {
      selected.value = [];
    },
  };
}

export interface BulkStart {
  /** The role chosen first: "as their link says" when every link names a role, else the default role. */
  role: number | null;
  /** How many of the people came through a link that names a role. */
  linkRoles: "all" | "some" | "none";
  /** Their shared link branch, when they all came with the same one (and the approver may give it). */
  branchIds: number[];
  homeId: number | null;
  /** Everyone came with a branch: leaving the branches empty sends each to their own link's branch. */
  everyoneHasBranch: boolean;
  /** Branches must be picked: there are two or more and someone came without one. */
  branchRequired: boolean;
}

/** What the bulk approve dialog starts with, from the people chosen and the approver's roles and branches. */
export function bulkStart(rows: readonly JoinRequest[], roles: readonly Role[], branches: readonly BranchRef[]): BulkStart {
  const withRole = rows.filter((row) => row.join_link?.role).length;
  const linkRoles = rows.length > 0 && withRole === rows.length ? "all" : withRole > 0 ? "some" : "none";
  const linkBranches = rows.map((row) => row.join_link?.branch?.id ?? null);
  const everyoneHasBranch = rows.length > 0 && linkBranches.every((id) => id !== null);
  const shared = everyoneHasBranch && new Set(linkBranches).size === 1 ? linkBranches[0]! : null;
  const prefill = shared !== null && branches.some((branch) => branch.id === shared) ? shared : null;
  return {
    role: linkRoles === "all" ? AS_LINK : (roles.find((role) => role.is_default)?.id ?? null),
    linkRoles,
    branchIds: prefill === null ? [] : [prefill],
    homeId: prefill,
    everyoneHasBranch,
    branchRequired: branches.length > 1 && !everyoneHasBranch,
  };
}

export interface BulkChoice {
  role: number | null;
  positionId: number | null;
  branchIds: number[];
  homeId: number | null;
}

/** The approve body: only what was chosen for everyone; the rest follows each person's link. */
export function bulkApproveBody(ids: readonly number[], choice: BulkChoice, severalBranches: boolean): BulkDecisionInput {
  const body: BulkDecisionInput = { ids: [...ids], action: "approve" };
  if (choice.role !== null && choice.role !== AS_LINK) body.role_id = choice.role;
  if (choice.positionId !== null) body.position_id = choice.positionId;
  if (severalBranches && choice.branchIds.length) {
    body.branch_ids = [...choice.branchIds];
    body.home_branch_id = choice.homeId;
  }
  return body;
}

export interface BulkOutcome {
  done: number;
  failed: Array<{ id: number; name: string; detail: string }>;
}

/** The answer in the page's terms: how many went through, and who didn't and why. */
export function bulkOutcome(result: BulkDecisionResult, rows: readonly JoinRequest[]): BulkOutcome {
  const names = new Map(rows.map((row) => [row.id, row.name]));
  return {
    done: result.results.filter((row) => row.ok).length,
    failed: result.results.filter((row) => !row.ok).map((row) => ({ id: row.id, name: names.get(row.id) ?? `#${row.id}`, detail: row.detail })),
  };
}

/** "Aziza Karimova, Bekzod Aliyev, Dilshod Rahimov and 9 more" */
export function namesLine(names: readonly string[], t: T, shown = 3): string {
  if (names.length <= shown + 1) return names.join(", ");
  return t("people.bulk.andMore", { names: names.slice(0, shown).join(", "), n: names.length - shown });
}
