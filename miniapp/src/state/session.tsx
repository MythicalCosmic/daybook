import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { Me, Membership } from "../api/types";

const STORAGE_KEY = "daybook.company";

type Session = {
  me: Me;
  membership: Membership | null;
  /** Approved memberships the person can switch between. */
  companies: Membership[];
  switchCompany: (companyId: number) => void;
};

const SessionContext = createContext<Session | null>(null);

/** Which membership the app shows: the chosen company if still approved, else the most useful. */
function pickMembership(me: Me, preferred: number | null): Membership | null {
  const memberships = me.memberships;
  const approved = memberships.filter((m) => m.status === "approved");
  return (
    approved.find((m) => m.company.id === preferred) ??
    approved[0] ??
    memberships.find((m) => m.status === "pending") ??
    memberships.find((m) => m.status === "rejected") ??
    memberships.find((m) => m.status === "blocked") ??
    null
  );
}

function savedCompany(): number | null {
  try {
    const value = Number(localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function SessionProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [preferred, setPreferred] = useState<number | null>(savedCompany);
  const value = useMemo<Session>(
    () => ({
      me,
      membership: pickMembership(me, preferred),
      companies: me.memberships.filter((m) => m.status === "approved" && m.is_onboarded),
      switchCompany: (companyId) => {
        setPreferred(companyId);
        try {
          localStorage.setItem(STORAGE_KEY, String(companyId));
        } catch {
          // Not remembered across launches, which is fine.
        }
      },
    }),
    [me, preferred],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession outside SessionProvider");
  return session;
}

/** The active, approved membership. Only for screens behind the membership gate. */
export function useMember(): Membership & { timeZone: string; companyId: number } {
  const { membership } = useSession();
  if (!membership) throw new Error("useMember without a membership");
  return { ...membership, timeZone: membership.company.timezone, companyId: membership.company.id };
}

export function initials(first: string, last: string): string {
  return `${first.trim().charAt(0)}${last.trim().charAt(0)}`.toUpperCase() || "?";
}
