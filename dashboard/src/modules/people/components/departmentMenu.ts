/** The structure actions on a department, the same on its card and in its panel. */
import { CornerDownRight, FolderPlus, Pencil, Trash2, UserRoundCheck, UserRoundX } from "@lucide/vue";

import type { MenuEntry } from "@/components/menuTypes";

import type { Department } from "../types";

export type DepartmentAction = "addSub" | "rename" | "move" | "head" | "clearHead" | "delete";

export function departmentMenu(department: Department, t: (key: string) => string, act: (action: DepartmentAction) => void): MenuEntry[] {
  const entries: MenuEntry[] = [
    { label: t("people.dept.addSub"), icon: FolderPlus, onSelect: () => act("addSub") },
    { label: t("people.dept.rename"), icon: Pencil, onSelect: () => act("rename") },
    { label: t("people.dept.move"), icon: CornerDownRight, onSelect: () => act("move") },
    { label: department.head ? t("people.dept.changeHead") : t("people.dept.setHead"), icon: UserRoundCheck, onSelect: () => act("head") },
  ];
  if (department.head) entries.push({ label: t("people.dept.clearHead"), icon: UserRoundX, onSelect: () => act("clearHead") });
  entries.push({ type: "separator" }, { label: t("common.delete"), icon: Trash2, danger: true, onSelect: () => act("delete") });
  return entries;
}
