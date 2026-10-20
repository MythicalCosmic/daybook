/** Extension slots: a host module renders `<ExtensionSlot name="…">`, other modules fill it. */
import type { Component } from "vue";

import type { Company } from "@/api/types";
import { isModuleVisible } from "@/core/access";
import { modules as registry, type DashboardModule, type ExtensionPoint } from "@/core/modules";

export interface ExtensionEntry {
  key: string;
  moduleId: string;
  component: Component;
}

/** Components registered for `point` by modules visible in `company`, in sidebar order. */
export function extensionsFor(
  point: ExtensionPoint,
  company: Company | null | undefined,
  list: readonly DashboardModule[] = registry,
): ExtensionEntry[] {
  const out: ExtensionEntry[] = [];
  for (const module of list) {
    const components = module.extensions?.[point];
    if (!components?.length || !isModuleVisible(module, company)) continue;
    components.forEach((component, index) => out.push({ key: `${module.id}:${index}`, moduleId: module.id, component }));
  }
  return out;
}

export function hasExtension(point: ExtensionPoint, company: Company | null | undefined, list?: readonly DashboardModule[]): boolean {
  return extensionsFor(point, company, list).length > 0;
}
