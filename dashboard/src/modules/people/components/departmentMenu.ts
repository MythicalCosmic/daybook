/** The structure actions on a department, the same on its card and in its panel. */
import { CornerDownRight, FolderPlus, Pencil, Trash2, UserRoundCheck, UserRoundX } from "@lucide/vue";

import type { MenuEntry } from "@/components/menuTypes";

import type { Department } from "../types";

export type DepartmentAction = "addSub" | "rename" | "move" | "head" | "clearHead" | "delete";

/**
 * `heads`: the viewer may choose heads (an owner, or someone holding tasks.assign, tasks.confirm and
 * tasks.view_all: a head gives and checks work, so only someone who may do that hands it out).
 */
export function departmentMenu(department: Department, t: (key: string) => string, act: (action: DepartmentAction) => void, heads = true): MenuEntry[] {
  const entries: MenuEntry[] = [
    { label: t("people.dept.addSub"), icon: FolderPlus, onSelect: () => act("addSub") },
    { label: t("people.dept.rename"), icon: Pencil, onSelect: () => act("rename") },
    { label: t("people.dept.move"), icon: CornerDownRight, onSelect: () => act("move") },
  ];
  if (heads) {
    entries.push({ label: department.head ? t("people.dept.changeHead") : t("people.dept.setHead"), icon: UserRoundCheck, onSelect: () => act("head") });
    if (department.head) entries.push({ label: t("people.dept.clearHead"), icon: UserRoundX, onSelect: () => act("clearHead") });
  }
  entries.push({ type: "separator" }, { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => act("delete") });
  return entries;
}

/** Who may choose heads (the server answers 403 to anyone else). */
export const HEAD_PERMS = ["tasks.assign", "tasks.confirm", "tasks.view_all"] as const;
