/**
 * The four roles a Davomat install starts with (docs/DAVOMAT.md §1.3): Owner (everything),
 * Administrator (everything but the owner's role), Manager (attendance and the team of their
 * locations) and Viewer (reads only). `GET users/roles/` sends them strongest first, each with its
 * kind; the server names them in the organization's language.
 */
import type { RoleOption } from "../../api";
import type { RoleKind } from "../../types";

export type KnownKind = RoleKind | "other";

const ORDER: readonly RoleKind[] = ["owner", "admin", "manager", "viewer"];

/** Roles that see only their own locations' people and data. */
export const SCOPED: readonly KnownKind[] = ["manager", "viewer"];

const NAMES: Record<Exclude<RoleKind, "owner">, RegExp> = {
  admin: /^(admin|administrator|администратор)$/i,
  manager: /^(manager|menejer|boshqaruvchi|менеджер|управляющий)$/i,
  viewer: /^(viewer|kuzatuvchi|наблюдатель)$/i,
};

/** A role's kind: the server's, else read from the owner flag and the name ("other" when unknown). */
export function roleKind(role: { name: string; is_owner?: boolean; kind?: string | null } | null | undefined): KnownKind {
  if (!role) return "other";
  if (role.kind && (ORDER as readonly string[]).includes(role.kind)) return role.kind as RoleKind;
  if (role.is_owner) return "owner";
  const name = role.name.trim();
  for (const kind of ["admin", "manager", "viewer"] as const) if (NAMES[kind].test(name)) return kind;
  return "other";
}

/**
 * The roles a user can be given here, strongest first: administrator, manager and viewer, and the
 * owner's role only when an owner gives it (the server refuses it to anyone else).
 */
export function assignableRoles(roles: readonly RoleOption[], options: { owner?: boolean } = {}): Array<RoleOption & { roleKind: KnownKind }> {
  return roles
    .map((role) => ({ ...role, roleKind: roleKind(role) }))
    .filter((role) => role.roleKind !== "other" && (options.owner || role.roleKind !== "owner"))
    .sort((a, b) => ORDER.indexOf(a.roleKind as RoleKind) - ORDER.indexOf(b.roleKind as RoleKind));
}

/** The chip's tone for a role. */
export function roleTone(kind: KnownKind): "primary" | "info" | "success" | "neutral" {
  return kind === "owner" ? "primary" : kind === "admin" ? "info" : kind === "manager" ? "success" : "neutral";
}
