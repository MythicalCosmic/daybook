import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/client";
import { isSuspended } from "../api/membership";
import type { Me, Membership } from "../api/types";
import { cloudStorage } from "../telegram";

const STORAGE_KEY = "daybook.company";
/** The same choice in Telegram's cloud storage: a new phone opens the company used last too. */
const CLOUD_KEY = "company";

type Session = {
  me: Me;
  membership: Membership | null;
  /** Approved memberships the person can switch between. */
  companies: Membership[];
  /** The person picked another company here: the app works in it, and so does the bot. */
  switchCompany: (companyId: number) => void;
  /** A link opened a task of another company: the app shows that company, the bot keeps its own. */
  showCompany: (companyId: number) => void;
};

const SessionContext = createContext<Session | null>(null);

/**
 * Which membership the app shows: the company chosen on a phone if still approved, else the one
 * the server says the person works in (`bot_company`, the bot's company: the one picked last, else
 * a company they own with the most branches, which a first visit to the dashboard opens too),
 * else the first.
 */
function pickMembership(me: Me, preferred: number | null): Membership | null {
  const memberships = me.memberships;
  const approved = memberships.filter((m) => m.status === "approved");
  return (
    approved.find((m) => m.company.id === preferred) ??
    approved.find((m) => m.company.id === me.bot_company) ??
    approved[0] ??
    // A suspended person (§13.4) sees the "Access paused" screen, ahead of older states.
    memberships.find(isSuspended) ??
    memberships.find((m) => m.status === "pending") ??
    memberships.find((m) => m.status === "rejected") ??
    memberships.find((m) => m.status === "blocked") ??
    // Someone who used to work here hears "thank you" rather than "you're not in a company yet".
    memberships.find((m) => m.status === "left") ??
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

/** How long the first screen waits for the company remembered on another phone. */
const CLOUD_WAIT_MS = 400;

export function SessionProvider({ me, children }: { me: Me; children: ReactNode }) {
  const [preferred, setPreferred] = useState<number | null>(savedCompany);
  // Nothing remembered on this phone and more than one company: ask Telegram's cloud for the one
  // used last on another phone before the first screen, so the company never changes under a
  // screen already open (or a draft already started).
  const [ready, setReady] = useState(() => preferred !== null || me.memberships.filter((m) => m.status === "approved").length < 2);
  useEffect(() => {
    if (ready) return;
    let decided = false;
    const decide = (id: number | null) => {
      if (decided) return;
      decided = true;
      if (id !== null) setPreferred(id);
      setReady(true);
    };
    const timer = window.setTimeout(() => decide(null), CLOUD_WAIT_MS);
    void cloudStorage.get(CLOUD_KEY).then((value) => {
      const id = Number(value);
      decide(id > 0 && me.memberships.some((m) => m.company.id === id && m.status === "approved") ? id : null);
    });
    return () => {
      decided = true;
      window.clearTimeout(timer);
    };
    // Only at launch: later choices are made here and saved by switchCompany.
  }, []);
  const value = useMemo<Session>(() => {
    const showCompany = (companyId: number) => {
      setPreferred(companyId);
      try {
        localStorage.setItem(STORAGE_KEY, String(companyId));
      } catch {
        // Not remembered across launches, which is fine.
      }
      void cloudStorage.set(CLOUD_KEY, String(companyId));
    };
    return {
      me,
      membership: pickMembership(me, preferred),
      companies: me.memberships.filter((m) => m.status === "approved" && m.is_onboarded),
      showCompany,
      switchCompany: (companyId) => {
        const moved = companyId !== pickMembership(me, preferred)?.company.id;
        showCompany(companyId);
        // One company everywhere: the bot works in the company picked here from now on and says so
        // in its chat, with that company's menu. Only a pick here moves it, never a link opened
        // to another company's task (showCompany). Best effort: the app works in it either way.
        if (moved) void api<Me>("/me/", { method: "PATCH", json: { bot_company: companyId } }).catch(() => undefined);
      },
    };
  }, [me, preferred]);
  return <SessionContext.Provider value={value}>{ready ? children : null}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession outside SessionProvider");
  return session;
}

/** The active, approved membership plus the two things every screen needs from it. */
export type Member = Membership & { timeZone: string; companyId: number };

/** The active, approved membership. Only for screens behind the membership gate. */
export function useMember(): Member {
  const { membership } = useSession();
  if (!membership) throw new Error("useMember without a membership");
  return { ...membership, timeZone: membership.company.timezone, companyId: membership.company.id };
}

export function initials(first: string, last: string): string {
  return `${first.trim().charAt(0)}${last.trim().charAt(0)}`.toUpperCase() || "?";
}
